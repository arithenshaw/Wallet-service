"""
Main FastAPI application for Wallet Service
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.database import init_db
from app.routes import auth, keys, wallet

# Initialize database
init_db()

# Create FastAPI app
app = FastAPI(
    title="Wallet Service API",
    version="1.0.0",
    description="Wallet service with Paystack integration, JWT authentication, and API key management"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth.router)
app.include_router(keys.router)
app.include_router(wallet.router)


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "message": "Wallet Service API",
        "version": "1.0.0",
        "docs": "/docs",
        "features": [
            "Google OAuth authentication",
            "JWT token generation",
            "API key management",
            "Paystack payment integration",
            "Wallet deposits and transfers",
            "Transaction history"
        ]
    }


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

