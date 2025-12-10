"""
Pydantic schemas for request/response validation
"""

from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List
from datetime import datetime
from decimal import Decimal


# Auth Schemas
class GoogleAuthResponse(BaseModel):
    google_auth_url: str


class JWTAuthResponse(BaseModel):
    token: str
    user_id: int
    email: str
    name: str
    wallet_number: Optional[str] = None


# API Key Schemas
class CreateAPIKeyRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    permissions: List[str] = Field(..., min_items=1)
    expiry: str = Field(..., pattern="^(1H|1D|1M|1Y)$")  # Hour, Day, Month, Year


class CreateAPIKeyResponse(BaseModel):
    api_key_id: int
    api_key: str
    expires_at: datetime


class RolloverAPIKeyRequest(BaseModel):
    expired_key_id: str
    expiry: str = Field(..., pattern="^(1H|1D|1M|1Y)$")


class APIKeyInfo(BaseModel):
    id: int
    name: str
    api_key: str  # Masked/encrypted version
    permissions: List[str]
    expires_at: datetime
    is_revoked: bool
    is_expired: bool
    created_at: datetime


# Wallet Schemas
class DepositRequest(BaseModel):
    amount: int = Field(..., gt=0)  # Amount in kobo


class DepositResponse(BaseModel):
    reference: str
    authorization_url: str


class DepositStatusResponse(BaseModel):
    reference: str
    status: str
    amount: Decimal
    message: str


class WalletBalanceResponse(BaseModel):
    balance: Decimal
    wallet_number: str


class TransferRequest(BaseModel):
    wallet_number: str = Field(..., min_length=1)
    amount: int = Field(..., gt=0)  # Amount in kobo


class TransferResponse(BaseModel):
    status: str
    message: str
    reference: str


class TransactionResponse(BaseModel):
    id: int
    reference: str
    type: str
    amount: Decimal
    status: str
    description: Optional[str] = None
    created_at: datetime
    wallet_number: Optional[str] = None
    
    class Config:
        from_attributes = True


# Webhook Schemas
class WebhookResponse(BaseModel):
    status: bool


# User Schemas
class UserResponse(BaseModel):
    id: int
    email: str
    name: str
    wallet_number: Optional[str] = None
    
    class Config:
        from_attributes = True

