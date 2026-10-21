"""
Authentication and Authorization Module
Handles user login, password hashing, and role-based access control.
"""
import hashlib
import secrets
import database
import jwt
import config
from datetime import datetime, timedelta

# JWT values are loaded by python-dotenv through config.py.
JWT_SECRET = config.JWT_SECRET
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = config.JWT_EXPIRATION_HOURS


def hash_password(password: str) -> str:
    """Hash a password using SHA-256 with salt."""
    salt = secrets.token_hex(16)
    password_hash = hashlib.sha256((password + salt).encode()).hexdigest()
    return f"{salt}${password_hash}"


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a password against its hash."""
    try:
        salt, hash_value = password_hash.split('$')
        computed_hash = hashlib.sha256((password + salt).encode()).hexdigest()
        return computed_hash == hash_value
    except Exception:
        return False


def authenticate_user(username: str, password: str) -> dict:
    """Authenticate a user and return user data if valid."""
    user = database.get_user_by_username(username)
    if not user or not user['is_active']:
        return None
    
    if verify_password(password, user['password_hash']):
        # Remove sensitive data from response
        user_data = {
            'id': user['id'],
            'username': user['username'],
            'full_name': user['full_name'],
            'role': user['role']
        }
        return user_data
    return None


def generate_jwt_token(user_data: dict) -> str:
    """Generate a JWT token for authenticated user."""
    payload = {
        'user_id': user_data['id'],
        'username': user_data['username'],
        'role': user_data['role'],
        'exp': datetime.utcnow() + timedelta(hours=JWT_EXPIRATION_HOURS),
        'iat': datetime.utcnow()
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def verify_jwt_token(token: str) -> dict:
    """Verify a JWT token and return the payload if valid."""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


def require_role(allowed_roles: list):
    """Decorator to require specific user roles for API endpoints."""
    def decorator(f):
        def wrapper(*args, **kwargs):
            # This would be used with Flask request context
            # For now, it's a placeholder for the implementation
            return f(*args, **kwargs)
    return wrapper


def is_manager(user_data: dict) -> bool:
    """Check if user has manager role."""
    return user_data.get('role') == 'manager'


def is_sales_person(user_data: dict) -> bool:
    """Check if user has sales person role."""
    return user_data.get('role') == 'sales_person'
