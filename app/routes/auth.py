"""
Authentication routes for Google OAuth
"""

from fastapi import APIRouter, HTTPException, status, Depends, Request
from fastapi.responses import RedirectResponse, JSONResponse
from sqlalchemy.orm import Session
from typing import Optional
from app.database import get_db
from app.services.auth_service import get_google_auth_url, handle_google_callback
from app.schemas import GoogleAuthResponse, JWTAuthResponse

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.get("/google")
async def trigger_google_signin(request: Request):
    """
    Trigger Google sign-in flow
    Returns redirect to Google OAuth or JSON with URL
    """
    auth_url = get_google_auth_url()
    
    # Check if client wants JSON response
    accept = request.headers.get("accept", "")
    if "application/json" in accept:
        return JSONResponse({"google_auth_url": auth_url})
    
    # Default: redirect
    return RedirectResponse(url=auth_url, status_code=302)


@router.get("/google/callback")
async def google_oauth_callback(
    code: Optional[str] = None,
    db: Session = Depends(get_db)
) -> JWTAuthResponse:
    """
    Google OAuth callback
    Exchange code for token, fetch user info, create/update user
    Returns JWT token
    """
    if not code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing authorization code"
        )
    
    try:
        return await handle_google_callback(code, db)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"OAuth callback failed: {str(e)}"
        )

