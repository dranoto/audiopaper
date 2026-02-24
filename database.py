import os
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.exc import IntegrityError

db = SQLAlchemy()

# Try to import encryption, but don't fail if not available
try:
    from utils.encryption import encrypt_key, decrypt_key

    ENCRYPTION_AVAILABLE = True
except ImportError:
    ENCRYPTION_AVAILABLE = False

    def encrypt_key(key):
        return key

    def decrypt_key(key):
        return key


class Folder(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    files = db.relationship("PDFFile", backref="folder", lazy=True)

    def __repr__(self):
        return f"<Folder {self.name}>"


class PDFFile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(100), unique=True, nullable=False)
    text = db.Column(
        db.Text, nullable=True
    )  # Optional - for legacy uploads; new imports fetch from Ragflow
    figures = db.Column(db.Text)
    captions = db.Column(db.Text)
    summary = db.Column(db.Text, nullable=True)
    transcript = db.Column(db.Text, nullable=True)
    chat_history = db.Column(db.Text, nullable=True)  # Store as JSON string
    folder_id = db.Column(db.Integer, db.ForeignKey("folder.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=db.func.current_timestamp())
    updated_at = db.Column(
        db.DateTime,
        default=db.func.current_timestamp(),
        onupdate=db.func.current_timestamp(),
    )

    # Ragflow references - for on-demand fetching
    ragflow_document_id = db.Column(
        db.String(100), nullable=True
    )  # Ragflow document ID
    ragflow_dataset_id = db.Column(db.String(100), nullable=True)  # Ragflow dataset ID

    # Helper property to check if content should be fetched from Ragflow
    @property
    def is_ragflow_backed(self):
        """Returns True if this file should fetch content from Ragflow."""
        return bool(self.ragflow_document_id and self.ragflow_dataset_id)

    # Helper property to get content (from local or fetch from Ragflow)
    def get_content(self, ragflow_client=None):
        """Get document content - local or from Ragflow."""
        if self.text:
            return self.text

        if self.is_ragflow_backed and ragflow_client:
            try:
                return ragflow_client.get_document_content(
                    self.ragflow_dataset_id, self.ragflow_document_id
                )
            except Exception as e:
                logger.error(
                    f"Failed to fetch content from Ragflow for file {self.id}: {e}"
                )
                return None

        return None

    def __repr__(self):
        return f"<PDFFile {self.filename}>"


# Import logger for get_content method
import logging

logger = logging.getLogger(__name__)


class Task(db.Model):
    id = db.Column(db.String(36), primary_key=True)  # UUID length
    status = db.Column(db.String(20), nullable=False, default="processing")
    result = db.Column(db.Text, nullable=True)  # Will store JSON result

    def __repr__(self):
        return f"<Task {self.id} [{self.status}]>"


class Settings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    lock = db.Column(
        db.String(10), unique=True, default="main_settings", nullable=False
    )
    _gemini_api_key = db.Column(db.String(200), nullable=True, name="gemini_api_key")
    _nanogpt_api_key = db.Column(db.String(200), nullable=True, name="nanogpt_api_key")
    _deepinfra_api_key = db.Column(
        db.String(200), nullable=True, name="deepinfra_api_key"
    )
    _ragflow_api_key = db.Column(db.String(200), nullable=True, name="ragflow_api_key")
    ragflow_url = db.Column(db.String(200), nullable=True)
    summary_model = db.Column(
        db.String(100), nullable=False, default="zai-org/glm-5:thinking"
    )
    transcript_model = db.Column(
        db.String(100), nullable=False, default="zai-org/glm-5:thinking"
    )
    chat_model = db.Column(
        db.String(100), nullable=False, default="zai-org/glm-5:thinking"
    )
    tts_model = db.Column(db.String(100), nullable=False, default="hexgrad/Kokoro-82M")
    tts_host_voice = db.Column(db.String(100), nullable=False, default="af_bella")
    tts_expert_voice = db.Column(db.String(100), nullable=False, default="am_onyx")
    summary_prompt = db.Column(
        db.Text,
        nullable=False,
        default="Summarize this research paper. Provide a concise overview of the introduction, methods, key findings, and conclusion.",
    )
    transcript_prompt = db.Column(
        db.Text,
        nullable=False,
        default="\n".join(
            [
                "Generate a podcast-style dialogue script based on the attached document.",
                "The script should be a conversation between a 'Host' and an 'Expert'.",
                "The Host should ask engaging questions, and the Expert should explain the key concepts from the document clearly.",
                'Start each line with the speaker\'s name followed by a colon (e.g., "Host: ...").',
            ]
        ),
    )
    transcript_length = db.Column(db.String(20), nullable=False, default="medium")

    @property
    def gemini_api_key(self):
        return decrypt_key(self._gemini_api_key) if self._gemini_api_key else None

    @gemini_api_key.setter
    def gemini_api_key(self, value):
        self._gemini_api_key = encrypt_key(value) if value else None

    @property
    def nanogpt_api_key(self):
        return decrypt_key(self._nanogpt_api_key) if self._nanogpt_api_key else None

    @nanogpt_api_key.setter
    def nanogpt_api_key(self, value):
        self._nanogpt_api_key = encrypt_key(value) if value else None

    @property
    def deepinfra_api_key(self):
        return decrypt_key(self._deepinfra_api_key) if self._deepinfra_api_key else None

    @deepinfra_api_key.setter
    def deepinfra_api_key(self, value):
        self._deepinfra_api_key = encrypt_key(value) if value else None

    @property
    def ragflow_api_key(self):
        return decrypt_key(self._ragflow_api_key) if self._ragflow_api_key else None

    @ragflow_api_key.setter
    def ragflow_api_key(self, value):
        self._ragflow_api_key = encrypt_key(value) if value else None

    def __repr__(self):
        return f"<Settings {self.id}>"


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
