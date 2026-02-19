import os
import json
import pathlib
import re
import uuid
import threading
import io
from flask import Flask, render_template, request, redirect, url_for, send_from_directory, jsonify, Response, stream_with_context
from werkzeug.utils import secure_filename
from pydub import AudioSegment
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from database import db, init_db, Folder, PDFFile, Settings, get_settings, Task
from services import (
    init_tts_client,
    init_text_client,
    process_pdf,
    allowed_file,
    available_text_models,
    available_tts_models,
    available_voices,
    generate_voice_sample,
    generate_podcast_audio,
    generate_text_with_file,
    generate_text_completion,
)

# Try to import Google GenAI for text generation (optional)
try:
    from google import genai
    from google.genai import types
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False

# --- App and DB Setup ---
app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['GENERATED_AUDIO_FOLDER'] = 'generated_audio'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///db.sqlite3'
app.config['SERVER_NAME'] = os.environ.get('SERVER_NAME', 'localhost:5000')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
ALLOWED_EXTENSIONS = {'pdf'}

init_db(app)

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['GENERATED_AUDIO_FOLDER'], exist_ok=True)

# --- Flask Routes ---
@app.route('/')
def index():
    folders = Folder.query.all()
    files_without_folder = PDFFile.query.filter_by(folder_id=None).all()

    # Check for audio file existence for all files

    def _set_audio_exists(file_obj):
        mp3_filename = f"dialogue_{file_obj.id}.mp3"
        mp3_filepath = os.path.join(app.config['GENERATED_AUDIO_FOLDER'], mp3_filename)
        file_obj.audio_exists = os.path.exists(mp3_filepath)

    for file in files_without_folder:
        _set_audio_exists(file)

    for folder in folders:
        for file in folder.files:
            _set_audio_exists(file)

    return render_template('index.html', folders=folders, files_without_folder=files_without_folder)

@app.route('/create_folder', methods=['POST'])
def create_folder():
    folder_name = request.form.get('folder_name')
    if folder_name:
        new_folder = Folder(name=folder_name)
        db.session.add(new_folder)
        db.session.commit()
    return redirect(url_for('index'))

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return redirect(request.url)
    file = request.files['file']
    folder_id = request.form.get('folder_id')
    if file.filename == '' or not allowed_file(file.filename):
        return redirect(request.url)

    filename = secure_filename(file.filename)
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(filepath)

    # The new process_pdf returns text, a JSON string of elements, and an empty list for captions
    text, elements_json, _ = process_pdf(filepath)
    new_file = PDFFile(filename=filename, text=text, figures=elements_json, captions=json.dumps([]))
    if folder_id:
        new_file.folder_id = folder_id
    db.session.add(new_file)
    db.session.commit()

    return redirect(url_for('index'))

def _get_or_upload_file(app, pdf_file):
    """
    Checks if a file is already uploaded to Gemini and still exists.
    If not, it uploads the file. Returns the Gemini file object.
    """
    client = app.gemini_client
    if pdf_file.gemini_file_id:
        try:
            app.logger.info(f"Checking for existing file {pdf_file.gemini_file_id}...")
            found_file = client.files.get(name=pdf_file.gemini_file_id)
            app.logger.info(f"Found existing file: {found_file.name}")
            return found_file
        except Exception as e:
            app.logger.warning(f"Could not retrieve file {pdf_file.gemini_file_id}. It may have expired. Error: {e}. Re-uploading.")
            pass

    filepath = pathlib.Path(os.path.join(app.config['UPLOAD_FOLDER'], pdf_file.filename))
    app.logger.info(f"Uploading {filepath} to Gemini...")
    uploaded_file = client.files.upload(file=filepath)
    pdf_file.gemini_file_id = uploaded_file.name
    db.session.commit()
    app.logger.info(f"File uploaded successfully. New file ID: {uploaded_file.name}")
    return uploaded_file


