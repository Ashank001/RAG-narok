import os
from datetime import datetime, timedelta, timezone
from typing import Optional
# pyrefly: ignore [missing-import]
from fastapi import Depends, Header, HTTPException, Request, status
# pyrefly: ignore [missing-import]
from fastapi.security import OAuth2PasswordBearer
# pyrefly: ignore [missing-source-for-stubs]
from jose import JWTError, jwt
# pyrefly: ignore [missing-import]
from dotenv import load_dotenv

load_dotenv()

SECRET_KEY = os.getenv("JWT_SECRET_KEY")
if not SECRET_KEY:
    raise ValueError("CRITICAL: JWT_SECRET_KEY is missing from .env. Set a strong random secret.")
ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", 60))

# Internal service-to-service secret (used by api-gateway BullMQ worker)
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY")

# NOTE: pwd_context / verify_password / get_password_hash removed — app uses
# GitHub OAuth exclusively. Re-add if local password auth is ever needed.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token", auto_error=False)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def get_current_user(request: Request, token: Optional[str] = Depends(oauth2_scheme)):
    # ----------------------------------------------------------------
    # Internal service-to-service bypass:
    # The api-gateway BullMQ worker sends X-Internal-Key instead of a
    # user JWT. Validate it against INTERNAL_API_KEY from .env.
    # ----------------------------------------------------------------
    internal_key = request.headers.get("X-Internal-Key")
    if internal_key:
        if INTERNAL_API_KEY and internal_key == INTERNAL_API_KEY:
            return "internal-service"
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid internal service key",
        )

    # Standard JWT path for user-facing requests
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if token is None:
        raise credentials_exception
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        # pyrefly: ignore [bad-assignment]
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
        return username
    except JWTError:
        raise credentials_exception