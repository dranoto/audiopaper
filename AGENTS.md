# AGENTS.md - AudioPaper Development Guide

## Project Overview
AudioPaper is a Flask web application for uploading PDFs and generating AI-powered summaries and audio podcasts.

## Build, Run, and Test Commands

### Running the Application
```bash
# Install dependencies
pip install -r requirements.txt

# Run Flask development server
python app.py
# Access at http://localhost:8010 (or configured SERVER_NAME)

# Run with Gunicorn (production-like)
gunicorn --bind 0.0.0.0:8000 --timeout 300 app:app
```

### Docker
```bash
docker-compose up --build
# Access at http://localhost:8000
```

### Testing
```bash
# Run all tests
pytest

# Run with verbose output
pytest -v

# Run a single test file
pytest tests/test_routes.py

# Run a single test function
pytest tests/test_routes.py::TestIndex::test_index_GET

# Run tests matching a pattern
pytest -k "test_name_pattern"

# Run with coverage
pytest --cov=. --cov-report=html
```

### Database
```bash
# Seed database with test data
python seed_db.py

# Database location: data/db.sqlite3 (mounted to instance/ in docker)
```

### Linting
```bash
pip install flake8 black
flake8 .
black --check .
```

## Code Style Guidelines

### Naming Conventions
- **Classes**: PascalCase (`class Folder`, `class PDFFile`)
- **Functions/variables**: snake_case (`get_audio_filename`, `pdf_file`)
- **Constants**: UPPER_SNAKE_CASE (`ALLOWED_EXTENSIONS`)
- **Database columns**: snake_case

### Import Organization
Order imports with blank lines between groups:
1. Standard library (`os`, `json`, `re`, `uuid`, etc.)
2. Third-party (`flask`, `sqlalchemy`, `requests`, etc.)
3. Local application (`from database import ...`, `from services import ...`)

```python
import os
import json
import threading

from flask import Flask, render_template, request, jsonify
from werkzeug.utils import secure_filename
from sqlalchemy.exc import SQLAlchemyError, IntegrityError

from database import db, Folder, PDFFile
from services import process_pdf, init_tts_client
```

### Type Hints
- Use type hints for function parameters and return values when beneficial
- Be consistent with existing code patterns

### Error Handling
- Use try/except blocks for operations that may fail
- Log errors with `app.logger.error()` or `app.logger.info()`
- Return appropriate HTTP status codes (200, 400, 404, 500)
- Return JSON with error messages for API errors

```python
try:
    db.session.commit()
except IntegrityError:
    db.session.rollback()
    return jsonify({'error': 'Duplicate entry'}), 400
except Exception as e:
    app.logger.error(f"Operation failed: {e}")
    return jsonify({'error': str(e)}), 500
```

### Database Models (SQLAlchemy)
- Define models in `database.py`
- Use meaningful column names
- Include `__repr__` methods for debugging
- Use relationships for associated models

```python
class PDFFile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(100), unique=True, nullable=False)
    text = db.Column(db.Text, nullable=True)
    folder_id = db.Column(db.Integer, db.ForeignKey('folder.id'), nullable=True)

    def __repr__(self):
        return f'<PDFFile {self.filename}>'
```

### Flask Routes
- Use blueprints in `routes/` directory for organization
- Group related routes together
- Return JSON for API endpoints, templates for UI pages

### Logging
- Use `app.logger.info()`, `app.logger.error()`, `app.logger.warning()`
- Include context (task ID, file ID, etc.) in log messages

### Testing Best Practices
- Place tests in `tests/` directory
- Use `pytest` with `pytest-flask`
- Use fixtures for test setup with in-memory SQLite

```python
@pytest.fixture
def app():
    from app import app as _app
    _app.config["TESTING"] = True
    _app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    with _app.app_context():
        db.create_all()
    yield _app
    with _app.app_context():
        db.drop_all()
```

## Project Structure
```
audiopaper/
├── app.py              # Main Flask application entry point
├── config.py           # Configuration settings
├── database.py         # SQLAlchemy models (Folder, PDFFile, Settings, Task)
├── services.py         # Business logic (PDF processing, TTS, AI clients)
├── ragflow_service.py  # Ragflow API client
├── errors.py           # Error handlers
├── migrations.py       # Database migrations
├── routes/             # Flask blueprints
│   ├── files.py        # File upload/download routes
│   ├── generation.py   # Audio/summary generation routes
│   ├── chat.py         # Chat API routes
│   ├── ragflow.py      # Ragflow integration routes
│   └── settings.py     # Settings routes
├── tasks/              # Background task workers
│   └── workers.py      # Task execution logic
├── utils/              # Utility modules
│   ├── task_queue.py   # Background task queue
│   ├── cache.py        # Caching utilities
│   └── encryption.py   # Encryption utilities
├── templates/          # HTML templates
├── static/            # CSS, JS, images
├── tests/             # Test files
├── uploads/           # Uploaded PDF files
├── generated_audio/   # Generated MP3 files
└── instance/          # SQLite database
```

## Key Dependencies
- Flask, Flask-SQLAlchemy - Web framework and ORM
- PyMuPDF (fitz) - PDF processing
- pydub - Audio processing
- openai, google-genai - AI API clients
- pytest, pytest-flask - Testing

## Configuration
- Set API keys in `.env` file (see `.env.example`)
- Database: SQLite at `data/db.sqlite3` (docker mounts to `instance/`)
- Upload folder: `uploads/`
- Generated audio: `generated_audio/`