def _run_summary_generation(app, task_id, file_id):
    """Worker function to run summary generation in the background using NanoGPT."""
    with app.app_context():
        try:
            task = Task.query.get(task_id)
            if not task:
                app.logger.error(f"Task {task_id} not found in database.")
                return

            pdf_file = PDFFile.query.get(file_id)
            settings = get_settings()

            if not hasattr(app, 'text_client') or not app.text_client:
                raise Exception("NanoGPT text client not initialized. Please set API key in settings.")

            # Use the extracted text from the PDF instead of uploading
            prompt = settings.summary_prompt
            model_name = settings.summary_model

            app.logger.info(f"Task {task_id}: Generating summary with {model_name}...")
            
            response_text = generate_text_with_file(
                app.text_client,
                model_name,
                pdf_file.text,
                prompt,
                "You are a helpful research assistant that summarizes documents clearly."
            )

            pdf_file.summary = response_text
            task.status = 'complete'
            task.result = json.dumps({'success': True})
            db.session.commit()
            app.logger.info(f"Task {task_id}: Summary saved for file_id {file_id}.")

        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Task {task_id}: Error generating summary for file_id {file_id}: {e}")
            task = Task.query.get(task_id)
            if task:
                task.status = 'error'
                task.result = json.dumps({'error': str(e)})
                db.session.commit()

@app.route('/summarize_file/<int:file_id>', methods=['POST'])
def summarize_file(file_id):
    task_id = str(uuid.uuid4())
    new_task = Task(id=task_id, status='processing')
    db.session.add(new_task)
    db.session.commit()

    thread = threading.Thread(target=_run_summary_generation, args=(app, task_id, file_id))
    thread.start()

    return jsonify({'task_id': task_id}), 202

def _get_task_status_response(task_id):
    """Helper function to get task status and clean up completed tasks."""
    task = Task.query.get_or_404(task_id)
    response_data = {
        'status': task.status,
        'result': json.loads(task.result) if task.result else None
    }
    if task.status in ['complete', 'error']:
        db.session.delete(task)
        db.session.commit()
    return jsonify(response_data)

@app.route('/summarize_status/<task_id>')
def summarize_status(task_id):
    return _get_task_status_response(task_id)


@app.route('/file_content/<int:file_id>')
def file_content(file_id):
    pdf_file = PDFFile.query.get_or_404(file_id)
    audio_url = None
    mp3_filename = f"dialogue_{file_id}.mp3"
    mp3_filepath = os.path.join(app.config['GENERATED_AUDIO_FOLDER'], mp3_filename)
    if os.path.exists(mp3_filepath):
        audio_url = url_for('generated_audio', filename=mp3_filename)

    return {
        'summary': pdf_file.summary,
        'transcript': pdf_file.transcript,
        'chat_history': json.loads(pdf_file.chat_history or '[]'),
        'audio_url': audio_url
    }

def _run_transcript_generation(app, task_id, file_id):
    """Worker function to run transcript generation in the background using NanoGPT."""
    with app.app_context():
        try:
            task = Task.query.get(task_id)
            if not task:
                app.logger.error(f"Task {task_id} not found in database.")
                return

            pdf_file = PDFFile.query.get(file_id)
            settings = get_settings()

            if not hasattr(app, 'text_client') or not app.text_client:
                raise Exception("NanoGPT text client not initialized. Please set API key in settings.")

            transcript_model_name = settings.transcript_model
            app.logger.info(f"Task {task_id}: Generating transcript with {transcript_model_name}...")
            
            transcript_text = generate_text_with_file(
                app.text_client,
                transcript_model_name,
                pdf_file.text,
                settings.transcript_prompt,
                "You are a helpful research assistant that creates engaging podcast scripts from documents."
            )
            
            pdf_file.transcript = transcript_text

            task.status = 'complete'
            task.result = json.dumps({'success': True, 'transcript': transcript_text})
            db.session.commit()
            app.logger.info(f"Task {task_id}: Transcript saved for file_id {file_id}.")

        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Task {task_id}: Error generating transcript for file_id {file_id}: {e}")
            task = Task.query.get(task_id)
            if task:
                task.status = 'error'
                task.result = json.dumps({'error': str(e)})
                db.session.commit()

