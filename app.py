import os
from flask import Flask, render_template, request, redirect, url_for, send_from_directory
from werkzeug.utils import secure_filename
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.exc import IntegrityError
import json
import fitz # PyMuPDF
from google import genai
from google.genai import types
import io
import wave
import pathlib
from pydub import AudioSegment

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['GENERATED_AUDIO_FOLDER'] = 'generated_audio'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///db.sqlite3'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
ALLOWED_EXTENSIONS = {'pdf'}

db = SQLAlchemy(app)

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
    figures = db.Column(db.Text)  # JSON-encoded list of figure paths
    captions = db.Column(db.Text)  # JSON-encoded list of captions
    summary = db.Column(db.Text, nullable=True)
    dialogue_transcript = db.Column(db.Text, nullable=True)
    folder_id = db.Column(db.Integer, db.ForeignKey('folder.id'), nullable=True)

    def __repr__(self):
        return f'<PDFFile {self.filename}>'

class Settings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    lock = db.Column(db.String(10), unique=True, default='main_settings', nullable=False)
    gemini_api_key = db.Column(db.String(200), nullable=True)
    summary_model = db.Column(db.String(100), nullable=False, default='gemini-pro')
    dialogue_model = db.Column(db.String(100), nullable=False, default='gemini-pro')
    tts_host_voice = db.Column(db.String(100), nullable=False, default='Kore')
    tts_expert_voice = db.Column(db.String(100), nullable=False, default='Puck')
    summary_prompt = db.Column(db.Text, nullable=True, default='Summarize this document as a list of the most important takeaways.')

    def __repr__(self):
        return f'<Settings {self.id}>'

with app.app_context():
    db.create_all()

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['GENERATED_AUDIO_FOLDER'], exist_ok=True)

def get_settings():
    settings = Settings.query.first()
    if settings:
        return settings

    # To prevent race conditions in a multi-process environment like gunicorn,
    # we'll try to create the settings row, but expect that it might fail
    # if another process created it first.
    try:
        settings = Settings()
        db.session.add(settings)
        db.session.commit()
        return settings
    except IntegrityError:
        # The row was likely created by another process in the meantime.
        db.session.rollback()
        return Settings.query.first()


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

        # Get text blocks for caption finding
        text_blocks = page.get_text("blocks")

        # Extract images
        image_list = page.get_images(full=True)
        for img_index, img in enumerate(image_list):
            xref = img[0]

            # Get image bounding box
            try:
                img_bbox = page.get_image_bbox(img)
            except ValueError:
                # Skip if bbox not found
                continue

            base_image = doc.extract_image(xref)
            image_bytes = base_image["image"]
            image_ext = base_image["ext"]
            image_filename = f"image_{page_num+1}_{img_index}.{image_ext}"
            image_path = os.path.join(figure_dir, image_filename)

            with open(image_path, "wb") as f:
                f.write(image_bytes)
            figures.append(image_path)

            # Find caption for the image
            found_caption = ""
            for tb in text_blocks:
                text_bbox = fitz.Rect(tb[:4])
                block_text = tb[4]

                # Check if text block is below the image and close to it
                if text_bbox.y0 > img_bbox.y1 and (text_bbox.y0 - img_bbox.y1) < 50:
                    # Check for horizontal alignment
                    text_center_x = (text_bbox.x0 + text_bbox.x1) / 2
                    if img_bbox.x0 < text_center_x < img_bbox.x1:
                        if block_text.strip().lower().startswith(('figure', 'fig.')):
                            found_caption = block_text.strip().replace('\n', ' ')
                            break

            captions.append(found_caption if found_caption else f"Figure {len(figures)}")

    return text, json.dumps(figures), json.dumps(captions)


def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

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
    folder_id = request.form.get('folder_id') # get folder_id from form
    if file.filename == '':
        return redirect(request.url)
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)

        # Process the PDF and save to database
        text, figures, captions = process_pdf(filepath)
        new_file = PDFFile(filename=filename, text=text, figures=figures, captions=captions)
        if folder_id:
            new_file.folder_id = folder_id
        db.session.add(new_file)
        db.session.commit()

        return redirect(url_for('index'))
    return redirect(request.url)

@app.route('/summarize_file/<int:file_id>', methods=['POST'])
def summarize_file(file_id):
    pdf_file = PDFFile.query.get_or_404(file_id)
    settings = get_settings()

    if not app.gemini_client:
        return {'error': 'Gemini client is not initialized. Please check the API key.'}, 500

    try:
        # 1. Upload the file to the File API
        filepath = pathlib.Path(os.path.join(app.config['UPLOAD_FOLDER'], pdf_file.filename))
        uploaded_file = app.gemini_client.files.upload(file=filepath)

        # 2. Generate the summary
        prompt = settings.summary_prompt or "Summarize this document."
        response = app.gemini_client.models.generate_content(
            model=settings.summary_model,
            contents=[uploaded_file, prompt]
        )
        summary = response.text

        # 3. Save the summary to the database
        pdf_file.summary = summary
        db.session.commit()

        # 4. Clean up the file from the server
        app.gemini_client.files.delete(name=uploaded_file.name)

        return {'success': True, 'redirect_url': url_for('view_summary', file_id=file_id)}

    except Exception as e:
        app.logger.error(f"Error generating summary for file_id {file_id}: {e}")
        return {'error': f'An error occurred while generating the summary. {e}'}, 500


