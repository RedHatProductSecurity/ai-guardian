"""Read-only installation discovery for already-running SSH daemons on main."""

import os
import sys
from unittest import mock

import pytest

from ai_guardian.daemon.ssh_probe import PROBE_SCRIPT

pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="The transmitted probe runs on POSIX SSH hosts"
)


@pytest.fixture
def probe():
    namespace = {}
    # Define the actual transmitted functions without reading local user config.
    exec(PROBE_SCRIPT.split("\ntry:\n    result = probe()", 1)[0], namespace)
    return namespace


@pytest.mark.parametrize(
    "entry", [["-m", "ai_guardian"], ["/vm/odd venv/bin/ai-guardian"]]
)
def test_main_daemon_context_uses_live_process_interpreter_not_system_python(
    probe, entry
):
    interpreter = "/vm/odd venv/bin/python"
    argv = [interpreter, *entry, "daemon", "start", "--foreground"]
    with (
        mock.patch("pathlib.Path.stat", return_value=mock.Mock(st_uid=os.getuid())),
        mock.patch.dict(probe, read=mock.Mock(return_value="\0".join(argv) + "\0")),
        mock.patch("os.path.samefile", return_value=True) as samefile,
    ):
        context = probe["legacy_cli_context"](12345, "/vm/config", "/vm/state")
    assert context == {
        "python": interpreter,
        "config_dir": "/vm/config",
        "state_dir": "/vm/state",
        "system": sys.platform,
    }
    samefile.assert_called_once_with(interpreter, "/proc/12345/exe")


@pytest.mark.parametrize(
    "case",
    [
        "unrelated",
        "relative",
        "wrong_user",
        "different_executable",
        "no_proc",
        "oversized",
        "invalid_path",
    ],
)
def test_ambiguous_process_does_not_enable_cli_or_guess_an_installation(probe, case):
    argv = ["/vm/venv/bin/python", "-m", "ai_guardian", "daemon", "start"]
    uid = os.getuid()
    if case == "unrelated":
        argv[2] = "other_package"
    elif case == "relative":
        argv[0] = "python3"
    elif case == "wrong_user":
        uid += 1
    elif case == "oversized":
        argv.append("x" * 131073)
    elif case == "invalid_path":
        argv[0] = "/vm/venv/bin/python\n"
    with (
        mock.patch("pathlib.Path.stat", return_value=mock.Mock(st_uid=uid)),
        mock.patch.dict(
            probe,
            read=mock.Mock(
                return_value="\0".join(argv) + "\0",
                side_effect=OSError if case == "no_proc" else None,
            ),
        ),
        mock.patch("os.path.samefile", return_value=case != "different_executable"),
        mock.patch("subprocess.run") as run,
        mock.patch("subprocess.Popen") as popen,
    ):
        assert probe["legacy_cli_context"](12345, "/vm/config", "/vm/state") is None
    run.assert_not_called()
    popen.assert_not_called()


@pytest.mark.skipif(
    sys.platform != "linux", reason="Legacy interpreter proof uses Linux procfs"
)
def test_live_procfs_keeps_virtualenv_symlink_instead_of_resolving_to_base_python(
    tmp_path, probe
):
    import subprocess

    interpreter = tmp_path / "custom venv" / "bin" / "python"
    interpreter.parent.mkdir(parents=True)
    interpreter.symlink_to(sys.executable)
    # Disposable no-op module, not a real daemon, with the same process layout.
    (tmp_path / "ai_guardian.py").write_text("import time\ntime.sleep(30)\n")
    process = subprocess.Popen(
        [str(interpreter), "-m", "ai_guardian", "daemon", "start"],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(tmp_path)},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        context = probe["legacy_cli_context"](
            process.pid, str(tmp_path / "config"), str(tmp_path / "state")
        )
        assert context["python"] == str(interpreter)
        assert context["python"] != os.path.realpath(interpreter)
    finally:
        process.terminate()
        process.wait(timeout=5)