def _run_podcast_generation(app, task_id, file_id):
    """Worker function to run podcast audio generation in the background using DeepInfra Kokoro."""
    with app.app_context():
        try:
            task = Task.query.get(task_id)
            if not task:
                app.logger.error(f"Task {task_id} not found in database.")
                return

            pdf_file = PDFFile.query.get(file_id)
            settings = get_settings()

            if not pdf_file.transcript:
                raise Exception("Transcript not found for this file.")

            if not hasattr(app, 'tts_client') or not app.tts_client:
                raise Exception("DeepInfra TTS client not initialized. Please set API key in settings.")

            transcript = pdf_file.transcript
            app.logger.info(f"Task {task_id}: Generating audio from transcript for file {file_id} using DeepInfra Kokoro...")
            
            # Get voice settings - use defaults if not set
            host_voice = settings.tts_host_voice or 'af_bella'
            expert_voice = settings.tts_expert_voice or 'am_onyx'
            
            # Generate podcast audio with two voices
            combined_audio = generate_podcast_audio(
                app.tts_client, 
                transcript, 
                host_voice, 
                expert_voice,
                speed=1.0
            )
            
            # Export to MP3
            mp3_filename = f"dialogue_{file_id}.mp3"
            mp3_filepath = os.path.join(app.config['GENERATED_AUDIO_FOLDER'], mp3_filename)
            combined_audio.export(mp3_filepath, format="mp3")

            audio_url = url_for('generated_audio', filename=mp3_filename)

            task.status = 'complete'
            task.result = json.dumps({'audio_url': audio_url})
            db.session.commit()
            app.logger.info(f"Task {task_id}: Podcast audio saved for file_id {file_id}.")

        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Task {task_id}: Error generating podcast for file_id {file_id}: {e}")
            task = Task.query.get(task_id)
            if task:
                task.status = 'error'
                task.result = json.dumps({'error': str(e)})
                db.session.commit()

@app.route('/generate_transcript/<int:file_id>', methods=['POST'])
def generate_transcript(file_id):
    task_id = str(uuid.uuid4())
    new_task = Task(id=task_id, status='processing')
    db.session.add(new_task)
    db.session.commit()

    thread = threading.Thread(target=_run_transcript_generation, args=(app, task_id, file_id))
    thread.start()

    return jsonify({'task_id': task_id}), 202

@app.route('/transcript_status/<task_id>')
def transcript_status(task_id):
    return _get_task_status_response(task_id)

@app.route('/generate_podcast/<int:file_id>', methods=['POST'])
def generate_podcast(file_id):
    task_id = str(uuid.uuid4())
    new_task = Task(id=task_id, status='processing')
    db.session.add(new_task)
    db.session.commit()
    thread = threading.Thread(target=_run_podcast_generation, args=(app, task_id, file_id))
    thread.start()
    return jsonify({'task_id': task_id}), 202

@app.route('/podcast_status/<task_id>')
def podcast_status(task_id):
    return _get_task_status_response(task_id)


def _generate_chat_response(uploaded_file, history, question, model_name, client, app_logger):
    """Generates a chat response using the File API."""
    system_prompt = {
        "role": "system",
        "parts": [
            "You are a helpful research assistant. Your task is to answer questions based "
            "solely on the content of the attached file. Do not use any external knowledge. "
            "If the answer cannot be found within the document, state that clearly. "
            "The user is having a conversation with you, so maintain context from the history. "
            "Format your answers clearly using Markdown where appropriate (e.g., lists, bold text)."
        ]
    }

    full_conversation = [system_prompt] + history + [{'role': 'user', 'parts': [question]}]

    try:
        response = client.models.generate_content(
            model=model_name,
            contents=[uploaded_file] + full_conversation
        )
        return response.text
    except Exception as e:
        app_logger.error(f"Error generating chat response: {e}")
        return f"Error: Could not generate a response. Details: {str(e)}"


