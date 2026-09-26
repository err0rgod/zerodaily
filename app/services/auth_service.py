import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any
import bcrypt
import jwt
from google.oauth2 import id_token
import google.auth.transport.requests
from botocore.exceptions import ClientError

from app.config import get_settings

logger = logging.getLogger("zerodaily.auth")
logger.setLevel(logging.INFO)


class AuthService:
    """
    Handles ZeroDaily JWT minting & verification, secure password hashing,
    and Firebase ID token validation.
    """

    def __init__(self):
        self.settings = get_settings()
        self._auth_request = google.auth.transport.requests.Request()

    def hash_password(self, password: str) -> str:
        """Hashes a plaintext password using bcrypt with salt (truncates to 72 bytes for bcrypt compatibility)."""
        pw_bytes = password.encode("utf-8")[:72]
        salt = bcrypt.gensalt(rounds=12)
        hashed = bcrypt.hashpw(pw_bytes, salt)
        return hashed.decode("utf-8")

    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        """Verifies a plaintext password against a stored bcrypt hash."""
        if not plain_password or not hashed_password:
            return False
        try:
            pw_bytes = plain_password.encode("utf-8")[:72]
            return bcrypt.checkpw(pw_bytes, hashed_password.encode("utf-8"))
        except Exception as e:
            logger.warning(f"Password verification error: {e}")
            return False

    def create_access_token(
        self,
        user_id: str,
        email: Optional[str] = None,
        is_anonymous: bool = False,
        expires_delta: Optional[timedelta] = None,
    ) -> str:
        """
        Creates a signed JWT access token for mobile client and web sessions.
        """
        now = datetime.now(timezone.utc)
        if expires_delta:
            expire = now + expires_delta
        else:
            expire = now + timedelta(minutes=self.settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)

        payload = {
            "sub": user_id,
            "email": email,
            "is_anon": is_anonymous,
            "iat": int(now.timestamp()),
            "exp": int(expire.timestamp()),
            "iss": "zerodaily-api",
        }

        token = jwt.encode(payload, self.settings.JWT_SECRET_KEY, algorithm=self.settings.JWT_ALGORITHM)
        return token

    def decode_access_token(self, token: str) -> Optional[Dict[str, Any]]:
        """
        Decodes and validates a ZeroDaily JWT access token.
        Returns payload dict if valid, None otherwise.
        """
        try:
            payload = jwt.decode(
                token,
                self.settings.JWT_SECRET_KEY,
                algorithms=[self.settings.JWT_ALGORITHM],
                issuer="zerodaily-api",
            )
            return payload
        except jwt.ExpiredSignatureError:
            logger.debug("Token has expired")
            return None
        except jwt.InvalidTokenError as e:
            logger.debug(f"Invalid token: {e}")
            return None

    def verify_firebase_id_token(self, id_token_str: str) -> Optional[Dict[str, Any]]:
        """
        Verifies a Firebase Auth ID token using Google's public certificates.
        """
        try:
            project_id = self.settings.FIREBASE_PROJECT_ID
            decoded = id_token.verify_firebase_token(
                id_token_str,
                self._auth_request,
                audience=project_id,
            )
            return decoded
        except Exception as e:
            logger.warning(f"Firebase token verification failed: {e}")
            return None

    def verify_token(self, token: str) -> Optional[Dict[str, Any]]:
        """
        Unified token validator:
        1. Checks ZeroDaily JWT token.
        2. If invalid, attempts Firebase ID token validation.
        """
        # 1. Try ZeroDaily JWT
        claims = self.decode_access_token(token)
        if claims and "sub" in claims:
            return {
                "user_id": claims["sub"],
                "email": claims.get("email"),
                "is_anonymous": claims.get("is_anon", False),
                "auth_type": "zerodaily_jwt",
            }

        # 2. Try Firebase ID Token
        fb_claims = self.verify_firebase_id_token(token)
        if fb_claims and "sub" in fb_claims:
            fb_uid = fb_claims["sub"]
            return {
                "user_id": f"fb_{fb_uid}",
                "firebase_uid": fb_uid,
                "email": fb_claims.get("email"),
                "display_name": fb_claims.get("name"),
                "avatar_url": fb_claims.get("picture"),
                "is_anonymous": fb_claims.get("firebase", {}).get("sign_in_provider") == "anonymous",
                "auth_type": "firebase",
            }

        return None


# Global singleton
_auth_service: Optional[AuthService] = None


def get_auth_service() -> AuthService:
    global _auth_service
    if _auth_service is None:
        _auth_service = AuthService()
    return _auth_service
