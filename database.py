import os
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.exc import IntegrityError

db = SQLAlchemy()

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
    transcript = db.Column(db.Text, nullable=True)
    gemini_file_id = db.Column(db.String(100), nullable=True)
    chat_history = db.Column(db.Text, nullable=True)  # Store as JSON string
    folder_id = db.Column(db.Integer, db.ForeignKey('folder.id'), nullable=True)

    def __repr__(self):
        return f'<PDFFile {self.filename}>'

class Task(db.Model):
    id = db.Column(db.String(36), primary_key=True)  # UUID length
    status = db.Column(db.String(20), nullable=False, default='processing')
    result = db.Column(db.Text, nullable=True) # Will store JSON result

    def __repr__(self):
        return f'<Task {self.id} [{self.status}]>'

class Settings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    lock = db.Column(db.String(10), unique=True, default='main_settings', nullable=False)
    gemini_api_key = db.Column(db.String(200), nullable=True)
    nanogpt_api_key = db.Column(db.String(200), nullable=True)
    deepinfra_api_key = db.Column(db.String(200), nullable=True)
    ragflow_url = db.Column(db.String(200), nullable=True)
    ragflow_api_key = db.Column(db.String(200), nullable=True)
    summary_model = db.Column(db.String(100), nullable=False, default='zai-org/glm-5:thinking')
    transcript_model = db.Column(db.String(100), nullable=False, default='zai-org/glm-5:thinking')
    chat_model = db.Column(db.String(100), nullable=False, default='zai-org/glm-5:thinking')
    tts_model = db.Column(db.String(100), nullable=False, default='hexgrad/Kokoro-82M')
    tts_host_voice = db.Column(db.String(100), nullable=False, default='af_bella')
    tts_expert_voice = db.Column(db.String(100), nullable=False, default='am_onyx')
    summary_prompt = db.Column(db.Text, nullable=False, default='Summarize this research paper. Provide a concise overview of the introduction, methods, key findings, and conclusion.')
    transcript_prompt = db.Column(db.Text, nullable=False, default='\n'.join([
        "Generate a podcast-style dialogue script based on the attached document.",
        "The script should be a conversation between a 'Host' and an 'Expert'.",
        "The Host should ask engaging questions, and the Expert should explain the key concepts from the document clearly.",
        "Start each line with the speaker's name followed by a colon (e.g., \"Host: ...\")."
    ]))

    # Note: transcript_length column may not exist in older databases

    def __repr__(self):
        return f'<Settings {self.id}>'

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

def init_db(app):
    with app.app_context():
        db.init_app(app)
        db.create_all()
