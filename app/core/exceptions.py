"""Domain exceptions mapped to HTTP responses by the API layer.

Services and repositories raise these; the FastAPI exception handlers in
``app.main`` translate them to clean JSON without leaking internals.
"""
from __future__ import annotations


class TrustLensError(Exception):
    """Base for all domain errors. ``status_code`` drives the HTTP response."""

    status_code: int = 500
    code: str = "internal_error"

    def __init__(self, message: str | None = None, *, code: str | None = None):
        self.message = message or self.__class__.__doc__ or "Error"
        if code:
            self.code = code
        super().__init__(self.message)


class NotFoundError(TrustLensError):
    """Requested resource does not exist."""

    status_code = 404
    code = "not_found"


class ConflictError(TrustLensError):
    """Resource already exists or violates a uniqueness constraint."""

    status_code = 409
    code = "conflict"


class ValidationError(TrustLensError):
    """Input failed a business-rule validation."""

    status_code = 422
    code = "validation_error"


class AuthenticationError(TrustLensError):
    """Credentials are missing or invalid."""

    status_code = 401
    code = "authentication_error"


class AuthorizationError(TrustLensError):
    """Authenticated principal lacks permission for this action."""

    status_code = 403
    code = "authorization_error"


class StateTransitionError(TrustLensError):
    """Illegal application state transition."""

    status_code = 409
    code = "invalid_state_transition"


class StorageError(TrustLensError):
    """Object storage operation failed."""

    status_code = 502
    code = "storage_error"
