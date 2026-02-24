import os
import base64
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2
import hashlib


class KeyEncryption:
    """Handles encryption/decryption of sensitive API keys."""

    _instance = None
    _fernet = None

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        if KeyEncryption._fernet is not None:
            return

        # Generate key from environment or create a derived key
        # In production, set ENCRYPTION_KEY environment variable
        encryption_key = os.environ.get("ENCRYPTION_KEY")

        if encryption_key:
            # Use provided key (must be URL-safe base64 encoded 32 bytes)
            try:
                KeyEncryption._fernet = Fernet(
                    encryption_key.encode()
                    if isinstance(encryption_key, str)
                    else encryption_key
                )
            except Exception:
                # Invalid key, generate a new one
                KeyEncryption._fernet = self._generate_fernet()
        else:
            # Try to load from file, otherwise generate
            key_file = os.path.join(os.path.dirname(__file__), "..", "instance", ".key")
            if os.path.exists(key_file):
                with open(key_file, "rb") as f:
                    KeyEncryption._fernet = Fernet(f.read())
            else:
                KeyEncryption._fernet = self._generate_fernet()
                # Save for future use
                os.makedirs(os.path.dirname(key_file), exist_ok=True)
                with open(key_file, "wb") as f:
                    f.write(KeyEncryption._fernet._key)

    def _generate_fernet(self):
        """Generate a new Fernet key."""
        return Fernet(Fernet.generate_key())

    def encrypt(self, plaintext: str) -> str:
        """Encrypt a plaintext string."""
        if not plaintext:
            return ""
        return base64.urlsafe_b64encode(
            KeyEncryption._fernet.encrypt(plaintext.encode())
        ).decode()

    def decrypt(self, ciphertext: str) -> str:
        """Decrypt a ciphertext string."""
        if not ciphertext:
            return ""
        try:
            return KeyEncryption._fernet.decrypt(
                base64.urlsafe_b64decode(ciphertext.encode())
            ).decode()
        except Exception:
            # If decryption fails, might be plain text (legacy data)
            return ciphertext


# Convenience functions
def encrypt_key(key: str) -> str:
    """Encrypt an API key."""
    return KeyEncryption.get_instance().encrypt(key)


def decrypt_key(key: str) -> str:
    """Decrypt an API key."""
    return KeyEncryption.get_instance().decrypt(key)
