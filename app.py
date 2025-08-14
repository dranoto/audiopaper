import os
import json
import fitz  # PyMuPDF
from google import genai
from google.genai import types
import io
import re
import pathlib
from flask import Flask, render_template, request, redirect, url_for, send_from_directory
from werkzeug.utils import secure_filename
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.exc import IntegrityError
from pydub import AudioSegment

# --- App and DB Setup ---
app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['GENERATED_AUDIO_FOLDER'] = 'generated_audio'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///db.sqlite3'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
ALLOWED_EXTENSIONS = {'pdf'}

db = SQLAlchemy(app)

# --- Global lists for models and voices ---
available_text_models = []
available_tts_models = []
# The Gemini API does not currently provide an endpoint to list voices,
# so we are using a hardcoded list of available prebuilt voices.
available_voices = [
    'Zephyr', 'Puck', 'Charon', 'Kore', 'Fenrir', 'Leda', 'Orus', 'Aoede', 
    'Callirrhoe', 'Autonoe', 'Enceladus', 'Iapetus', 'Umbriel', 'Algieba', 
    'Despina', 'Erinome', 'Algenib', 'Rasalgethi', 'Laomedeia', 'Achernar', 
    'Alnilam', 'Schedar', 'Gacrux', 'Pulcherrima', 'Achird', 'Zubenelgenubi', 
    'Vindemiatrix', 'Sadachbia', 'Sadaltager', 'Sulafat'
]


# --- Database Models ---
class Folder(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    files = db.relationship('PDFFile', backref='folder', lazy=True)

    def __repr__(self):
        return f'<Folder {self.name}>'

class PDFFile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(100), unique=True, nullable=False)
    text = db.Column(db.Text, nullable=False)
    figures = db.Column(db.Text)
    captions = db.Column(db.Text)
    summary = db.Column(db.Text, nullable=True)
    dialogue_transcript = db.Column(db.Text, nullable=True)
    folder_id = db.Column(db.Integer, db.ForeignKey('folder.id'), nullable=True)

    def __repr__(self):
        return f'<PDFFile {self.filename}>'

class Settings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    lock = db.Column(db.String(10), unique=True, default='main_settings', nullable=False)
    gemini_api_key = db.Column(db.String(200), nullable=True)
    summary_model = db.Column(db.String(100), nullable=False, default='gemini-1.5-pro-latest')
    dialogue_model = db.Column(db.String(100), nullable=False, default='gemini-1.5-pro-latest')
    tts_model = db.Column(db.String(100), nullable=False, default='gemini-2.5-flash-preview-tts')
    tts_host_voice = db.Column(db.String(100), nullable=False, default='Kore')
    tts_expert_voice = db.Column(db.String(100), nullable=False, default='Puck')
    summary_prompt = db.Column(db.Text, nullable=False, default='Summarize this research paper. Provide a concise overview of the introduction, methods, key findings, and conclusion.')

    def __repr__(self):
        return f'<Settings {self.id}>'

# --- Initial Setup ---
with app.app_context():
    db.create_all()

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['GENERATED_AUDIO_FOLDER'], exist_ok=True)

# --- Helper Functions ---
def get_settings():
    settings = Settings.query.first()
    if settings:
        return settings
    try:
        settings = Settings()
        db.session.add(settings)
        db.session.commit()
        return settings
    except IntegrityError:
        db.session.rollback()
        return Settings.query.first()

def init_gemini_client(app_instance):
    global available_text_models, available_tts_models
    with app_instance.app_context():
        settings = get_settings()
        api_key = settings.gemini_api_key or os.environ.get('GEMINI_API_KEY')
        if api_key:
            try:
                client = genai.Client(api_key=api_key)
                app_instance.gemini_client = client
                app_instance.logger.info("Gemini Client initialized successfully.")
                
                # Fetch and filter models
                available_text_models.clear()
                available_tts_models.clear()
                for model in client.models.list():
                    model_name = model.name.replace("models/", "")
                    if 'generateContent' in model.supported_actions:
                         # Heuristic to separate TTS from other generative models
                        if 'tts' in model_name:
                            available_tts_models.append(model_name)
                        else:
                            available_text_models.append(model_name)
                
                available_text_models = sorted(available_text_models)
                available_tts_models = sorted(available_tts_models)
                app_instance.logger.info(f"Found {len(available_text_models)} text models and {len(available_tts_models)} TTS models.")

            except Exception as e:
                app_instance.gemini_client = None
                app_instance.logger.error(f"Failed to initialize Gemini Client or fetch models: {e}")
        else:
            app_instance.gemini_client = None
            app_instance.logger.warning("Gemini API key not found. Generative features will be disabled.")


def process_pdf(filepath):
    doc = fitz.open(filepath)
    text = ""
    figures = []
    captions = []
    figure_dir = os.path.join('static', 'figures', os.path.basename(filepath).replace('.pdf', ''))
    os.makedirs(figure_dir, exist_ok=True)

    for page_num in range(len(doc)):
        page = doc.load_page(page_num)
        text += page.get_text()
        text_blocks = page.get_text("blocks")
        image_list = page.get_images(full=True)

        for img_index, img in enumerate(image_list):
            xref = img[0]
            try:
                img_bbox = page.get_image_bbox(img)
            except ValueError:
                continue

            base_image = doc.extract_image(xref)
            image_bytes = base_image["image"]
            image_ext = base_image["ext"]
            image_filename = f"image_{page_num+1}_{img_index}.{image_ext}"
            image_path = os.path.join(figure_dir, image_filename)

            with open(image_path, "wb") as f:
                f.write(image_bytes)
            figures.append(image_path)

            found_caption = ""
            for tb in text_blocks:
                text_bbox = fitz.Rect(tb[:4])
                if text_bbox.y0 > img_bbox.y1 and (text_bbox.y0 - img_bbox.y1) < 50:
                    text_center_x = (text_bbox.x0 + text_bbox.x1) / 2
                    if img_bbox.x0 < text_center_x < img_bbox.x1 and tb[4].strip().lower().startswith(('figure', 'fig.')):
                        found_caption = tb[4].strip().replace('\n', ' ')
                        break
            captions.append(found_caption if found_caption else f"Figure {len(figures)}")

    return text, json.dumps(figures), json.dumps(captions)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

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


@app.route('/summary/<int:file_id>')
def view_summary(file_id):
    pdf_file = PDFFile.query.get_or_404(file_id)
    return render_template('summary.html', file=pdf_file)

@app.route('/generate_dialogue/<int:file_id>')
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

        transcript_prompt = f"""
        Generate a podcast-style dialogue script based on the attached document.
        The script should be a conversation between a 'Host' and an 'Expert'.
        The Host should ask engaging questions, and the Expert should explain the key concepts from the document clearly.
        Start each line with the speaker's name followed by a colon (e.g., "Host: ...").
        """
        dialogue_model_name = f"models/{settings.dialogue_model}"
        app.logger.info(f"Generating transcript with model {dialogue_model_name}...")
        transcript_response = app.gemini_client.models.generate_content(
            model=dialogue_model_name,
            contents=[uploaded_file, transcript_prompt]
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

# --- App Initialization ---
init_gemini_client(app)

if __name__ == '__main__':
    app.run(debug=True)
