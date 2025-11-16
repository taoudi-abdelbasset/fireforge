import requests
import time
from urllib.parse import urljoin
from abc import ABC, abstractmethod
from typing import Any, ClassVar
from ..exceptions import AuthenticationError
from ..functions import parse_config


class ConfigMixin:
    """Mixin to handle auth_config parsing for subclasses"""
    auth_config: ClassVar[dict[str, Any]] = {}
    _config: ClassVar[dict[str, Any]] = {}
    _is_parsed: ClassVar[bool] = False
    
    @classmethod
    def _init_config(cls):
        """Parse auth_config if present and not already parsed"""
        if not hasattr(cls, '_is_parsed') or not cls._is_parsed:
            if hasattr(cls, 'auth_config') and cls.auth_config:
                cls._config = parse_config(cls.auth_config)
                cls._is_parsed = True
                return True
        return False


class BaseAuth(ABC):
    """Base authentication handler"""
    _registry: ClassVar[dict[str, "BaseAuth"]] = {}

    @classmethod
    def __init_subclass__(cls, auth_type: str | None = None, **kwargs):
        """Register auth type and parse config"""
        super().__init_subclass__(**kwargs)
        
        if auth_type is not None:
            if not isinstance(auth_type, str):
                raise TypeError(f"auth_type must be str or None, got {type(auth_type).__name__}")
            if not auth_type.strip():
                raise ValueError("auth_type cannot be empty or whitespace")
            if auth_type in cls._registry:
                raise ValueError(f"Auth type '{auth_type}' already registered")
            
            cls._registry[auth_type] = cls

    @classmethod
    def create_instance(cls, auth_type: str) -> "BaseAuth":
        """Create auth instance by type"""
        if auth_type not in cls._registry:
            raise Exception(f"Unknown auth type: {auth_type}")
        subclass = cls._registry[auth_type]
        return object.__new__(subclass)
    
    @classmethod
    @abstractmethod
    def apply_auth(cls, request_params: dict[str, Any]) -> dict[str, Any]:
        """Apply authentication to request"""
        pass

class StaticTokenAuth(BaseAuth, ConfigMixin, auth_type="static_token"):
    """Static API key/token authentication"""
    
    token_placement: ClassVar[dict[str, Any]] = {}
    _token: ClassVar[str | None] = None

    @classmethod
    def __init_subclass__(cls, **kwargs):
        """Initialize config for StaticTokenAuth subclasses"""
        if cls._init_config():
            cls.token_placement = cls._config.get("token_placement", {})
            cls._token = cls._config.get("access_key")
            
            if not cls._token or cls._token in ("your_token_here", "default_token", ""):
                raise AuthenticationError(f"Invalid or missing token: {cls._token}")

    @classmethod
    def apply_auth(cls, request_params: dict[str, Any]) -> dict[str, Any]:
        """Add token to request"""
        if "request_kwargs" not in request_params:
            request_params["request_kwargs"] = {}
        
        placement_type = cls.token_placement.get("type", "header")
        token_field = cls.token_placement.get("token_field_name")

        match placement_type:
            case "header":
                prefix = cls.token_placement.get("prefix", "")
                token_value = f"{prefix} {cls._token}".strip() if prefix else cls._token
                
                if "headers" not in request_params["request_kwargs"]:
                    request_params["request_kwargs"]["headers"] = {}
                request_params["request_kwargs"]["headers"][token_field] = token_value
            
            case "query":
                if "params" not in request_params["request_kwargs"]:
                    request_params["request_kwargs"]["params"] = {}
                request_params["request_kwargs"]["params"][token_field] = cls._token
            
            case "body":            
                if "json" not in request_params["request_kwargs"]:
                    request_params["request_kwargs"]["json"] = {}
                request_params["request_kwargs"]["json"][token_field] = cls._token
            
            case _:
                raise AuthenticationError(f"Unknown placement type: {placement_type}")
        
        return request_params

