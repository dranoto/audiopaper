import json
import uuid
import threading
import os
import io
import re

from flask import Blueprint, request, jsonify, Response, stream_with_context, url_for

from database import db, PDFFile, Task, get_settings
from services import (
    generate_text_with_file,
    generate_text_stream,
    generate_voice_sample,
)
from pydub import AudioSegment
from tasks.workers import (
    _run_summary_generation,
    _run_transcript_generation,
    _run_podcast_generation,
)
from utils.task_queue import TaskStatus


def create_generation_bp(app):
    bp = Blueprint("generation", __name__)

    def _get_task_status_response(task_id):
        task = Task.query.get_or_404(task_id)
        response_data = {
            "status": task.status,
            "result": json.loads(task.result) if task.result else None,
        }
        if task.status in [TaskStatus.COMPLETE.value, TaskStatus.ERROR.value]:
            db.session.delete(task)
            db.session.commit()
        return jsonify(response_data)

    @bp.route("/summarize_file/<int:file_id>", methods=["POST"])
    def summarize_file(file_id):
        task_id = str(uuid.uuid4())
        new_task = Task(id=task_id, status=TaskStatus.PROCESSING)
        db.session.add(new_task)
        db.session.commit()

        thread = threading.Thread(
            target=_run_summary_generation, args=(app, task_id, file_id)
        )
        thread.start()

        return jsonify({"task_id": task_id}), 202

    @bp.route("/summarize_status/<task_id>")
    def summarize_status(task_id):
        return _get_task_status_response(task_id)

    @bp.route("/summarize_stream/<int:file_id>")
    def summarize_stream(file_id):
        PDFFile.query.get_or_404(file_id)
        settings = get_settings()

        if not hasattr(app, "text_client") or not app.text_client:
            return Response(
                f"data: {json.dumps({'error': 'Text client not initialized'})}\n\n",
                mimetype="text/event-stream",
            )

        def generate():
            pdf_file = PDFFile.query.get(file_id)
            if not pdf_file:
                yield f"data: {json.dumps({'type': 'error', 'error': 'File not found'})}\n\n"
                return

            try:
                prompt = settings.summary_prompt
                model_name = settings.summary_model

                yield f"data: {json.dumps({'type': 'start'})}\n\n"

                full_text = ""
                token_buffer = ""
                buffer_size = 50

                for token in generate_text_stream(
                    app.text_client,
                    model_name,
                    pdf_file.text,
                    prompt,
                    "You are a helpful research assistant that summarizes documents clearly.",
                ):
                    full_text += token
                    token_buffer += token
                    if len(token_buffer) >= buffer_size:
                        yield f"data: {json.dumps({'type': 'token', 'content': token_buffer})}\n\n"
                        token_buffer = ""

                if token_buffer:
                    yield f"data: {json.dumps({'type': 'token', 'content': token_buffer})}\n\n"

                pdf_file.summary = full_text
                db.session.commit()

                yield f"data: {json.dumps({'type': 'complete', 'summary': full_text[:500]})}\n\n"

            except Exception as e:
                import traceback

                error_detail = str(e) + "\n" + traceback.format_exc()
                yield f"data: {json.dumps({'type': 'error', 'error': error_detail})}\n\n"

        response = Response(
            stream_with_context(generate()), mimetype="text/event-stream"
        )
        response.headers["Cache-Control"] = "no-cache"
        response.headers["X-Accel-Buffering"] = "no"
        return response

    @bp.route("/generate_transcript/<int:file_id>", methods=["POST"])
    def generate_transcript(file_id):
        task_id = str(uuid.uuid4())
        new_task = Task(id=task_id, status=TaskStatus.PROCESSING)
        db.session.add(new_task)
        db.session.commit()

        thread = threading.Thread(
            target=_run_transcript_generation, args=(app, task_id, file_id)
        )
        thread.start()

        return jsonify({"task_id": task_id}), 202

    @bp.route("/transcript_status/<task_id>")
    def transcript_status(task_id):
        return _get_task_status_response(task_id)

    @bp.route("/transcript_stream/<int:file_id>")
    def transcript_stream(file_id):
        pdf_file = PDFFile.query.get_or_404(file_id)
        settings = get_settings()

        if not pdf_file.summary:
            return Response(
                f"data: {json.dumps({'type': 'error', 'error': 'No summary available. Generate summary first.'})}\n\n",
                mimetype="text/event-stream",
            )

        if not hasattr(app, "text_client") or not app.text_client:
            return Response(
                f"data: {json.dumps({'type': 'error', 'error': 'Text client not initialized'})}\n\n",
                mimetype="text/event-stream",
            )

        def generate():
            try:
                prompt = settings.transcript_prompt
                model_name = settings.transcript_model

                yield f"data: {json.dumps({'type': 'start'})}\n\n"

                full_text = ""
                token_buffer = ""
                buffer_size = 50

                for token in generate_text_stream(
                    app.text_client,
                    model_name,
                    pdf_file.summary,
                    prompt,
                    "You are a helpful research assistant that creates engaging podcast scripts from documents.",
                ):
                    full_text += token
                    token_buffer += token
                    if len(token_buffer) >= buffer_size:
                        yield f"data: {json.dumps({'type': 'token', 'content': token_buffer})}\n\n"
                        token_buffer = ""

                if token_buffer:
                    yield f"data: {json.dumps({'type': 'token', 'content': token_buffer})}\n\n"

                pdf_file.transcript = full_text
                db.session.commit()

                yield f"data: {json.dumps({'type': 'complete', 'transcript': full_text[:500]})}\n\n"

            except Exception as e:
                import traceback

                error_msg = str(e) + "\n" + traceback.format_exc()
                yield f"data: {json.dumps({'type': 'error', 'error': error_msg})}\n\n"

        response = Response(
            stream_with_context(generate()), mimetype="text/event-stream"
        )
        response.headers["Cache-Control"] = "no-cache"
        response.headers["X-Accel-Buffering"] = "no"
        return response

    @bp.route("/generate_podcast/<int:file_id>", methods=["POST"])
    def generate_podcast(file_id):
        task_id = str(uuid.uuid4())
        new_task = Task(id=task_id, status=TaskStatus.PROCESSING)
        db.session.add(new_task)
        db.session.commit()
        thread = threading.Thread(
            target=_run_podcast_generation, args=(app, task_id, file_id)
        )
        thread.start()
        return jsonify({"task_id": task_id}), 202

    @bp.route("/podcast_status/<task_id>")
    def podcast_status(task_id):
        return _get_task_status_response(task_id)

    @bp.route("/save_transcript/<int:file_id>", methods=["POST"])
    def save_transcript(file_id):
        pdf_file = PDFFile.query.get_or_404(file_id)
        data = request.get_json()

        if not data or "transcript" not in data:
            return jsonify({"error": "Transcript is required"}), 400

        pdf_file.transcript = data["transcript"]
        db.session.commit()

        from utils.audio import get_audio_filename

        mp3_filename = get_audio_filename(pdf_file)
        mp3_filepath = os.path.join(app.config["GENERATED_AUDIO_FOLDER"], mp3_filename)
        if os.path.exists(mp3_filepath):
            os.remove(mp3_filepath)
            app.logger.info(
                f"Deleted existing audio file for file_id {file_id} after transcript edit."
            )

        return jsonify({"success": True})

    @bp.route("/play_voice_sample", methods=["POST"])
    def play_voice_sample():
        data = request.get_json()
        voice = data.get("voice")
        if not voice:
            return jsonify({"error": "Voice parameter is required"}), 400

        if not hasattr(app, "tts_client") or not app.tts_client:
            return jsonify(
                {
                    "error": "DeepInfra TTS client not initialized. Please set API key in settings."
                }
            ), 500

        sample_text = "Hello, this is a sample of the selected voice."
        samples_folder = os.path.join(app.config["GENERATED_AUDIO_FOLDER"], "samples")
        os.makedirs(samples_folder, exist_ok=True)

        safe_filename = re.sub(r"[^a-zA-Z0-9_-]", "_", voice)
        mp3_filename = f"{safe_filename}.mp3"
        mp3_filepath = os.path.join(samples_folder, mp3_filename)

        if not os.path.exists(mp3_filepath):
            try:
                app.logger.info(f"Generating voice sample for '{voice}'...")

                audio_data, _ = generate_voice_sample(
                    app.tts_client, voice, sample_text
                )

                audio = AudioSegment.from_file(io.BytesIO(audio_data), format="mp3")
                audio.export(mp3_filepath, format="mp3")
                app.logger.info(f"Saved voice sample to {mp3_filepath}")

            except Exception as e:
                app.logger.error(f"Error generating voice sample for '{voice}': {e}")
                return jsonify({"error": str(e)}), 500

        audio_url = url_for(
            "static.generated_audio", filename=f"samples/{mp3_filename}"
        )
        return jsonify({"audio_url": audio_url})

    return bp
