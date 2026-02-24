from flask import jsonify, render_template


def register_error_handlers(app):
    """Register error handlers for the Flask app."""

    @app.errorhandler(400)
    def bad_request(error):
        return jsonify({"error": "Bad request", "message": str(error)}), 400

    @app.errorhandler(401)
    def unauthorized(error):
        return jsonify(
            {"error": "Unauthorized", "message": "Authentication required"}
        ), 401

    @app.errorhandler(403)
    def forbidden(error):
        return jsonify({"error": "Forbidden", "message": "Access denied"}), 403

    @app.errorhandler(404)
    def not_found(error):
        if request_wants_json():
            return jsonify(
                {
                    "error": "Not found",
                    "message": "The requested resource was not found",
                }
            ), 404
        return render_template("error.html", error="Page not found", code=404), 404

    @app.errorhandler(405)
    def method_not_allowed(error):
        return jsonify({"error": "Method not allowed", "message": str(error)}), 405

    @app.errorhandler(413)
    def request_entity_too_large(error):
        return jsonify(
            {
                "error": "File too large",
                "message": "The uploaded file exceeds the maximum size",
            }
        ), 413

    @app.errorhandler(422)
    def unprocessable_entity(error):
        return jsonify({"error": "Unprocessable entity", "message": str(error)}), 422

    @app.errorhandler(429)
    def rate_limited(error):
        return jsonify(
            {
                "error": "Rate limited",
                "message": "Too many requests. Please try again later.",
            }
        ), 429

    @app.errorhandler(500)
    def internal_error(error):
        app.logger.error(f"Internal server error: {error}")
        return jsonify(
            {
                "error": "Internal server error",
                "message": "An unexpected error occurred",
            }
        ), 500

    @app.errorhandler(502)
    def bad_gateway(error):
        return jsonify(
            {
                "error": "Bad gateway",
                "message": "The server received an invalid response",
            }
        ), 502

    @app.errorhandler(503)
    def service_unavailable(error):
        return jsonify(
            {
                "error": "Service unavailable",
                "message": "The service is temporarily unavailable",
            }
        ), 503


def request_wants_json():
    """Check if the request prefers JSON response."""
    from flask import request

    best = request.accept_mimetypes.best_match(["application/json", "text/html"])
    return (
        best == "application/json"
        and request.accept_mimetypes[best] > request.accept_mimetypes["text/html"]
    )
