import os
import json
import pathlib
import re
from flask import Flask, render_template, request, redirect, url_for, send_from_directory
from werkzeug.utils import secure_filename
from pydub import AudioSegment
from google.genai import types
from sqlalchemy.exc import SQLAlchemyError
from database import db, init_db, Folder, PDFFile, Settings, get_settings
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

@app.route('/summarize_file/<int:file_id>', methods=['POST'])
def summarize_file(file_id):
    pdf_file = PDFFile.query.get_or_404(file_id)
    settings = get_settings()

    if not app.gemini_client:
        return {'error': 'Gemini client is not initialized. Please check the API key in settings.'}, 500

    uploaded_file = None
    try:
        filepath = pathlib.Path(os.path.join(app.config['UPLOAD_FOLDER'], pdf_file.filename))
        app.logger.info(f"Uploading {filepath} to Gemini File API...")
        uploaded_file = app.gemini_client.files.upload(file=filepath)

        prompt = settings.summary_prompt
        model_name = f"models/{settings.summary_model}"
        
        app.logger.info(f"Generating summary with model {model_name}...")
        response = app.gemini_client.models.generate_content(
            model=model_name,
            contents=[uploaded_file, prompt]
        )
        
        pdf_file.summary = response.text
        db.session.commit()
        app.logger.info(f"Summary saved for file_id {file_id}.")

        return {'success': True, 'redirect_url': url_for('view_summary', file_id=file_id)}

    except Exception as e:
        app.logger.error(f"Error generating summary for file_id {file_id}: {e}")
        return {'error': f'An error occurred: {e}'}, 500
    finally:
        if uploaded_file:
            app.logger.info(f"Deleting uploaded file {uploaded_file.name} from Gemini server.")
            app.gemini_client.files.delete(name=uploaded_file.name)


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
        'dialogue_transcript': pdf_file.dialogue_transcript,
        'audio_url': audio_url
    }

@app.route('/generate_dialogue/<int:file_id>', methods=['POST'])
def generate_dialogue(file_id):
    pdf_file = PDFFile.query.get_or_404(file_id)
    settings = get_settings()

    if not app.gemini_client:
        return {'error': 'Gemini client is not initialized. Please check API key.'}, 500

    uploaded_file = None
    try:
        filepath = pathlib.Path(os.path.join(app.config['UPLOAD_FOLDER'], pdf_file.filename))
        app.logger.info(f"Uploading {filepath} to Gemini File API for dialogue generation...")
        uploaded_file = app.gemini_client.files.upload(file=filepath)

        dialogue_model_name = f"models/{settings.dialogue_model}"
        app.logger.info(f"Generating transcript with model {dialogue_model_name}...")
        transcript_response = app.gemini_client.models.generate_content(
            model=dialogue_model_name,
            contents=[uploaded_file, settings.dialogue_prompt]
        )
        transcript = transcript_response.text

        pdf_file.dialogue_transcript = transcript
        db.session.commit()
        app.logger.info(f"Transcript saved for file_id {file_id}.")

        app.logger.info(f"Generating audio from transcript...")
        tts_model_name = f"models/{settings.tts_model}"
        tts_config = types.GenerateContentConfig(
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
        
        tts_response = app.gemini_client.models.generate_content(
            model=tts_model_name,
            contents=[transcript],
            config=tts_config
        )
        
        audio_part = tts_response.candidates[0].content.parts[0]
        audio_data = audio_part.inline_data.data
        mime_type = audio_part.inline_data.mime_type
        
        match = re.search(r'rate=(\d+)', mime_type)
        sample_rate = int(match.group(1)) if match else 24000

        audio = AudioSegment(data=audio_data, sample_width=2, frame_rate=sample_rate, channels=1)
        
        mp3_filename = f"dialogue_{file_id}.mp3"
        mp3_filepath = os.path.join(app.config['GENERATED_AUDIO_FOLDER'], mp3_filename)
        audio.export(mp3_filepath, format="mp3")

        audio_url = url_for('generated_audio', filename=mp3_filename)
        return {'audio_url': audio_url, 'transcript': pdf_file.dialogue_transcript}

    except Exception as e:
        app.logger.error(f"Error generating dialogue for file_id {file_id}: {e}")
        return {'error': f'An error occurred: {e}'}, 500
    finally:
        if uploaded_file:
            app.logger.info(f"Deleting uploaded file {uploaded_file.name} from Gemini server.")
            app.gemini_client.files.delete(name=uploaded_file.name)


@app.route('/settings', methods=['GET', 'POST'])
def settings():
    settings = get_settings()
    if request.method == 'POST':
        settings.gemini_api_key = request.form.get('gemini_api_key')
        settings.summary_model = request.form.get('summary_model')
        settings.dialogue_model = request.form.get('dialogue_model')
        settings.tts_model = request.form.get('tts_model')
        settings.tts_host_voice = request.form.get('tts_host_voice')
        settings.tts_expert_voice = request.form.get('tts_expert_voice')
        settings.summary_prompt = request.form.get('summary_prompt')
        settings.dialogue_prompt = request.form.get('dialogue_prompt')
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
    new_filename = request.json.get('new_filename')
    if not new_filename:
        return {'error': 'New filename is required'}, 400

    if not new_filename.lower().endswith('.pdf'):
        new_filename += '.pdf'

    original_filename = pdf_file.filename
    old_path = os.path.join(app.config['UPLOAD_FOLDER'], original_filename)
    new_path = os.path.join(app.config['UPLOAD_FOLDER'], new_filename)

    if os.path.exists(new_path):
        return {'error': 'A file with this name already exists'}, 400

    # 1. Rename the physical file
    try:
        os.rename(old_path, new_path)
        app.logger.info(f"Renamed {old_path} to {new_path}")
    except OSError as e:
        app.logger.error(f"Error renaming physical file for file_id {file_id}: {e}")
        return {'error': 'Failed to rename file on disk'}, 500

    # 2. Try to update the filename in the database
    try:
        pdf_file.filename = new_filename
        db.session.commit()
        app.logger.info(f"Renamed file_id {file_id} to {new_filename} in database.")
        return {'success': True, 'new_filename': new_filename}
    except SQLAlchemyError as e:
        db.session.rollback()
        app.logger.error(f"Database error renaming file_id {file_id}, rolling back: {e}")

        # 3. Attempt to roll back the physical file rename
        try:
            os.rename(new_path, old_path)
            app.logger.info(f"Successfully rolled back file rename from {new_path} to {old_path}")
        except OSError as rollback_e:
            app.logger.critical(
                f"CRITICAL: Failed to roll back file rename for file_id {file_id}. "
                f"File is at {new_path} but DB has {original_filename}. Manual intervention required. "
                f"Rollback error: {rollback_e}"
            )
            return {'error': 'A critical error occurred: Database update failed and filesystem rollback also failed. Please contact support.'}, 500

        return {'error': 'Failed to update file record in the database. The file rename has been reverted.'}, 500

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

    folder.name = new_name
    db.session.commit()
    app.logger.info(f"Renamed folder_id {folder_id} to {new_name}.")
    return {'success': True, 'new_name': new_name}


# --- App Initialization ---
init_gemini_client(app)

if __name__ == '__main__':
    app.run(debug=True)
