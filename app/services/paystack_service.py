"""
Paystack payment service
"""

import httpx
import hmac
import hashlib
import secrets
from typing import Dict, Optional
from app.config import settings


async def initiate_paystack_payment(amount: int, email: str, reference: str) -> dict:
    """Initialize Paystack payment"""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://api.paystack.co/transaction/initialize",
            json={
                "amount": amount,
                "email": email,
                "reference": reference,
                "callback_url": f"{settings.BASE_URL}/wallet/paystack/callback",
            },
            headers={
                "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )
        if response.status_code != 200:
            raise ValueError(f"Payment initiation failed: {response.text}")
        return response.json()


async def verify_paystack_transaction(reference: str) -> dict:
    """Verify Paystack transaction status"""
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"https://api.paystack.co/transaction/verify/{reference}",
            headers={
                "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
            },
            timeout=30.0,
        )
        if response.status_code != 200:
            raise ValueError(f"Failed to verify transaction: {response.text}")
        return response.json()


def verify_paystack_webhook_signature(payload: bytes, signature: str) -> bool:
    """Verify Paystack webhook signature"""
    if not settings.PAYSTACK_WEBHOOK_SECRET:
        return False  # If no secret configured, reject
    
    computed_signature = hmac.new(
        settings.PAYSTACK_WEBHOOK_SECRET.encode(),
        payload,
        hashlib.sha512
    ).hexdigest()
    return hmac.compare_digest(computed_signature, signature)


def generate_payment_reference() -> str:
    """Generate unique payment reference"""
    return f"ref_{secrets.token_hex(16)}"

