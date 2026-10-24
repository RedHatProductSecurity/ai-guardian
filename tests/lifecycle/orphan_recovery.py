"""CI-only real package-first lifecycle; never run against an operator install.

This exercises setup registrations, not running host CLIs or live host failure
semantics. Unit/UX tests are the only required local validation.
"""

import json
import hashlib
import os
import runpy
import subprocess
import sys
import tempfile
from pathlib import Path


def main():
    if os.environ.get("GITHUB_ACTIONS") != "true" or not os.environ.get("RUNNER_TEMP"):
        raise SystemExit(
            "CI-only: this scenario removes the runner's installed test package"
        )
    repo = Path(__file__).resolve().parents[2]
    engine = runpy.run_path(str(repo / "scripts/ai_guardian_recovery.py"))
    with tempfile.TemporaryDirectory(
        prefix="orphan-lifecycle-", dir=os.environ["RUNNER_TEMP"]
    ) as temporary:
        root = Path(temporary).resolve()
        home = root / "home"
        project = root / "selected-project"
        home.mkdir()
        project.mkdir()
        env = os.environ.copy()
        # Every setup/config/state/cache path is disposable and explicit.
        for key in (
            "CLAUDE_CONFIG_DIR CURSOR_CONFIG_DIR COPILOT_HOME GROK_HOME CODEX_HOME "
            "GEMINI_CLI_HOME CLINE_DATA_DIR KIRO_HOME JUNIE_HOME AIDER_DESK_DIR "
            "AIDER_DESK_HOME_DIR OPENCLAW_STATE_DIR OPENCLAW_HOME OPENCLAW_CONFIG_PATH "
            "OPENCODE_CONFIG_DIR OPENCODE_CONFIG CRUSH_GLOBAL_CONFIG PI_CODING_AGENT_DIR"
        ).split():
            env.pop(key, None)
        env.update(
            {
                "HOME": str(home),
                "USERPROFILE": str(home),
                "APPDATA": str(home / "appdata"),
                "LOCALAPPDATA": str(home / "localappdata"),
                "XDG_CONFIG_HOME": str(home / "config"),
                "XDG_STATE_HOME": str(home / "state"),
                "XDG_CACHE_HOME": str(home / "cache"),
                "AI_GUARDIAN_CONFIG_DIR": str(home / "guardian-config"),
                "AI_GUARDIAN_STATE_DIR": str(home / "guardian-state"),
                "AI_GUARDIAN_CACHE_DIR": str(home / "guardian-cache"),
                "AI_GUARDIAN_PREFERRED_UI": "headless",
                "CODEX_HOME": str(home / "relocated-codex"),
                "OPENCODE_CONFIG_DIR": str(home / "relocated-opencode"),
                "PI_CODING_AGENT_DIR": str(home / "relocated-pi"),
            }
        )

        def run(command, environment=None):
            subprocess.run(
                command,
                env=environment if environment is not None else env,
                cwd=project,
                check=True,
            )

        for host in ("claude", "cursor", "codex", "opencode", "pi"):
            command = [
                sys.executable,
                "-I",
                "-m",
                "ai_guardian",
                "setup",
                "--ide",
                host,
                "--yes",
            ]
            if host == "pi":
                command.append("--no-mcp")  # No SDK download needed for hook recovery.
            run(command)
        run(
            [
                sys.executable,
                "-I",
                "-m",
                "ai_guardian",
                "setup",
                "--ide",
                "cursor",
                "--project",
                str(project),
                "--yes",
            ]
        )
        mixed = home / ".claude.json"
        config = json.loads(mixed.read_text(encoding="utf-8"))
        config["mcpServers"]["other"] = {"command": "third-party-sentinel"}
        mixed.write_text(json.dumps(config), encoding="utf-8")
        history = home / "guardian-state/retained-history.jsonl"
        history.parent.mkdir(parents=True, exist_ok=True)
        history.write_text("synthetic audit history", encoding="utf-8")

        # Deliberately remove the current runner installation before recovery.
        run([sys.executable, "-m", "pip", "uninstall", "-y", "ai-guardian"])
        run(
            [
                sys.executable,
                "-I",
                "-c",
                "import importlib.util; assert importlib.util.find_spec('ai_guardian') is None; assert importlib.util.find_spec('ai_guardian_hook_runtime') is None",
            ]
        )

        runtime = root / "powershell-runtime"
        recovery_env = env.copy()
        if os.name == "nt":
            runtime.mkdir()
            # These belong to PowerShell, not AI Guardian. Keep them separate
            # from every selected home/config/state directory being verified.
            recovery_env.update(
                {
                    "XDG_CACHE_HOME": str(runtime / "cache"),
                    "LOCALAPPDATA": str(runtime / "localappdata"),
                    "APPDATA": str(runtime / "appdata"),
                    "PSModuleAnalysisCachePath": str(runtime / "ModuleAnalysisCache"),
                }
            )
            wrapper = [
                "pwsh",
                "-NoProfile",
                "-File",
                str(repo / "uninstall.ps1"),
                "-IntegrationsOnly",
                "-Scope",
                "both",
                "-Project",
                str(project),
                "-Python",
                sys.executable,
            ]
            dry, yes = "-DryRun", "-Yes"
        else:
            wrapper = [
                "bash",
                str(repo / "uninstall.sh"),
                "--integrations-only",
                "--scope",
                "both",
                "--project",
                str(project),
                "--python",
                sys.executable,
            ]
            dry, yes = "--dry-run", "--yes"

        def snapshot():
            return {
                p.relative_to(root): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in root.rglob("*")
                if p.is_file() and not p.is_relative_to(runtime)
            }

        before = snapshot()
        run([*wrapper, dry], recovery_env)
        assert snapshot() == before, "Preview mutated the disposable installation"
        run([*wrapper, yes], recovery_env)
        assert json.loads(mixed.read_text())["mcpServers"] == {
            "other": {"command": "third-party-sentinel"}
        }
        assert history.read_text() == "synthetic audit history"
        # Validate every selected registration using the same finite inventory,
        # while checking expected artifacts independently below.
        previous = os.environ.copy()
        try:
            os.environ.update(env)
            configs, _ = engine["inventory"]("both", [project])
        finally:
            os.environ.clear()
            os.environ.update(previous)
        for target in configs:
            if target.path.is_file():
                text = target.path.read_text(encoding="utf-8")
                cleaned, problems = (
                    engine["clean_toml"](text)
                    if target.path.suffix == ".toml"
                    else engine["clean_json"](text, target.host, set())
                )
                assert not problems and cleaned == text, target.path
        for path in (
            home / "relocated-pi/extensions/ai-guardian/index.ts",
            home / "relocated-pi/extensions/ai-guardian/package.json",
            home / "relocated-opencode/plugins/ai-guardian.ts",
            home / "relocated-opencode/ai-guardian/ai-guardian-bridge.ts",
        ):
            assert not path.exists(), path
        after = snapshot()
        run([*wrapper, yes], recovery_env)
        assert snapshot() == after, "Repeated recovery was not a no-op"
        print(
            "Five-host package-first registration recovery: PASS (live host behavior untested)"
        )


if __name__ == "__main__":
    main()
