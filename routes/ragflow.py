import json
import os
import uuid
import threading

from flask import Blueprint, request, jsonify, render_template

from database import db, PDFFile, Task, get_settings
from ragflow_service import get_ragflow_client
from utils.cache import ragflow_cache
from tasks.workers import _run_summary_generation


def create_ragflow_bp(app):
    bp = Blueprint("ragflow", __name__, url_prefix="/ragflow")

    @bp.route("/")
    def ragflow_browser():
        settings = get_settings()
        client = get_ragflow_client(settings)

        if not client:
            return render_template(
                "ragflow_error.html",
                error="Ragflow not configured. Please add your Ragflow URL and API key in Settings.",
            )

        try:
            datasets = client.list_datasets()
        except Exception as e:
            return render_template(
                "ragflow_error.html", error=f"Failed to connect to Ragflow: {str(e)}"
            )

        all_files = PDFFile.query.all()
        imported_names = [f.filename for f in all_files]

        return render_template(
            "ragflow.html", datasets=datasets, imported_names=imported_names
        )

    @bp.route("/datasets")
    def ragflow_datasets():
        settings = get_settings()
        client = get_ragflow_client(settings)

        if not client:
            return jsonify({"error": "Ragflow not configured"}), 400

        try:
            datasets = client.list_datasets()
            return jsonify(
                {
                    "datasets": [
                        {"id": d.get("id"), "name": d.get("name")} for d in datasets
                    ]
                }
            )
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @bp.route("/dataset/<dataset_id>")
    def ragflow_dataset(dataset_id):
        settings = get_settings()
        client = get_ragflow_client(settings)

        if not client:
            return jsonify({"error": "Ragflow not configured"}), 400

        page = request.args.get("page", 1, type=int)
        size = request.args.get("size", 50, type=int)

        cache_key = f"docs_{dataset_id}_all"
        force_refresh = request.args.get("refresh", "false").lower() == "true"

        if force_refresh:
            ragflow_cache.invalidate(cache_key)

        cached = ragflow_cache.get(cache_key)

        try:
            if cached is None:
                documents, total = client.list_documents(dataset_id, page=1, size=1000)
                cached = {"documents": documents, "total": total}
                ragflow_cache.set(cache_key, cached)
            else:
                documents = cached.get("documents", [])
                total = cached.get("total", len(documents))

            datasets_cache_key = "datasets_list"
            datasets_cached = ragflow_cache.get(datasets_cache_key)
            if datasets_cached:
                datasets = datasets_cached
            else:
                datasets = client.list_datasets()
                ragflow_cache.set(datasets_cache_key, datasets)

            dataset_name = next(
                (
                    d.get("name", "Unknown")
                    for d in datasets
                    if d.get("id") == dataset_id
                ),
                "Unknown",
            )

            start_idx = (page - 1) * size
            end_idx = start_idx + size
            paginated_docs = documents[start_idx:end_idx]

        except Exception as e:
            return jsonify({"error": str(e)}), 500

        return jsonify(
            {
                "documents": paginated_docs,
                "total": total,
                "dataset_name": dataset_name,
                "page": page,
                "size": size,
            }
        )

    @bp.route("/import/<dataset_id>/<document_id>", methods=["POST"])
    def ragflow_import(dataset_id, document_id):
        settings = get_settings()
        client = get_ragflow_client(settings)

        if not client:
            return jsonify({"error": "Ragflow not configured"}), 400

        try:
            content = client.get_document_content(dataset_id, document_id)

            cache_key = f"docs_{dataset_id}_all"
            cached = ragflow_cache.get(cache_key)
            if cached and cached.get("documents"):
                doc_info = next(
                    (d for d in cached["documents"] if d.get("id") == document_id), {}
                )
            else:
                documents, _ = client.list_documents(dataset_id, page=1, size=100)
                doc_info = next(
                    (d for d in documents if d.get("id") == document_id), {}
                )

            doc_title = doc_info.get("title", "") or doc_info.get(
                "name", "Imported Document"
            )
            doc_name = (
                doc_title
                if doc_title and doc_title != "Imported Document"
                else doc_info.get("name", "Imported Document")
            )

            new_file = PDFFile(
                filename=doc_name, text=content, figures="[]", captions="[]"
            )
            db.session.add(new_file)
            db.session.commit()

            task_id = None
            if content and len(content) > 100:
                task_id = str(uuid.uuid4())
                new_task = Task(id=task_id, status="processing")
                db.session.add(new_task)
                db.session.commit()

                thread = threading.Thread(
                    target=_run_summary_generation, args=(app, task_id, new_file.id)
                )
                thread.start()

            ragflow_cache.invalidate(f"docs_{dataset_id}_all")

            return jsonify(
                {
                    "success": True,
                    "file_id": new_file.id,
                    "filename": doc_name,
                    "task_id": task_id,
                }
            )
        except Exception as e:
            db.session.rollback()
            return jsonify({"error": str(e)}), 500

    @bp.route("/search/<dataset_id>", methods=["POST"])
    def ragflow_search(dataset_id):
        settings = get_settings()
        client = get_ragflow_client(settings)

        if not client:
            return jsonify({"error": "Ragflow not configured"}), 400

        query = request.json.get("query", "")
        if not query:
            return jsonify({"error": "Query required"}), 400

        try:
            result = client.request(
                "POST",
                f"/datasets/{dataset_id}/retrieval",
                json={"query": query, "top_k": 10},
            )
            return jsonify(result)
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    return bp
