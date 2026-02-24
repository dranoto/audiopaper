import json
import os
import re
from flask import url_for
from database import db, PDFFile, Task, get_settings
from services import generate_text_with_file, generate_podcast_audio
from ragflow_service import get_ragflow_client
from utils.audio import get_audio_filename
from utils.task_queue import TaskStatus

COMMON_TOPICS = [
    "machine learning",
    "deep learning",
    "neural network",
    "artificial intelligence",
    "natural language processing",
    "computer vision",
    "robotics",
    "reinforcement learning",
    "data science",
    "statistics",
    "bioinformatics",
    "genomics",
    "medicine",
    "healthcare",
    "climate change",
    "environment",
    "physics",
    "chemistry",
    "materials science",
    "quantum computing",
    "blockchain",
    "cybersecurity",
    "networking",
    "distributed systems",
    "database",
    "software engineering",
    "algorithms",
    "optimization",
    "game theory",
    "economics",
    "psychology",
    "sociology",
    "education",
    "policy",
    "ethics",
    "philosophy",
]


def extract_tags_from_summary(summary_text):
    """Extract tags from summary using keyword matching."""
    if not summary_text:
        return []

    summary_lower = summary_text.lower()
    tags = []

    for topic in COMMON_TOPICS:
        if topic in summary_lower:
            tags.append(topic.title())

    return tags[:5]


def _get_document_content(pdf_file, settings):
    """Get document content - from local storage or fetch from Ragflow."""
    import logging

    logger = logging.getLogger(__name__)

    # First try local text
    if pdf_file.text:
        logger.info(
            f"Using local text for file {pdf_file.id}, length: {len(pdf_file.text)}"
        )
        return pdf_file.text

    # Try fetching from Ragflow if backed by Ragflow
    if pdf_file.is_ragflow_backed:
        logger.info(f"File {pdf_file.id} is Ragflow-backed, fetching content...")
        client = get_ragflow_client(settings)
        if client:
            try:
                content = client.get_document_content(
                    pdf_file.ragflow_dataset_id, pdf_file.ragflow_document_id
                )
                if content:
                    logger.info(f"Fetched from Ragflow, content length: {len(content)}")
                    return content
            except Exception as e:
                logger.error(f"Error fetching from Ragflow: {e}")
                raise Exception(f"Failed to fetch document from Ragflow: {e}")

    logger.warning(
        f"No content found for file {pdf_file.id} - text: {bool(pdf_file.text)}, is_ragflow_backed: {pdf_file.is_ragflow_backed}"
    )
    raise Exception(
        "No document content available. Please re-import or upload the PDF."
    )


def _run_summary_generation(app, task_id, file_id):
    with app.app_context():
        try:
            task = Task.query.get(task_id)
            if not task:
                app.logger.error(f"Task {task_id} not found in database.")
                return

            pdf_file = PDFFile.query.get(file_id)
            settings = get_settings()

            if not hasattr(app, "text_client") or not app.text_client:
                raise Exception(
                    "NanoGPT text client not initialized. Please set API key in settings."
                )

            # Get content (from local or Ragflow)
            document_content = _get_document_content(pdf_file, settings)

            if not document_content:
                raise Exception(
                    "No document content available - _get_document_content returned empty"
                )

            app.logger.info(
                f"Task {task_id}: Document content length: {len(document_content)} chars"
            )
            app.logger.info(
                f"Task {task_id}: is_ragflow_backed: {pdf_file.is_ragflow_backed}"
            )
            app.logger.info(
                f"Task {task_id}: ragflow_dataset_id: {pdf_file.ragflow_dataset_id}"
            )
            app.logger.info(
                f"Task {task_id}: ragflow_document_id: {pdf_file.ragflow_document_id}"
            )

            prompt = settings.summary_prompt
            model_name = settings.summary_model

            app.logger.info(f"Task {task_id}: Generating summary with {model_name}...")

            response_text = generate_text_with_file(
                app.text_client,
                model_name,
                document_content,
                prompt,
                "You are a helpful research assistant that summarizes documents clearly.",
            )

            pdf_file.summary = response_text

            tags = extract_tags_from_summary(response_text)
            if tags:
                pdf_file.tags = json.dumps(tags)

            task.status = TaskStatus.COMPLETE
            task.result = json.dumps({"success": True})
            db.session.commit()
            app.logger.info(
                f"Task {task_id}: Summary saved for file_id {file_id} with tags: {tags}"
            )

        except Exception as e:
            db.session.rollback()
            app.logger.error(
                f"Task {task_id}: Error generating summary for file_id {file_id}: {e}"
            )
            task = Task.query.get(task_id)
            if task:
                task.status = TaskStatus.ERROR
                task.result = json.dumps({"error": str(e)})
                db.session.commit()


