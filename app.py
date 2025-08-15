import os
import json
import pathlib
import re
import uuid
import threading
from flask import Flask, render_template, request, redirect, url_for, send_from_directory, jsonify, Response, stream_with_context
from werkzeug.utils import secure_filename
from pydub import AudioSegment
from google.genai import types
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from database import db, init_db, Folder, PDFFile, Settings, get_settings, Task
from services import (
    init_gemini_client,
    process_pdf,
    allowed_file,
    available_text_models,
    available_tts_models,
    available_voices,
)

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

    text, figures, captions = process_pdf(filepath)
    new_file = PDFFile(filename=filename, text=text, figures=figures, captions=captions)
    if folder_id:
        new_file.folder_id = folder_id
    db.session.add(new_file)
    db.session.commit()

    return redirect(url_for('index'))

@app.route('/cache_file/<int:file_id>', methods=['POST'])
def cache_file(file_id):
    pdf_file = PDFFile.query.get_or_404(file_id)
    if pdf_file.cached_content_name:
        return jsonify({'status': 'already_cached', 'cache_name': pdf_file.cached_content_name})

    if not app.gemini_client:
        return jsonify({'error': 'Gemini client not initialized.'}), 500

    try:
        filepath = pathlib.Path(os.path.join(app.config['UPLOAD_FOLDER'], pdf_file.filename))
        app.logger.info(f"Uploading {filepath} to Gemini File API...")
        uploaded_file = app.gemini_client.files.upload(file=filepath)

        app.logger.info(f"Creating cache for {uploaded_file.name}...")
        # Note: The model for the cache must match the model used for generation.
        # We'll use the summary_model as a default, but this could be a setting.
        settings = get_settings()
        cache = app.gemini_client.caches.create(
            model=f"models/{settings.summary_model}",
            contents=[uploaded_file]
        )

        # The temporary file can be deleted now that the cache is created.
        app.gemini_client.files.delete(name=uploaded_file.name)
        app.logger.info(f"Deleted temporary file {uploaded_file.name} after caching.")

        # Commit the cache name to the database as the final step.
        pdf_file.cached_content_name = cache.name
        db.session.commit()
        app.logger.info(f"Cache created successfully: {cache.name}")

        return jsonify({'status': 'cached', 'cache_name': cache.name})

    except Exception as e:
        app.logger.error(f"Error caching file {file_id}: {e}")
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

def _run_summary_generation(app, task_id, file_id):
    """Worker function to run summary generation in the background."""
    with app.app_context():
        try:
            task = Task.query.get(task_id)
            if not task:
                app.logger.error(f"Task {task_id} not found in database.")
                return

            pdf_file = PDFFile.query.get(file_id)
            settings = get_settings()

            if not app.gemini_client:
                raise Exception("Gemini client not initialized.")
            if not pdf_file.cached_content_name:
                raise Exception(f"File {file_id} is not cached.")

            prompt = settings.summary_prompt
            model_name = f"models/{settings.summary_model}"

            app.logger.info(f"Task {task_id}: Generating summary with {model_name} using cache {pdf_file.cached_content_name}...")
            response = app.gemini_client.models.generate_content(
                model=model_name,
                contents=[prompt],
                config=types.GenerateContentConfig(
                    cached_content=pdf_file.cached_content_name
                )
            )

            pdf_file.summary = response.text
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

@app.route('/summarize_status/<task_id>')
def summarize_status(task_id):
    task = Task.query.get_or_404(task_id)
    response_data = {
        'status': task.status,
        'result': json.loads(task.result) if task.result else None
    }

    if task.status in ['complete', 'error']:
        db.session.delete(task)
        db.session.commit()

    return jsonify(response_data)


@app.route('/file_content/<int:file_id>')
def file_content(file_id):
    pdf_file = PDFFile.query.get_or_404(file_id)
    audio_url = None
    mp3_filename = f"podcast_{file_id}.mp3"
    mp3_filepath = os.path.join(app.config['GENERATED_AUDIO_FOLDER'], mp3_filename)
    if os.path.exists(mp3_filepath):
        audio_url = url_for('generated_audio', filename=mp3_filename)

    return {
        'summary': pdf_file.summary,
        'transcript': pdf_file.transcript,
        'audio_url': audio_url
    }

