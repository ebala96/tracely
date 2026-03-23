"""
JWT verification middleware.
For now this is a lightweight dependency — routes can opt in via Depends(verify_token).
All routes are unprotected by default to keep local dev simple.
"""
import os
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt

JWT_SECRET    = os.environ.get("JWT_SECRET", "changeme_very_long_secret")
JWT_ALGORITHM = "HS256"

_bearer = HTTPBearer(auto_error=False)


def verify_token(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> Optional[dict]:
    """
    Validate Bearer JWT if present.
    Returns the decoded payload, or None if no token is provided.
    Raises 401 if a token is present but invalid.
    """
    if credentials is None:
        return None  # Unauthenticated — allowed in local-only mode

    try:
        payload = jwt.decode(
            credentials.credentials,
            JWT_SECRET,
            algorithms=[JWT_ALGORITHM],
        )
        return payload
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )
