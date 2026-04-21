import requests
import time
from urllib.parse import urljoin
from abc import ABC, abstractmethod
from typing import Any, ClassVar
from ..exceptions import AuthenticationError
from ..functions import parse_config
import traceback


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

    multi_user: ClassVar[bool] = False
    multi_user_fallback: ClassVar[bool] = False
    _store: ClassVar[dict] = {}

    @classmethod
    def __init_subclass__(cls, **kwargs):
        """Initialize config for LoginTokenAuth subclasses"""
        if cls._init_config():
            print(f"🔧 [AUTH INIT] Initializing {cls.__name__}")
            print(f"   └─ Token before init: {getattr(cls, 'access_token', None)}")
            if hasattr(cls, 'base_url') and cls.base_url:
                cls._base_url = parse_config(cls.base_url)
            
            cls.login_endpoint = cls._config.get("login_endpoint", {})
            cls.token_placement = cls._config.get("token_placement", {})
            cls.login_body = cls.login_endpoint.get("login_body", {})
            cls.login_timeout = cls.login_endpoint.get("timeout", 30)
            
            if not cls.login_endpoint:
                raise AuthenticationError("Login endpoint config required")
            if not cls.token_placement:
                raise AuthenticationError("Token placement config required")
            if not hasattr(cls, '_base_url') or not cls._base_url:
                raise ValueError("Base URL config required")

    @classmethod
    def on_before_login(cls, request_kwargs: dict[str, Any]) -> dict[str, Any]:
        """
        Override to modify the full request before it is sent.
        Receives and must return the full request_kwargs dict.
        You can add/modify url, method, json, headers, params.
        You cannot remove existing keys (merge enforced by caller).
        """
        return request_kwargs

    @classmethod
    def on_after_login(cls, response_data: dict[str, Any]) -> None:
        """
        Override to handle the successful login response.
        Raise AuthenticationError here to abort the login.
        """
        pass

    @classmethod
    def on_login_error(cls, status_code: int, response_data: dict[str, Any]) -> None:
        """
        Override to handle login HTTP errors (non-2xx).
        Raise AuthenticationError with a custom message,
        or do nothing to let the default fallback proceed.
        """
        pass

    @classmethod
    def login(cls, credentials: dict[str, Any] | None = None, key=None) -> str:
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
        
        if cls.multi_user and key is None:
            raise AuthenticationError("multi_user mode requires a key")
        
        login_path = cls.login_endpoint.get('path')
        login_method = cls.login_endpoint.get('method', 'POST')
        login_url = urljoin(cls._base_url,login_path.lstrip('/'))
        
        request_kwargs: dict[str, Any] = {
            "url":     login_url,
            "method":  login_method,
            "json":    dict(creds),
            "headers": {},
            "params":  {},
        }

        hook_result = cls.on_before_login(dict(request_kwargs))

        if isinstance(hook_result, dict):
            for item_key in ("url", "method"):
                if item_key in hook_result:
                    request_kwargs[item_key] = hook_result[item_key]
            for item_key in ("json", "headers", "params"):
                if item_key in hook_result and isinstance(hook_result[item_key], dict):
                    request_kwargs[item_key].update(hook_result[item_key])

        try:

            response = requests.request(
                method  = request_kwargs["method"],
                url     = request_kwargs["url"],
                json    = request_kwargs["json"]    or None,
                headers = request_kwargs["headers"] or None,
                params  = request_kwargs["params"]  or None,
                timeout = cls.login_timeout,
            )

        except requests.exceptions.Timeout:
            raise AuthenticationError(f"Login request timed out after {cls.login_timeout}s")
        except requests.exceptions.ConnectionError:
            raise AuthenticationError("Login request failed: unable to connect")
        
        if response.status_code not in [200, 201]:
            try:
                error_data = response.json()
            except Exception:
                error_data = {}
            try:
                cls.on_login_error(response.status_code, error_data)
            except Exception:
                raise
            raise AuthenticationError(
                error_data.get('message', f"Login failed with status {response.status_code}")
            )
        
        data = response.json()
        
        # Extract access token
        token_field = cls.login_endpoint.get('token_field', 'access_token')
        token_value = data.get(token_field)
        if not token_value:
            raise AuthenticationError(f"Token field '{token_field}' not found in response")

        # Extract refresh token
        refresh_value = None
        refresh_field = cls.login_endpoint.get('refresh_token_field')
        if refresh_field:
            refresh_value = data.get(refresh_field)

        # Extract expiry
        expiry_value = None
        expires_field = cls.login_endpoint.get('expires_in_field')
        if expires_field and expires_field in data:
            expiry_value = time.time() + data[expires_field]

        # Store — multi_user or single
        if cls.multi_user:
            cls._store[key] = {
                "token":         token_value,
                "refresh_token": refresh_value,
                "expiry":        expiry_value,
            }
        else:
            cls.access_token  = token_value
            cls.refresh_token = refresh_value
            cls.token_expiry  = expiry_value

        cls.on_after_login(data)
        return token_value

    @classmethod
    def logout(cls, key=None):
        if cls.multi_user:
            cls._store.pop(key, None)
        else:
            cls.access_token  = None
            cls.refresh_token = None
            cls.token_expiry  = None

    @classmethod
    def is_token_expired(cls, key=None) -> bool:
        if cls.multi_user:
            entry = cls._store.get(key, {})
            expiry = entry.get("expiry")
            if not expiry:
                return False
            return time.time() >= (expiry - 60)
        else:
            if not cls.token_expiry:
                return False
            return time.time() >= (cls.token_expiry - 60)

    @classmethod
    def has_token(cls, key=None) -> bool:
        if cls.multi_user:
            return bool(cls._store.get(key, {}).get("token"))
        return bool(cls.access_token)

    @classmethod
    def apply_auth(cls, request_params: dict[str, Any], key=None) -> dict[str, Any]:
        # Resolve which token to use
        if cls.multi_user:
            if key is None:
                if not cls.multi_user_fallback:
                    raise AuthenticationError(
                        "multi_user mode requires a key. Pass instant_key= or set multi_user_fallback=True"
                    )
                # fallback to class-level token
                token = cls.access_token
                expired = cls.is_token_expired()
            else:
                entry = cls._store.get(key)
                if not entry or not entry.get("token"):
                    raise AuthenticationError(
                        f"No token found for key '{key}'. Call login(credentials=..., key='{key}') first."
                    )
                token = entry["token"]
                expired = cls.is_token_expired(key=key)
        else:
            token = cls.access_token
            expired = cls.is_token_expired()

        if not token:
            raise AuthenticationError("Not authenticated. Call login() first.")
        if expired:
            raise AuthenticationError("Access token has expired. Call login() again.")

        if "request_kwargs" not in request_params:
            request_params["request_kwargs"] = {}

        placement_type = cls.token_placement.get("type", "header")
        token_field    = cls.token_placement.get("token_field_name", "Authorization")

        match placement_type:
            case "header":
                prefix = cls.token_placement.get("prefix", "")
                token_value = f"{prefix} {token}".strip() if prefix else token
                if "headers" not in request_params["request_kwargs"]:
                    request_params["request_kwargs"]["headers"] = {}
                request_params["request_kwargs"]["headers"][token_field] = token_value
            case "query":
                if "params" not in request_params["request_kwargs"]:
                    request_params["request_kwargs"]["params"] = {}
                request_params["request_kwargs"]["params"][token_field] = token
            case "body":
                if "json" not in request_params["request_kwargs"]:
                    request_params["request_kwargs"]["json"] = {}
                request_params["request_kwargs"]["json"][token_field] = token
            case _:
                raise AuthenticationError(f"Unknown placement type: {placement_type}")

        return request_params