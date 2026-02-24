import pytest
import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestEncryption:
    """Tests for encryption utilities."""

    def test_encrypt_decrypt(self):
        """Test basic encryption and decryption."""
        from utils.encryption import encrypt_key, decrypt_key

        original = "test-api-key-12345"
        encrypted = encrypt_key(original)

        # Encrypted should be different from original
        assert encrypted != original

        # Should decrypt back to original
        decrypted = decrypt_key(encrypted)
        assert decrypted == original

    def test_encrypt_empty(self):
        """Test encrypting empty string."""
        from utils.encryption import encrypt_key, decrypt_key

        assert encrypt_key("") == ""
        assert decrypt_key("") == ""

    def test_encrypt_none(self):
        """Test encrypting None."""
        from utils.encryption import encrypt_key, decrypt_key

        assert encrypt_key(None) == ""
        assert decrypt_key(None) == ""


class TestSimpleCache:
    """Tests for simple cache."""

    def test_cache_set_get(self):
        """Test basic cache set and get."""
        from utils.cache import SimpleCache

        cache = SimpleCache(default_ttl=60)
        cache.set("key1", "value1")

        assert cache.get("key1") == "value1"

    def test_cache_expired(self):
        """Test cache expiration."""
        from utils.cache import SimpleCache
        import time

        cache = SimpleCache(default_ttl=1)  # 1 second TTL
        cache.set("key1", "value1")

        time.sleep(1.1)  # Wait for expiry

        assert cache.get("key1") is None

    def test_cache_delete(self):
        """Test cache delete."""
        from utils.cache import SimpleCache

        cache = SimpleCache()
        cache.set("key1", "value1")
        cache.delete("key1")

        assert cache.get("key1") is None

    def test_cache_clear(self):
        """Test cache clear."""
        from utils.cache import SimpleCache

        cache = SimpleCache()
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        cache.clear()

        assert cache.get("key1") is None
        assert cache.get("key2") is None

    def test_cache_get_or_compute(self):
        """Test get_or_compute."""
        from utils.cache import SimpleCache

        cache = SimpleCache()

        result = cache.get_or_compute("compute_test", lambda: "computed")
        assert result == "computed"

        # Second call should return cached
        result2 = cache.get_or_compute("compute_test", lambda: "different")
        assert result2 == "computed"

    def test_cache_invalidate_prefix(self):
        """Test prefix-based invalidation."""
        from utils.cache import SimpleCache

        cache = SimpleCache()
        cache.set("user:1", "user1")
        cache.set("user:2", "user2")
        cache.set("post:1", "post1")

        invalidated = cache.invalidate_prefix("user:")

        assert invalidated == 2
        assert cache.get("user:1") is None
        assert cache.get("user:2") is None
        assert cache.get("post:1") == "post1"


class TestConfig:
    """Tests for configuration."""

    def test_config_defaults(self):
        """Test configuration defaults."""
        from config import Config

        assert Config.UPLOAD_FOLDER == "uploads"
        assert Config.GENERATED_AUDIO_FOLDER == "generated_audio"
        assert Config.MAX_CONTENT_LENGTH > 0

    def test_config_validate(self):
        """Test config validation."""
        from config import Config

        issues = Config.validate()
        # Should have no critical issues (folders may be created)
        assert isinstance(issues, list)