@app.route('/chat/<int:file_id>', methods=['POST'])
def chat_with_file(file_id):
    pdf_file = PDFFile.query.get_or_404(file_id)
    data = request.get_json()
    if not data or 'message' not in data:
        return jsonify({'error': 'Message is required in the request body.'}), 400

    question = data['message']
    # Load history from the database
    history = json.loads(pdf_file.chat_history or '[]')

    if not hasattr(app, 'text_client') or not app.text_client:
        return jsonify({'error': 'NanoGPT text client not initialized. Please set API key in settings.'}), 500

    settings = get_settings()
    model_name = settings.chat_model

    try:
        # Build conversation history in NanoGPT format
        messages = [
            {"role": "system", "content": "You are a helpful research assistant. Your task is to answer questions based solely on the content of the attached document. Do not use any external knowledge. If the answer cannot be found within the document, state that clearly."}
        ]
        
        # Add document content as context
        messages.append({
            "role": "user", 
            "content": f"Here is the document content:\n\n{pdf_file.text}\n\n---\n\nPlease answer questions about this document."
        })
        
        # Add chat history
        for msg in history:
            role = msg.get('role', 'user')
            if role == 'model':
                role = 'assistant'
            messages.append({"role": role, "content": msg.get('parts', [{}])[0].get('text', '')})
        
        # Add current question
        messages.append({"role": "user", "content": question})
        
        # Generate response
        response = app.text_client.chat.completions.create(
            model=model_name,
            messages=messages
        )
        
        response_text = response.choices[0].message.content

        # Update history and save to database
        history.append({'role': 'user', 'parts': [{'text': question}]})
        history.append({'role': 'model', 'parts': [{'text': response_text}]})
        pdf_file.chat_history = json.dumps(history)
        db.session.commit()

        return jsonify({'message': response_text})
    except Exception as e:
        app.logger.error(f"Chat generation failed for file_id {file_id}: {e}")
        return jsonify({'error': f'Could not generate a response. Details: {str(e)}'}), 500


@app.route('/settings', methods=['GET', 'POST'])
def settings():
    settings = get_settings()
    if request.method == 'POST':
        settings.gemini_api_key = request.form.get('gemini_api_key')
        settings.nanogpt_api_key = request.form.get('nanogpt_api_key')
        settings.deepinfra_api_key = request.form.get('deepinfra_api_key')
        settings.summary_model = request.form.get('summary_model')
        settings.transcript_model = request.form.get('transcript_model')
        settings.chat_model = request.form.get('chat_model')
        settings.tts_model = request.form.get('tts_model')
        settings.tts_host_voice = request.form.get('tts_host_voice')
        settings.tts_expert_voice = request.form.get('tts_expert_voice')
        settings.summary_prompt = request.form.get('summary_prompt')
        settings.transcript_prompt = request.form.get('transcript_prompt')
        db.session.commit()
        init_tts_client(app)
        init_text_client(app)
        return redirect(url_for('settings'))

    return render_template('settings.html', 
                           settings=settings,
                           text_models=available_text_models,
                           tts_models=available_tts_models,
                           voices=available_voices)

# --- Static File Routes ---
@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/file_details/<int:file_id>')
def file_details(file_id):
    pdf_file = PDFFile.query.get_or_404(file_id)
    # The 'figures' column now stores a JSON string of 'elements' (figures and tables)
    elements = json.loads(pdf_file.figures or '[]')
    return jsonify({
        'id': pdf_file.id,
        'filename': pdf_file.filename,
        'elements': elements
    })

@app.route('/generated_audio/<filename>')
def generated_audio(filename):
    return send_from_directory(app.config['GENERATED_AUDIO_FOLDER'], filename)

