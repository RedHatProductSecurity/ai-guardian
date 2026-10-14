"""Contracts for release-readiness coverage of human-operated scoped controls."""

from pathlib import Path

import yaml

WORKFLOW = (
    Path(__file__).resolve().parents[2] / ".github/workflows/release-readiness.yml"
)


def _python_step(name):
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    step = next(
        step
        for step in workflow["jobs"]["daemon-lifecycle"]["steps"]
        if step["name"] == name
    )
    lines = step["run"].splitlines()
    assert lines[0] == "python - <<'PY'"
    assert lines[-1] == "PY"
    script = "\n".join(lines[1:-1])
    compile(script, str(WORKFLOW), "exec")
    return script


def test_release_readiness_checks_top_level_scope_options_and_stable_keys():
    script = _python_step("Verify top-level directory and session scopes")
    assert "send_hook_request" in script
    assert "session['session_key']" in script
    assert "os.chdir(project)" in script
    assert "os.chdir(previous_directory)" in script
    assert "session['project_dir'] == directory" in script
    assert "command('pause', *duration, '--dir', alias)" in script
    assert "command('resume', '--dir', alias)" in script
    assert "command('pause', *duration, '--session', first)" in script
    assert "command('resume', '--session', first)" in script
    assert "paused[first] and not paused[second]" in script
    assert "command(operation, selector, '', expected=2)" in script
    assert "'not-an-active-session', expected=1" in script


def test_release_readiness_checks_no_autostart_or_offline_pause_changes():
    script = _python_step("Verify scoped controls do not auto-start a stopped daemon")
    assert "for operation in ('pause', 'resume')" in script
    assert "['--dir', '.']" in script
    assert "['--session', 'not-an-active-session']" in script
    assert "result.returncode == 1" in script
    assert "assert not is_daemon_running()" in script
    assert "assert after == before" in script
