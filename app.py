import os
from flask import Flask
from database import init_db
from services import init_gemini_client
from routes.main import main_bp
from routes.files import files_bp
from routes.tasks import tasks_bp
from routes.static import static_bp

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

# --- Register Blueprints ---
app.register_blueprint(main_bp)
app.register_blueprint(files_bp)
app.register_blueprint(tasks_bp)
app.register_blueprint(static_bp)

# --- App Initialization ---
init_gemini_client(app)

if __name__ == '__main__':
    app.run(debug=True)