def _run_transcript_generation(app, task_id, file_id):
    """Worker function to run transcript generation in the background."""
    with app.app_context():
        try:
            task = Task.query.get(task_id)
            pdf_file = PDFFile.query.get(file_id)
            settings = get_settings()

            if not app.gemini_client:
                raise Exception("Gemini client not initialized.")
            if not pdf_file.cached_content_name:
                raise Exception(f"File {file_id} is not cached.")

            model_name = f"models/{settings.transcript_model}"
            app.logger.info(f"Task {task_id}: Generating transcript with {model_name} using cache {pdf_file.cached_content_name}...")
            response = app.gemini_client.models.generate_content(
                model=model_name,
                contents=[settings.transcript_prompt],
                config=types.GenerateContentConfig(
                    cached_content=pdf_file.cached_content_name
                )
            )
            pdf_file.transcript = response.text
            task.status = 'complete'
            task.result = json.dumps({'success': True})
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
    task = Task.query.get_or_404(task_id)
    response_data = {
        'status': task.status,
        'result': json.loads(task.result) if task.result else None
    }
    if task.status in ['complete', 'error']:
        db.session.delete(task)
        db.session.commit()
    return jsonify(response_data)


def _run_podcast_generation(app, task_id, file_id):
    """Worker function to run podcast (TTS) generation in the background."""
    with app.app_context():
        try:
            task = Task.query.get(task_id)
            pdf_file = PDFFile.query.get(file_id)
            settings = get_settings()

            if not app.gemini_client:
                raise Exception("Gemini client not initialized.")
            if not pdf_file.transcript:
                raise Exception(f"No transcript available for file {file_id} to generate podcast.")

            app.logger.info(f"Task {task_id}: Generating audio from transcript...")
            tts_model_name = f"models/{settings.tts_model}"
            tts_response = app.gemini_client.models.generate_content(
                model=tts_model_name,
                contents=[pdf_file.transcript],
                config=types.GenerateContentConfig(
                    response_modalities=["AUDIO"],
                    speech_config=types.SpeechConfig(
                        multi_speaker_voice_config=types.MultiSpeakerVoiceConfig(
                            speaker_voice_configs=[
                                types.SpeakerVoiceConfig(
                                    speaker='Host',
                                    voice_config=types.VoiceConfig(prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=settings.tts_host_voice))
                                ),
                                types.SpeakerVoiceConfig(
                                    speaker='Expert',
                                    voice_config=types.VoiceConfig(prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=settings.tts_expert_voice))
                                ),
                            ]
                        )
                    )
                )
            )
            audio_part = tts_response.candidates[0].content.parts[0]
            audio_data = audio_part.inline_data.data
            mime_type = audio_part.inline_data.mime_type
            match = re.search(r'rate=(\d+)', mime_type)
            sample_rate = int(match.group(1)) if match else 24000
            audio = AudioSegment(data=audio_data, sample_width=2, frame_rate=sample_rate, channels=1)
            mp3_filename = f"podcast_{file_id}.mp3"
            mp3_filepath = os.path.join(app.config['GENERATED_AUDIO_FOLDER'], mp3_filename)
            audio.export(mp3_filepath, format="mp3")

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
    task = Task.query.get_or_404(task_id)
    response_data = {
        'status': task.status,
        'result': json.loads(task.result) if task.result else None
    }
    if task.status in ['complete', 'error']:
        db.session.delete(task)
        db.session.commit()
    return jsonify(response_data)


def _generate_chat_response(cached_content_name, history, question, model_name, client, app_logger):
    """Generator function to stream chat responses using a cached document."""
    system_prompt = (
        "You are a helpful research assistant. Your task is to answer questions based "
        "solely on the content of the document provided in the cache. Do not use any external knowledge. "
        "If the answer cannot be found within the document, state that clearly. "
        "The user is having a conversation with you, so maintain context from the history. "
        "Format your answers clearly using Markdown where appropriate (e.g., lists, bold text)."
    )

    # The context from the cached document is implicitly handled by the API.
    # We build the conversational history.
    contents = [system_prompt]
    for entry in history:
        contents.append({'role': 'user', 'parts': [{'text': entry['user']}]})
        contents.append({'role': 'model', 'parts': [{'text': entry['assistant']}]})
    contents.append({'role': 'user', 'parts': [{'text': question}]})

    try:
        response = client.models.generate_content(
            model=model_name,
            contents=contents,
            stream=True,
            config=types.GenerateContentConfig(
                cached_content=cached_content_name
            )
        )
        for chunk in response:
            if chunk.text:
                yield chunk.text
    except Exception as e:
        app_logger.error(f"Error streaming chat response with cache {cached_content_name}: {e}")
        yield f"Error: Could not generate a response. Details: {str(e)}"


