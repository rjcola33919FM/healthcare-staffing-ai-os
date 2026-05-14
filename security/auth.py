"""
Auth0 JWT validation — FastAPI dependency for protecting internal endpoints.
Validates Bearer tokens against the Auth0 JWKS endpoint.
Falls back to API-key authentication when Auth0 is not configured.
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import Any

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

logger = logging.getLogger(__name__)

AUTH0_DOMAIN   = os.environ.get("AUTH0_DOMAIN", "")
AUTH0_AUDIENCE = os.environ.get("AUTH0_API_AUDIENCE", "")
INTERNAL_API_KEY = os.environ.get("INTERNAL_API_KEY", "")

_bearer_scheme = HTTPBearer(auto_error=False)


# ── JWT Validator ──────────────────────────────────────────────────────────────

class JWTValidator:
    """
    Validates Auth0-issued JWTs using the JWKS public key endpoint.
    Caches the JWKS response (TTL handled by jose's jwks_client).
    """

    def __init__(self, domain: str, audience: str):
        self.domain   = domain
        self.audience = audience
        self._jwks_client = None

    @property
    def jwks_uri(self) -> str:
        return f"https://{self.domain}/.well-known/jwks.json"

    def _get_client(self):
        if self._jwks_client is None:
            try:
                from jose import jwk
                from jose.backends import RSAKey
                import urllib.request, json
                # Lazy-load JWKS
                with urllib.request.urlopen(self.jwks_uri, timeout=5) as resp:
                    self._jwks_client = json.loads(resp.read())
            except Exception as exc:
                logger.error("[AUTH] Failed to load JWKS from %s: %s", self.jwks_uri, exc)
                raise
        return self._jwks_client

    def validate(self, token: str) -> dict[str, Any]:
        """Decode and validate JWT. Returns payload dict or raises HTTPException."""
        try:
            from jose import jwt, JWTError
            jwks = self._get_client()
            payload = jwt.decode(
                token,
                jwks,
                algorithms=["RS256"],
                audience=self.audience,
                issuer=f"https://{self.domain}/",
            )
            return payload
        except Exception as exc:
            logger.warning("[AUTH] JWT validation failed: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token.",
                headers={"WWW-Authenticate": "Bearer"},
            )


@lru_cache(maxsize=1)
def _get_validator() -> JWTValidator | None:
    if AUTH0_DOMAIN and AUTH0_AUDIENCE:
        return JWTValidator(AUTH0_DOMAIN, AUTH0_AUDIENCE)
    return None


# ── FastAPI Dependencies ───────────────────────────────────────────────────────

def require_auth(
    credentials: HTTPAuthorizationCredentials | None = Security(_bearer_scheme),
) -> dict[str, Any]:
    """
    FastAPI dependency. Enforces authentication on protected endpoints.

    Auth flow (in priority order):
      1. Auth0 JWT Bearer token (production)
      2. Internal API key header (internal services / CI)
      3. Unauthenticated — 401

    Returns the decoded JWT payload (or {"sub": "api_key"} for key auth).
    """
    validator = _get_validator()

    if credentials and credentials.credentials:
        token = credentials.credentials

        # Try Auth0 JWT first
        if validator:
            return validator.validate(token)

        # Fall back to raw API key comparison
        if INTERNAL_API_KEY and token == INTERNAL_API_KEY:
            return {"sub": "api_key", "scope": "internal"}

    # Check for API key in Authorization: Bearer <key> when Auth0 not configured
    if not validator and not INTERNAL_API_KEY:
        # Dev mode — allow unauthenticated access with a warning
        logger.warning("[AUTH] No auth configured — request allowed (dev mode only).")
        return {"sub": "unauthenticated", "env": "development"}

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def require_scope(required_scope: str):
    """
    Factory for scope-checking FastAPI dependencies.
    Usage: Depends(require_scope("write:contacts"))
    """
    def _check(payload: dict[str, Any] = Depends(require_auth)) -> dict[str, Any]:
        scopes = payload.get("scope", "").split()
        if required_scope not in scopes and "admin" not in scopes:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Scope '{required_scope}' required.",
            )
        return payload
    return _check
