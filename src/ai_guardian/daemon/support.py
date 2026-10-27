"""Bounded, authenticated-API collection jobs; never review or publish remotely."""

import json
import logging
import os
import re
import site
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path

from ai_guardian.reporting.remote_support import MAX_WIRE_BYTES, validate_diagnostics

logger = logging.getLogger(__name__)
COLLECTION_TIMEOUT = 90
JOB_TTL = 300


def _collector_command() -> list[str]:
    """Use this installation, including user-site/editable installs, never cwd."""
    roots = [str(Path(__file__).resolve().parents[2])]
    if site.ENABLE_USER_SITE:
        # -I omits the user site. Restore only the interpreter's enabled user
        # installation for editable dependencies, never a sys.path/metadata scan
        # which could select a project's forged .dist-info directory.
        user_site = str(Path(site.getusersitepackages()).resolve())
        if user_site not in roots:
            roots.append(user_site)
    bootstrap = (
        "import runpy, sys\n"
        "sys.path[:0] = sys.argv[1:]\n"
        "runpy.run_module('ai_guardian.daemon.support', run_name='__main__')\n"
    )
    return [sys.executable, "-I", "-c", bootstrap, *roots]


class SupportJobs:
    """One collector at a time, at most four short-lived results per API server."""

    def __init__(self, state, name):
        self.state = state
        self.name = name or "ai-guardian"
        self._lock = threading.Lock()
        self._jobs: dict[str, dict] = {}
        self._running = False
        self._closed = False

    def start(self) -> dict:
        with self._lock:
            now = time.monotonic()
            self._jobs = {
                key: value
                for key, value in self._jobs.items()
                if now - value["started"] < JOB_TTL
            }
            if self._closed or self._running or len(self._jobs) >= 4:
                return {"status": "error", "error_code": "busy"}
            job_id = uuid.uuid4().hex
            self._jobs[job_id] = {"started": now, "status": "preparing"}
            self._running = True
        try:
            threading.Thread(
                target=self._collect,
                args=(job_id,),
                daemon=True,
                name="support-collection",
            ).start()
        except RuntimeError:
            with self._lock:
                self._running = False
                if job_id in self._jobs:
                    self._jobs[job_id].update(status="error", error_code="collection")
        return {"job_id": job_id, "status": "preparing"}

    def get(self, job_id: str) -> dict:
        with self._lock:
            job = (
                self._jobs.get(job_id)
                if re.fullmatch(r"[a-f0-9]{32}", job_id)
                else None
            )
            if job is None or time.monotonic() - job["started"] >= JOB_TTL:
                return {"status": "error", "error_code": "expired"}
            return {
                "job_id": job_id,
                **{k: v for k, v in job.items() if k != "started"},
            }

    def _collect(self, job_id: str) -> None:
        result: dict = {"status": "error", "error_code": "collection"}
        try:
            from ai_guardian import __version__

            # These paths come exclusively from the daemon's own observed state,
            # never HTTP input, tray working directories or discovery metadata.
            snapshot = self.state.get_project_cache_status()
            paths = sorted(
                {
                    item["config_path"]
                    for item in snapshot.get("projects", [])
                    if item.get("config_path")
                }
            )
            if len(paths) > 100:
                raise ValueError("Too many source projects")
            with (
                tempfile.TemporaryDirectory(
                    prefix="ai-guardian-support-job-"
                ) as staging,
                tempfile.TemporaryFile(dir=staging) as output,
            ):
                (Path(staging) / ".ai-read-deny").touch(mode=0o600)
                completed = subprocess.run(
                    _collector_command(),
                    input=json.dumps(
                        {
                            "name": self.name,
                            "projects": paths,
                            "daemon_version": __version__,
                        }
                    ).encode("utf-8"),
                    stdout=output,
                    stderr=subprocess.DEVNULL,
                    timeout=COLLECTION_TIMEOUT,
                    check=False,
                    # All child-created diagnostic staging is removed even when
                    # subprocess.run kills a timed-out collector.
                    env={
                        **os.environ,
                        "TMPDIR": staging,
                        "TEMP": staging,
                        "TMP": staging,
                    },
                )
                if completed.returncode != 0:
                    raise ValueError("Source collector failed")
                output.seek(0)
                raw = output.read(MAX_WIRE_BYTES + 1)
                if len(raw) > MAX_WIRE_BYTES:
                    result["error_code"] = "size"
                    raise ValueError("Source result too large")
            payload = json.loads(raw)
            validate_diagnostics(payload)
            result = {"status": "ready", "diagnostics": payload}
        except subprocess.TimeoutExpired:
            result["error_code"] = "timeout"
            logger.warning("Source support collection timed out")
        except Exception:
            # Never log raw subprocess/parser exceptions or private source paths.
            logger.warning("Source support diagnostics could not be collected safely")
        finally:
            with self._lock:
                self._running = False
                if not self._closed and job_id in self._jobs:
                    self._jobs[job_id].update(result)

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._jobs.clear()


def _main() -> None:
    from ai_guardian.config.utils import get_project_config_path
    from ai_guardian.reporting.remote_support import collect_diagnostics

    request = json.load(sys.stdin)
    paths = [Path(path) for path in request["projects"]]
    project = get_project_config_path()
    if project is not None and project not in paths:
        paths.append(project)
    payload = collect_diagnostics(
        request["name"], paths, daemon_version=request.get("daemon_version")
    )
    sys.stdout.write(json.dumps(payload))


if __name__ == "__main__":
    _main()
