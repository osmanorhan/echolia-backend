"""
E2EE cryptographic operations using X25519 and ChaCha20-Poly1305.
"""
import base64
import secrets
import structlog
from datetime import datetime, timedelta
from typing import Tuple, Optional
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric import x25519
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305

from app.config import settings


logger = structlog.get_logger()


class E2EECrypto:
    """
    Handles X25519 key exchange and ChaCha20-Poly1305 encryption for E2EE inference.
    """

    HKDF_INFO = b"echolia-inference-v1"
    KEY_ROTATION_DAYS = 30  # Rotate keys monthly

    def __init__(self):
        self._private_key: Optional[x25519.X25519PrivateKey] = None
        self._public_key: Optional[x25519.X25519PublicKey] = None
        self._key_id: Optional[str] = None
        self._key_created_at: Optional[datetime] = None
        self._key_expires_at: Optional[datetime] = None

        # Store path for key persistence
        self._key_file = Path(settings.data_dir) / "inference_key.bin"

        # Initialize or load keys
        self._initialize_keys()

    def _initialize_keys(self) -> None:
        """Initialize or load X25519 keypair."""
        try:
            # Ensure data directory exists
            Path(settings.data_dir).mkdir(parents=True, exist_ok=True)

            # Try to load existing key
            if self._key_file.exists():
                self._load_key()

                # Check if key needs rotation
                if datetime.utcnow() > self._key_expires_at:
                    logger.info("inference_key_expired_rotating")
                    self._generate_new_key()
            else:
                self._generate_new_key()

        except Exception as e:
            logger.error("inference_key_initialization_failed", error=str(e))
            # Generate new key as fallback
            self._generate_new_key()

    def _generate_new_key(self) -> None:
        """Generate new X25519 keypair."""
        self._private_key = x25519.X25519PrivateKey.generate()
        self._public_key = self._private_key.public_key()

        self._key_created_at = datetime.utcnow()
        self._key_expires_at = self._key_created_at + timedelta(days=self.KEY_ROTATION_DAYS)

        # Generate key ID based on timestamp
        self._key_id = f"server-key-{self._key_created_at.strftime('%Y-%m')}"

        # Persist key
        self._save_key()

        logger.info(
            "inference_key_generated",
            key_id=self._key_id,
            expires_at=self._key_expires_at.isoformat()
        )

    def _save_key(self) -> None:
        """Save private key to disk (encrypted in production, use HSM/KMS)."""
        try:
            # Serialize private key bytes
            private_bytes = self._private_key.private_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PrivateFormat.Raw,
                encryption_algorithm=serialization.NoEncryption()
            )

            # Create metadata
            metadata = (
                f"{self._key_id}\n"
                f"{self._key_created_at.isoformat()}\n"
                f"{self._key_expires_at.isoformat()}\n"
            ).encode('utf-8')

            # Write to file (32 bytes key + metadata)
            with open(self._key_file, 'wb') as f:
                f.write(private_bytes)
                f.write(b'\n---\n')
                f.write(metadata)

            # Set restrictive permissions
            self._key_file.chmod(0o600)

            logger.info("inference_key_saved", path=str(self._key_file))

        except Exception as e:
            logger.error("inference_key_save_failed", error=str(e))
            raise

    def _load_key(self) -> None:
        """Load private key from disk."""
        try:
            with open(self._key_file, 'rb') as f:
                content = f.read()

            # Split key and metadata
            parts = content.split(b'\n---\n')
            private_bytes = parts[0]
            metadata_lines = parts[1].decode('utf-8').strip().split('\n')

            # Recreate private key
            self._private_key = x25519.X25519PrivateKey.from_private_bytes(private_bytes)
            self._public_key = self._private_key.public_key()

            # Parse metadata
            self._key_id = metadata_lines[0]
            self._key_created_at = datetime.fromisoformat(metadata_lines[1])
            self._key_expires_at = datetime.fromisoformat(metadata_lines[2])

            logger.info(
                "inference_key_loaded",
                key_id=self._key_id,
                expires_at=self._key_expires_at.isoformat()
            )

        except Exception as e:
            logger.error("inference_key_load_failed", error=str(e))
            raise

    def get_public_key_info(self) -> dict:
        """
        Get server's public key information for clients.

        Returns:
            Dict with public_key (base64), key_id, expires_at, algorithm
        """
        # Check for key rotation
        if datetime.utcnow() > self._key_expires_at:
            self._generate_new_key()

        public_bytes = self._public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw
        )

        return {
            "public_key": base64.b64encode(public_bytes).decode('utf-8'),
            "key_id": self._key_id,
            "expires_at": self._key_expires_at.isoformat() + "Z",
            "algorithm": "X25519"
        }

    def derive_shared_secret(self, client_ephemeral_public_key_b64: str) -> bytes:
        """
        Derive shared secret using X25519 key exchange.

        Args:
            client_ephemeral_public_key_b64: Base64-encoded client ephemeral public key

        Returns:
            32-byte encryption key derived via HKDF
        """
        try:
            # Decode client's ephemeral public key
            client_public_bytes = base64.b64decode(client_ephemeral_public_key_b64)
            client_public_key = x25519.X25519PublicKey.from_public_bytes(client_public_bytes)

            # Perform X25519 key exchange
            shared_secret = self._private_key.exchange(client_public_key)

            # Derive encryption key using HKDF
            hkdf = HKDF(
                algorithm=hashes.SHA256(),
                length=32,  # ChaCha20 key size
                salt=None,
                info=self.HKDF_INFO,
            )
            encryption_key = hkdf.derive(shared_secret)

            return encryption_key

        except Exception as e:
            logger.error(
                "shared_secret_derivation_failed",
                error=str(e),
                client_pub_b64_len=len(client_ephemeral_public_key_b64 or ""),
                key_id=self._key_id,
            )
            raise ValueError("Failed to derive shared secret") from e

    def decrypt_content(
        self,
        ciphertext_b64: str,
        nonce_b64: str,
        mac_b64: str,
        encryption_key: bytes
    ) -> str:
        """
        Decrypt content using ChaCha20-Poly1305.

        Args:
            ciphertext_b64: Base64-encoded ciphertext
            nonce_b64: Base64-encoded 12-byte nonce
            mac_b64: Base64-encoded 16-byte MAC tag
            encryption_key: 32-byte encryption key

        Returns:
            Decrypted plaintext string
        """
        try:
            # Decode base64 inputs
            ciphertext = base64.b64decode(ciphertext_b64)
            nonce = base64.b64decode(nonce_b64)
            mac = base64.b64decode(mac_b64)

            # ChaCha20-Poly1305 expects ciphertext + tag
            authenticated_ciphertext = ciphertext + mac

            # Decrypt
            chacha = ChaCha20Poly1305(encryption_key)
            plaintext_bytes = chacha.decrypt(nonce, authenticated_ciphertext, None)

            return plaintext_bytes.decode('utf-8')

        except Exception as e:
            logger.error(
                "decryption_failed",
                error=str(e),
                ciphertext_b64_len=len(ciphertext_b64 or ""),
                nonce_b64_len=len(nonce_b64 or ""),
                mac_b64_len=len(mac_b64 or ""),
            )
            raise ValueError("Decryption failed - invalid encryption") from e

    def encrypt_response(self, plaintext: str, encryption_key: bytes) -> Tuple[str, str, str]:
        """
        Encrypt response using ChaCha20-Poly1305.

        Args:
            plaintext: Plaintext string to encrypt
            encryption_key: 32-byte encryption key

        Returns:
            Tuple of (ciphertext_b64, nonce_b64, mac_b64)
        """
        try:
            # Generate random nonce (12 bytes for ChaCha20-Poly1305)
            nonce = secrets.token_bytes(12)

            # Encrypt
            chacha = ChaCha20Poly1305(encryption_key)
            authenticated_ciphertext = chacha.encrypt(nonce, plaintext.encode('utf-8'), None)

            # Split ciphertext and tag (tag is last 16 bytes)
            ciphertext = authenticated_ciphertext[:-16]
            mac = authenticated_ciphertext[-16:]

            # Base64 encode
            return (
                base64.b64encode(ciphertext).decode('utf-8'),
                base64.b64encode(nonce).decode('utf-8'),
                base64.b64encode(mac).decode('utf-8')
            )

        except Exception as e:
            logger.error("encryption_failed", error=str(e))
            raise ValueError("Encryption failed") from e


# Global crypto instance
e2ee_crypto = E2EECrypto()
