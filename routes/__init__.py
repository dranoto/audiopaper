def register_blueprints(app):
    from routes.files import create_files_bp
    from routes.generation import create_generation_bp
    from routes.chat import create_chat_bp
    from routes.ragflow import create_ragflow_bp
    from routes.settings import create_settings_bp
    from routes.static import create_static_bp

    app.register_blueprint(create_files_bp(app))
    app.register_blueprint(create_generation_bp(app))
    app.register_blueprint(create_chat_bp(app))
    app.register_blueprint(create_ragflow_bp(app))
    app.register_blueprint(create_settings_bp(app))
    app.register_blueprint(create_static_bp(app))
