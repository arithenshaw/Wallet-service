"""
Wallet service for balance, transfers, and transactions
"""

from decimal import Decimal
from datetime import datetime
from typing import List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import and_
from app.models import Wallet, Transaction, User, TransactionType, TransactionStatus
from app.schemas import TransactionResponse
import secrets


def get_wallet_balance(user_id: int, db: Session) -> Decimal:
    """Get wallet balance for user"""
    wallet = db.query(Wallet).filter(Wallet.user_id == user_id).first()
    if not wallet:
        raise ValueError("Wallet not found")
    return wallet.balance


def create_deposit_transaction(
    user_id: int,
    amount: Decimal,
    reference: str,
    authorization_url: str,
    db: Session
) -> Transaction:
    """Create a deposit transaction"""
    wallet = db.query(Wallet).filter(Wallet.user_id == user_id).first()
    if not wallet:
        raise ValueError("Wallet not found")
    
    transaction = Transaction(
        reference=reference,
        user_id=user_id,
        wallet_id=wallet.id,
        type=TransactionType.DEPOSIT,
        amount=amount,
        status=TransactionStatus.PENDING,
        authorization_url=authorization_url,
        description=f"Deposit of ₦{amount:,.2f}",
    )
    db.add(transaction)
    db.commit()
    db.refresh(transaction)
    return transaction


def credit_wallet_from_deposit(
    reference: str,
    db: Session
) -> bool:
    """Credit wallet from successful deposit (called by webhook)"""
    transaction = db.query(Transaction).filter(
        Transaction.reference == reference
    ).first()
    
    if not transaction:
        return False
    
    # Idempotency check - don't credit twice
    if transaction.status == TransactionStatus.SUCCESS:
        return True
    
    if transaction.type != TransactionType.DEPOSIT:
        return False
    
    wallet = db.query(Wallet).filter(Wallet.id == transaction.wallet_id).first()
    if not wallet:
        return False
    
    # Credit wallet
    wallet.balance += transaction.amount
    transaction.status = TransactionStatus.SUCCESS
    transaction.updated_at = datetime.utcnow()
    
    db.commit()
    return True


def transfer_funds(
    sender_user_id: int,
    recipient_wallet_number: str,
    amount: Decimal,
    db: Session
) -> Transaction:
    """Transfer funds between wallets"""
    # Get sender wallet
    sender_wallet = db.query(Wallet).filter(Wallet.user_id == sender_user_id).first()
    if not sender_wallet:
        raise ValueError("Sender wallet not found")
    
    # Check balance
    if sender_wallet.balance < amount:
        raise ValueError("Insufficient balance")
    
    # Get recipient wallet
    recipient_wallet = db.query(Wallet).filter(
        Wallet.wallet_number == recipient_wallet_number
    ).first()
    if not recipient_wallet:
        raise ValueError("Recipient wallet not found")
    
    if recipient_wallet.user_id == sender_user_id:
        raise ValueError("Cannot transfer to your own wallet")
    
    # Generate transfer reference
    reference = f"transfer_{secrets.token_hex(16)}"
    
    # Create transfer transaction (sender)
    transfer_transaction = Transaction(
        reference=reference,
        user_id=sender_user_id,
        wallet_id=sender_wallet.id,
        recipient_wallet_id=recipient_wallet.id,
        type=TransactionType.TRANSFER,
        amount=amount,
        status=TransactionStatus.SUCCESS,
        description=f"Transfer to {recipient_wallet_number}",
    )
    db.add(transfer_transaction)
    
    # Create received transaction (recipient)
    received_transaction = Transaction(
        reference=f"{reference}_received",
        user_id=recipient_wallet.user_id,
        wallet_id=recipient_wallet.id,
        type=TransactionType.RECEIVED,
        amount=amount,
        status=TransactionStatus.SUCCESS,
        description=f"Received from {sender_wallet.wallet_number}",
    )
    db.add(received_transaction)
    
    # Update balances (atomic operation)
    sender_wallet.balance -= amount
    recipient_wallet.balance += amount
    
    db.commit()
    db.refresh(transfer_transaction)
    return transfer_transaction


def get_transaction_history(
    user_id: int,
    limit: int = 50,
    offset: int = 0,
    db: Session = None
) -> List[TransactionResponse]:
    """Get transaction history for user"""
    transactions = db.query(Transaction).filter(
        Transaction.user_id == user_id
    ).order_by(
        Transaction.created_at.desc()
    ).limit(limit).offset(offset).all()
    
    # Get user's wallet number
    wallet = db.query(Wallet).filter(Wallet.user_id == user_id).first()
    wallet_number = wallet.wallet_number if wallet else None
    
    return [
        TransactionResponse(
            id=t.id,
            reference=t.reference,
            type=t.type.value,
            amount=t.amount,
            status=t.status.value,
            description=t.description,
            created_at=t.created_at,
            wallet_number=wallet_number,
        )
        for t in transactions
    ]


def get_transaction_by_reference(
    reference: str,
    db: Session
) -> Optional[Transaction]:
    """Get transaction by reference"""
    return db.query(Transaction).filter(Transaction.reference == reference).first()

