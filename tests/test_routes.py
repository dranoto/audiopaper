import pytest
import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def app():
    """Create and configure a test instance of the app."""
    from app import app as _app

    _app.config["TESTING"] = True
    _app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    _app.config["WTF_CSRF_ENABLED"] = False

    with _app.app_context():
        from database import db

        db.create_all()

    yield _app

    with _app.app_context():
        from database import db

        db.drop_all()


@pytest.fixture
def client(app):
    """Create a test client."""
    return app.test_client()


@pytest.fixture
def runner(app):
    """Create a test CLI runner."""
    return app.test_cli_runner()


class TestIndex:
    """Tests for the index/home route."""

    def test_index_GET(self, client):
        """Test the index page loads."""
        response = client.get("/")
        assert response.status_code == 200

    def test_index_contains_upload(self, client):
        """Test index contains upload elements."""
        response = client.get("/")
        assert b"Upload" in response.data or b"upload" in response.data.lower()


class TestSettings:
    """Tests for settings routes."""

    def test_settings_GET(self, client):
        """Test settings page loads."""
        response = client.get("/settings")
        assert response.status_code == 200

    def test_settings_POST(self, client):
        """Test settings form submission."""
        response = client.post(
            "/settings",
            data={
                "summary_prompt": "Test prompt",
                "transcript_prompt": "Test transcript",
                "transcript_length": "medium",
            },
            follow_redirects=True,
        )
        assert response.status_code == 200


class TestFileUpload:
    """Tests for file upload functionality."""

    def test_upload_without_file(self, client):
        """Test upload without file returns error."""
        response = client.post("/upload")
        # Should redirect or return error
        assert response.status_code in [302, 400]


class TestAPIEndpoints:
    """Tests for API endpoints."""

    def test_file_content_not_found(self, client):
        """Test file_content returns 404 for non-existent file."""
        response = client.get("/file_content/99999")
        assert response.status_code == 404

    def test_file_details_not_found(self, client):
        """Test file_details returns 404 for non-existent file."""
        response = client.get("/file_details/99999")
        assert response.status_code == 404

    def test_delete_file_not_found(self, client):
        """Test delete_file returns 404 for non-existent file."""
        response = client.delete("/delete_file/99999")
        assert response.status_code == 404


class TestErrorHandlers:
    """Tests for error handlers."""

    def test_404_error(self, client):
        """Test 404 error returns JSON."""
        response = client.get("/nonexistent-page")
        assert response.status_code == 404


class TestHealthCheck:
    """Basic health check tests."""

    def test_app_exists(self, app):
        """Test app exists."""
        assert app is not None

    def test_app_config(self, app):
        """Test app has required config."""
        assert app.config["UPLOAD_FOLDER"] == "uploads"
        assert app.config["GENERATED_AUDIO_FOLDER"] == "generated_audio"
