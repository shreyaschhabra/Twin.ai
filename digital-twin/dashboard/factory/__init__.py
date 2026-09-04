"""Factory configuration for the dashboard.

Public API:

* :func:`ensure_factory` -- load the configured factory, generating a demo only when
  the configured path does not exist.
* :func:`load_factory` -- strict load + validate.
* :func:`factory_state` -- non-raising status used by the UI shell.
* :func:`validate_factory` / :func:`validate_factory_file` -- simulator-contract checks.
* :func:`generate_demo_factory` -- write one deterministic demo definition.
"""

from dashboard.factory.manager import (
    FactoryState,
    FactoryStatus,
    ensure_factory,
    factory_state,
    generate_demo_factory,
    is_demo_factory,
    load_factory,
    write_factory,
)
from dashboard.factory.validator import (
    FactoryValidation,
    is_valid_factory,
    validate_factory,
    validate_factory_file,
)

__all__ = [
    "FactoryState",
    "FactoryStatus",
    "FactoryValidation",
    "ensure_factory",
    "factory_state",
    "generate_demo_factory",
    "is_demo_factory",
    "is_valid_factory",
    "load_factory",
    "validate_factory",
    "validate_factory_file",
    "write_factory",
]
