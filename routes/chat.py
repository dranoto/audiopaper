import json

from flask import Blueprint, request, jsonify

from database import PDFFile, get_settings
from ragflow_service import get_ragflow_client


def create_chat_bp(app):
    bp = Blueprint("chat", __name__)

    @bp.route("/chat/<int:file_id>", methods=["POST"])
    def chat_with_file(file_id):
        pdf_file = PDFFile.query.get_or_404(file_id)
        data = request.get_json()
        if not data or "message" not in data:
            return jsonify({"error": "Message is required in the request body."}), 400

        question = data.get("message")
        use_ragflow = data.get("use_ragflow", False)
        ragflow_dataset_id = data.get("ragflow_dataset_id")

        history = json.loads(pdf_file.chat_history or "[]")

        if not hasattr(app, "text_client") or not app.text_client:
            return jsonify(
                {
                    "error": "NanoGPT text client not initialized. Please set API key in settings."
                }
            ), 500

        settings = get_settings()
        model_name = settings.chat_model

        system_prompt = "You are a helpful research assistant. Your task is to answer questions based on the provided document content."

        ragflow_context = ""
        if use_ragflow:
            try:
                client = get_ragflow_client(settings)
                if client:
                    datasets = client.list_datasets()
                    if datasets:
                        target_dataset = ragflow_dataset_id
                        if not target_dataset and settings.ragflow_default_dataset:
                            target_dataset = settings.ragflow_default_dataset
                        if not target_dataset:
                            target_dataset = datasets[0].get("id")

                        if target_dataset:
                            result = client.request(
                                "POST",
                                f"/datasets/{target_dataset}/retrieval",
                                json={"query": question, "top_k": 5},
                            )

                            chunks = result.get("data", {}).get("chunks", [])
                            if chunks:
                                ragflow_context = "\n\n".join(
                                    [
                                        f"[From related documents in knowledge base:]\n{c.get('content', '')}"
                                        for c in chunks[:5]
                                    ]
                                )
                                system_prompt += " You may also use relevant context from the attached knowledge base to provide better answers."
            except Exception as e:
                app.logger.warning(f"Ragflow retrieval failed: {e}")

        try:
            messages = [{"role": "system", "content": system_prompt}]

            context_parts = [f"Document content:\n{pdf_file.text}"]
            if ragflow_context:
                context_parts.append(ragflow_context)

            context_section = "\n\n---\n\n".join(context_parts)

            messages.append(
                {
                    "role": "user",
                    "content": f"{context_section}\n\n---\n\nPlease answer questions about this document.",
                }
            )

            for msg in history[-6:]:
                role = msg.get("role", "user")
                if role == "model":
                    role = "assistant"
                messages.append(
                    {"role": role, "content": msg.get("parts", [{}])[0].get("text", "")}
                )

            messages.append({"role": "user", "content": question})

            response = app.text_client.chat.completions.create(
                model=model_name, messages=messages
            )

            response_text = response.choices[0].message.content

            history.append({"role": "user", "parts": [{"text": question}]})
            history.append({"role": "model", "parts": [{"text": response_text}]})
            pdf_file.chat_history = json.dumps(history)
            from database import db

            db.session.commit()

            return jsonify(
                {"message": response_text, "ragflow_used": bool(ragflow_context)}
            )
        except Exception as e:
            app.logger.error(f"Chat generation failed for file_id {file_id}: {e}")
            return jsonify(
                {"error": f"Could not generate a response. Details: {str(e)}"}
            ), 500

    return bp
