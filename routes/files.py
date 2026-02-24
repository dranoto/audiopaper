import os
import json
import uuid
import threading

from flask import Blueprint, request, redirect, url_for, jsonify, render_template
from werkzeug.utils import secure_filename

from database import db, PDFFile, Folder, Task, get_settings
from services import process_pdf, allowed_file, init_tts_client, init_text_client
from ragflow_service import get_ragflow_client
from tasks.workers import _run_summary_generation, _get_document_content


def get_all_tags():
    """Get all unique tags from all files."""
    all_files = PDFFile.query.filter(PDFFile.tags.isnot(None)).all()
    tags_set = set()
    for f in all_files:
        if f.tags:
            try:
                tags = json.loads(f.tags)
                if isinstance(tags, list):
                    tags_set.update(tags)
            except:
                pass
    return sorted(list(tags_set))


def create_files_bp(app):
    bp = Blueprint("files", __name__)

    FILES_PER_PAGE = 50

    @bp.route("/")
    def index():
        file_id = request.args.get("file", type=int)
        generate = request.args.get("generate")
        page = request.args.get("page", 1, type=int)
        search_query = request.args.get("search", "").strip()
        filter_tag = request.args.get("tag", "").strip()
        current_file = PDFFile.query.get(file_id) if file_id else None

        query = PDFFile.query

        if search_query:
            query = query.filter(
                PDFFile.filename.ilike(f"%{search_query}%")
                | PDFFile.summary.ilike(f"%{search_query}%")
            )

        if filter_tag:
            query = query.filter(PDFFile.tags.ilike(f'%"{filter_tag}"%'))

        pagination = query.order_by(PDFFile.id.desc()).paginate(
            page=page, per_page=FILES_PER_PAGE, error_out=False
        )
        all_files = pagination.items

        from utils.audio import get_audio_filename

        audio_folder = app.config["GENERATED_AUDIO_FOLDER"]
        for file in all_files:
            mp3_filename = get_audio_filename(file)
            mp3_filepath = os.path.join(audio_folder, mp3_filename)
            file.audio_exists = os.path.exists(mp3_filepath)
            file.audio_filename = mp3_filename

        if current_file:
            mp3_filename = get_audio_filename(current_file)
            mp3_filepath = os.path.join(
                app.config["GENERATED_AUDIO_FOLDER"], mp3_filename
            )
            current_file.audio_exists = os.path.exists(mp3_filepath)
            current_file.audio_filename = mp3_filename

        all_tags = get_all_tags()

        return render_template(
            "index.html",
            all_files=all_files,
            current_file=current_file,
            auto_generate=generate,
            pagination=pagination,
            current_page=page,
            search_query=search_query,
            filter_tag=filter_tag,
            all_tags=all_tags,
        )

    @bp.route("/upload", methods=["POST"])
    def upload_file():
        if "file" not in request.files:
            return redirect(request.url)
        file = request.files["file"]
        folder_id = request.form.get("folder_id")
        upload_to_ragflow = request.form.get("upload_to_ragflow")
        ragflow_dataset = request.form.get("ragflow_dataset")

        if file.filename == "" or not allowed_file(file.filename):
            return redirect(request.url)

        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        file.save(filepath)

        text, elements_json, _ = process_pdf(filepath)
        new_file = PDFFile(
            filename=filename, text=text, figures=elements_json, captions=json.dumps([])
        )
        if folder_id:
            new_file.folder_id = folder_id
        db.session.add(new_file)
        db.session.commit()

        if upload_to_ragflow == "on" and ragflow_dataset:
            try:
                settings = get_settings()
                client = get_ragflow_client(settings)
                if client:
                    markdown_content = f"# {filename}\n\n{text}"
                    temp_md = f"/tmp/{filename.rsplit('.', 1)[0]}.md"
                    with open(temp_md, "w") as f:
                        f.write(markdown_content)

                    result = client.request(
                        "POST",
                        f"/datasets/{ragflow_dataset}/documents",
                        files={"file": open(temp_md, "rb")},
                    )
                    os.remove(temp_md)
            except Exception as e:
                app.logger.error(f"Failed to upload to Ragflow: {e}")

        return redirect(url_for("files.index", file=new_file.id, generate="summary"))

    @bp.route("/file_content/<int:file_id>")
    def file_content(file_id):
        pdf_file = PDFFile.query.get_or_404(file_id)
        audio_url = None
        from utils.audio import get_audio_filename

        mp3_filename = get_audio_filename(pdf_file)
        mp3_filepath = os.path.join(app.config["GENERATED_AUDIO_FOLDER"], mp3_filename)
        if os.path.exists(mp3_filepath):
            audio_url = url_for("static.generated_audio", filename=mp3_filename)

        return {
            "summary": pdf_file.summary,
            "transcript": pdf_file.transcript,
            "chat_history": json.loads(pdf_file.chat_history or "[]"),
            "audio_url": audio_url,
        }

    @bp.route("/file_text/<int:file_id>")
    def file_text(file_id):
        pdf_file = PDFFile.query.get_or_404(file_id)
        text = _get_document_content(pdf_file, get_settings())
        return {"text": text}

    @bp.route("/file_details/<int:file_id>")
    def file_details(file_id):
        pdf_file = PDFFile.query.get_or_404(file_id)
        elements = json.loads(pdf_file.figures or "[]")
        return jsonify(
            {"id": pdf_file.id, "filename": pdf_file.filename, "elements": elements}
        )

    @bp.route("/delete_file/<int:file_id>", methods=["DELETE"])
    def delete_file(file_id):
        pdf_file = PDFFile.query.get_or_404(file_id)

        pdf_path = os.path.join(app.config["UPLOAD_FOLDER"], pdf_file.filename)
        from utils.audio import get_audio_filename

        mp3_filename = get_audio_filename(pdf_file)
        mp3_filepath = os.path.join(app.config["GENERATED_AUDIO_FOLDER"], mp3_filename)

        db.session.delete(pdf_file)
        db.session.commit()
        app.logger.info(f"Deleted file_id {file_id} from database.")

        try:
            if os.path.exists(pdf_path):
                os.remove(pdf_path)
                app.logger.info(f"Deleted PDF file: {pdf_path}")
            if os.path.exists(mp3_filepath):
                os.remove(mp3_filepath)
                app.logger.info(f"Deleted audio file: {mp3_filepath}")
        except Exception as e:
            app.logger.error(
                f"Error deleting physical files for file_id {file_id}: {e}"
            )

        return {"success": True}

    @bp.route("/rename_file/<int:file_id>", methods=["POST"])
    def rename_file(file_id):
        pdf_file = PDFFile.query.get_or_404(file_id)
        new_filename_req = request.json.get("new_filename")
        if not new_filename_req:
            return {"error": "New filename is required"}, 400

        new_filename = (
            new_filename_req
            if new_filename_req.lower().endswith(".pdf")
            else f"{new_filename_req}.pdf"
        )

        original_filename = pdf_file.filename
        old_pdf_path = os.path.join(app.config["UPLOAD_FOLDER"], original_filename)
        new_pdf_path = os.path.join(app.config["UPLOAD_FOLDER"], new_filename)

        if os.path.exists(new_pdf_path):
            return {"error": "A file with this name already exists"}, 400

        old_fig_dir_basename = os.path.splitext(original_filename)[0]
        new_fig_dir_basename = os.path.splitext(new_filename)[0]
        old_fig_dir = os.path.join("static", "figures", old_fig_dir_basename)
        new_fig_dir = os.path.join("static", "figures", new_fig_dir_basename)

        from sqlalchemy.exc import SQLAlchemyError

        try:
            os.rename(old_pdf_path, new_pdf_path)
            app.logger.info(f"Renamed PDF {old_pdf_path} to {new_pdf_path}")

            if os.path.isdir(old_fig_dir):
                os.rename(old_fig_dir, new_fig_dir)
                app.logger.info(f"Renamed figures dir {old_fig_dir} to {new_fig_dir}")

            pdf_file.filename = new_filename
            if pdf_file.figures:
                figures_list = json.loads(pdf_file.figures)
                updated_figures = [
                    p.replace(
                        f"static/figures/{old_fig_dir_basename}",
                        f"static/figures/{new_fig_dir_basename}",
                        1,
                    )
                    for p in figures_list
                ]
                pdf_file.figures = json.dumps(updated_figures)

            db.session.commit()
            app.logger.info(
                f"Updated database for file_id {file_id} to new name {new_filename}"
            )

            return {
                "success": True,
                "new_filename": new_filename,
                "new_url": url_for("static.uploaded_file", filename=new_filename),
            }

        except (OSError, SQLAlchemyError) as e:
            db.session.rollback()
            app.logger.error(
                f"Error during rename for file_id {file_id}: {e}. Rolling back changes."
            )

            if os.path.exists(new_pdf_path) and not os.path.exists(old_pdf_path):
                try:
                    os.rename(new_pdf_path, old_pdf_path)
                    app.logger.info(
                        f"Rolled back PDF rename from {new_pdf_path} to {old_pdf_path}"
                    )
                except OSError as rollback_e:
                    app.logger.critical(
                        f"CRITICAL: Filesystem rollback failed for PDF. Path: {new_pdf_path}. DB rolled back. Error: {rollback_e}"
                    )

            if os.path.exists(new_fig_dir) and not os.path.exists(old_fig_dir):
                try:
                    os.rename(new_fig_dir, old_fig_dir)
                    app.logger.info(
                        f"Rolled back figures dir rename from {new_fig_dir} to {old_fig_dir}"
                    )
                except OSError as rollback_e:
                    app.logger.critical(
                        f"CRITICAL: Filesystem rollback failed for figures dir. Path: {new_fig_dir}. DB rolled back. Error: {rollback_e}"
                    )

            return {
                "error": "An error occurred during the rename operation. All changes have been reverted."
            }, 500

    @bp.route("/move_file/<int:file_id>", methods=["POST"])
    def move_file(file_id):
        pdf_file = PDFFile.query.get_or_404(file_id)
        new_folder_id = request.json.get("new_folder_id")

        if new_folder_id == "root":
            pdf_file.folder_id = None
        else:
            target_folder = Folder.query.get_or_404(new_folder_id)
            pdf_file.folder_id = target_folder.id

        db.session.commit()
        app.logger.info(f"Moved file_id {file_id} to folder_id {new_folder_id}.")
        return {"success": True}

    @bp.route("/create_folder", methods=["POST"])
    def create_folder():
        folder_name = request.form.get("folder_name")
        if folder_name:
            new_folder = Folder(name=folder_name)
            db.session.add(new_folder)
            db.session.commit()
        return redirect(url_for("files.index"))

    @bp.route("/delete_folder/<int:folder_id>", methods=["DELETE"])
    def delete_folder(folder_id):
        folder = Folder.query.get_or_404(folder_id)

        if folder.files:
            return {"error": "Cannot delete a folder that is not empty."}, 400

        db.session.delete(folder)
        db.session.commit()
        app.logger.info(f"Deleted folder_id {folder_id}.")
        return {"success": True}

    @bp.route("/rename_folder/<int:folder_id>", methods=["POST"])
    def rename_folder(folder_id):
        folder = Folder.query.get_or_404(folder_id)
        new_name = request.json.get("new_name")
        if not new_name:
            return {"error": "New folder name is required"}, 400

        original_name = folder.name
        folder.name = new_name
        try:
            db.session.commit()
            app.logger.info(
                f"Renamed folder_id {folder_id} from '{original_name}' to '{new_name}'."
            )
            return {"success": True, "new_name": new_name}
        except Exception:
            db.session.rollback()
            folder.name = original_name
            app.logger.warning(
                f"Failed to rename folder_id {folder_id} to '{new_name}' because the name already exists."
            )
            return {"error": "A folder with this name already exists."}, 400

    return bp
