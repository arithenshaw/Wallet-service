"""
Authentication service for Google OAuth and JWT
"""

import jwt
import httpx
from datetime import datetime, timedelta
from typing import Optional, Dict
from urllib.parse import urlencode
from sqlalchemy.orm import Session
from app.config import settings
from app.models import User, Wallet
from app.schemas import JWTAuthResponse


def get_google_auth_url() -> str:
    """Generate Google OAuth authorization URL"""
    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": settings.GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "offline",
        "prompt": "consent",
    }
    return f"https://accounts.google.com/o/oauth2/v2/auth?{urlencode(params)}"


async def exchange_code_for_token(code: str) -> dict:
    """Exchange authorization code for access token"""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "redirect_uri": settings.GOOGLE_REDIRECT_URI,
                "grant_type": "authorization_code",
            },
        )
        if response.status_code != 200:
            raise ValueError(f"Failed to exchange code for token: {response.text}")
        return response.json()


async def get_google_user_info(access_token: str) -> dict:
    """Get user information from Google"""
    async with httpx.AsyncClient() as client:
        response = await client.get(
            "https://www.googleapis.com/oauth2/v2/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if response.status_code != 200:
            raise ValueError(f"Failed to fetch user info: {response.text}")
        return response.json()


def create_jwt_token(user_id: int, email: str) -> str:
    """Create JWT token for user"""
    expiration = datetime.utcnow() + timedelta(hours=settings.JWT_EXPIRATION_HOURS)
    payload = {
        "user_id": user_id,
        "email": email,
        "exp": expiration,
        "iat": datetime.utcnow(),
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def verify_jwt_token(token: str) -> Optional[Dict]:
    """Verify and decode JWT token"""
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


async def handle_google_callback(code: str, db: Session) -> JWTAuthResponse:
    """Handle Google OAuth callback and return JWT token"""
    # Exchange code for token
    token_data = await exchange_code_for_token(code)
    access_token = token_data.get("access_token")
    
    # Get user info
    user_info = await get_google_user_info(access_token)
    
    google_id = user_info.get("id")
    email = user_info.get("email")
    name = user_info.get("name", "")
    picture = user_info.get("picture")
    
    # Find or create user
    user = db.query(User).filter(User.google_id == google_id).first()
    if not user:
        user = db.query(User).filter(User.email == email).first()
    
    if user:
        # Update existing user
        user.google_id = google_id
        user.name = name
        user.picture = picture
        user.updated_at = datetime.utcnow()
    else:
        # Create new user
        user = User(
            google_id=google_id,
            email=email,
            name=name,
            picture=picture,
        )
        db.add(user)
        db.flush()  # Get user ID
        
        # Create wallet for new user
        wallet_number = generate_wallet_number(db)
        wallet = Wallet(
            user_id=user.id,
            wallet_number=wallet_number,
            balance=0.00,
        )
        db.add(wallet)
    
    db.commit()
    db.refresh(user)
    
    # Get wallet number
    wallet = db.query(Wallet).filter(Wallet.user_id == user.id).first()
    wallet_number = wallet.wallet_number if wallet else None
    
    # Generate JWT token
    token = create_jwt_token(user.id, user.email)
    
    return JWTAuthResponse(
        token=token,
        user_id=user.id,
        email=user.email,
        name=user.name,
        wallet_number=wallet_number,
    )


def generate_wallet_number(db: Session) -> str:
    """Generate unique wallet number"""
    import secrets
    while True:
        wallet_number = ''.join([str(secrets.randbelow(10)) for _ in range(13)])
        existing = db.query(Wallet).filter(Wallet.wallet_number == wallet_number).first()
        if not existing:
            return wallet_number

