import json
import requests
import inspect
from abc import ABC
from pathlib import Path
from typing import Any, ClassVar
from ..functions import parse_config
from ..exceptions import APIError, AuthenticationError
from .auth import BaseAuth

from urllib.parse import urljoin

class StaticBaseApiClient(ABC):
    """Base API client designed for static method usage only"""    
    # Class-level configuration that subclasses should override
    api_name: ClassVar[str] = "unknown_api"
    api_config: ClassVar[dict[str, Any]] = {}
    version: ClassVar[str] = "unknown_version"
    auth_handler:ClassVar[BaseAuth] = None

    # reduce multiple initialization in case of multiple inheritance
    _class_is_initialized: ClassVar[bool] = False

    # private class variable to hold parsed config
    _config: ClassVar[dict[str, Any]] = {}

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
        params: dict | None = None,
        body: Any | None = None,
        headers: dict | None = None,
        endpoint_headers: dict | None = None,
        override_default_headers: bool = False,
        timeout: int | None = None,
        auth_required: bool = True,
        auth_handler: BaseAuth | None = None,
        files: dict | None = None 
    ) -> Any:
        """Execute HTTP request - called by decorator"""
                
        # Get fresh config each time (no cache) [Dynamic config read]
        parsed_config = cls._config.copy()
        
        # Build full URL
        resolved_base_url = parsed_config.get('base_url')
        if not resolved_base_url:
            raise ValueError(f"Base URL not configured for {cls.api_name}")

        url = urljoin(resolved_base_url, path.lstrip('/'))
        
        # Add additional headers
        request_headers = {}
        
        # Level 1: Global default headers (skip if override is True)
        if not override_default_headers and 'default_headers' in parsed_config:
            request_headers.update(parsed_config['default_headers'])
        
        # Level 2: Endpoint-specific headers
        if endpoint_headers:
            request_headers.update(endpoint_headers)
        
        # Level 3: Runtime headers (user-provided)
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

        # Add request body (TODO: handle different body types later)
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
    
    @classmethod
    def _prepare_files(cls, files: dict) -> dict:
        prepared = {}
        
        for field_name, file_data in files.items():
            if isinstance(file_data, tuple):
                # Already formatted: (filename, file_obj, content_type)
                prepared[field_name] = file_data
            elif isinstance(file_data, str):
                # File path string
                file_path = Path(file_data)
                if not file_path.exists():
                    raise FileNotFoundError(f"File not found: {file_data}")
                
                # Open file and prepare tuple
                prepared[field_name] = (
                    file_path.name,
                    open(file_path, 'rb'),
                    cls._get_content_type(file_path)
                )
            elif hasattr(file_data, 'read'):
                # File-like object
                filename = getattr(file_data, 'name', 'file')
                prepared[field_name] = (
                    filename,
                    file_data,
                    'application/octet-stream'
                )
            else:
                raise ValueError(f"Invalid file data for {field_name}")
        
        return prepared

    @classmethod
    def _get_content_type(cls, file_path: Path) -> str:
        """Get content type from file extension"""
        ext = file_path.suffix.lower()
        content_types = {
            '.pdf': 'application/pdf',
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.png': 'image/png',
            '.txt': 'text/plain',
            '.json': 'application/json'
        }
        return content_types.get(ext, 'application/octet-stream')

    # # TODO: Fix this method remove repsonse_model param
    @classmethod
    def _parse_response(cls, response: requests.Response) -> Any:
        """Parse response data"""
        try:
            data = response.json()
        except ValueError:
            return response.text if response.text else None
        
        return data