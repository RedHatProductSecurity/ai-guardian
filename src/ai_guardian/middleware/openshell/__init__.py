"""Version-selected NVIDIA OpenShell supervisor-middleware adapters."""

from .registry import (
    OpenShellAdapterSpec,
    OpenShellCompatibilityError,
    OpenShellVersion,
    select_adapter,
)

__all__ = [
    "OpenShellAdapterSpec",
    "OpenShellCompatibilityError",
    "OpenShellVersion",
    "select_adapter",
]