def _run_transcript_generation(app, task_id, file_id):
    with app.app_context():
        try:
            task = Task.query.get(task_id)
            if not task:
                app.logger.error(f"Task {task_id} not found in database.")
                return

            pdf_file = PDFFile.query.get(file_id)
            settings = get_settings()

            if not hasattr(app, "text_client") or not app.text_client:
                raise Exception(
                    "NanoGPT text client not initialized. Please set API key in settings."
                )

            # Get content (from local or Ragflow)
            document_content = _get_document_content(pdf_file, settings)

            transcript_model_name = settings.transcript_model

            length_guidance = {
                "short": "Keep the script brief, approximately 2-3 minutes of dialogue.",
                "medium": "Create a moderate-length script, approximately 5-7 minutes of dialogue.",
                "long": "Create a comprehensive, detailed script approximately 10+ minutes of dialogue.",
            }
            transcript_len = getattr(settings, "transcript_length", "medium")
            length_instruction = length_guidance.get(
                transcript_len, length_guidance["medium"]
            )
            full_prompt = f"{settings.transcript_prompt}\n\n{length_instruction}"

            app.logger.info(
                f"Task {task_id}: Generating transcript with {transcript_model_name}..."
            )

            transcript_text = generate_text_with_file(
                app.text_client,
                transcript_model_name,
                document_content,
                full_prompt,
                "You are a helpful research assistant that creates engaging podcast scripts from documents.",
            )

            pdf_file.transcript = transcript_text

            task.status = TaskStatus.COMPLETE
            task.result = json.dumps({"success": True, "transcript": transcript_text})
            db.session.commit()
            app.logger.info(f"Task {task_id}: Transcript saved for file_id {file_id}.")

        except Exception as e:
            db.session.rollback()
            app.logger.error(
                f"Task {task_id}: Error generating transcript for file_id {file_id}: {e}"
            )
            task = Task.query.get(task_id)
            if task:
                task.status = TaskStatus.ERROR
                task.result = json.dumps({"error": str(e)})
                db.session.commit()


def _run_podcast_generation(app, task_id, file_id):
    with app.app_context():
        try:
            task = Task.query.get(task_id)
            if not task:
                app.logger.error(f"Task {task_id} not found in database.")
                return

            pdf_file = PDFFile.query.get(file_id)
            settings = get_settings()

            if not pdf_file.transcript:
                app.logger.info(
                    f"Task {task_id}: No transcript found, auto-generating..."
                )

                if not hasattr(app, "text_client") or not app.text_client:
                    raise Exception(
                        "NanoGPT text client not initialized. Please set API key in settings."
                    )

                # Get content from Ragflow or local
                document_content = _get_document_content(pdf_file, settings)

                transcript_model_name = settings.transcript_model

                length_guidance = {
                    "short": "Keep the script brief, approximately 2-3 minutes of dialogue.",
                    "medium": "Create a moderate-length script, approximately 5-7 minutes of dialogue.",
                    "long": "Create a comprehensive, detailed script approximately 10+ minutes of dialogue.",
                }
                transcript_len = getattr(settings, "transcript_length", "medium")
                length_instruction = length_guidance.get(
                    transcript_len, length_guidance["medium"]
                )
                full_prompt = f"{settings.transcript_prompt}\n\n{length_instruction}"

                transcript_text = generate_text_with_file(
                    app.text_client,
                    transcript_model_name,
                    document_content,
                    full_prompt,
                    "You are a helpful research assistant that creates engaging podcast scripts from documents.",
                )

                pdf_file.transcript = transcript_text
                db.session.commit()
                app.logger.info(
                    f"Task {task_id}: Auto-generated transcript for file_id {file_id}."
                )

            if not hasattr(app, "tts_client") or not app.tts_client:
                raise Exception(
                    "DeepInfra TTS client not initialized. Please set API key in settings."
                )

            transcript = pdf_file.transcript
            app.logger.info(
                f"Task {task_id}: Generating audio from transcript for file {file_id} using DeepInfra Kokoro..."
            )

            host_voice = settings.tts_host_voice or "af_bella"
            expert_voice = settings.tts_expert_voice or "am_onyx"

            combined_audio = generate_podcast_audio(
                app.tts_client, transcript, host_voice, expert_voice, speed=1.0
            )

            mp3_filename = get_audio_filename(pdf_file)
            mp3_filepath = os.path.join(
                app.config["GENERATED_AUDIO_FOLDER"], mp3_filename
            )
            combined_audio.export(mp3_filepath, format="mp3")

            audio_url = url_for("generated_audio", filename=mp3_filename)

            task.status = TaskStatus.COMPLETE
            task.result = json.dumps({"audio_url": audio_url})
            db.session.commit()
            app.logger.info(
                f"Task {task_id}: Podcast audio saved for file_id {file_id}."
            )

        except Exception as e:
            db.session.rollback()
            app.logger.error(
                f"Task {task_id}: Error generating podcast for file_id {file_id}: {e}"
            )
            task = Task.query.get(task_id)
            if task:
                task.status = TaskStatus.ERROR
                task.result = json.dumps({"error": str(e)})
                db.session.commit()
