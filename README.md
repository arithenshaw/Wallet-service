# Wallet Service API

A comprehensive wallet service backend with Paystack integration, JWT authentication (Google OAuth), and API key management for service-to-service access.

## Features

- **Google OAuth Authentication**: Sign in with Google and receive JWT tokens
- **API Key Management**: Create, manage, and rollover API keys with permission-based access
- **Paystack Integration**: Deposit funds using Paystack payment gateway
- **Wallet Operations**: View balance, transfer funds, and view transaction history
- **Webhook Support**: Mandatory Paystack webhook handling for transaction updates
- **Security**: JWT and API key authentication with permission enforcement

## Requirements

- Python 3.8+
- SQLite (default) or PostgreSQL
- Paystack account with API keys
- Google OAuth credentials

## Installation

1. Clone the repository and navigate to the project directory:
```bash
cd "stage 8"
```

2. Create a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Create a `.env` file in the project root:
```env
# Database
DATABASE_URL=sqlite:///./wallet.db

# Google OAuth
GOOGLE_CLIENT_ID=your-google-client-id
GOOGLE_CLIENT_SECRET=your-google-client-secret
GOOGLE_REDIRECT_URI=http://localhost:8000/auth/google/callback

# JWT
JWT_SECRET_KEY=your-secret-key-change-in-production
JWT_ALGORITHM=HS256
JWT_EXPIRATION_HOURS=24

# Paystack
PAYSTACK_SECRET_KEY=sk_test_your_secret_key
PAYSTACK_PUBLIC_KEY=pk_test_your_public_key
PAYSTACK_WEBHOOK_SECRET=your_webhook_secret

# Base URL
BASE_URL=http://localhost:8000
```

5. Run the application:
```bash
python -m app.main
# Or
uvicorn app.main:app --reload
```

The API will be available at `http://localhost:8000`

## API Endpoints

### Authentication

#### `GET /auth/google`
Triggers Google sign-in flow. Returns redirect to Google OAuth or JSON with auth URL.

#### `GET /auth/google/callback`
Google OAuth callback. Creates/updates user and returns JWT token.

**Response:**
```json
{
  "token": "eyJ...",
  "user_id": 1,
  "email": "user@example.com",
  "name": "John Doe"
}
```

### API Key Management

#### `POST /keys/create`
Create a new API key with specified permissions.

**Request:**
```json
{
  "name": "wallet-service",
  "permissions": ["deposit", "transfer", "read"],
  "expiry": "1D"
}
```

**Response:**
```json
{
  "api_key": "sk_live_xxxxx",
  "expires_at": "2025-01-01T12:00:00Z"
}
```

**Expiry Options:** `1H`, `1D`, `1M`, `1Y` (Hour, Day, Month, Year)

**Valid Permissions:** `deposit`, `transfer`, `read`

**Limits:** Maximum 5 active API keys per user

#### `POST /keys/rollover`
Rollover an expired API key with the same permissions.

**Request:**
```json
{
  "expired_key_id": "123",
  "expiry": "1M"
}
```

### Wallet Operations

#### `POST /wallet/deposit`
Initiate wallet deposit using Paystack.

**Authentication:** JWT or API key with `deposit` permission

**Request:**
```json
{
  "amount": 5000
}
```
*Amount is in kobo (5000 kobo = 50 Naira)*

**Response:**
```json
{
  "reference": "ref_xxxxx",
  "authorization_url": "https://paystack.co/checkout/..."
}
```

#### `POST /wallet/paystack/webhook`
Paystack webhook endpoint (mandatory). Only webhooks can credit wallets.

**Headers:**
- `x-paystack-signature`: Webhook signature for verification

**Response:**
```json
{
  "status": true
}
```

#### `GET /wallet/deposit/{reference}/status`
Get deposit transaction status. Does NOT credit wallets.

**Authentication:** JWT or API key with `read` permission

**Response:**
```json
{
  "reference": "ref_xxxxx",
  "status": "success",
  "amount": 50.00
}
```

**Status Values:** `pending`, `success`, `failed`

#### `GET /wallet/balance`
Get wallet balance.

**Authentication:** JWT or API key with `read` permission

**Response:**
```json
{
  "balance": 15000.00
}
```

#### `POST /wallet/transfer`
Transfer funds to another user's wallet.

**Authentication:** JWT or API key with `transfer` permission

**Request:**
```json
{
  "wallet_number": "4566678954356",
  "amount": 3000
}
```
*Amount is in kobo*

**Response:**
```json
{
  "status": "success",
  "message": "Transfer completed",
  "reference": "transfer_xxxxx"
}
```

#### `GET /wallet/transactions`
Get transaction history.

**Authentication:** JWT or API key with `read` permission

**Query Parameters:**
- `limit`: Number of transactions (default: 50, max: 100)
- `offset`: Pagination offset (default: 0)

**Response:**
```json
[
  {
    "id": 1,
    "reference": "ref_xxxxx",
    "type": "deposit",
    "amount": 50.00,
    "status": "success",
    "description": "Deposit of ₦50.00",
    "created_at": "2025-01-01T12:00:00Z"
  },
  {
    "id": 2,
    "reference": "transfer_xxxxx",
    "type": "transfer",
    "amount": 30.00,
    "status": "success",
    "description": "Transfer to 4566678954356",
    "created_at": "2025-01-01T13:00:00Z"
  }
]
```

## Authentication

The API supports two authentication methods:

### JWT Authentication
1. Sign in via Google OAuth: `GET /auth/google`
2. Receive JWT token from callback
3. Include in requests: `Authorization: Bearer <token>`

JWT users have full access to all wallet operations.

### API Key Authentication
1. Create API key: `POST /keys/create`
2. Include in requests: `x-api-key: <key>`

API keys have permission-based access:
- `deposit`: Can initiate deposits
- `transfer`: Can transfer funds
- `read`: Can view balance and transactions

## Security Features

- **Webhook Signature Verification**: All Paystack webhooks are verified
- **Idempotent Operations**: Deposit references are unique, webhooks are idempotent
- **Atomic Transfers**: Wallet transfers are atomic (no partial deductions)
- **Permission Enforcement**: API keys can only perform allowed operations
- **Key Limits**: Maximum 5 active API keys per user
- **Expiration**: API keys automatically expire based on expiry setting

## Error Handling

The API returns clear error messages for:
- Insufficient balance
- Invalid API key
- Expired API key
- Missing permissions
- Invalid wallet number
- Duplicate transactions

## Database Schema

- **Users**: Google OAuth user information
- **Wallets**: User wallet with balance and wallet number
- **Transactions**: Deposit, transfer, and received transactions
- **API Keys**: API keys with permissions and expiration

## Development

### Running Tests
```bash
# Add test files and run
pytest
```

### Database Migrations
The database is automatically initialized on startup. For production, consider using Alembic for migrations.

## Production Considerations

1. **Environment Variables**: Use secure environment variables, never commit secrets
2. **Database**: Use PostgreSQL instead of SQLite for production
3. **JWT Secret**: Use a strong, random JWT secret key
4. **HTTPS**: Always use HTTPS in production
5. **Webhook Secret**: Configure Paystack webhook secret for signature verification
6. **Rate Limiting**: Consider adding rate limiting for production
7. **Logging**: Add proper logging for monitoring

## License

This project is part of HNG13 Stage 8 task submission.