class LoginTokenAuth(BaseAuth, ConfigMixin, auth_type="login_token"):
    """Login-based token authentication"""
    
    base_url: ClassVar[str] = ""
    login_endpoint: ClassVar[dict[str, Any]] = {}
    token_placement: ClassVar[dict[str, Any]] = {}
    login_body: ClassVar[dict[str, Any]] = {}

    # Token state
    access_token: ClassVar[str | None] = None
    refresh_token: ClassVar[str | None] = None
    token_expiry: ClassVar[float | None] = None

    @classmethod
    def __init_subclass__(cls, **kwargs):
        """Initialize config for LoginTokenAuth subclasses"""
        if cls._init_config():
            if hasattr(cls, 'base_url') and cls.base_url:
                cls._base_url = parse_config(cls.base_url)
            
            cls.login_endpoint = cls._config.get("login_endpoint", {})
            cls.token_placement = cls._config.get("token_placement", {})
            cls.login_body = cls.login_endpoint.get("login_body", {})
            
            if not cls.login_endpoint:
                raise AuthenticationError("Login endpoint config required")
            if not cls.token_placement:
                raise AuthenticationError("Token placement config required")
            if not hasattr(cls, '_base_url') or not cls._base_url:
                raise ValueError("Base URL config required")

    @classmethod
    def login(cls, credentials: dict[str, Any] | None = None) -> str:
        """
        Perform login and return access token.
        User must call this manually before making API requests.
        
        Returns:
            Access token string
        """
        creds = credentials or cls.login_body
        creds = {k: v for k, v in creds.items() if v and v != ""}
        
        if not creds:
            raise AuthenticationError("No login credentials provided")
        
        login_path = cls.login_endpoint.get('path')
        login_method = cls.login_endpoint.get('method', 'POST')
        login_url = urljoin(cls._base_url,login_path.lstrip('/'))
        
        response = requests.request(method=login_method, url=login_url, json=creds)
        
        if response.status_code not in [200, 201]:
            error_msg = f"Login failed: {response.status_code}"
            try:
                error_data = response.json()
                if isinstance(error_data, dict) and 'message' in error_data:
                    error_msg = error_data['message']
            except:
                pass
            raise AuthenticationError(error_msg)
        
        data = response.json()
        
        # Extract access token
        token_field = cls.login_endpoint.get('token_field', 'access_token')
        cls.access_token = data.get(token_field)
        
        if not cls.access_token:
            raise AuthenticationError(f"Token field '{token_field}' not found in response")
        
        # Extract refresh token (optional)
        refresh_field = cls.login_endpoint.get('refresh_token_field')
        if refresh_field:
            cls.refresh_token = data.get(refresh_field)
        
        # Extract expiry (optional)
        expires_field = cls.login_endpoint.get('expires_in_field')
        if expires_field and expires_field in data:
            expires_in = data[expires_field]
            cls.token_expiry = time.time() + expires_in
        
        return cls.access_token

    @classmethod
    def logout(cls):
        """Clear all tokens"""
        cls.access_token = None
        cls.refresh_token = None
        cls.token_expiry = None

    @classmethod
    def is_token_expired(cls) -> bool:
        """Check if token is expired"""
        if not cls.token_expiry:
            return False
        return time.time() >= (cls.token_expiry - 60)  # 60s buffer

    @classmethod
    def apply_auth(cls, request_params: dict[str, Any]) -> dict[str, Any]:
        """
        Apply authentication to request.
        Raises error if token is missing or expired.
        User must call login() first.
        """
        # Check if token exists
        if not cls.access_token:
            raise AuthenticationError(
                "Not authenticated. Call login() first to obtain access token."
            )
        
        # Check if token is expired
        if cls.is_token_expired():
            raise AuthenticationError(
                "Access token has expired. Call login() again to refresh."
            )
        
        # Apply token to request
        if "request_kwargs" not in request_params:
            request_params["request_kwargs"] = {}
        
        placement_type = cls.token_placement.get("type", "header")
        token_field = cls.token_placement.get("token_field_name", "Authorization")
        
        match placement_type:
            case "header":
                prefix = cls.token_placement.get("prefix", "")
                token_value = f"{prefix} {cls.access_token}".strip() if prefix else cls.access_token
                
                if "headers" not in request_params["request_kwargs"]:
                    request_params["request_kwargs"]["headers"] = {}
                request_params["request_kwargs"]["headers"][token_field] = token_value
            
            case "query":
                if "params" not in request_params["request_kwargs"]:
                    request_params["request_kwargs"]["params"] = {}
                request_params["request_kwargs"]["params"][token_field] = cls.access_token
            
            case "body":
                if "json" not in request_params["request_kwargs"]:
                    request_params["request_kwargs"]["json"] = {}
                request_params["request_kwargs"]["json"][token_field] = cls.access_token
            
            case _:
                raise AuthenticationError(f"Unknown placement type: {placement_type}")
        
        return request_params