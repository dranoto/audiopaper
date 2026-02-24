import json
import os
import uuid
import threading

from flask import Blueprint, request, jsonify, render_template

from database import db, PDFFile, Task, get_settings
from ragflow_service import get_ragflow_client
from utils.cache import ragflow_cache
from utils.task_queue import TaskQueue, TaskStatus
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
            # Get document info from cache or API
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

            # Check if already imported
            existing = PDFFile.query.filter_by(ragflow_document_id=document_id).first()
            if existing:
                return jsonify(
                    {
                        "success": True,
                        "file_id": existing.id,
                        "filename": existing.filename,
                        "message": "Document already imported",
                    }
                ), 200

            # Create new file with Ragflow references ONLY (no local content)
            new_file = PDFFile(
                filename=doc_name,
                text=None,  # Don't store locally - fetch on demand
                figures="[]",
                captions="[]",
                ragflow_document_id=document_id,
                ragflow_dataset_id=dataset_id,
            )
            db.session.add(new_file)
            db.session.commit()

            # Queue summary generation (fetched from Ragflow when needed)
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

    @bp.route("/import_batch/<dataset_id>", methods=["POST"])
    def ragflow_import_batch(dataset_id):
        """Import multiple documents from a dataset at once."""
        settings = get_settings()
        client = get_ragflow_client(settings)

        if not client:
            return jsonify({"error": "Ragflow not configured"}), 400

        data = request.get_json() or {}
        document_ids = data.get("document_ids", [])
        auto_generate = data.get("auto_generate", True)

        if not document_ids:
            return jsonify({"error": "No document IDs provided"}), 400

        batch_id = str(uuid.uuid4())[:8]
        imported_files = []
        task_ids = []

        try:
            # Get all documents info
            cache_key = f"docs_{dataset_id}_all"
            cached = ragflow_cache.get(cache_key)
            if cached and cached.get("documents"):
                all_docs = cached.get("documents", [])
            else:
                all_docs, _ = client.list_documents(dataset_id, page=1, size=1000)
                ragflow_cache.set(cache_key, {"documents": all_docs})

            for doc_id in document_ids:
                # Find document info
                doc_info = next((d for d in all_docs if d.get("id") == doc_id), {})
                doc_title = doc_info.get("title", "") or doc_info.get(
                    "name", "Imported Document"
                )
                doc_name = (
                    doc_title
                    if doc_title and doc_title != "Imported Document"
                    else doc_info.get("name", "Imported Document")
                )

                # Check if already imported
                existing = PDFFile.query.filter_by(ragflow_document_id=doc_id).first()
                if existing:
                    imported_files.append(
                        {
                            "document_id": doc_id,
                            "file_id": existing.id,
                            "filename": existing.filename,
                            "status": "already_imported",
                        }
                    )
                    continue

                # Create new file
                new_file = PDFFile(
                    filename=doc_name,
                    text=None,
                    figures="[]",
                    captions="[]",
                    ragflow_document_id=doc_id,
                    ragflow_dataset_id=dataset_id,
                )
                db.session.add(new_file)
                db.session.flush()

                imported_files.append(
                    {
                        "document_id": doc_id,
                        "file_id": new_file.id,
                        "filename": new_file.filename,
                        "status": "imported",
                    }
                )

                # Queue summary generation if requested
                if auto_generate:
                    task_id = str(uuid.uuid4())
                    new_task = Task(
                        id=task_id,
                        status=TaskStatus.PENDING,
                        result=json.dumps(
                            {
                                "task_type": "summary",
                                "file_id": new_file.id,
                                "batch_id": batch_id,
                                "priority": 10,
                                "attempts": 0,
                                "max_attempts": 3,
                            }
                        ),
                    )
                    db.session.add(new_task)
                    task_ids.append(task_id)

            db.session.commit()

            # Start workers if tasks were queued
            if task_ids:
                task_queue = TaskQueue.get_instance()
                task_queue.start_workers(app)

            ragflow_cache.invalidate(f"docs_{dataset_id}_all")

            return jsonify(
                {
                    "success": True,
                    "batch_id": batch_id,
                    "imported": imported_files,
                    "tasks_queued": len(task_ids),
                }
            )

        except Exception as e:
            db.session.rollback()
            return jsonify({"error": str(e)}), 500

    @bp.route("/task/<task_id>")
    def get_task_status(task_id):
        """Get status of a single task."""
        task = Task.query.get(task_id)
        if not task:
            return jsonify({"error": "Task not found"}), 404

        task_data = json.loads(task.result) if task.result else {}

        return jsonify(
            {
                "id": task.id,
                "status": task.status,
                "task_type": task_data.get("task_type"),
                "file_id": task_data.get("file_id"),
                "batch_id": task_data.get("batch_id"),
                "error": task_data.get("error"),
                "attempts": task_data.get("attempts", 0),
            }
        )

    @bp.route("/tasks")
    def get_all_tasks():
        """Get all tasks, optionally filtered by file_id or batch_id."""
        file_id = request.args.get("file_id", type=int)
        batch_id = request.args.get("batch_id")

        if file_id:
            all_tasks = Task.query.order_by(Task.id.desc()).limit(200).all()
            filtered = [
                t
                for t in all_tasks
                if json.loads(t.result or "{}").get("file_id") == file_id
            ]
        elif batch_id:
            all_tasks = Task.query.order_by(Task.id.desc()).limit(200).all()
            filtered = [
                t
                for t in all_tasks
                if json.loads(t.result or "{}").get("batch_id") == batch_id
            ]
        else:
            filtered = Task.query.order_by(Task.id.desc()).limit(50).all()

        result = []
        for task in filtered:
            task_data = json.loads(task.result) if task.result else {}
            result.append(
                {
                    "id": task.id,
                    "status": task.status,
                    "task_type": task_data.get("task_type"),
                    "file_id": task_data.get("file_id"),
                    "batch_id": task_data.get("batch_id"),
                    "error": task_data.get("error"),
                    "attempts": task_data.get("attempts", 0),
                }
            )

        return jsonify({"tasks": result})

    @bp.route("/task/<task_id>/retry", methods=["POST"])
    def retry_task(task_id):
        """Manually retry a failed task."""
        task_queue = TaskQueue.get_instance()
        success = task_queue.retry_task(task_id)

        if success:
            task_queue.start_workers(app)
            return jsonify({"success": True, "message": "Task queued for retry"})
        return jsonify({"error": "Task not found"}), 404

    @bp.route("/batch/<batch_id>")
    def get_batch_status(batch_id):
        """Get status of a batch of tasks."""
        task_queue = TaskQueue.get_instance()
        status = task_queue.get_batch_status(batch_id)
        return jsonify(status)

    return bp
