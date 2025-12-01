"""
Authentication Routes with AWS Cognito Integration

Handles:
- User registration via Cognito
- User login with rate limiting
- Token refresh
- User profile sync with MongoDB
"""

import boto3
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends, Request, status
from pydantic import BaseModel, EmailStr, Field
from botocore.exceptions import ClientError

from app.config import settings
from app.database import get_database
from app.middleware.rate_limiter import rate_limit_check, rate_limiter, get_client_ip

import logging
logger = logging.getLogger(__name__)

router = APIRouter()

# Initialize Cognito client
cognito_client = boto3.client(
    'cognito-idp',
    region_name=settings.AWS_REGION
)


# ========================================
# Request/Response Models
# ========================================

class RegisterRequest(BaseModel):
    """User registration request"""
    email: EmailStr
    password: str = Field(..., min_length=8)
    name: str = Field(..., min_length=2, max_length=100)
    phone_number: Optional[str] = None


class LoginRequest(BaseModel):
    """User login request"""
    email: EmailStr
    password: str


class ConfirmRegistrationRequest(BaseModel):
    """Email verification code confirmation"""
    email: EmailStr
    confirmation_code: str


class RefreshTokenRequest(BaseModel):
    """Token refresh request"""
    refresh_token: str


class AuthResponse(BaseModel):
    """Authentication response with tokens"""
    access_token: str
    id_token: str
    refresh_token: str
    expires_in: int
    token_type: str = "Bearer"
    user: dict


class ForgotPasswordRequest(BaseModel):
    """Forgot password request"""
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    """Reset password with code"""
    email: EmailStr
    confirmation_code: str
    new_password: str = Field(..., min_length=8)


# ========================================
# Authentication Endpoints
# ========================================

@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(request_data: RegisterRequest):
    """
    Register a new user with AWS Cognito.

    Flow:
    1. Create user in Cognito
    2. Cognito sends verification email
    3. User must confirm email before login
    4. User profile created in MongoDB after confirmation
    """
    try:
        # Prepare user attributes
        user_attributes = [
            {'Name': 'email', 'Value': request_data.email},
            {'Name': 'name', 'Value': request_data.name},
        ]

        if request_data.phone_number:
            user_attributes.append({
                'Name': 'phone_number',
                'Value': request_data.phone_number
            })

        # Create user in Cognito
        response = cognito_client.sign_up(
            ClientId=settings.COGNITO_CLIENT_ID,
            Username=request_data.email,
            Password=request_data.password,
            UserAttributes=user_attributes
        )

        logger.info(f"User registered: {request_data.email}")

        return {
            "message": "Registration successful. Please check your email for verification code.",
            "user_sub": response['UserSub'],
            "email": request_data.email,
            "confirmed": response['UserConfirmed']
        }

    except ClientError as e:
        error_code = e.response['Error']['Code']
        error_message = e.response['Error']['Message']

        logger.warning(f"Registration failed for {request_data.email}: {error_code}")

        if error_code == 'UsernameExistsException':
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email already registered"
            )
        elif error_code == 'InvalidPasswordException':
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Password does not meet requirements. Must have uppercase, lowercase, and numbers."
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error_message
            )


@router.post("/confirm")
async def confirm_registration(request_data: ConfirmRegistrationRequest):
    """
    Confirm user registration with verification code.

    After confirmation, creates user profile in MongoDB.
    """
    try:
        # Confirm the user in Cognito
        cognito_client.confirm_sign_up(
            ClientId=settings.COGNITO_CLIENT_ID,
            Username=request_data.email,
            ConfirmationCode=request_data.confirmation_code
        )

        # Get user info from Cognito
        user_info = cognito_client.admin_get_user(
            UserPoolId=settings.COGNITO_USER_POOL_ID,
            Username=request_data.email
        )

        # Extract attributes
        attributes = {attr['Name']: attr['Value'] for attr in user_info['UserAttributes']}

        # Create user in MongoDB
        db = await get_database()
        user_doc = {
            "cognito_sub": attributes.get('sub'),
            "email": request_data.email,
            "name": attributes.get('name', ''),
            "phone_number": attributes.get('phone_number'),
            "stats": {
                "events_created": 0,
                "events_attended": 0,
                "collectibles_count": 0,
                "total_video_minutes": 0
            },
            "current_location": None,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }

        # Check if user already exists (by cognito_sub or email)
        existing = await db.users.find_one({
            "$or": [
                {"cognito_sub": attributes.get('sub')},
                {"email": request_data.email}
            ]
        })

        if not existing:
            await db.users.insert_one(user_doc)
            logger.info(f"User profile created in MongoDB: {request_data.email}")

        return {
            "message": "Email confirmed successfully. You can now log in.",
            "email": request_data.email
        }

    except ClientError as e:
        error_code = e.response['Error']['Code']
        error_message = e.response['Error']['Message']

        logger.warning(f"Confirmation failed for {request_data.email}: {error_code}")

        if error_code == 'CodeMismatchException':
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid verification code"
            )
        elif error_code == 'ExpiredCodeException':
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Verification code has expired. Request a new one."
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error_message
            )


@router.post("/resend-code")
async def resend_confirmation_code(email: EmailStr):
    """Resend email verification code"""
    try:
        cognito_client.resend_confirmation_code(
            ClientId=settings.COGNITO_CLIENT_ID,
            Username=email
        )

        return {"message": "Verification code resent to your email"}

    except ClientError as e:
        error_message = e.response['Error']['Message']
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_message
        )


