import json
import requests
import inspect
from abc import ABC
from pathlib import Path
from typing import Optional, Dict, Any, List, ClassVar
from ..functions import parse_config
from ..exceptions import APIError, AuthenticationError
from .auth import BaseAuth

from urllib.parse import urljoin

class StaticBaseApiClient(ABC):
    """Base API client designed for static method usage only"""    
    # Class-level configuration that subclasses should override
    api_name: ClassVar[str] = "unknown_api"
    api_config: ClassVar[Dict[str, Any]] = {}
    version: ClassVar[str] = "unknown_version"
    auth_handler:ClassVar[BaseAuth] = None

    # reduce multiple initialization in case of multiple inheritance
    _class_is_initialized: ClassVar[bool] = False

    # private class variable to hold parsed config
    _config: ClassVar[Dict[str, Any]] = {}

    def __init_subclass__(cls, **kwargs):
        # a class function to ensure class is initialized only once class attribute level, Not INIT instance level
        cls._config = parse_config(cls.api_config) if cls.api_config is not None else {}
        
        if cls._class_is_initialized:
            return
        
        cls._class_is_initialized = True

    @classmethod
    def execute_request(
        cls,
        method: str,
        path: str,
        params: Optional[Dict] = None,
        body: Optional[Any] = None,
        headers: Optional[Dict] = None,
        timeout: Optional[int] = None,
        auth_required: bool = True,
        base_url: Optional[str] = None,
        auth_handler: Optional[BaseAuth] = None
    ) -> Any:
        """Execute HTTP request - called by decorator"""
                
        # Get fresh config each time (no cache) [Dynamic config read]
        parsed_config = cls._config.copy()
        
        # Build full URL
        resolved_base_url = parsed_config.get('base_url')
        if not resolved_base_url:
            raise ValueError(f"Base URL not configured for {cls.api_name}")

        url = urljoin(resolved_base_url, path.lstrip('/'))
        
        # Prepare request headers with class config defaults
        # Basic headers configuration for rest APIs
        request_headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json', # can be adjusted based on API requirements
            'User-Agent': f'Generated-API-Client/{cls.__name__}/1.0'
        }
        
        # Add additional headers
        if headers:
            request_headers.update(headers)
        
        # Prepare request kwargs
        kwargs = {
            'headers': request_headers
        }
        
        # Resolve timeout (parameter > class config > default)
        if timeout is not None:
            kwargs['timeout'] = timeout
        elif parsed_config.get('timeout') is not None:
            kwargs['timeout'] = parsed_config.get('timeout')
        
        # Add query parameters
        if params:
            kwargs['params'] = {k: v for k, v in params.items() if v is not None}
        
        # Add request body
        if body is not None:
            if isinstance(body, (dict, list)):
                kwargs['json'] = body
            else:
                kwargs['data'] = body
        
        # Apply authentication if required
        if auth_required:
            auth_handler = auth_handler or cls.auth_handler

            if not auth_handler or not (isinstance(auth_handler, BaseAuth) or issubclass(auth_handler, BaseAuth)):
                raise AuthenticationError("Authentication required but no valid BaseAuth handler provided")
            
            request_params = {"request_kwargs": kwargs}

            # add auth to request
            updated_params = auth_handler.apply_auth(request_params)

            kwargs = updated_params.get("request_kwargs", kwargs)

        # Make request
        try:
            # Execute the request
            response = requests.request(method, url, **kwargs)
            
            # Check for errors - respect raise_on_error config (fresh read)
            if parsed_config.get('raise_on_error', False):
                # logic to raise error on bad status codes
                pass
            
            # Parse response
            return cls._parse_response(response)
            
        except requests.exceptions.RequestException as e:
            if parsed_config.get('raise_on_error', False):
                raise APIError(f"Request failed: {str(e)}")
            else:
                print(f"Request failed: {str(e)}")
                return None

    # # TODO: Fix this method remove repsonse_model param
    @classmethod
    def _parse_response(cls, response: requests.Response) -> Any:
        """Parse response data"""
        try:
            data = response.json()
        except ValueError:
            return response.text if response.text else None
        
        return data