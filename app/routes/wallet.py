"""
Wallet routes for deposits, transfers, and transactions
"""

from fastapi import APIRouter, HTTPException, status, Depends, Request
from sqlalchemy.orm import Session
from decimal import Decimal
import json
from app.database import get_db
from app.middleware.auth import get_current_user, AuthUser, require_permission
from app.services.paystack_service import (
    initiate_paystack_payment,
    verify_paystack_transaction,
    verify_paystack_webhook_signature,
    generate_payment_reference,
)
from app.services.wallet_service import (
    get_wallet_balance,
    create_deposit_transaction,
    credit_wallet_from_deposit,
    transfer_funds,
    get_transaction_history,
    get_transaction_by_reference,
)
from app.models import User, Transaction, TransactionStatus
from app.schemas import (
    DepositRequest,
    DepositResponse,
    DepositStatusResponse,
    WalletBalanceResponse,
    TransferRequest,
    TransferResponse,
    TransactionResponse,
    WebhookResponse,
)

router = APIRouter(prefix="/wallet", tags=["Wallet"])


@router.post(
    "/deposit", 
    response_model=DepositResponse, 
    status_code=201,
    dependencies=[Depends(require_permission("deposit"))],
    summary="Deposit Funds",
    description="Initiate wallet deposit using Paystack. Requires 'deposit' permission."
)
async def deposit_funds(
    request: DepositRequest,
    current_user: AuthUser = Depends(require_permission("deposit")),
    db: Session = Depends(get_db),
):
    """
    Initiate wallet deposit using Paystack
    Requires 'deposit' permission
    """
    if request.amount < 100:  # Minimum 1 Naira (100 kobo)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Minimum deposit amount is 100 kobo (1 Naira)"
        )
    
    # Get user
    user = db.query(User).filter(User.id == current_user.user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    # Generate unique reference
    reference = generate_payment_reference()
    
    # Check for duplicate reference (idempotency)
    existing_transaction = db.query(Transaction).filter(
        Transaction.reference == reference
    ).first()
    if existing_transaction:
        return DepositResponse(
            reference=existing_transaction.reference,
            authorization_url=existing_transaction.authorization_url or "",
        )
    
    try:
        # Initialize Paystack payment
        paystack_response = await initiate_paystack_payment(
            request.amount,
            user.email,
            reference,
        )
        
        authorization_url = paystack_response["data"]["authorization_url"]
        amount_naira = Decimal(request.amount) / 100  # Convert kobo to Naira
        
        # Create transaction record
        create_deposit_transaction(
            current_user.user_id,
            amount_naira,
            reference,
            authorization_url,
            db,
        )
        
        return DepositResponse(
            reference=reference,
            authorization_url=authorization_url,
        )
    
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Payment initiation failed: {str(e)}"
        )


@router.post("/paystack/webhook", response_model=WebhookResponse)
async def paystack_webhook(request: Request, db: Session = Depends(get_db)):
    """
    Paystack webhook endpoint
    Receives transaction updates from Paystack
    Only webhooks can credit wallets
    """
    payload = await request.body()
    signature = request.headers.get("x-paystack-signature", "")
    
    # Verify signature
    if not verify_paystack_webhook_signature(payload, signature):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid webhook signature"
        )
    
    try:
        event_data = json.loads(payload)
        
        if event_data.get("event") == "charge.success":
            transaction_data = event_data.get("data", {})
            reference = transaction_data.get("reference")
            
            if reference:
                # Credit wallet (idempotent operation)
                success = credit_wallet_from_deposit(reference, db)
                if not success:
                    # Transaction not found or already processed
                    pass
        
        return WebhookResponse(status=True)
    
    except json.JSONDecodeError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON payload"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Webhook processing failed: {str(e)}"
        )


@router.get("/deposit/{reference}/status", response_model=DepositStatusResponse)
async def get_deposit_status(
    reference: str,
    current_user: AuthUser = Depends(require_permission("read")),
    db: Session = Depends(get_db),
):
    """
    Get deposit transaction status
    This endpoint does NOT credit wallets - only webhooks can do that
    Requires 'read' permission
    """
    transaction = get_transaction_by_reference(reference, db)
    
    if not transaction:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transaction not found"
        )
    
    # Verify transaction belongs to user
    if transaction.user_id != current_user.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied"
        )
    
    # Optionally verify with Paystack (but don't credit wallet)
    if transaction.status == TransactionStatus.PENDING:
        try:
            paystack_data = await verify_paystack_transaction(reference)
            transaction_data = paystack_data.get("data", {})
            
            if transaction_data.get("status") == "success":
                transaction.status = TransactionStatus.SUCCESS
            elif transaction_data.get("status") == "failed":
                transaction.status = TransactionStatus.FAILED
            
            db.commit()
            db.refresh(transaction)
        except:
            pass  # If verification fails, return current status
    
    return DepositStatusResponse(
        reference=transaction.reference,
        status=transaction.status.value,
        amount=transaction.amount,
    )


@router.get(
    "/balance", 
    response_model=WalletBalanceResponse,
    dependencies=[Depends(require_permission("read"))],
    summary="Get Wallet Balance",
    description="Get current wallet balance. Requires 'read' permission."
)
async def get_balance(
    current_user: AuthUser = Depends(require_permission("read")),
    db: Session = Depends(get_db),
):
    """
    Get wallet balance
    Requires 'read' permission
    """
    try:
        balance = get_wallet_balance(current_user.user_id, db)
        return WalletBalanceResponse(balance=balance)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e)
        )


@router.post("/transfer", response_model=TransferResponse)
async def transfer_funds_to_wallet(
    request: TransferRequest,
    current_user: AuthUser = Depends(require_permission("transfer")),
    db: Session = Depends(get_db),
):
    """
    Transfer funds to another user's wallet
    Requires 'transfer' permission
    """
    if request.amount < 100:  # Minimum 1 Naira (100 kobo)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Minimum transfer amount is 100 kobo (1 Naira)"
        )
    
    try:
        amount_naira = Decimal(request.amount) / 100  # Convert kobo to Naira
        transaction = transfer_funds(
            current_user.user_id,
            request.wallet_number,
            amount_naira,
            db,
        )
        
        return TransferResponse(
            status="success",
            message="Transfer completed",
            reference=transaction.reference,
        )
    
    except ValueError as e:
        error_msg = str(e)
        if "Insufficient balance" in error_msg:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Insufficient balance"
            )
        elif "not found" in error_msg.lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=error_msg
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error_msg
            )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Transfer failed: {str(e)}"
        )


@router.get("/transactions", response_model=list[TransactionResponse])
async def get_transactions(
    limit: int = 50,
    offset: int = 0,
    current_user: AuthUser = Depends(require_permission("read")),
    db: Session = Depends(get_db),
):
    """
    Get transaction history
    Requires 'read' permission
    """
    if limit > 100:
        limit = 100
    if limit < 1:
        limit = 10
    
    try:
        transactions = get_transaction_history(
            current_user.user_id,
            limit=limit,
            offset=offset,
            db=db,
        )
        return transactions
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch transactions: {str(e)}"
        )

