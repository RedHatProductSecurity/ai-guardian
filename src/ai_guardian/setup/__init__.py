#!/usr/bin/env python3
"""
Setup Command for ai-guardian

Thin orchestrator that delegates to focused setup modules.
All symbols are re-exported for backward compatibility.
"""

import contextlib
import io
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from ai_guardian.config.utils import get_cache_dir, get_config_dir

# --- Canonical imports used by orchestrator functions ---

from ai_guardian.setup.utils import (
    _notify_daemon_reload,
    _resolve_binary_path,
    _strip_deprecated_config_keys,
)
from ai_guardian.setup.config import (
    create_default_config,
    _get_default_config_template,
)
from ai_guardian.setup.hooks import (
    IDESetup,
    _auto_install_hook,
    install_precommit_hooks,
    uninstall_precommit_hooks,
)
from ai_guardian.setup.mcp import (
    _MCP_IDE_CONFIGS,
    _MCP_SERVER_ENTRY,
    _handle_mcp_setup,
    _install_mcp_config,
    _remove_mcp_config,
)
from ai_guardian.setup.rules import (
    _RULES_IDE_CONFIGS,
    _RULES_FILE_CONTENT,
    _handle_rules_setup,
)

# --- Re-exports for backward compatibility ---
# These symbols are imported by tests and other modules via
# ``from ai_guardian.setup import X``.

from ai_guardian.setup.utils import (  # noqa: F811,F401
    _create_vbs_wrapper,
    _is_ai_guardian_command,
    _strip_jsonc_comments,
    _substitute_command,
    _upgrade_ide_flag,
    _walk_commands,
)
from ai_guardian.setup.hooks import (  # noqa: F811,F401
    _AIDERDESK_EXTENSION_TS,
    _AIDERDESK_PACKAGE_JSON,
    _OPENCODE_PLUGIN_TS,
    _OPENCLAW_PACKAGE_JSON,
    _OPENCLAW_PLUGIN_TS,
)