@router.post("/login", response_model=AuthResponse)
async def login(
    request: Request,
    request_data: LoginRequest,
    _: bool = Depends(rate_limit_check)
):
    """
    Login with email and password.

    Security:
    - Rate limited: 5 attempts per minute per IP
    - IP blocked for 15 minutes after exceeding limit
    - Returns JWT tokens from Cognito

    Tokens:
    - access_token: For API authorization (24h expiry)
    - id_token: Contains user claims (24h expiry)
    - refresh_token: For getting new tokens (30 days expiry)
    """
    ip = get_client_ip(request)

    try:
        # Authenticate with Cognito
        response = cognito_client.initiate_auth(
            ClientId=settings.COGNITO_CLIENT_ID,
            AuthFlow='USER_PASSWORD_AUTH',
            AuthParameters={
                'USERNAME': request_data.email,
                'PASSWORD': request_data.password
            }
        )

        # Successful login - reset rate limiter
        await rate_limiter.record_successful_attempt(ip)

        auth_result = response['AuthenticationResult']

        # Get user info from Cognito
        user_info = cognito_client.get_user(
            AccessToken=auth_result['AccessToken']
        )

        # Extract user attributes
        attributes = {attr['Name']: attr['Value'] for attr in user_info['UserAttributes']}

        # Get or create user in MongoDB
        db = await get_database()
        mongo_user = await db.users.find_one({"cognito_sub": attributes.get('sub')})

        if not mongo_user:
            # Create user if doesn't exist
            user_doc = {
                "cognito_sub": attributes.get('sub'),
                "email": request_data.email,
                "name": attributes.get('name', ''),
                "phone_number": attributes.get('phone_number'),
                "stats": {
                    "events_created": 0,
                    "events_attended": 0,
                    "collectibles_count": 0,
                    "total_video_minutes": 0
                },
                "current_location": None,
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow()
            }
            result = await db.users.insert_one(user_doc)
            mongo_user = await db.users.find_one({"_id": result.inserted_id})

        logger.info(f"User logged in: {request_data.email} from IP: {ip}")

        return AuthResponse(
            access_token=auth_result['AccessToken'],
            id_token=auth_result['IdToken'],
            refresh_token=auth_result['RefreshToken'],
            expires_in=auth_result['ExpiresIn'],
            user={
                "id": str(mongo_user['_id']),
                "cognito_sub": attributes.get('sub'),
                "email": request_data.email,
                "name": attributes.get('name', ''),
                "stats": mongo_user.get('stats', {})
            }
        )

    except ClientError as e:
        error_code = e.response['Error']['Code']

        # Record failed attempt for rate limiting
        blocked, duration = await rate_limiter.record_failed_attempt(ip)

        if blocked:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "error": "Too many failed login attempts",
                    "blocked_for_seconds": duration,
                    "message": f"IP blocked for {duration // 60} minutes"
                },
                headers={"Retry-After": str(duration)}
            )

        logger.warning(f"Login failed for {request_data.email} from IP {ip}: {error_code}")

        if error_code == 'NotAuthorizedException':
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password"
            )
        elif error_code == 'UserNotConfirmedException':
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Email not verified. Please check your email for verification code."
            )
        elif error_code == 'UserNotFoundException':
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password"
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=e.response['Error']['Message']
            )


@router.post("/refresh")
async def refresh_token(request_data: RefreshTokenRequest):
    """
    Refresh access token using refresh token.

    Use when access token expires (after 24h).
    """
    try:
        response = cognito_client.initiate_auth(
            ClientId=settings.COGNITO_CLIENT_ID,
            AuthFlow='REFRESH_TOKEN_AUTH',
            AuthParameters={
                'REFRESH_TOKEN': request_data.refresh_token
            }
        )

        auth_result = response['AuthenticationResult']

        return {
            "access_token": auth_result['AccessToken'],
            "id_token": auth_result['IdToken'],
            "expires_in": auth_result['ExpiresIn'],
            "token_type": "Bearer"
        }

    except ClientError as e:
        error_code = e.response['Error']['Code']

        if error_code == 'NotAuthorizedException':
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Refresh token is invalid or expired. Please log in again."
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=e.response['Error']['Message']
            )


@router.post("/forgot-password")
async def forgot_password(request_data: ForgotPasswordRequest):
    """
    Initiate password reset flow.

    Sends reset code to user's email.
    """
    try:
        cognito_client.forgot_password(
            ClientId=settings.COGNITO_CLIENT_ID,
            Username=request_data.email
        )

        return {
            "message": "Password reset code sent to your email"
        }

    except ClientError as e:
        error_code = e.response['Error']['Code']

        if error_code == 'UserNotFoundException':
            # Don't reveal if user exists
            return {"message": "If the email exists, a reset code has been sent"}
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=e.response['Error']['Message']
            )


@router.post("/reset-password")
async def reset_password(request_data: ResetPasswordRequest):
    """
    Reset password with confirmation code.
    """
    try:
        cognito_client.confirm_forgot_password(
            ClientId=settings.COGNITO_CLIENT_ID,
            Username=request_data.email,
            ConfirmationCode=request_data.confirmation_code,
            Password=request_data.new_password
        )

        return {"message": "Password reset successfully. You can now log in with your new password."}

    except ClientError as e:
        error_code = e.response['Error']['Code']

        if error_code == 'CodeMismatchException':
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid reset code"
            )
        elif error_code == 'ExpiredCodeException':
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Reset code has expired. Request a new one."
            )
        elif error_code == 'InvalidPasswordException':
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Password does not meet requirements"
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=e.response['Error']['Message']
            )


@router.get("/rate-limit-status")
async def get_rate_limit_status(request: Request):
    """
    Check rate limit status for current IP (for debugging/monitoring).
    """
    ip = get_client_ip(request)
    status = await rate_limiter.get_ip_status(ip)
    return status
