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
        files: dict | None = None,
        instant_key=None,
        body_config: dict | None = None 
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

        kwargs_update, prepared_files = cls._handle_request_body(
            body=body,
            files=files,
            body_config=body_config
        )

        kwargs.update(kwargs_update)
        
        # Apply authentication if required
        if auth_required:
            auth_handler = auth_handler or cls.auth_handler

            if not auth_handler or not (isinstance(auth_handler, BaseAuth) or issubclass(auth_handler, BaseAuth)):
                raise AuthenticationError("Authentication required but no valid BaseAuth handler provided")
            
            request_params = {"request_kwargs": kwargs}

            # add auth to request
            updated_params = auth_handler.apply_auth(request_params, key=instant_key)

            kwargs = updated_params.get("request_kwargs", kwargs)
        
        opened_files = []  # Track opened files
        # Make request
        try:
            # Track file handles for cleanup
            if 'files' in kwargs:
                files_param = kwargs['files']
                
                # Handle list format: [('field', (filename, file_obj, content_type)), ...]
                if isinstance(files_param, list):
                    for item in files_param:
                        if isinstance(item, tuple) and len(item) >= 2:
                            # item = ('field_name', (filename, file_obj, content_type))
                            file_data = item[1]
                            if isinstance(file_data, tuple) and len(file_data) >= 2:
                                file_obj = file_data[1]
                                if hasattr(file_obj, 'close'):
                                    opened_files.append(file_obj)
                
                # Handle dict format (backward compatibility)
                elif isinstance(files_param, dict):
                    for field_name, file_data in files_param.items():
                        # single file (tuple)
                        if isinstance(file_data, tuple) and len(file_data) >= 2:
                            file_obj = file_data[1]
                            if hasattr(file_obj, 'close'):
                                opened_files.append(file_obj)
                        
                        # multiple files (list of tuples)
                        elif isinstance(file_data, list):
                            for file_tuple in file_data:
                                if isinstance(file_tuple, tuple) and len(file_tuple) >= 2:
                                    file_obj = file_tuple[1]
                                    if hasattr(file_obj, 'close'):
                                        opened_files.append(file_obj)

            # Execute the request
            response = requests.request(method, url, **kwargs)
            
            # Check for errors - respect raise_on_error config (fresh read)
            if parsed_config.get('raise_on_error', False):
                response.raise_for_status()
            
            # Parse response
            return cls._parse_response(response)
            
        except requests.exceptions.RequestException as e:
            if parsed_config.get('raise_on_error', False):
                raise APIError(f"Request failed: {str(e)}")
            else:
                print(f"Request failed: {str(e)}")
                return None
        finally:
            # close file handles
            for file_obj in opened_files:
                try:
                    file_obj.close()
                except:
                    pass

    # # TODO: Fix this method
    @classmethod
    def _parse_response(cls, response: requests.Response) -> Any:
        """Parse response data"""
        if not response.text or response.text.strip() == "":
            if response.status_code >= 400:
                return {"_status_code": response.status_code, "_error": True}
            return None
        
        try:
            data = response.json()
            # attach status code to dict responses for error handling downstream
            if isinstance(data, dict):
                data["_status_code"] = response.status_code
                if response.status_code >= 400:
                    data["_error"] = True
            return data
        except (ValueError, requests.exceptions.JSONDecodeError):
            return response.text if response.text else None
    
    @classmethod
    def _handle_request_body(cls, body, files, body_config):
        return RequestBodyHandler.handle(body, files, body_config)

