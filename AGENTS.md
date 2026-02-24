# AGENTS.md - AudioPaper Development Guide

## Project Overview
AudioPaper is a Flask web application that allows users to upload PDF documents and generate text summaries and audio podcasts using AI APIs (Gemini, OpenAI, DeepInfra).

## Build, Run, and Test Commands

### Running the Application

#### Local Development
```bash
# Install dependencies
pip install -r requirements.txt

# Run Flask development server
python app.py
# Access at http://localhost:8010 (or configures SERVER_NAME)

# Or run with Gunicorn (like production)
gunicorn --bind 0.0.0.0:8000 --timeout 300 app:app
```

#### Using Docker
```bash
# Build and run with Docker Compose
docker-compose up --build

# Access at http://localhost:8000
```

### Testing

```bash
# Run all tests
pytest

# Run tests with verbose output
pytest -v

# Run a single test file
pytest tests/test_file.py

# Run a single test function
pytest tests/test_file.py::test_function_name

# Run tests matching a pattern
pytest -k "test_name_pattern"

# Run with coverage (if installed)
pytest --cov=. --cov-report=html
```

### Database Operations
```bash
# Seed database with test data
python seed_db.py

# Database file location: instance/db.sqlite3
```

### Linting (No formal linting configured)
If you want to add linting, consider:
```bash
pip install flake8 pylint black
flake8 .
black --check .
```

## Code Style Guidelines

### General Principles
- Write clean, readable code following Python idioms
- Keep functions focused and reasonably sized (<100 lines preferred)
- Use meaningful variable and function names

### Naming Conventions
- **Classes**: PascalCase (e.g., `class Folder`, `class PDFFile`)
- **Functions/variables**: snake_case (e.g., `get_audio_filename`, `pdf_file`)
- **Constants**: UPPER_SNAKE_CASE (e.g., `ALLOWED_EXTENSIONS`)
- **Database columns**: snake_case (defined in models)

### Import Organization
Organize imports in this order (separate with blank lines):
1. Standard library imports (`os`, `json`, `re`, `uuid`, etc.)
2. Third-party imports (`flask`, `sqlalchemy`, `requests`, etc.)
3. Local application imports (`from database import ...`, `from services import ...`)

Example from `app.py`:
```python
import os
import json
import re
import uuid
import threading
import io
import time
from functools import lru_cache

from flask import Flask, render_template, request, redirect, url_for, ...
from werkzeug.utils import secure_filename
from pydub import AudioSegment
from sqlalchemy.exc import SQLAlchemyError, IntegrityError

from database import db, init_db, Folder, PDFFile, Settings, get_settings, Task
from services import (
    init_tts_client,
    init_text_client,
    process_pdf,
    ...
)
from ragflow_service import get_ragflow_client
```

### Type Hints
- Use type hints for function parameters and return values when beneficial
- Be consistent with existing code (some functions use hints, some don't)

### Error Handling
- Use try/except blocks for operations that may fail
- Log errors using `app.logger.error()` or `app.logger.info()`
- Return appropriate HTTP status codes (200, 400, 404, 500)
- For API errors, return JSON with error messages

Example pattern:
```python
try:
    # operation that may fail
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
- Use meaningful column names matching the data they store
- Include `__repr__` methods for debugging
- Use relationships for associated models

Example:
```python
class PDFFile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(100), unique=True, nullable=False)
    text = db.Column(db.Text, nullable=False)
    folder_id = db.Column(db.Integer, db.ForeignKey('folder.id'), nullable=True)
    
    def __repr__(self):
        return f'<PDFFile {self.filename}>'
```

### Flask Routes
- Use descriptive route names matching the resource
- Group related routes together
- Use appropriate HTTP methods (GET for viewing, POST for modifications)
- Return JSON for API endpoints, templates for UI pages

### Logging
- Use `app.logger.info()`, `app.logger.error()`, `app.logger.warning()`
- Include context in log messages (e.g., task ID, file ID)
- Use traceback for exceptions when helpful

### Templates and Static Files
- Templates go in `templates/` directory
- Static files (CSS, JS, images) go in `static/`
- Use Flask's `url_for()` for static file URLs

### Environment Variables
- Use `.env` file for local development (see `.env.example`)
- Never commit secrets to version control
- Use `os.environ.get()` or `os.getenv()` to access environment variables

### Testing Best Practices
- Place tests in `tests/` directory
- Use `pytest` with `pytest-flask` for Flask app testing
- Use fixtures for common test setup
- Test both success and error cases

Example test structure:
```python
import pytest
from app import app, db

@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as client:
        with app.app_context():
            db.create_all()
            yield client
            db.session.remove()
            db.drop_all()

def test_index_route(client):
    response = client.get('/')
    assert response.status_code == 200
```

## Project Structure
```
audiopaper/
├── app.py              # Main Flask application with routes
├── database.py         # SQLAlchemy models
├── services.py         # Business logic (PDF processing, TTS, etc.)
├── ragflow_service.py # Ragflow API client
├── seed_db.py         # Database seeding script
├── requirements.txt   # Python dependencies
├── Dockerfile         # Docker configuration
├── docker-compose.yml # Docker Compose configuration
├── templates/         # HTML templates
├── static/           # CSS, JS, images
├── uploads/          # Uploaded PDF files
├── generated_audio/  # Generated MP3 files
└── instance/        # SQLite database
```

## Key Dependencies
- Flask - Web framework
- Flask-SQLAlchemy - ORM
- PyMuPDF (fitz) - PDF processing
- pydub - Audio processing
- openai - API client
- google-genai - Google AI API
- pytest, pytest-flask - Testing

## Configuration
- Set `GEMINI_API_KEY` or other API keys in `.env`
- Database: SQLite at `instance/db.sqlite3`
- Upload folder: `uploads/`
- Generated audio: `generated_audio/`
