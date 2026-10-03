"""Pipeline contracts. Importing this package starts no external services."""

from .contracts import StageMessage, StageContext, StageInput, ProviderIdentity

__all__ = ["StageMessage", "StageContext", "StageInput", "ProviderIdentity"]