@app.route('/delete_file/<int:file_id>', methods=['DELETE'])
def delete_file(file_id):
    pdf_file = PDFFile.query.get_or_404(file_id)

    # Store file paths before deleting the database record
    pdf_path = os.path.join(app.config['UPLOAD_FOLDER'], pdf_file.filename)
    mp3_filename = f"dialogue_{file_id}.mp3"
    mp3_filepath = os.path.join(app.config['GENERATED_AUDIO_FOLDER'], mp3_filename)

    # Delete from database first
    db.session.delete(pdf_file)
    db.session.commit()
    app.logger.info(f"Deleted file_id {file_id} from database.")

    # Then, delete the physical files
    try:
        if os.path.exists(pdf_path):
            os.remove(pdf_path)
            app.logger.info(f"Deleted PDF file: {pdf_path}")
        if os.path.exists(mp3_filepath):
            os.remove(mp3_filepath)
            app.logger.info(f"Deleted audio file: {mp3_filepath}")
    except Exception as e:
        # Log the error, but don't return an error response to the client
        # because the database record is already gone.
        app.logger.error(f"Error deleting physical files for what was file_id {file_id}: {e}")

    return {'success': True}

@app.route('/rename_file/<int:file_id>', methods=['POST'])
def rename_file(file_id):
    pdf_file = PDFFile.query.get_or_404(file_id)
    new_filename_req = request.json.get('new_filename')
    if not new_filename_req:
        return {'error': 'New filename is required'}, 400

    new_filename = new_filename_req if new_filename_req.lower().endswith('.pdf') else f"{new_filename_req}.pdf"

    original_filename = pdf_file.filename
    old_pdf_path = os.path.join(app.config['UPLOAD_FOLDER'], original_filename)
    new_pdf_path = os.path.join(app.config['UPLOAD_FOLDER'], new_filename)

    if os.path.exists(new_pdf_path):
        return {'error': 'A file with this name already exists'}, 400

    # Figure directory paths
    old_fig_dir_basename = os.path.splitext(original_filename)[0]
    new_fig_dir_basename = os.path.splitext(new_filename)[0]
    old_fig_dir = os.path.join('static', 'figures', old_fig_dir_basename)
    new_fig_dir = os.path.join('static', 'figures', new_fig_dir_basename)

    # --- Start Transaction ---
    try:
        # 1. Rename PDF file
        os.rename(old_pdf_path, new_pdf_path)
        app.logger.info(f"Renamed PDF {old_pdf_path} to {new_pdf_path}")

        # 2. Rename figures directory if it exists
        if os.path.isdir(old_fig_dir):
            os.rename(old_fig_dir, new_fig_dir)
            app.logger.info(f"Renamed figures dir {old_fig_dir} to {new_fig_dir}")

        # 3. Update database
        pdf_file.filename = new_filename
        if pdf_file.figures:
            figures_list = json.loads(pdf_file.figures)
            updated_figures = [p.replace(f"static/figures/{old_fig_dir_basename}", f"static/figures/{new_fig_dir_basename}", 1) for p in figures_list]
            pdf_file.figures = json.dumps(updated_figures)

        db.session.commit()
        app.logger.info(f"Updated database for file_id {file_id} to new name {new_filename}")

        return {
            'success': True,
            'new_filename': new_filename,
            'new_url': url_for('uploaded_file', filename=new_filename)
        }

    except (OSError, SQLAlchemyError) as e:
        db.session.rollback()
        app.logger.error(f"Error during rename for file_id {file_id}: {e}. Rolling back changes.")

        # Attempt to roll back filesystem changes
        if os.path.exists(new_pdf_path) and not os.path.exists(old_pdf_path):
            try:
                os.rename(new_pdf_path, old_pdf_path)
                app.logger.info(f"Rolled back PDF rename from {new_pdf_path} to {old_pdf_path}")
            except OSError as rollback_e:
                app.logger.critical(f"CRITICAL: Filesystem rollback failed for PDF. Path: {new_pdf_path}. DB rolled back. Error: {rollback_e}")

        if os.path.exists(new_fig_dir) and not os.path.exists(old_fig_dir):
            try:
                os.rename(new_fig_dir, old_fig_dir)
                app.logger.info(f"Rolled back figures dir rename from {new_fig_dir} to {old_fig_dir}")
            except OSError as rollback_e:
                app.logger.critical(f"CRITICAL: Filesystem rollback failed for figures dir. Path: {new_fig_dir}. DB rolled back. Error: {rollback_e}")

        return {'error': 'An error occurred during the rename operation. All changes have been reverted.'}, 500

