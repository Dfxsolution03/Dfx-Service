from typing import Any, Dict, List, Optional
from fastapi import status


class JROSException(Exception):
    """
    Base exception class for all JROS custom application exceptions.
    """
    def __init__(
        self,
        message: str = "An error occurred",
        code: str = "SERVER_ERROR",
        status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
        errors: Optional[List[Dict[str, Any]]] = None,
    ):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.errors = errors or [
            {
                "code": code,
                "message": message,
            }
        ]


class AppHTTPException(JROSException):
    """
    Generic HTTP exception with standard error code and status code.
    """
    pass


class ValidationException(JROSException):
    def __init__(self, message: str = "Validation failed", field: Optional[str] = None):
        errors = [
            {
                "code": "VALIDATION_ERROR",
                "message": message,
                **({"field": field} if field else {}),
            }
        ]
        super().__init__(
            message=message,
            code="VALIDATION_ERROR",
            status_code=status.HTTP_400_BAD_REQUEST,
            errors=errors,
        )


class UnauthorizedException(JROSException):
    def __init__(self, message: str = "Authentication required"):
        super().__init__(
            message=message,
            code="UNAUTHENTICATED",
            status_code=status.HTTP_401_UNAUTHORIZED,
        )


class ForbiddenException(JROSException):
    def __init__(self, message: str = "Permission denied"):
        super().__init__(
            message=message,
            code="FORBIDDEN",
            status_code=status.HTTP_403_FORBIDDEN,
        )


class ResourceNotFoundException(JROSException):
    def __init__(self, message: str = "Resource not found"):
        super().__init__(
            message=message,
            code="NOT_FOUND",
            status_code=status.HTTP_404_NOT_FOUND,
        )


class ConflictException(JROSException):
    def __init__(self, message: str = "Resource conflict occurred"):
        super().__init__(
            message=message,
            code="CONFLICT",
            status_code=status.HTTP_409_CONFLICT,
        )


class PaymentFailedException(JROSException):
    def __init__(self, message: str = "Payment processing failed"):
        super().__init__(
            message=message,
            code="PAYMENT_FAILED",
            status_code=status.HTTP_400_BAD_REQUEST,
        )


class PlanLimitExceededException(JROSException):
    def __init__(self, message: str = "Tenant plan limit exceeded"):
        super().__init__(
            message=message,
            code="PLAN_LIMIT_EXCEEDED",
            status_code=status.HTTP_403_FORBIDDEN,
        )
