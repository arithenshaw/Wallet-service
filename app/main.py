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

# Add security schemes to OpenAPI schema (must be after routers are included)
def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    
    from fastapi.openapi.utils import get_openapi
    
    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    
    # Add security schemes
    openapi_schema["components"]["securitySchemes"] = {
        "Bearer": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
            "description": "Enter JWT token from Google OAuth callback. Format: Bearer <token>"
        },
        "APIKey": {
            "type": "apiKey",
            "in": "header",
            "name": "x-api-key",
            "description": "Enter API key (starts with sk_live_)"
        }
    }
    
    # Add security to protected endpoints
    public_paths = ["/", "/health", "/auth/google", "/auth/google/callback", "/wallet/paystack/webhook"]
    
    for path, path_item in openapi_schema.get("paths", {}).items():
        for method, operation in path_item.items():
            if method in ["post", "get", "put", "delete", "patch"]:
                # Skip public endpoints
                if path in public_paths:
                    continue
                # Add security requirements
                if "security" not in operation:
                    operation["security"] = [
                        {"Bearer": []},
                        {"APIKey": []}
                    ]
    
    app.openapi_schema = openapi_schema
    return app.openapi_schema

app.openapi = custom_openapi


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