@app.route('/move_file/<int:file_id>', methods=['POST'])
def move_file(file_id):
    pdf_file = PDFFile.query.get_or_404(file_id)
    new_folder_id = request.json.get('new_folder_id')

    if new_folder_id == 'root':
        pdf_file.folder_id = None
    else:
        target_folder = Folder.query.get_or_404(new_folder_id)
        pdf_file.folder_id = target_folder.id

    db.session.commit()
    app.logger.info(f"Moved file_id {file_id} to folder_id {new_folder_id}.")
    return {'success': True}

@app.route('/delete_folder/<int:folder_id>', methods=['DELETE'])
def delete_folder(folder_id):
    folder = Folder.query.get_or_404(folder_id)

    if folder.files:
        return {'error': 'Cannot delete a folder that is not empty.'}, 400

    db.session.delete(folder)
    db.session.commit()
    app.logger.info(f"Deleted folder_id {folder_id}.")
    return {'success': True}

@app.route('/rename_folder/<int:folder_id>', methods=['POST'])
def rename_folder(folder_id):
    folder = Folder.query.get_or_404(folder_id)
    new_name = request.json.get('new_name')
    if not new_name:
        return {'error': 'New folder name is required'}, 400

    original_name = folder.name
    folder.name = new_name
    try:
        db.session.commit()
        app.logger.info(f"Renamed folder_id {folder_id} from '{original_name}' to '{new_name}'.")
        return {'success': True, 'new_name': new_name}
    except IntegrityError:
        db.session.rollback()
        folder.name = original_name  # Revert the name in the object
        app.logger.warning(f"Failed to rename folder_id {folder_id} to '{new_name}' because the name already exists.")
        return {'error': 'A folder with this name already exists.'}, 400

@app.route('/play_voice_sample', methods=['POST'])
def play_voice_sample():
    data = request.get_json()
    voice = data.get('voice')
    if not voice:
        return jsonify({'error': 'Voice parameter is required'}), 400

    if not hasattr(app, 'tts_client') or not app.tts_client:
         return jsonify({'error': 'DeepInfra TTS client not initialized. Please set API key in settings.'}), 500

    sample_text = "Hello, this is a sample of the selected voice."
    samples_folder = os.path.join(app.config['GENERATED_AUDIO_FOLDER'], 'samples')
    os.makedirs(samples_folder, exist_ok=True)

    # Sanitize voice name for filename
    safe_filename = re.sub(r'[^a-zA-Z0-9_-]', '_', voice)
    mp3_filename = f"{safe_filename}.mp3"
    mp3_filepath = os.path.join(samples_folder, mp3_filename)

    if not os.path.exists(mp3_filepath):
        try:
            app.logger.info(f"Generating voice sample for '{voice}'...")

            audio_data, _ = generate_voice_sample(app.tts_client, voice, sample_text)

            audio = AudioSegment.from_file(io.BytesIO(audio_data), format="mp3")
            audio.export(mp3_filepath, format="mp3")
            app.logger.info(f"Saved voice sample to {mp3_filepath}")

        except Exception as e:
            app.logger.error(f"Error generating voice sample for '{voice}': {e}")
            return jsonify({'error': str(e)}), 500

    audio_url = url_for('generated_audio', filename=f'samples/{mp3_filename}')
    return jsonify({'audio_url': audio_url})


# --- App Initialization ---
init_tts_client(app)
init_text_client(app)

if __name__ == '__main__':
    app.run(debug=True)