def setup_hooks(
    ide_type: Optional[str] = None,
    remote_config_url: Optional[str] = None,
    dry_run: bool = False,
    force: bool = False,
    interactive: bool = True,
    migrate_pattern_server: bool = False,
    create_config: bool = False,
    permissive: bool = False,
    pre_commit: bool = False,
    log_violations: bool = False,
    auto_install_hooks: bool = False,
    uninstall_hooks: bool = False,
    install_scanner: Optional[List[str]] = None,
    use_pinned: bool = False,
    json_output: bool = False,
    profile: Optional[str] = None,
    save_profile: Optional[str] = None,
    list_profiles: bool = False,
    no_mcp: Optional[bool] = None,
    rules: Optional[bool] = None,
) -> bool:
    """
    Setup IDE hooks with optional remote config and default config creation.

    Args:
        ide_type: IDE type ('claude' or 'cursor') or None for auto-detect
        remote_config_url: Optional remote config URL to add
        dry_run: If True, show what would be changed without applying
        force: If True, overwrite existing hooks
        interactive: If True, prompt user for confirmation
        migrate_pattern_server: If True, check and migrate old pattern_server config
        create_config: If True, create default ai-guardian.json config
        permissive: If True with create_config, use permissive config (permissions disabled)
        pre_commit: If True, install pre-commit hooks for git
        log_violations: If True, include --log-violations in pre-commit scan command
        auto_install_hooks: If True, allow automatic hook installation (default: False for safety)
        uninstall_hooks: If True, remove AI Guardian pre-commit hooks
        install_scanner: Optional list of scanner names to install (gitleaks, betterleaks, or leaktk)
        json_output: If True, output only clean JSON (suppresses all log text)
        profile: Optional security profile to apply (use with create_config)
        save_profile: Optional name to save current config as a custom profile
        list_profiles: If True, list available security profiles
        no_mcp: If True, skip MCP server installation (MCP is installed by default)

    Returns:
        bool: True if successful, False otherwise
    """
    # JSON output mode: clean JSON only, no log text (Issue #518)
    if json_output and not list_profiles and not save_profile:
        return _setup_hooks_json_output(
            ide_type=ide_type,
            dry_run=dry_run,
            force=force,
            create_config=create_config,
            permissive=permissive,
            profile=profile,
            no_mcp=no_mcp,
            rules=rules,
        )

    setup = IDESetup()

    # Handle profile listing if requested
    if list_profiles:
        from ai_guardian.profile_manager import format_profile_list

        print(format_profile_list())
        return True

    # Handle saving current config as a profile
    if save_profile:
        from ai_guardian.profile_manager import save_profile as _save_profile

        config_dir = get_config_dir()
        config_path = config_dir / "ai-guardian.json"
        if not config_path.exists():
            print(
                "Error: No config file found. Create one first with --create-config",
                file=sys.stderr,
            )
            return False
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
        except json.JSONDecodeError as e:
            print(f"Error: Invalid JSON in {config_path}: {e}", file=sys.stderr)
            return False
        success, message = _save_profile(save_profile, config)
        print(message)
        return success

    # Validate --profile usage
    if profile and not create_config:
        print("Error: --profile requires --create-config", file=sys.stderr)
        print(
            "Usage: ai-guardian setup --create-config --profile @strict",
            file=sys.stderr,
        )
        return False

    if profile and permissive:
        print(
            "Warning: --profile overrides --permissive, ignoring --permissive",
            file=sys.stderr,
        )

    # Handle scanner installation if requested (NEW in v1.6.0)
    if install_scanner:
        if dry_run:
            if use_pinned:
                print(
                    f"[DRY RUN] Would install pinned scanner(s): {', '.join(install_scanner)}"
                )
            else:
                print(
                    f"[DRY RUN] Would install scanner(s): {', '.join(install_scanner)}"
                )
        else:
            try:
                from ai_guardian.scanners.installer import ScannerInstaller

                installer = ScannerInstaller()

                for scanner_name in install_scanner:
                    print(f"\n🛡️  Installing {scanner_name} scanner...\n")

                    success = installer.install(
                        scanner_name,
                        use_pinned=use_pinned,
                        ensure_only=not use_pinned,
                    )

                    if success:
                        if installer.verify_installation(scanner_name):
                            print(f"\n✓ {scanner_name} is ready to use\n")
                        else:
                            print(
                                f"\n⚠  Installation completed but {scanner_name} verification failed"
                            )
                            print("Make sure ~/.local/bin is in your PATH\n")
                            if interactive:
                                response = input(
                                    "Continue with IDE setup anyway? (y/n): "
                                )
                                if response.lower() != "y":
                                    return False
                    else:
                        print(f"\n✗ Failed to install {scanner_name}\n")
                        if interactive:
                            response = input("Continue with IDE setup anyway? (y/n): ")
                            if response.lower() != "y":
                                return False

            except Exception as e:
                print(f"Error installing scanner: {e}")
                if interactive:
                    response = input("Continue with IDE setup anyway? (y/n): ")
                    if response.lower() != "y":
                        return False

    # Handle pre-commit hook uninstallation if requested
    if pre_commit and uninstall_hooks:
        success, message = uninstall_precommit_hooks(
            dry_run=dry_run, interactive=interactive
        )
        print(message)
        return success

    # Handle pre-commit hook installation if requested
    if pre_commit:
        success, message = install_precommit_hooks(
            dry_run=dry_run,
            interactive=interactive,
            allow_auto_install=auto_install_hooks,
            log_violations=log_violations,
            force=force,
        )
        print(message)
        if not success:
            return False
        # If only installing pre-commit (no IDE setup or config), return early
        if (
            ide_type is None
            and not remote_config_url
            and not migrate_pattern_server
            and not create_config
        ):
            return success

    # Handle default config creation if requested
    if create_config:
        config_success, message = create_default_config(
            permissive=permissive,
            dry_run=dry_run,
            json_output=False,
            profile=profile,
            force=force,
        )
        print(message)
        if not config_success:
            return False
        else:
            # If only creating config (no IDE setup or remote config), return early
            if (
                ide_type is None
                and not remote_config_url
                and not migrate_pattern_server
                and not no_mcp
            ):
                if config_success:
                    _notify_daemon_reload()
                return config_success

    # Handle pattern_server migration if requested
    if migrate_pattern_server:
        success, message = setup.check_and_migrate_pattern_server(
            dry_run=dry_run, interactive=interactive
        )
        print(message)
        if not success and not message.endswith("cancelled"):
            return False
        # If only migrating (no IDE setup or remote config), return early
        if ide_type is None and not remote_config_url:
            return success

    # Handle remote config setup if requested
    if remote_config_url:
        success, message = setup.setup_remote_config(remote_config_url, dry_run=dry_run)
        print(message)
        if not success:
            return False
        # If only setting up remote config (no IDE setup), return early
        if ide_type is None and not migrate_pattern_server:
            return success

    # Auto-detect IDE if not specified
    if not ide_type:
        detected_ides = setup.list_detected_ides()

        if not detected_ides:
            print(
                "Error: No IDE detected. Please install Claude Code or Cursor IDE.",
                file=sys.stderr,
            )
            print("\nSupported IDEs:", file=sys.stderr)
            print("  - Claude Code: https://claude.ai/code", file=sys.stderr)
            print("  - Cursor: https://cursor.sh", file=sys.stderr)
            return False

        elif len(detected_ides) == 1:
            ide_type = detected_ides[0]
            print(f"Detected IDE: {setup.IDE_CONFIGS[ide_type]['name']}")

        else:
            # Multiple IDEs detected
            print("Multiple IDEs detected:")
            for i, ide in enumerate(detected_ides, 1):
                print(f"  {i}. {setup.IDE_CONFIGS[ide]['name']}")

            if interactive and not dry_run:
                try:
                    choice = input("\nSelect IDE (1-{}): ".format(len(detected_ides)))
                    idx = int(choice) - 1
                    if 0 <= idx < len(detected_ides):
                        ide_type = detected_ides[idx]
                    else:
                        print("Error: Invalid selection", file=sys.stderr)
                        return False
                except (ValueError, KeyboardInterrupt):
                    print("\nError: Invalid input", file=sys.stderr)
                    return False
            else:
                print(
                    "\nError: Multiple IDEs detected. Please specify with --ide flag.",
                    file=sys.stderr,
                )
                return False

    # Validate IDE type
    if ide_type not in setup.IDE_CONFIGS:
        print(f"Error: Unknown IDE type: {ide_type}", file=sys.stderr)
        print(f"Supported IDEs: {', '.join(setup.IDE_CONFIGS.keys())}", file=sys.stderr)
        return False

    # Confirm with user if interactive
    if interactive and not dry_run and not force:
        ide_name = setup.IDE_CONFIGS[ide_type]["name"]
        config_path = setup.get_config_path(ide_type)

        print(f"\nThis will configure ai-guardian hooks for {ide_name}")
        print(f"Config file: {config_path}")

        try:
            response = input("\nContinue? [y/N]: ")
            if response.lower() not in ["y", "yes"]:
                print("Aborted.")
                return False
        except KeyboardInterrupt:
            print("\nAborted.")
            return False

    # Setup IDE hooks
    success, message = setup.setup_ide_hooks(ide_type, dry_run=dry_run, force=force)
    print(message)

    # MCP server always installed by default (Issue #477, #808, #1377)
    if success:
        if no_mcp:
            _handle_mcp_setup(setup, ide_type, no_mcp=True, dry_run=dry_run)
        else:
            _handle_mcp_setup(setup, ide_type, dry_run=dry_run)

    # Handle rules/guidelines file installation (Issue #637)
    if success and rules:
        _handle_rules_setup(ide_type, dry_run=dry_run, force=force)

    if success and not dry_run:
        _notify_daemon_reload()

    return success


