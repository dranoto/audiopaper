from flask import Blueprint, send_from_directory


def create_static_bp(app):
    bp = Blueprint("static", __name__)

    @bp.route("/uploads/<filename>")
    def uploaded_file(filename):
        return send_from_directory(app.config["UPLOAD_FOLDER"], filename)

    @bp.route("/generated_audio/<filename>")
    def generated_audio(filename):
        return send_from_directory(app.config["GENERATED_AUDIO_FOLDER"], filename)

    return bp
