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
    description=(
        "Start a Paystack payment to add money to your wallet.\n"
        "For non-technical users:\n"
        "1) Click 'Try it out'.\n"
        "2) Enter amount in kobo (e.g., 5000 = ₦50).\n"
        "3) Execute. Copy the 'authorization_url'.\n"
        "4) Open that URL in a new tab and complete payment.\n"
        "5) Your wallet is credited when Paystack webhook confirms the payment."
    )
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


@router.get("/paystack/callback")
async def paystack_callback(
    reference: str,
    trxref: str = None,
    db: Session = Depends(get_db),
):
    """
    Paystack payment callback (user redirect after payment)
    This is where Paystack redirects users after they complete payment.
    Shows a success/failure message to the user.
    Note: The actual wallet crediting happens via webhook, not here.
    """
    from fastapi.responses import HTMLResponse
    
    # Verify transaction status
    transaction = get_transaction_by_reference(reference, db)
    
    if transaction:
        if transaction.status == TransactionStatus.SUCCESS:
            html_content = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <title>Payment Successful</title>
                <style>
                    body {{
                        font-family: Arial, sans-serif;
                        display: flex;
                        justify-content: center;
                        align-items: center;
                        height: 100vh;
                        margin: 0;
                        background-color: #f5f5f5;
                    }}
                    .container {{
                        text-align: center;
                        background: white;
                        padding: 40px;
                        border-radius: 10px;
                        box-shadow: 0 2px 10px rgba(0,0,0,0.1);
                    }}
                    .success {{
                        color: #28a745;
                        font-size: 48px;
                        margin-bottom: 20px;
                    }}
                    h1 {{
                        color: #333;
                        margin-bottom: 10px;
                    }}
                    p {{
                        color: #666;
                        margin: 10px 0;
                    }}
                    .reference {{
                        background: #f8f9fa;
                        padding: 10px;
                        border-radius: 5px;
                        font-family: monospace;
                        margin: 20px 0;
                    }}
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="success">✓</div>
                    <h1>Payment Successful!</h1>
                    <p>Your payment has been processed successfully.</p>
                    <p>Reference: <span class="reference">{reference}</span></p>
                    <p>Amount: ₦{transaction.amount:,.2f}</p>
                    <p style="margin-top: 30px; color: #999; font-size: 14px;">
                        Your wallet will be credited shortly. You can close this window.
                    </p>
                </div>
            </body>
            </html>
            """
            return HTMLResponse(content=html_content)
        elif transaction.status == TransactionStatus.FAILED:
            html_content = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <title>Payment Failed</title>
                <style>
                    body {{
                        font-family: Arial, sans-serif;
                        display: flex;
                        justify-content: center;
                        align-items: center;
                        height: 100vh;
                        margin: 0;
                        background-color: #f5f5f5;
                    }}
                    .container {{
                        text-align: center;
                        background: white;
                        padding: 40px;
                        border-radius: 10px;
                        box-shadow: 0 2px 10px rgba(0,0,0,0.1);
                    }}
                    .error {{
                        color: #dc3545;
                        font-size: 48px;
                        margin-bottom: 20px;
                    }}
                    h1 {{
                        color: #333;
                        margin-bottom: 10px;
                    }}
                    p {{
                        color: #666;
                        margin: 10px 0;
                    }}
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="error">✗</div>
                    <h1>Payment Failed</h1>
                    <p>Your payment could not be processed.</p>
                    <p>Reference: <span style="font-family: monospace; background: #f8f9fa; padding: 5px 10px; border-radius: 3px;">{reference}</span></p>
                    <p style="margin-top: 30px; color: #999; font-size: 14px;">
                        Please try again or contact support.
                    </p>
                </div>
            </body>
            </html>
            """
            return HTMLResponse(content=html_content)
    
    # Transaction not found or still pending
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Payment Processing</title>
        <style>
            body {{
                font-family: Arial, sans-serif;
                display: flex;
                justify-content: center;
                align-items: center;
                height: 100vh;
                margin: 0;
                background-color: #f5f5f5;
            }}
            .container {{
                text-align: center;
                background: white;
                padding: 40px;
                border-radius: 10px;
                box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            }}
            .pending {{
                color: #ffc107;
                font-size: 48px;
                margin-bottom: 20px;
            }}
            h1 {{
                color: #333;
                margin-bottom: 10px;
            }}
            p {{
                color: #666;
                margin: 10px 0;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="pending">⏳</div>
            <h1>Payment Processing</h1>
            <p>Your payment is being processed.</p>
            <p>Reference: <span style="font-family: monospace; background: #f8f9fa; padding: 5px 10px; border-radius: 3px;">{reference}</span></p>
            <p style="margin-top: 30px; color: #999; font-size: 14px;">
                Please wait while we confirm your payment. You can check the status later.
            </p>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)


@router.post(
    "/paystack/webhook",
    response_model=WebhookResponse,
    summary="Paystack Webhook (automatic)",
    description=(
        "This is called by Paystack automatically after payment.\n"
        "You do NOT need to trigger this manually.\n"
        "It validates the signature and credits the wallet if the payment succeeded."
    )
)
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


@router.get(
    "/deposit/{reference}/status",
    response_model=DepositStatusResponse,
    summary="Check Deposit Status",
    description=(
        "Check if a deposit is pending, success, or failed.\n"
        "Steps:\n"
        "1) Get the 'reference' from the deposit response.\n"
        "2) Paste it here and Execute.\n"
        "Note: This does NOT credit your wallet; only the webhook does."
    )
)
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
    description="Shows your current wallet balance. Click 'Try it out' → 'Execute'."
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


@router.post(
    "/transfer",
    response_model=TransferResponse,
    summary="Transfer to Another Wallet",
    description=(
        "Send money to another user's wallet.\n"
        "Steps:\n"
        "1) Click 'Try it out'.\n"
        "2) Enter the recipient 'wallet_number'.\n"
        "3) Enter amount in kobo (e.g., 1000 = ₦10).\n"
        "4) Execute. You need enough balance and the 'transfer' permission."
    )
)
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


@router.get(
    "/transactions",
    response_model=list[TransactionResponse],
    summary="Transaction History",
    description=(
        "See your deposits, transfers, and received transactions.\n"
        "Steps:\n"
        "1) Click 'Try it out'.\n"
        "2) Optionally set 'limit' (max 100) and 'offset' for paging.\n"
        "3) Execute to view your history."
    )
)
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

