"""External service adapters."""

from backend.app.integrations.identity import (
    ExternalIdentity,
    IdentityProvider,
    PlaceholderIdentityProvider,
)

__all__ = [
    "ExternalIdentity",
    "IdentityProvider",
    "PlaceholderIdentityProvider",
]
