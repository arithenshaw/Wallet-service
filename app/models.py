"""
Database models for the wallet service
"""

from sqlalchemy import Column, Integer, String, DateTime, Enum, ForeignKey, Boolean, Text, Numeric
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from datetime import datetime
import enum
from app.database import Base


class TransactionType(str, enum.Enum):
    DEPOSIT = "deposit"
    TRANSFER = "transfer"
    RECEIVED = "received"


class TransactionStatus(str, enum.Enum):
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"


class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    google_id = Column(String, unique=True, index=True, nullable=True)
    email = Column(String, unique=True, index=True)
    name = Column(String)
    picture = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    wallet = relationship("Wallet", back_populates="user", uselist=False)
    api_keys = relationship("APIKey", back_populates="user", cascade="all, delete-orphan")
    transactions = relationship("Transaction", back_populates="user")


class Wallet(Base):
    __tablename__ = "wallets"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, index=True)
    wallet_number = Column(String, unique=True, index=True)  # Unique wallet identifier
    balance = Column(Numeric(15, 2), default=0.00)  # Balance in Naira (stored as decimal)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    user = relationship("User", back_populates="wallet")
    transactions = relationship(
        "Transaction", 
        primaryjoin="Wallet.id == Transaction.wallet_id",
        back_populates="wallet"
    )


class Transaction(Base):
    __tablename__ = "transactions"
    
    id = Column(Integer, primary_key=True, index=True)
    reference = Column(String, unique=True, index=True)  # Paystack reference or transfer reference
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    wallet_id = Column(Integer, ForeignKey("wallets.id"), nullable=True)
    recipient_wallet_id = Column(Integer, ForeignKey("wallets.id"), nullable=True)  # For transfers
    type = Column(Enum(TransactionType))
    amount = Column(Numeric(15, 2))  # Amount in Naira
    status = Column(Enum(TransactionStatus), default=TransactionStatus.PENDING)
    authorization_url = Column(String, nullable=True)  # Paystack payment URL
    description = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    user = relationship("User", back_populates="transactions")
    wallet = relationship("Wallet", foreign_keys=[wallet_id], back_populates="transactions")
    recipient_wallet = relationship("Wallet", foreign_keys=[recipient_wallet_id])


class APIKey(Base):
    __tablename__ = "api_keys"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    key = Column(String, unique=True, index=True)  # The actual API key
    name = Column(String)  # User-friendly name
    permissions = Column(Text)  # JSON string of permissions array
    expires_at = Column(DateTime)
    is_revoked = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    user = relationship("User", back_populates="api_keys")
    
    @property
    def is_expired(self):
        """Check if API key is expired"""
        if not self.expires_at:
            return False
        return datetime.utcnow() > self.expires_at
    
    @property
    def is_active(self):
        """Check if API key is active (not revoked and not expired)"""
        return not self.is_revoked and not self.is_expired

