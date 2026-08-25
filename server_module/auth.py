import os
from fastapi import Header, Query, HTTPException, status
from typing import Optional

# Default security: a simple password check
SERVER_PASSWORD = os.getenv("SERVER_PASSWORD", "vibe-coding-secret")
if os.getenv("API_KEY"): # Support alternative env name
    SERVER_PASSWORD = os.getenv("API_KEY")

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
