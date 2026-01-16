"""
OAuth token verification for Google and Apple Sign-In.
"""
import structlog
import time
from typing import Optional, Dict, Any
import jwt
import requests
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

from app.config import settings


logger = structlog.get_logger()


class UserInfo:
    """OAuth user information extracted from ID token."""

    def __init__(
        self,
        provider: str,
        provider_user_id: str,
        email: Optional[str] = None,
        name: Optional[str] = None,
        email_verified: bool = False
    ):
        self.provider = provider
        self.provider_user_id = provider_user_id
        self.email = email
        self.name = name
        self.email_verified = email_verified

    def to_dict(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "provider_user_id": self.provider_user_id,
            "email": self.email,
            "name": self.name,
            "email_verified": self.email_verified
        }


class GoogleTokenVerifier:
    """Verifies Google ID tokens using Google's public keys."""

    def __init__(self):
        self.client_id = settings.google_client_id

    def verify(self, id_token_string: str) -> Optional[UserInfo]:
        """
        Verify Google ID token and extract user info.

        Args:
            id_token_string: JWT token from Google Sign-In

        Returns:
            UserInfo if valid, None otherwise
        """
        try:
            # Verify the token with Google
            idinfo = id_token.verify_oauth2_token(
                id_token_string,
                google_requests.Request(),
                self.client_id
            )

            # Verify issuer
            if idinfo['iss'] not in ['accounts.google.com', 'https://accounts.google.com']:
                logger.error("google_token_invalid_issuer", issuer=idinfo.get('iss'))
                return None

            # Extract user info
            user_info = UserInfo(
                provider="google",
                provider_user_id=idinfo['sub'],
                email=idinfo.get('email'),
                name=idinfo.get('name'),
                email_verified=idinfo.get('email_verified', False)
            )

            logger.info(
                "google_token_verified",
                provider_user_id=user_info.provider_user_id,
                email_verified=user_info.email_verified
            )

            return user_info

        except ValueError as e:
            logger.error("google_token_verification_failed", error=str(e))
            return None
        except Exception as e:
            logger.error("google_token_verification_error", error=str(e))
            return None


class AppleTokenVerifier:
    """Verifies Apple ID tokens using Apple's public keys."""

    APPLE_PUBLIC_KEYS_URL = "https://appleid.apple.com/auth/keys"
    APPLE_ISSUER = "https://appleid.apple.com"

    def __init__(self):
        self._public_keys_cache: Optional[Dict[str, Any]] = None
        self._cache_timestamp: Optional[int] = None
        self._cache_ttl = 3600  # 1 hour

    def _get_apple_public_keys(self) -> Dict[str, Any]:
        """
        Fetch Apple's public keys for token verification.
        Cached for 1 hour.

        Returns:
            Dict of public keys indexed by key ID
        """
        current_time = int(time.time())

        # Return cached keys if still valid
        if (
            self._public_keys_cache is not None and
            self._cache_timestamp is not None and
            current_time - self._cache_timestamp < self._cache_ttl
        ):
            return self._public_keys_cache

        try:
            response = requests.get(self.APPLE_PUBLIC_KEYS_URL, timeout=10)
            response.raise_for_status()
            keys_data = response.json()

            # Index keys by kid (key ID)
            keys_dict = {key['kid']: key for key in keys_data['keys']}

            # Cache the keys
            self._public_keys_cache = keys_dict
            self._cache_timestamp = current_time

            logger.info("apple_public_keys_fetched", key_count=len(keys_dict))
            return keys_dict

        except Exception as e:
            logger.error("apple_public_keys_fetch_failed", error=str(e))
            raise

    def verify(self, id_token_string: str) -> Optional[UserInfo]:
        """
        Verify Apple ID token and extract user info.

        Args:
            id_token_string: JWT token from Apple Sign-In

        Returns:
            UserInfo if valid, None otherwise
        """
        try:
            # Decode token header to get key ID
            unverified_header = jwt.get_unverified_header(id_token_string)
            kid = unverified_header.get('kid')

            if not kid:
                logger.error("apple_token_missing_kid")
                return None

            # Get Apple's public keys
            public_keys = self._get_apple_public_keys()

            if kid not in public_keys:
                logger.error("apple_token_unknown_kid", kid=kid)
                return None

            # Get the specific key for this token
            key_data = public_keys[kid]

            # Convert JWK to PEM format for verification
            public_key = jwt.algorithms.RSAAlgorithm.from_jwk(key_data)

            # Verify and decode the token
            decoded = jwt.decode(
                id_token_string,
                public_key,
                algorithms=['RS256'],
                audience=settings.apple_client_ids + ([settings.apple_team_id] if settings.apple_team_id else []),
                issuer=self.APPLE_ISSUER
            )

            # Extract user info
            # Note: Apple may not provide email if user chose to hide it
            user_info = UserInfo(
                provider="apple",
                provider_user_id=decoded['sub'],
                email=decoded.get('email'),
                name=None,  # Apple doesn't provide name in token
                email_verified=decoded.get('email_verified', False)
            )

            logger.info(
                "apple_token_verified",
                provider_user_id=user_info.provider_user_id,
                email_verified=user_info.email_verified,
                email_provided=user_info.email is not None
            )

            return user_info

        except jwt.ExpiredSignatureError:
            logger.error("apple_token_expired")
            return None
        except jwt.InvalidTokenError as e:
            logger.error("apple_token_invalid", error=str(e))
            return None
        except Exception as e:
            logger.error("apple_token_verification_error", error=str(e))
            return None


# Global verifier instances
google_verifier = GoogleTokenVerifier()
apple_verifier = AppleTokenVerifier()


def verify_oauth_token(provider: str, id_token: str) -> Optional[UserInfo]:
    """
    Verify OAuth token from provider.

    Args:
        provider: 'google' or 'apple'
        id_token: JWT token from provider

    Returns:
        UserInfo if valid, None otherwise
    """
    if provider == "google":
        return google_verifier.verify(id_token)
    elif provider == "apple":
        return apple_verifier.verify(id_token)
    else:
        logger.error("unknown_oauth_provider", provider=provider)
        return None
