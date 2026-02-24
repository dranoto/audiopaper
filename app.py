import os
import threading

from flask import Flask
from database import init_db
from services import init_tts_client, init_text_client
from errors import register_error_handlers
from config import config


app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = config.UPLOAD_FOLDER
app.config["GENERATED_AUDIO_FOLDER"] = config.GENERATED_AUDIO_FOLDER
app.config["SQLALCHEMY_DATABASE_URI"] = config.SQLALCHEMY_DATABASE_URI
app.config["SQLALCHEMY_ENGINE_OPTIONS"] = config.SQLALCHEMY_ENGINE_OPTIONS
app.config["SERVER_NAME"] = config.SERVER_NAME
app.config["PREFERRED_URL_SCHEME"] = config.PREFERRED_URL_SCHEME
app.config["APPLICATION_ROOT"] = config.APPLICATION_ROOT
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = config.SQLALCHEMY_TRACK_MODIFICATIONS
app.config["MAX_CONTENT_LENGTH"] = config.MAX_CONTENT_LENGTH

issues = config.validate()
if issues:
    for issue in issues:
        app.logger.warning(f"Config issue: {issue}")

os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
os.makedirs(app.config["GENERATED_AUDIO_FOLDER"], exist_ok=True)

init_db(app)

from utils.task_queue import TaskQueue
from tasks.workers import (
    _run_summary_generation,
    _run_transcript_generation,
    _run_podcast_generation,
)

task_queue = TaskQueue.get_instance(max_workers=3)
task_queue.register_handler("summary", _run_summary_generation)
task_queue.register_handler("transcript", _run_transcript_generation)
task_queue.register_handler("podcast", _run_podcast_generation)

_worker_start_lock = threading.Lock()


@app.before_request
def start_workers_if_needed():
    with _worker_start_lock:
        if not task_queue._running:
            task_queue.start_workers(app)


import atexit


def cleanup_task_queue():
    task_queue.stop_workers()


atexit.register(cleanup_task_queue)

from routes import register_blueprints

register_blueprints(app)

register_error_handlers(app)

init_tts_client(app)
init_text_client(app)

if __name__ == "__main__":
    app.run(debug=config.DEBUG)
