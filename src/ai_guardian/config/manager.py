#!/usr/bin/env python3
"""
Configuration Manager for ai-guardian

Manages installation config, user config, and project config files.
"""

from pathlib import Path
from typing import Dict, List, Optional, Tuple

from ai_guardian.config.utils import get_config_dir

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore

import tomli_w


class ConfigManager:
    """
    Manage ai-guardian configuration files.

    Handles:
    - Installation config (~/.config/ai-guardian/config.toml)
    - User global config (~/.config/ai-guardian/allowed-tools.toml)
    - Project local config (./.allowed-tools.toml)
    """

    def __init__(self):
        """Initialize configuration manager."""
        # get_config_dir() applies the full priority order, including the
        # AI_GUARDIAN_HOME compatibility alias.
        self.config_dir = get_config_dir()
        self.installation_config_path = self.config_dir / "config.toml"
        self.user_config_path = self.config_dir / "allowed-tools.toml"
        self.project_config_path = Path.cwd() / ".allowed-tools.toml"

    def get_installation_config_path(self) -> Path:
        """Get installation config file path."""
        return self.installation_config_path

    def set_installation_url(self, url: str) -> bool:
        """
        Set or remove the installation remote URL.

        Args:
            url: Remote URL to set, or 'none' to remove

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Ensure config directory exists
            self.config_dir.mkdir(parents=True, exist_ok=True)

            if url.lower() == "none":
                # Remove installation config
                if self.installation_config_path.exists():
                    self.installation_config_path.unlink()
                return True

            # Create or update installation config
            config = {"url": url}

            with open(self.installation_config_path, "wb") as f:
                tomli_w.dump(config, f)

            return True

        except Exception as e:
            import sys

            print(f"Error setting installation URL: {e}", file=sys.stderr)
            return False

    def get_installation_url(self) -> Optional[str]:
        """
        Get the installation remote URL.

        Returns:
            str or None: Remote URL or None if not configured
        """
        if not self.installation_config_path.exists():
            return None

        try:
            with open(self.installation_config_path, "rb") as f:
                config = tomllib.load(f)
            return config.get("url")
        except Exception:
            return None

    def show_configuration(self) -> Dict:
        """
        Get current configuration summary.

        Returns:
            dict: Configuration information
        """
        from ai_guardian.tools.policy import ToolPolicyChecker

        # Load installation config
        installation_url = self.get_installation_url()

        # Load user config
        user_config = None
        user_remote_urls = []
        if self.user_config_path.exists():
            user_config = self._load_toml(self.user_config_path)
            if user_config and "remote_configs" in user_config:
                user_remote_urls = user_config["remote_configs"]

        # Load project config
        project_config = None
        project_remote_urls = []
        if self.project_config_path.exists():
            project_config = self._load_toml(self.project_config_path)
            if project_config and "remote_configs" in project_config:
                project_remote_urls = project_config["remote_configs"]

        # Load merged policy
        policy_checker = ToolPolicyChecker()
        merged_policy = policy_checker.config

        return {
            "installation_config_path": str(self.installation_config_path),
            "installation_url": installation_url,
            "user_config_path": str(self.user_config_path),
            "user_config_exists": self.user_config_path.exists(),
            "user_remote_urls": user_remote_urls,
            "project_config_path": str(self.project_config_path),
            "project_config_exists": self.project_config_path.exists(),
            "project_remote_urls": project_remote_urls,
            "merged_policy": merged_policy,
        }

    def validate_configuration(self) -> Tuple[bool, List[str]]:
        """
        Validate current configuration.

        Returns:
            tuple: (is_valid: bool, errors: List[str])
        """
        errors = []

        # Check user config syntax
        if self.user_config_path.exists():
            config = self._load_toml(self.user_config_path)
            if config is None:
                errors.append(f"Invalid TOML syntax in {self.user_config_path}")
            else:
                errors.extend(self._validate_config_structure(config, "user"))

        # Check project config syntax
        if self.project_config_path.exists():
            config = self._load_toml(self.project_config_path)
            if config is None:
                errors.append(f"Invalid TOML syntax in {self.project_config_path}")
            else:
                errors.extend(self._validate_config_structure(config, "project"))

        # Check installation config syntax
        if self.installation_config_path.exists():
            config = self._load_toml(self.installation_config_path)
            if config is None:
                errors.append(f"Invalid TOML syntax in {self.installation_config_path}")

        return len(errors) == 0, errors

    def _validate_config_structure(self, config: Dict, source: str) -> List[str]:
        """
        Validate configuration structure.

        Args:
            config: Configuration dict
            source: Source name for error messages

        Returns:
            list: List of error messages
        """
        errors = []

        # Check for valid keys
        valid_keys = {
            "remote_configs",
            "builtin_deny_patterns",
            "skill_allowed_patterns",
            "skill_deny_patterns",
            "mcp_allowed_patterns",
            "mcp_deny_patterns",
        }

        for key in config.keys():
            if key not in valid_keys:
                errors.append(f"{source} config: unknown key '{key}'")

        # Check pattern types
        pattern_keys = [
            "builtin_deny_patterns",
            "skill_allowed_patterns",
            "skill_deny_patterns",
            "mcp_allowed_patterns",
            "mcp_deny_patterns",
        ]

        for key in pattern_keys:
            if key in config:
                if not isinstance(config[key], list):
                    errors.append(f"{source} config: '{key}' must be a list")
                else:
                    for pattern in config[key]:
                        if not isinstance(pattern, str):
                            errors.append(
                                f"{source} config: '{key}' must contain strings"
                            )

        # Check remote_configs type
        if "remote_configs" in config:
            if not isinstance(config["remote_configs"], list):
                errors.append(f"{source} config: 'remote_configs' must be a list")
            else:
                for url in config["remote_configs"]:
                    if not isinstance(url, str):
                        errors.append(
                            f"{source} config: 'remote_configs' must contain strings"
                        )

        return errors

    def _load_toml(self, path: Path) -> Optional[Dict]:
        """
        Load TOML file.

        Args:
            path: Path to TOML file

        Returns:
            dict or None: Parsed config or None if error
        """
        try:
            with open(path, "rb") as f:
                return tomllib.load(f)
        except Exception:
            return None
