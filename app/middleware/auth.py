"""
JWT Authentication Middleware for AWS Cognito
Validates JWT tokens from Cognito User Pool and extracts user claims.

Security Scenario 1: Delegated Authentication with JWT (Cloud Provider)
- Backend does NOT generate tokens, only validates
- Validates signature and claims from Cognito JWT
- Rejects invalid, manipulated, or expired tokens with 401
- Target: 100% protected endpoints, validation < 100ms
"""

import time
import httpx
from typing import Optional
from datetime import datetime
from functools import lru_cache

from fastapi import Depends, HTTPException, status, Request, WebSocket
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import jwt, JWTError, jwk
from jose.utils import base64url_decode
from pydantic import BaseModel

from app.config import settings

import logging
logger = logging.getLogger(__name__)

# HTTP Bearer security scheme
security = HTTPBearer()


class CognitoUser(BaseModel):
    """Authenticated user from Cognito JWT"""
    sub: str  # Cognito user ID (unique identifier)
    email: str
    email_verified: bool = False
    name: Optional[str] = None
    phone_number: Optional[str] = None
    token_use: str  # 'access' or 'id'
    exp: int  # Token expiration timestamp
    iat: int  # Token issued at timestamp

    @property
    def user_id(self) -> str:
        """Alias for sub (Cognito user ID)"""
        return self.sub

    @property
    def is_token_valid(self) -> bool:
        """Check if token is not expired"""
        return datetime.utcnow().timestamp() < self.exp


class CognitoJWKS:
    """Manages Cognito JSON Web Key Set for token validation"""

    def __init__(self):
        self.jwks: Optional[dict] = None
        self.jwks_url = (
            f"https://cognito-idp.{settings.AWS_REGION}.amazonaws.com/"
            f"{settings.COGNITO_USER_POOL_ID}/.well-known/jwks.json"
        )
        self._last_fetch: float = 0
        self._cache_duration: int = 3600  # Cache JWKS for 1 hour

    async def get_jwks(self) -> dict:
        """Fetch and cache JWKS from Cognito"""
        current_time = time.time()

        # Return cached JWKS if still valid
        if self.jwks and (current_time - self._last_fetch) < self._cache_duration:
            return self.jwks

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(self.jwks_url, timeout=10.0)
                response.raise_for_status()
                self.jwks = response.json()
                self._last_fetch = current_time
                logger.info("JWKS fetched successfully from Cognito")
                return self.jwks
        except Exception as e:
            logger.error(f"Failed to fetch JWKS: {e}")
            # Return cached version if available
            if self.jwks:
                return self.jwks
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Authentication service unavailable"
            )

    async def get_key(self, kid: str) -> Optional[dict]:
        """Get specific key from JWKS by key ID"""
        jwks = await self.get_jwks()
        for key in jwks.get("keys", []):
            if key.get("kid") == kid:
                return key
        return None


# Global JWKS manager instance
cognito_jwks = CognitoJWKS()


async def verify_jwt_token(token: str) -> CognitoUser:
    """
    Verify and decode a Cognito JWT token.

    Security measures:
    - Validates token signature against Cognito public keys
    - Checks token expiration
    - Verifies issuer matches Cognito User Pool
    - Verifies audience/client_id
    - Validates token_use claim

    Returns CognitoUser on success, raises HTTPException on failure.
    Validation time target: < 100ms
    """
    start_time = time.time()

    try:
        # Decode token header to get key ID
        header = jwt.get_unverified_header(token)
        kid = header.get("kid")

        if not kid:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token: missing key ID",
                headers={"WWW-Authenticate": "Bearer"}
            )

        # Get the signing key from JWKS
        key_data = await cognito_jwks.get_key(kid)
        if not key_data:
            # Key not found, refresh JWKS and retry
            cognito_jwks._last_fetch = 0  # Force refresh
            key_data = await cognito_jwks.get_key(kid)
            if not key_data:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid token: signing key not found",
                    headers={"WWW-Authenticate": "Bearer"}
                )

        # Construct public key
        public_key = jwk.construct(key_data)

        # Expected issuer
        issuer = f"https://cognito-idp.{settings.AWS_REGION}.amazonaws.com/{settings.COGNITO_USER_POOL_ID}"

        # Decode and verify the token
        payload = jwt.decode(
            token,
            public_key.to_pem().decode('utf-8'),
            algorithms=["RS256"],
            audience=settings.COGNITO_CLIENT_ID,
            issuer=issuer,
            options={
                "verify_aud": True,
                "verify_iss": True,
                "verify_exp": True,
                "require_exp": True,
            }
        )

        # Additional validation for token_use
        token_use = payload.get("token_use")
        if token_use not in ["access", "id"]:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token: invalid token_use claim",
                headers={"WWW-Authenticate": "Bearer"}
            )

        # Create user object from token claims
        user = CognitoUser(
            sub=payload.get("sub"),
            email=payload.get("email", ""),
            email_verified=payload.get("email_verified", False),
            name=payload.get("name"),
            phone_number=payload.get("phone_number"),
            token_use=token_use,
            exp=payload.get("exp"),
            iat=payload.get("iat")
        )

        # Log validation time
        validation_time = (time.time() - start_time) * 1000
        logger.debug(f"JWT validation completed in {validation_time:.2f}ms")

        if validation_time > 100:
            logger.warning(f"JWT validation exceeded 100ms target: {validation_time:.2f}ms")

        return user

    except JWTError as e:
        logger.warning(f"JWT validation failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"}
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in JWT validation: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token validation failed",
            headers={"WWW-Authenticate": "Bearer"}
        )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> CognitoUser:
    """
    FastAPI dependency to get the current authenticated user.

    Usage:
        @router.get("/protected")
        async def protected_route(user: CognitoUser = Depends(get_current_user)):
            return {"user_id": user.user_id, "email": user.email}
    """
    return await verify_jwt_token(credentials.credentials)


async def get_current_user_optional(
    request: Request
) -> Optional[CognitoUser]:
    """
    Optional authentication - returns None if no valid token.
    Useful for endpoints that work with or without authentication.
    """
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        return None

    token = auth_header.split(" ")[1]
    try:
        return await verify_jwt_token(token)
    except HTTPException:
        return None


async def verify_websocket_token(websocket: WebSocket, token: str) -> CognitoUser:
    """
    Verify JWT token for WebSocket connections.

    WebSocket connections must pass token as query parameter or in first message.

    Usage:
        @app.websocket("/ws/{user_id}")
        async def websocket_endpoint(websocket: WebSocket, user_id: str):
            token = websocket.query_params.get("token")
            user = await verify_websocket_token(websocket, token)
            ...
    """
    if not token:
        await websocket.close(code=4001, reason="Missing authentication token")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="WebSocket authentication required"
        )

    try:
        user = await verify_jwt_token(token)
        return user
    except HTTPException as e:
        await websocket.close(code=4001, reason=str(e.detail))
        raise


def get_user_id_from_token(token: str) -> Optional[str]:
    """
    Quick extraction of user ID from token without full validation.
    Useful for logging/metrics. Does NOT validate the token.
    """
    try:
        payload = jwt.get_unverified_claims(token)
        return payload.get("sub")
    except Exception:
        return None