@app.route('/chat/<int:file_id>', methods=['POST'])
def chat_with_file(file_id):
    pdf_file = PDFFile.query.get_or_404(file_id)
    if not pdf_file.cached_content_name:
        return Response("Error: This file has not been cached yet. Please select the file again.", status=400, mimetype='text/plain')

    data = request.get_json()
    if not data or 'message' not in data:
        return Response("Error: Message is required in the request body.", status=400, mimetype='text/plain')

    question = data['message']
    history = data.get('history', [])

    if not hasattr(app, 'gemini_client') or not app.gemini_client:
        return Response("Error: Gemini client not initialized. Please set API key in settings.", status=500, mimetype='text/plain')

    settings = get_settings()
    model_name = f"models/{settings.summary_model}" # Chat will use the same model as summary for cache compatibility

    return Response(stream_with_context(_generate_chat_response(pdf_file.cached_content_name, history, question, model_name, app.gemini_client, app.logger)), mimetype='text/plain')


@app.route('/settings', methods=['GET', 'POST'])
def settings():
    settings = get_settings()
    if request.method == 'POST':
        settings.gemini_api_key = request.form.get('gemini_api_key')
        settings.summary_model = request.form.get('summary_model')
        settings.transcript_model = request.form.get('transcript_model')
        settings.tts_model = request.form.get('tts_model')
        settings.tts_host_voice = request.form.get('tts_host_voice')
        settings.tts_expert_voice = request.form.get('tts_expert_voice')
        settings.summary_prompt = request.form.get('summary_prompt')
        settings.transcript_prompt = request.form.get('transcript_prompt')
        db.session.commit()
        init_gemini_client(app)
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
    return {
        'id': pdf_file.id,
        'filename': pdf_file.filename,
        'figures': json.loads(pdf_file.figures or '[]'),
        'captions': json.loads(pdf_file.captions or '[]')
    }

@app.route('/generated_audio/<filename>')
def generated_audio(filename):
    return send_from_directory(app.config['GENERATED_AUDIO_FOLDER'], filename)

@app.route('/delete_file/<int:file_id>', methods=['DELETE'])
def delete_file(file_id):
    pdf_file = PDFFile.query.get_or_404(file_id)

    # Store info before deleting the database record
    pdf_path = os.path.join(app.config['UPLOAD_FOLDER'], pdf_file.filename)
    mp3_filename = f"podcast_{file_id}.mp3"
    mp3_filepath = os.path.join(app.config['GENERATED_AUDIO_FOLDER'], mp3_filename)
    cached_content_name = pdf_file.cached_content_name

    # Delete from database first
    db.session.delete(pdf_file)
    db.session.commit()
    app.logger.info(f"Deleted file_id {file_id} from database.")

    # Then, delete the physical files and remote cache
    try:
        if os.path.exists(pdf_path):
            os.remove(pdf_path)
            app.logger.info(f"Deleted PDF file: {pdf_path}")
        if os.path.exists(mp3_filepath):
            os.remove(mp3_filepath)
            app.logger.info(f"Deleted audio file: {mp3_filepath}")
        if cached_content_name and app.gemini_client:
            app.gemini_client.caches.delete(name=cached_content_name)
            app.logger.info(f"Deleted Gemini cache: {cached_content_name}")

    except Exception as e:
        # Log the error, but don't return an error response to the client
        # because the database record is already gone.
        app.logger.error(f"Error during physical/remote deletion for what was file_id {file_id}: {e}")

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


# --- App Initialization ---
init_gemini_client(app)

if __name__ == '__main__':
    app.run(debug=True)
