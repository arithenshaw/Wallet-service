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


@router.get(
    "/google",
    summary="Start Google Sign‑In",
    description=(
        "Returns a Google login link. Steps for non‑technical users:\n"
        "1) Click 'Try it out' → Execute.\n"
        "2) Copy the 'google_auth_url' value from the response.\n"
        "3) Open that link in your browser and sign in with Google.\n"
        "4) After signing in, you will be redirected back to this API and the next step (/auth/google/callback) will return your login details."
    ),
)
async def trigger_google_signin(request: Request):
    auth_url = get_google_auth_url()
    
    # Check if client wants JSON response
    accept = request.headers.get("accept", "")
    if "application/json" in accept:
        return JSONResponse({"google_auth_url": auth_url})
    
    # Default: redirect
    return RedirectResponse(url=auth_url, status_code=302)


@router.get(
    "/google/callback",
    summary="Complete Google Sign‑In and Get Token",
    description=(
        "You normally arrive here automatically after logging in with the link from /auth/google.\n"
        "What you get back:\n"
        "- token: your login token (JWT)\n"
        "- user_id, email, name: your account details\n\n"
        "If you got the login link from /auth/google and signed in, just look at the response here and copy the 'token' value."
    ),
)
async def google_oauth_callback(
    code: Optional[str] = None,
    db: Session = Depends(get_db)
) -> JWTAuthResponse:
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

