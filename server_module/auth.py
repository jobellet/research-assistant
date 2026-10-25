import os
import secrets
from fastapi import Header, Query, HTTPException, status
from typing import Optional

# Default security: a simple password check
# Password comes from SERVER_PASSWORD (or API_KEY / AUTH_TOKEN). If none is set, a random
# per-process token is generated and printed so there is never a publicly known default.
SERVER_PASSWORD = os.getenv("SERVER_PASSWORD") or os.getenv("API_KEY") or os.getenv("AUTH_TOKEN")
if not SERVER_PASSWORD:
    SERVER_PASSWORD = secrets.token_urlsafe(16)
    print(f"[auth] SERVER_PASSWORD not set; generated one-time token for this run: {SERVER_PASSWORD}")

def verify_auth_token(x_auth_token: Optional[str] = Header(None), token: Optional[str] = Query(None)):
    """
    Dependency to verify the presence of a valid auth token in the headers OR query params.
    """
    effective_token = x_auth_token or token
    
    if not effective_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication token.",
        )
    
    if effective_token != SERVER_PASSWORD:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid authentication token.",
        )
    
    return True