def _setup_hooks_json_output(
    ide_type: Optional[str] = None,
    dry_run: bool = False,
    force: bool = False,
    create_config: bool = False,
    permissive: bool = False,
    profile: Optional[str] = None,
    no_mcp: Optional[bool] = None,
    rules: Optional[bool] = None,
) -> bool:
    """Run setup and output results as clean JSON with no log text (Issue #518)."""
    setup = IDESetup()
    result: Dict[str, Any] = {"success": True, "dry_run": dry_run}

    # Handle ai-guardian config creation
    if create_config:
        if profile:
            from ai_guardian.profile_manager import load_profile, ProfileNotFoundError

            try:
                ag_config = load_profile(profile)
            except (ProfileNotFoundError, json.JSONDecodeError) as e:
                print(json.dumps({"success": False, "error": str(e)}, indent=2))
                return False
        else:
            ag_config = _get_default_config_template(permissive)

        ag_config = _strip_deprecated_config_keys(ag_config)
        result["ai_guardian_config"] = ag_config

        if not dry_run:
            config_dir = get_config_dir()
            config_path = config_dir / "ai-guardian.json"
            if config_path.exists() and not force:
                result["config_preserved"] = True
                result["config_path"] = str(config_path)
            else:
                config_dir.mkdir(parents=True, exist_ok=True)
                with open(config_path, "w", encoding="utf-8") as f:
                    json.dump(ag_config, f, indent=2)
                    f.write("\n")
            get_cache_dir().mkdir(parents=True, exist_ok=True)

    # Auto-detect IDE if not specified
    if ide_type is None:
        detected_ides = setup.list_detected_ides()
        if not detected_ides:
            if create_config:
                print(json.dumps(result, indent=2))
                return True
            print(
                json.dumps(
                    {
                        "success": False,
                        "error": "No IDE detected. Specify --ide flag.",
                    },
                    indent=2,
                )
            )
            return False
        elif len(detected_ides) == 1:
            ide_type = detected_ides[0]
        else:
            if create_config:
                print(json.dumps(result, indent=2))
                return True
            print(
                json.dumps(
                    {
                        "success": False,
                        "error": (
                            f"Multiple IDEs detected: {', '.join(detected_ides)}. "
                            "Specify --ide flag."
                        ),
                    },
                    indent=2,
                )
            )
            return False

    if ide_type not in setup.IDE_CONFIGS:
        print(
            json.dumps(
                {
                    "success": False,
                    "error": f"Unknown IDE type: {ide_type}",
                },
                indent=2,
            )
        )
        return False

    result["ide"] = ide_type
    result["config_path"] = str(Path(setup.get_config_path(ide_type)).expanduser())

    # Run IDE hook setup with all print output suppressed
    _devnull = io.StringIO()
    with contextlib.redirect_stdout(_devnull), contextlib.redirect_stderr(_devnull):
        success, message = setup.setup_ide_hooks(
            ide_type,
            dry_run=dry_run,
            force=force,
        )

    result["success"] = success
    if success and setup._last_merged_config is not None:
        result["hooks"] = setup._last_merged_config
    elif not success:
        result["error"] = message

    # MCP server always installed by default (Issue #477, #808, #1377)
    if success:
        with contextlib.redirect_stdout(_devnull), contextlib.redirect_stderr(_devnull):
            if no_mcp:
                _handle_mcp_setup(setup, ide_type, no_mcp=True, dry_run=dry_run)
            else:
                _handle_mcp_setup(setup, ide_type, dry_run=dry_run)

    # Always include MCP server config in JSON output (unless --no-mcp)
    if success and not no_mcp:
        mcp_ide = _MCP_IDE_CONFIGS.get(ide_type, {})
        mcp_path = mcp_ide.get("config_file", "")
        result["mcp_config_path"] = (
            str(Path(mcp_path).expanduser()) if mcp_path else None
        )
        abs_path = _resolve_binary_path()
        mcp_entry = dict(_MCP_SERVER_ENTRY)
        mcp_entry["command"] = abs_path
        result["mcp_servers"] = {"ai-guardian": mcp_entry}

    # Handle rules/guidelines file setup (Issue #637)
    if success and rules:
        with contextlib.redirect_stdout(_devnull), contextlib.redirect_stderr(_devnull):
            _handle_rules_setup(ide_type, dry_run=dry_run, force=force)
        rules_config = _RULES_IDE_CONFIGS.get(ide_type)
        if rules_config:
            result["rules_path"] = str(
                Path(rules_config["rules_dir"]) / rules_config["rules_file"]
            )

    print(json.dumps(result, indent=2))
    return result.get("success", False)