@app.route('/summary/<int:file_id>')
def view_summary(file_id):
    pdf_file = PDFFile.query.get_or_404(file_id)
    return render_template('summary.html', file=pdf_file)

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/file_details/<int:file_id>')
def file_details(file_id):
    pdf_file = PDFFile.query.get_or_404(file_id)
    return {
        'id': pdf_file.id,
        'filename': pdf_file.filename,
        'figures': json.loads(pdf_file.figures),
        'captions': json.loads(pdf_file.captions)
    }

@app.route('/generated_audio/<filename>')
def generated_audio(filename):
    return send_from_directory(app.config['GENERATED_AUDIO_FOLDER'], filename)

@app.route('/generate_dialogue/<int:file_id>')
def generate_dialogue(file_id):
    pdf_file = PDFFile.query.get_or_404(file_id)
    settings = get_settings()

    if not app.gemini_client:
        return {'error': 'Gemini client is not initialized. Please check the API key.'}, 500

    try:
        # 1. Generate dialogue script
        script_prompt = f"""
        Based on the following text, generate a dialogue script for a podcast episode between a 'Host' and an 'Expert'.
        The dialogue should be engaging and informative, summarizing the key points of the text.
        Format the output as a JSON array of objects, where each object has a 'speaker' ('Host' or 'Expert') and a 'line' (the text to be spoken).
        Ensure the JSON is well-formed.

        Here is the text:
        ---
        {pdf_file.text[:4000]}
        ---
        """
        generation_config = {"response_mime_type": "application/json"}
        response = app.gemini_client.models.generate_content(
            model=settings.dialogue_model,
            contents=[script_prompt],
            generation_config=generation_config
        )
        dialogue = json.loads(response.text)

        # Save the transcript
        pdf_file.dialogue_transcript = json.dumps(dialogue, indent=2)
        db.session.commit()

        # 2. Format the script for the TTS model
        tts_prompt = "TTS the following conversation between Host and Expert:\n"
        for part in dialogue:
            speaker = part.get('speaker', 'Expert')
            line = part.get('line', '')
            if line:
                tts_prompt += f"{speaker}: {line}\n"

        # 3. Generate multi-speaker TTS audio
        tts_response = app.gemini_client.models.generate_content(
           model="gemini-2.5-flash-preview-tts",
           contents=[tts_prompt],
           generation_config=types.GenerateContentConfig(
              response_modalities=["AUDIO"],
              speech_config=types.SpeechConfig(
                 multi_speaker_voice_config=types.MultiSpeakerVoiceConfig(
                    speaker_voice_configs=[
                       types.SpeakerVoiceConfig(
                          speaker='Host',
                          voice_config=types.VoiceConfig(
                             prebuilt_voice_config=types.PrebuiltVoiceConfig(
                                voice_name=settings.tts_host_voice,
                             )
                          )
                       ),
                       types.SpeakerVoiceConfig(
                          speaker='Expert',
                          voice_config=types.VoiceConfig(
                             prebuilt_voice_config=types.PrebuiltVoiceConfig(
                                voice_name=settings.tts_expert_voice,
                             )
                          )
                       ),
                    ]
                 )
              )
           )
        )
        audio_data = tts_response.candidates[0].content.parts[0].inline_data.data

        # 4. Save the audio file as MP3
        mp3_filename = f"dialogue_{file_id}.mp3"
        mp3_filepath = os.path.join(app.config['GENERATED_AUDIO_FOLDER'], mp3_filename)

        # Convert WAV data (in memory) to MP3
        audio = AudioSegment.from_wav(io.BytesIO(audio_data))
        audio.export(mp3_filepath, format="mp3")

        # 5. Return URL to the audio file
        audio_url = url_for('generated_audio', filename=mp3_filename)
        return {'audio_url': audio_url}

    except Exception as e:
        app.logger.error(f"Error generating dialogue for file_id {file_id}: {e}")
        return {'error': 'An error occurred while generating the dialogue. Please check the logs for details.'}, 500

@app.route('/settings', methods=['GET', 'POST'])
def settings():
    settings = get_settings()
    if request.method == 'POST':
        settings.gemini_api_key = request.form.get('gemini_api_key')
        settings.summary_model = request.form.get('summary_model')
        settings.dialogue_model = request.form.get('dialogue_model')
        settings.tts_host_voice = request.form.get('tts_host_voice')
        settings.tts_expert_voice = request.form.get('tts_expert_voice')
        settings.summary_prompt = request.form.get('summary_prompt')
        db.session.commit()
        # Re-initialize the client if the API key changed.
        init_gemini_client(app)
        return redirect(url_for('settings'))

    return render_template('settings.html', settings=settings)

def init_gemini_client(app_instance):
    with app_instance.app_context():
        settings = get_settings()
        api_key = settings.gemini_api_key or os.environ.get('GEMINI_API_KEY')
        if api_key:
            try:
                client = genai.Client(api_key=api_key)
                app_instance.gemini_client = client
                app_instance.logger.info("Gemini Client initialized successfully.")
            except Exception as e:
                app_instance.logger.error(f"Failed to initialize Gemini Client: {e}")
                app_instance.gemini_client = None
        else:
            app_instance.logger.warning("Gemini API key not found. Generative features will be disabled.")
            app_instance.gemini_client = None

init_gemini_client(app)
