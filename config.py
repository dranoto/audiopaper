"""
Configuration management for AudioPaper.
All settings should be accessed through this module.
"""

import os
from typing import Optional, Any
from functools import lru_cache


class Config:
    """Application configuration with defaults and environment override."""

    # Database
    SQLALCHEMY_DATABASE_URI: str = os.environ.get(
        "DATABASE_URL", "sqlite:///db.sqlite3"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS: bool = False

    # Folders
    UPLOAD_FOLDER: str = os.environ.get("UPLOAD_FOLDER", "uploads")
    GENERATED_AUDIO_FOLDER: str = os.environ.get(
        "GENERATED_AUDIO_FOLDER", "generated_audio"
    )

    # Server
    SERVER_NAME: Optional[str] = os.environ.get("SERVER_NAME")
    PREFERRED_URL_SCHEME: str = os.environ.get("PREFERRED_URL_SCHEME", "http")
    APPLICATION_ROOT: str = os.environ.get("APPLICATION_ROOT", "/")

    # Upload limits
    MAX_CONTENT_LENGTH: int = int(
        os.environ.get("MAX_CONTENT_LENGTH", 50 * 1024 * 1024)
    )  # 50MB default
    ALLOWED_EXTENSIONS: set = {"pdf"}

    # Default models (can be overridden in database settings)
    DEFAULT_SUMMARY_MODEL: str = os.environ.get("SUMMARY_MODEL", "openai/gpt-5.2")
    DEFAULT_TRANSCRIPT_MODEL: str = os.environ.get("TRANSCRIPT_MODEL", "openai/gpt-5.2")
    DEFAULT_CHAT_MODEL: str = os.environ.get("CHAT_MODEL", "openai/gpt-5.2")
    DEFAULT_TTS_MODEL: str = os.environ.get("TTS_MODEL", "hexgrad/Kokoro-82M")

    # Default voices
    DEFAULT_HOST_VOICE: str = os.environ.get("TTS_HOST_VOICE", "af_bella")
    DEFAULT_EXPERT_VOICE: str = os.environ.get("TTS_EXPERT_VOICE", "am_onyx")

    # Caching
    CACHE_TTL: int = int(os.environ.get("CACHE_TTL", 300))  # 5 minutes
    CACHE_ENABLED: bool = os.environ.get("CACHE_ENABLED", "true").lower() == "true"

    # Security
    SECRET_KEY: Optional[str] = os.environ.get("SECRET_KEY")
    ENCRYPTION_KEY: Optional[str] = os.environ.get("ENCRYPTION_KEY")

    # API Keys (from environment - for initial setup)
    NANOGPT_API_KEY: Optional[str] = os.environ.get("NANOGPT_API_KEY")
    DEEPINFRA_API_KEY: Optional[str] = os.environ.get("DEEPINFRA_API_KEY")
    RAGFLOW_URL: Optional[str] = os.environ.get("RAGFLOW_URL")
    RAGFLOW_API_KEY: Optional[str] = os.environ.get("RAGFLOW_API_KEY")
    GEMINI_API_KEY: Optional[str] = os.environ.get("GEMINI_API_KEY")

    #
    DEBUG: bool = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    TESTING: bool = False

    @classmethod
    def from_object(cls, obj):
        """Update config from an object."""
        for key in dir(obj):
            if key.isupper():
                setattr(cls, key, getattr(obj, key))
        return cls

    @classmethod
    @lru_cache()
    def get(cls, key: str, default: Any = None) -> Any:
        """Get a configuration value."""
        return getattr(cls, key, default)

    @classmethod
    def validate(cls) -> list:
        """Validate configuration and return list of issues."""
        issues = []

        # Check required folders exist
        if not os.path.exists(cls.UPLOAD_FOLDER):
            try:
                os.makedirs(cls.UPLOAD_FOLDER, exist_ok=True)
            except OSError as e:
                issues.append(f"Cannot create UPLOAD_FOLDER: {e}")

        if not os.path.exists(cls.GENERATED_AUDIO_FOLDER):
            try:
                os.makedirs(cls.GENERATED_AUDIO_FOLDER, exist_ok=True)
            except OSError as e:
                issues.append(f"Cannot create GENERATED_AUDIO_FOLDER: {e}")

        return issues


# Create singleton instance
config = Config()


def get_config() -> Config:
    """Get the application config instance."""
    return config
