import os

from flask import Flask
from database import init_db
from services import init_tts_client, init_text_client


app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = "uploads"
app.config["GENERATED_AUDIO_FOLDER"] = "generated_audio"
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///db.sqlite3"
app.config["SERVER_NAME"] = os.environ.get("SERVER_NAME", "localhost:8010")
app.config["PREFERRED_URL_SCHEME"] = "http"
app.config["APPLICATION_ROOT"] = "/"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

init_db(app)

os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
os.makedirs(app.config["GENERATED_AUDIO_FOLDER"], exist_ok=True)

from routes import register_blueprints

register_blueprints(app)

init_tts_client(app)
init_text_client(app)

if __name__ == "__main__":
    app.run(debug=True)
