"""Stable facade for version-selected OpenShell middleware adapters."""

from __future__ import annotations

import sys

from .registry import OpenShellCompatibilityError, load_adapter
from .v0_1_2.server import (
    JwtAuthInterceptor,
    MiddlewareServerSecurity,
    MiddlewareService,
    create_server,
    require_grpc,
)


def run_middleware_server(args) -> int:
    """Dispatch startup to the adapter compatible with the OpenShell release."""

    # Lifecycle operations do not need protocol selection and should work even
    # when the OpenShell CLI is absent from a minimal service environment.
    if (
        getattr(args, "stop", False)
        or getattr(args, "status", False)
        or getattr(args, "middleware_command", None)
        in {"stop", "status", "pause", "resume"}
    ):
        from .v0_1_2.server import run_middleware_server as run_default

        return run_default(args)
    try:
        adapter, target, source, module = load_adapter(
            getattr(args, "openshell_version", None),
            config_path=getattr(args, "config", None),
        )
    except OpenShellCompatibilityError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(
        f"OpenShell middleware adapter {adapter.version} selected for release "
        f"{target} ({source})",
        file=sys.stderr,
    )
    return module.run_middleware_server(args)


__all__ = [
    "JwtAuthInterceptor",
    "MiddlewareServerSecurity",
    "MiddlewareService",
    "create_server",
    "require_grpc",
    "run_middleware_server",
]