class RequestBodyHandler:
    """Handles different types of request bodies (json, form-data, urlencoded, raw, etc.)"""
    # TODO : Add handeling GraphQL , etc 
    @staticmethod
    def handle(
        body: Any | None,
        files: dict | None,
        body_config: dict | None
    ) -> tuple[dict, dict | None]:
        """
        Main entry point - returns (kwargs_update, prepared_files)
        """
        if not body_config:
            # Backward compatibility mode
            if files:
                prepared = FileProcessor.prepare_files(files)
                return {'files': prepared, 'data': body} if body else {'files': prepared}, None
            if body is not None:
                if isinstance(body, (dict, list)):
                    return {'json': body}, None
                return {'data': body}, None
            return {}, None

        body_type = body_config.get('type', 'json')

        if body_type == 'json':
            return RequestBodyHandler._handle_json_body(body)
        elif body_type == 'form_data':
            return RequestBodyHandler._handle_form_data_body(body, files, body_config)
        elif body_type == 'urlencoded':
            return RequestBodyHandler._handle_urlencoded_body(body, body_config)
        elif body_type == 'raw':
            return RequestBodyHandler._handle_raw_body(body, body_config)
        elif body_type == 'none':
            return {}, None
        else:
            raise ValueError(f"Unknown body type: {body_type}")

    @staticmethod
    def _handle_json_body(body: Any) -> tuple[dict, None]:
        if body is None:
            return {}, None
        if isinstance(body, (dict, list)):
            return {'json': body}, None
        raise ValueError("JSON body must be dict or list")

    @classmethod
    def _handle_form_data_body(
        cls, 
        body: dict | None, 
        files: dict | None, 
        body_config: dict
    ) -> tuple[dict, None]:
        """Handle multipart/form-data body"""
        fields_config = body_config.get('fields', {})
        
        prepared_files = []
        form_data = {}
        
        # Loop through configured fields
        for field_name, field_config in fields_config.items():
            field_type = field_config.get('field_type', 'text')
            is_required = field_config.get('required', False)
            
            if field_type == 'file':
                # Look in files dict
                if files and field_name in files:
                    file_value = files[field_name]
                    prepared_file = FileProcessor.process_file_field(
                        field_name, file_value, field_config
                    )
                    if isinstance(prepared_file, list):
                        for file_tuple in prepared_file:
                            prepared_files.append((field_name, file_tuple))
                    else:
                        prepared_files.append((field_name, prepared_file))
                elif is_required:
                    raise ValueError(f"Required file field '{field_name}' is missing")
            
            else:  # text field
                # Look in body dict
                if body and field_name in body:
                    text_value = body[field_name]
                    processed_text = cls._process_text_field(
                        field_name, text_value, field_config
                    )

                    content_type = field_config.get('content_type') 
                    if content_type:
                        # For text fields, use field_name as filename
                        prepared_files.append((field_name, (field_name, processed_text, content_type)))
                    else:
                        form_data[field_name] = processed_text

                elif is_required:
                    raise ValueError(f"Required text field '{field_name}' is missing")
        
        # Return both files and data for multipart
        return {'files': prepared_files, 'data': form_data}, None

    @classmethod
    def _handle_urlencoded_body(cls, body: dict | None, body_config: dict) -> tuple[dict, None]:
        """Handle application/x-www-form-urlencoded body"""
        # Similar to form_data but only text fields, no files
        # TODO: Implement validation
        if body is None:
            return {}, None
        return {'data': body}, None

    @classmethod
    def _handle_raw_body(cls, body: Any, body_config: dict) -> tuple[dict, None]:
        """Handle raw body (XML, CSV, plain text, etc.)"""
        if body is None:
            return {}, None
        return {'data': body}, None
    
    @classmethod
    def _process_text_field(
        cls,
        field_name: str,
        text_value: Any,
        field_config: dict
    ) -> str:
        """Process a text field"""
        content_type = field_config.get('content_type')
        
        if content_type == 'application/json' and isinstance(text_value, dict):
            return json.dumps(text_value)
        
        return str(text_value)

class FileProcessor:
    """Handles file validation, preparation and conversion to requests-compatible format"""

    DEFAULT_MIME = 'application/octet-stream'
    EXT_MAP = {
        '.pdf': 'application/pdf',
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.png': 'image/png',
        '.txt': 'text/plain',
        '.json': 'application/json'
    }

    @staticmethod
    def prepare_files(files: dict) -> dict:
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
                    FileProcessor.get_content_type(file_path)
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

    @staticmethod
    def get_content_type(file_path: Path) -> str:
        """Get content type from file extension"""
        ext = file_path.suffix.lower()
        return FileProcessor.EXT_MAP.get(ext, FileProcessor.DEFAULT_MIME)

    @staticmethod
    def process_file_field(
        field_name: str,
        file_value: Any,
        field_config: dict
    ) -> Any:
        """
        Process a file field with validation
        
        Handles:
        - Single file: str path, file object, bytes, tuple
        - Multiple files: list of above
        """
        is_multiple = field_config.get('multiple', False)
        allowed_extensions = field_config.get('allowed_extensions', [])
        max_file_size = field_config.get('max_file_size')
        content_type = field_config.get('content_type')
        
        # Handle multiple files
        if is_multiple:
            if not isinstance(file_value, list):
                file_value = [file_value]
            
            processed = []
            for file_item in file_value:
                processed_item = FileProcessor.process_single_file(
                    field_name, file_item, allowed_extensions, max_file_size, content_type
                )
                processed.append(processed_item)
            return processed
        
        # Handle single file
        return FileProcessor.process_single_file(
            field_name, file_value, allowed_extensions, max_file_size, content_type
        )

    @staticmethod
    def process_single_file(
        field_name: str,
        file_value: Any,
        allowed_extensions: list,
        max_file_size: int | None,
        content_type: str | None = None,                          # ← ADD PARAM
    ) -> tuple:
        # Case 1: Already a tuple — trust it as-is
        if isinstance(file_value, tuple):
            return file_value

        # Case 2: File path (string)
        if isinstance(file_value, str):
            file_path = Path(file_value)
            if not file_path.exists():
                raise FileNotFoundError(f"File not found: {file_value}")
            if allowed_extensions and file_path.suffix.lower() not in allowed_extensions:
                raise ValueError(
                    f"File '{file_path.name}' has invalid extension. "
                    f"Allowed: {', '.join(allowed_extensions)}"
                )
            if max_file_size:
                file_size = file_path.stat().st_size
                if file_size > max_file_size:
                    raise ValueError(
                        f"File '{file_path.name}' exceeds max size "
                        f"({file_size} > {max_file_size} bytes)"
                    )
            resolved_ct = content_type or FileProcessor.get_content_type(file_path)  # ← USE IT
            file_obj = open(file_path, 'rb')
            return (file_path.name, file_obj, resolved_ct)

        # Case 3: File-like object
        if hasattr(file_value, 'read'):
            filename = getattr(file_value, 'name', field_name)
            resolved_ct = content_type or 'application/octet-stream'                  # ← USE IT
            return (filename, file_value, resolved_ct)

        # Case 4: Bytes
        if isinstance(file_value, bytes):
            resolved_ct = content_type or 'application/octet-stream'                  # ← USE IT
            return (field_name, file_value, resolved_ct)

        raise ValueError(f"Invalid file data for field '{field_name}'")
