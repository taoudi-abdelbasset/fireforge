"""
Enhanced decorators for static API clients - Fixed for @classmethod
"""
import functools
import inspect
import re
import time

from typing import Callable
from ..exceptions import RetryExhaustedError
from .client import StaticBaseApiClient
from ..consts import URL_PATH_PARAM_PATTERN

def endpoint(
    method: str, 
    path: str, 
    auth_required: bool = True,
    body_required: bool = False,
    timeout: int | None = None,
    max_attempts: int = 1,
    delay: float = 1.0,
    backoff_factor: float = 2.0
):
    """
    Decorator to define API endpoint for class methods
    
    Args:
        method: HTTP method (GET, POST, PUT, DELETE, etc.)
        path: API endpoint path (supports {param} placeholders)
        auth_required: Whether authentication is required
        timeout: Request timeout in seconds
        body_required: Whether request body is required
    """
    def decorator(func: Callable) -> Callable:
        
        @functools.wraps(func)
        def wrapper(cls, *args, **kwargs):
            # Validate that cls is a subclass of StaticBaseApiClient
            if not (inspect.isclass(cls) and issubclass(cls, StaticBaseApiClient)):
                raise TypeError(
                    f"Class {cls.__name__ if hasattr(cls, '__name__') else cls} must inherit from StaticBaseApiClient to use @endpoint"
                )
            
            # Bind arguments
            sig = inspect.signature(func)
            bound_args = sig.bind(cls, *args, **kwargs)
            bound_args.apply_defaults()
            args_dict = bound_args.arguments
            
            # Extract parameters
            params = args_dict.get('params')
            body = args_dict.get('body') or args_dict.get('data')
            headers = args_dict.get('headers')
            req_timeout = args_dict.get('timeout', timeout)
            base_url = args_dict.get('base_url')
            
            attempts = args_dict.get('max_attempts', max_attempts)
            retry_delay = args_dict.get('delay', delay)
            retry_backoff = args_dict.get('backoff_factor', backoff_factor)
            
            # Resolve path parameters
            resolved_path = _resolve_path(path, args_dict)
            
            # Check if body is required
            if body_required and body is None:
                raise ValueError("Request body is required but not provided")
            
            # Execute with retry logic
            return _execute_with_retry(
                cls=cls,
                method=method,
                path=resolved_path,
                params=params,
                body=body,
                headers=headers,
                auth_required=auth_required,
                timeout=req_timeout,
                base_url=base_url,
                auth_handler=cls.auth_handler if hasattr(cls, 'auth_handler') else None,
                max_attempts=attempts,
                delay=retry_delay,
                backoff_factor=retry_backoff
            )
        
        return classmethod(wrapper)
    return decorator

# if Path param is missing in args, raise error "users/{user_id}/posts/{post_id}" -> user_id, post_id   
def _resolve_path(path: str, args: dict) -> str:
    """Resolve path parameters from arguments"""
    path_params = re.compile(URL_PATH_PARAM_PATTERN).findall(path)
    
    missing = [p for p in path_params if p not in args]
    if missing:
        raise ValueError(f"Missing path parameters: {', '.join(missing)}")
    
    return path.format(**{p: args[p] for p in path_params})


def _execute_with_retry(
    cls,
    method: str,
    path: str,
    params,
    body,
    headers,
    auth_required: bool,
    timeout,
    base_url,
    auth_handler,
    max_attempts: int,
    delay: float,
    backoff_factor: float
):
    """Execute request with retry logic"""
    # No retry needed
    if max_attempts <= 1:
        return cls.execute_request(
            method=method,
            path=path,
            params=params,
            body=body,
            headers=headers,
            auth_required=auth_required,
            timeout=timeout,
            base_url=base_url,
            auth_handler=auth_handler
        )
    
    # Retry logic
    current_delay = delay
    last_error = None
    
    for attempt in range(max_attempts):
        try:
            return cls.execute_request(
                method=method,
                path=path,
                params=params,
                body=body,
                headers=headers,
                auth_required=auth_required,
                timeout=timeout,
                base_url=base_url,
                auth_handler=auth_handler
            )
        except Exception as e:
            last_error = e
            
            # Last attempt - don't retry
            if attempt >= max_attempts - 1:
                break
            
            # Check if error is retryable
            if not _is_retryable(e):
                break
            
            # Wait before retry
            time.sleep(current_delay)
            current_delay *= backoff_factor
    
    raise RetryExhaustedError(
        f"Failed after {max_attempts} attempts: {method} {path}. "
        f"Last error: {last_error}"
    )

def _is_retryable(error: Exception) -> bool:
    """Check if error should be retried"""
    # Server errors (5xx) and rate limiting
    if hasattr(error, 'status_code'):
        return error.status_code in [429, 500, 502, 503, 504]
    
    # Network errors
    return isinstance(error, (ConnectionError, TimeoutError))