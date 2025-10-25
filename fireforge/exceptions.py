class APILibraryError(Exception):
    """Base exception for API library errors"""
    pass


class APIError(APILibraryError):
    """General API error"""
    
    def __init__(self, message: str, status_code: int = None):
        self.status_code = status_code
        super().__init__(message)


class AuthenticationError(APILibraryError):
    """Authentication-related errors"""
    pass


class ValidationError(APILibraryError):
    """Input validation errors"""
    pass


class RetryExhaustedError(APILibraryError):
    """Retry attempts exhausted"""
    pass


class ConfigurationError(APILibraryError):
    """Configuration-related errors"""
    pass
