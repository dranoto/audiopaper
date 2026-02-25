from flask import Blueprint, request, redirect, url_for, render_template, flash

from database import db, get_settings
from services import (
    SUMMARY_MODEL,
    TRANSCRIPT_MODEL,
    CHAT_MODEL,
    TTS_HOST_VOICE,
    TTS_MODEL,
    TTS_EXPERT_VOICE,
    available_voices,
    init_tts_client,
    init_text_client,
)


def create_settings_bp(app):
    bp = Blueprint("settings", __name__)

    @bp.route("/settings", methods=["GET", "POST"])
    def settings():
        s = get_settings()

        if not s.summary_model:
            s.summary_model = SUMMARY_MODEL
        if not s.transcript_model:
            s.transcript_model = TRANSCRIPT_MODEL
        if not s.chat_model:
            s.chat_model = CHAT_MODEL
        if not s.tts_model:
            s.tts_model = TTS_MODEL
        if not s.tts_host_voice:
            s.tts_host_voice = TTS_HOST_VOICE
        if not s.tts_expert_voice:
            s.tts_expert_voice = TTS_EXPERT_VOICE
        if not s.transcript_length:
            s.transcript_length = "medium"

        if request.method == "POST":
            s.summary_prompt = request.form.get("summary_prompt")
            s.transcript_prompt = request.form.get("transcript_prompt")
            s.transcript_length = request.form.get("transcript_length", "medium")

            # Save API keys (only if provided, to preserve existing keys)
            api_key_nanogpt = request.form.get("api_key_nanogpt", "").strip()
            if api_key_nanogpt:
                s.nanogpt_api_key = api_key_nanogpt

            api_key_deepinfra = request.form.get("api_key_deepinfra", "").strip()
            if api_key_deepinfra:
                s.deepinfra_api_key = api_key_deepinfra

            api_key_ragflow = request.form.get("api_key_ragflow", "").strip()
            if api_key_ragflow:
                s.ragflow_api_key = api_key_ragflow

            api_key_gemini = request.form.get("api_key_gemini", "").strip()
            if api_key_gemini:
                s.gemini_api_key = api_key_gemini

            db.session.commit()
            init_tts_client(app)
            init_text_client(app)

            from flask import flash

            flash("Settings saved successfully!", "success")
            return redirect(url_for("settings.settings"))

        return render_template(
            "settings.html",
            settings=s,
            text_models=[SUMMARY_MODEL, TRANSCRIPT_MODEL, CHAT_MODEL],
            tts_models=[TTS_MODEL],
            voices=available_voices,
        )

    return bp
