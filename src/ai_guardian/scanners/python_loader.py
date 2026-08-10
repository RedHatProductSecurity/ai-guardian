"""
Python scanner loader for ai-guardian.

Loads Scanner subclasses from multiple registration sources:
- Python module path (dotted import path + class name)
- File path (absolute/relative .py file + class name)
- Entry points (pip packages registering ai_guardian.scanners)
- Scanner directory (~/.config/ai-guardian/scanners/)
"""

import importlib
import importlib.metadata
import importlib.util
import logging
import sys
from pathlib import Path
from typing import Any, Dict, Type

from ai_guardian.scanners.sdk import Scanner

logger = logging.getLogger(__name__)


def _validate_path(path_str: str) -> None:
    """Validate a file path for security (no path traversal)."""
    if ".." in Path(path_str).parts:
        raise ValueError(f"Path traversal detected in scanner path: {path_str}")


def _validate_scanner_class(cls: Any, source: str) -> Type[Scanner]:
    """Validate that a loaded class is a Scanner subclass."""
    if not isinstance(cls, type) or not issubclass(cls, Scanner):
        raise TypeError(f"Loaded class {cls} from {source} is not a Scanner subclass")
    if cls is Scanner:
        raise TypeError(f"Cannot use Scanner base class directly from {source}")
    return cls


def load_from_module(module_path: str, class_name: str) -> Type[Scanner]:
    """Load a Scanner subclass from a dotted module path.

    Args:
        module_path: Dotted Python module path (e.g., "my_company.scanners.api_checker")
        class_name: Name of the Scanner subclass in the module

    Returns:
        Scanner subclass (not instantiated)

    Raises:
        ImportError: If the module cannot be imported
        AttributeError: If the class is not found in the module
        TypeError: If the class is not a Scanner subclass
    """
    _validate_path(module_path.replace(".", "/"))
    module = importlib.import_module(module_path)
    cls = getattr(module, class_name)
    return _validate_scanner_class(cls, f"module {module_path}")


def _load_module_from_file(file_path: Path, module_prefix: str):
    """Load a Python module from a file path."""
    module_name = f"{module_prefix}{file_path.stem}"
    spec = importlib.util.spec_from_file_location(module_name, str(file_path))
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module from {file_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def load_from_file(file_path: str, class_name: str) -> Type[Scanner]:
    """Load a Scanner subclass from a Python file.

    Args:
        file_path: Path to a .py file containing the scanner
        class_name: Name of the Scanner subclass in the file

    Returns:
        Scanner subclass (not instantiated)

    Raises:
        FileNotFoundError: If the file does not exist
        ValueError: If path traversal is detected
        TypeError: If the class is not a Scanner subclass
    """
    _validate_path(file_path)
    resolved = Path(file_path).expanduser().resolve()

    if not resolved.exists():
        raise FileNotFoundError(f"Scanner file not found: {resolved}")
    if not resolved.suffix == ".py":
        raise ValueError(f"Scanner file must be a .py file: {resolved}")

    module = _load_module_from_file(resolved, "_ai_guardian_custom_")
    cls = getattr(module, class_name)
    return _validate_scanner_class(cls, f"file {resolved}")


def discover_entry_points() -> Dict[str, Type[Scanner]]:
    """Discover scanners registered via pip entry points.

    Looks for entry points in the "ai_guardian.scanners" group.

    Returns:
        Dict mapping entry point name to Scanner subclass
    """
    discovered = {}
    try:
        if sys.version_info >= (3, 12):
            eps = importlib.metadata.entry_points(group="ai_guardian.scanners")
        else:
            eps = importlib.metadata.entry_points().get("ai_guardian.scanners", [])
    except Exception as e:
        logger.warning(f"Failed to discover scanner entry points: {e}")
        return discovered

    for ep in eps:
        try:
            cls = ep.load()
            _validate_scanner_class(cls, f"entry point {ep.name}")
            discovered[ep.name] = cls
            logger.info(f"Discovered scanner entry point: {ep.name} -> {cls.__name__}")
        except Exception as e:
            logger.warning(f"Failed to load scanner entry point {ep.name}: {e}")

    return discovered


def discover_scanner_directory() -> Dict[str, Type[Scanner]]:
    """Auto-discover scanners from the scanner directory.

    Scans ~/.config/ai-guardian/scanners/ (or XDG equivalent) for .py files
    containing Scanner subclasses.

    Security: Scanner files execute arbitrary Python at import time. Only place
    trusted scanner files in this directory. The directory is operator-controlled
    (~/.config/ai-guardian/scanners/) and requires local filesystem write access.

    Returns:
        Dict mapping scanner name to Scanner subclass
    """
    from ai_guardian.config.utils import get_config_dir

    scanner_dir = get_config_dir() / "scanners"
    if not scanner_dir.is_dir():
        return {}

    discovered = {}
    for py_file in sorted(scanner_dir.glob("*.py")):
        if py_file.name.startswith("_"):
            continue
        try:
            module = _load_module_from_file(py_file, "_ai_guardian_scanner_dir_")

            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (
                    isinstance(attr, type)
                    and issubclass(attr, Scanner)
                    and attr is not Scanner
                ):
                    discovered[attr.name] = attr
                    logger.info(
                        f"Discovered scanner from directory: "
                        f"{attr.name} ({py_file.name}::{attr_name})"
                    )
        except Exception as e:
            logger.warning(f"Failed to load scanner from {py_file}: {e}")

    return discovered


def load_python_scanner(engine_spec: Dict[str, Any]) -> Scanner:
    """Load and instantiate a Python scanner from an engine specification.

    Dispatches based on config dict keys:
    - "module" + "class": load from Python module
    - "path" + "class": load from file path
    - Neither: look up entry point by engine name

    Args:
        engine_spec: Engine configuration dict with type="python"

    Returns:
        Instantiated Scanner object

    Raises:
        ValueError: If the spec is invalid or scanner cannot be loaded
    """
    module_path = engine_spec.get("module")
    file_path = engine_spec.get("path")
    class_name = engine_spec.get("class")
    scanner_config = engine_spec.get("scanner_config", {})

    if module_path and class_name:
        logger.debug(f"Loading Python scanner from module: {module_path}::{class_name}")
        cls = load_from_module(module_path, class_name)
    elif file_path and class_name:
        logger.debug(f"Loading Python scanner from file: {file_path}::{class_name}")
        cls = load_from_file(file_path, class_name)
    else:
        raise ValueError(
            "Python scanner spec must include either "
            "'module' + 'class' or 'path' + 'class'. "
            f"Got: {engine_spec}"
        )

    instance = cls()
    if scanner_config:
        instance.configure(scanner_config)
    logger.info(
        f"Loaded Python scanner: name={instance.name} version={instance.version}"
    )
    return instance
