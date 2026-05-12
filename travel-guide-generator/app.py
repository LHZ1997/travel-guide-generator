"""Flask application entry point for Travel Guide Generator."""
import os
from flask import Flask, jsonify
from config import app_config


def create_app():
    """Application factory pattern."""
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )

    # Configuration
    app.config["SQLALCHEMY_DATABASE_URI"] = app_config.database_uri
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SECRET_KEY"] = app_config.secret_key
    app.config["DEBUG"] = app_config.debug

    # Initialize extensions
    from models import db
    db.init_app(app)

    with app.app_context():
        db.create_all()
        from services.init_service import InitService
        InitService.run()

        from skills.registry import skill_registry
        from pathlib import Path
        _skills_dir = Path(__file__).parent / "skills"
        skill_registry.load_from_directory(_skills_dir)

    # Register blueprints
    from routes import main_bp
    app.register_blueprint(main_bp)

    # Error handlers
    @app.errorhandler(404)
    def not_found(error):
        return jsonify({"error": "Not found"}), 404

    @app.errorhandler(500)
    def internal_error(error):
        return jsonify({"error": "Internal server error"}), 500

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(host="0.0.0.0", port=5002, debug=app_config.debug)
