"""
Unit tests for OpenCode transcript scanning via SQLite (Issue #934).

Tests reading conversation text from OpenCode's SQLite session DB
and feeding it into the transcript scanning pipeline.
"""

import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ai_guardian.scanners.transcript.opencode import (
    _extract_text_from_part,
    get_opencode_db_path,
    get_opencode_latest_timestamp,
    read_opencode_transcript,
)


def _create_test_db(db_path):
    """Create an OpenCode-schema SQLite DB for testing."""
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE session ("
        "  id TEXT PRIMARY KEY,"
        "  project_id TEXT NOT NULL,"
        "  directory TEXT NOT NULL,"
        "  title TEXT NOT NULL,"
        "  version TEXT NOT NULL,"
        "  slug TEXT NOT NULL,"
        "  time_created INTEGER NOT NULL,"
        "  time_updated INTEGER NOT NULL"
        ")"
    )
    conn.execute(
        "CREATE TABLE message ("
        "  id TEXT PRIMARY KEY,"
        "  session_id TEXT NOT NULL,"
        "  time_created INTEGER NOT NULL,"
        "  time_updated INTEGER NOT NULL,"
        "  data TEXT NOT NULL"
        ")"
    )
    conn.execute(
        "CREATE TABLE part ("
        "  id TEXT PRIMARY KEY,"
        "  message_id TEXT NOT NULL,"
        "  session_id TEXT NOT NULL,"
        "  time_created INTEGER NOT NULL,"
        "  time_updated INTEGER NOT NULL,"
        "  data TEXT NOT NULL"
        ")"
    )
    conn.commit()
    return conn


def _insert_session(conn, session_id="ses_test1", directory="/tmp/project"):
    conn.execute(
        "INSERT INTO session (id, project_id, directory, title, version, slug, time_created, time_updated) "
        "VALUES (?, 'proj1', ?, 'Test', '1.0', 'test', 1000, 1000)",
        (session_id, directory),
    )
    conn.commit()


def _insert_message(conn, msg_id, session_id, role="assistant", ts=1000):
    data = json.dumps({"role": role, "mode": "build"})
    conn.execute(
        "INSERT INTO message (id, session_id, time_created, time_updated, data) "
        "VALUES (?, ?, ?, ?, ?)",
        (msg_id, session_id, ts, ts, data),
    )
    conn.commit()


def _insert_part(conn, part_id, msg_id, session_id, data_dict, ts=1000):
    conn.execute(
        "INSERT INTO part (id, message_id, session_id, time_created, time_updated, data) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (part_id, msg_id, session_id, ts, ts, json.dumps(data_dict)),
    )
    conn.commit()


class TestGetOpenCodeDbPath(unittest.TestCase):
    """Test OpenCode DB path discovery."""

    def test_env_var_override(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "opencode.db")
            sqlite3.connect(db_path).close()
            with mock.patch.dict(os.environ, {"OPENCODE_HOME": tmpdir}):
                result = get_opencode_db_path()
                self.assertEqual(result, db_path)

    def test_env_var_missing_db(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch.dict(os.environ, {"OPENCODE_HOME": tmpdir}):
                with mock.patch("os.path.exists", return_value=False):
                    result = get_opencode_db_path()
                    self.assertIsNone(result)

    def test_no_env_no_default(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            env = dict(os.environ)
            env.pop("OPENCODE_HOME", None)
            with mock.patch.dict(os.environ, env, clear=True):
                with mock.patch("os.path.exists", return_value=False):
                    result = get_opencode_db_path()
                    self.assertIsNone(result)


class TestExtractTextFromPart(unittest.TestCase):
    """Test text extraction from OpenCode part data."""

    def test_text_part(self):
        data = {"type": "text", "text": "Hello world"}
        self.assertEqual(_extract_text_from_part(data), "Hello world")

    def test_text_part_empty(self):
        data = {"type": "text", "text": ""}
        self.assertEqual(_extract_text_from_part(data), "")

    def test_tool_part_with_output(self):
        data = {
            "type": "tool",
            "tool": "bash",
            "state": {"output": "file1.txt\nfile2.txt", "input": {"command": "ls"}},
        }
        result = _extract_text_from_part(data)
        self.assertIn("file1.txt", result)
        self.assertIn("ls", result)

    def test_tool_part_string_state(self):
        state = json.dumps({"output": "result text", "input": {"command": "echo hi"}})
        data = {"type": "tool", "tool": "bash", "state": state}
        result = _extract_text_from_part(data)
        self.assertIn("result text", result)
        self.assertIn("echo hi", result)

    def test_tool_part_no_output(self):
        data = {"type": "tool", "tool": "bash", "state": {"input": {}}}
        self.assertEqual(_extract_text_from_part(data), "")

    def test_unknown_part_type(self):
        data = {"type": "step-start", "text": "ignored"}
        self.assertEqual(_extract_text_from_part(data), "")

    def test_reasoning_part(self):
        data = {"type": "reasoning", "text": "thinking..."}
        self.assertEqual(_extract_text_from_part(data), "")

    def test_tool_part_no_state(self):
        data = {"type": "tool", "tool": "bash"}
        self.assertEqual(_extract_text_from_part(data), "")


class TestReadOpenCodeTranscript(unittest.TestCase):
    """Test reading transcript from SQLite DB."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "opencode.db")
        self.conn = _create_test_db(self.db_path)
        _insert_session(self.conn, "ses_1")
        _insert_message(self.conn, "msg_1", "ses_1", ts=1000)

    def tearDown(self):
        self.conn.close()
        import shutil

        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_reads_text_parts(self):
        _insert_part(
            self.conn,
            "p1",
            "msg_1",
            "ses_1",
            {"type": "text", "text": "Hello"},
            ts=2000,
        )
        _insert_part(
            self.conn,
            "p2",
            "msg_1",
            "ses_1",
            {"type": "text", "text": "World"},
            ts=3000,
        )

        text, ts = read_opencode_transcript(self.db_path, "ses_1", since_timestamp=0)
        self.assertIn("Hello", text)
        self.assertIn("World", text)
        self.assertEqual(ts, 3000)

    def test_reads_tool_output(self):
        _insert_part(
            self.conn,
            "p1",
            "msg_1",
            "ses_1",
            {
                "type": "tool",
                "tool": "bash",
                "state": {"output": "secret data", "input": {"command": "cat file"}},
            },
            ts=2000,
        )
        text, ts = read_opencode_transcript(self.db_path, "ses_1", since_timestamp=0)
        self.assertIn("secret data", text)
        self.assertIn("cat file", text)
        self.assertEqual(ts, 2000)

    def test_incremental_cursor(self):
        _insert_part(
            self.conn, "p1", "msg_1", "ses_1", {"type": "text", "text": "old"}, ts=1000
        )
        _insert_part(
            self.conn, "p2", "msg_1", "ses_1", {"type": "text", "text": "new"}, ts=2000
        )

        text, ts = read_opencode_transcript(self.db_path, "ses_1", since_timestamp=1500)
        self.assertNotIn("old", text)
        self.assertIn("new", text)
        self.assertEqual(ts, 2000)

    def test_empty_session(self):
        text, ts = read_opencode_transcript(
            self.db_path, "ses_nonexistent", since_timestamp=0
        )
        self.assertEqual(text, "")
        self.assertEqual(ts, 0)

    def test_nothing_new(self):
        _insert_part(
            self.conn, "p1", "msg_1", "ses_1", {"type": "text", "text": "old"}, ts=1000
        )
        text, ts = read_opencode_transcript(self.db_path, "ses_1", since_timestamp=5000)
        self.assertEqual(text, "")
        self.assertEqual(ts, 5000)

    def test_invalid_json_in_part(self):
        self.conn.execute(
            "INSERT INTO part (id, message_id, session_id, time_created, time_updated, data) "
            "VALUES ('p_bad', 'msg_1', 'ses_1', 2000, 2000, 'not json')"
        )
        self.conn.commit()
        _insert_part(
            self.conn,
            "p_good",
            "msg_1",
            "ses_1",
            {"type": "text", "text": "valid"},
            ts=3000,
        )

        text, ts = read_opencode_transcript(self.db_path, "ses_1", since_timestamp=0)
        self.assertIn("valid", text)
        self.assertEqual(ts, 3000)

    def test_skips_non_dict_json(self):
        self.conn.execute(
            "INSERT INTO part (id, message_id, session_id, time_created, time_updated, data) "
            "VALUES ('p_arr', 'msg_1', 'ses_1', 2000, 2000, '[1,2,3]')"
        )
        self.conn.commit()
        text, ts = read_opencode_transcript(self.db_path, "ses_1", since_timestamp=0)
        self.assertEqual(text, "")

    def test_db_not_found(self):
        text, ts = read_opencode_transcript(
            "/nonexistent/db.db", "ses_1", since_timestamp=0
        )
        self.assertEqual(text, "")
        self.assertEqual(ts, 0)


class TestGetOpenCodeLatestTimestamp(unittest.TestCase):
    """Test latest timestamp retrieval."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "opencode.db")
        self.conn = _create_test_db(self.db_path)
        _insert_session(self.conn, "ses_1")
        _insert_message(self.conn, "msg_1", "ses_1", ts=1000)

    def tearDown(self):
        self.conn.close()
        import shutil

        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_returns_max_timestamp(self):
        _insert_part(
            self.conn, "p1", "msg_1", "ses_1", {"type": "text", "text": "a"}, ts=1000
        )
        _insert_part(
            self.conn, "p2", "msg_1", "ses_1", {"type": "text", "text": "b"}, ts=5000
        )
        _insert_part(
            self.conn, "p3", "msg_1", "ses_1", {"type": "text", "text": "c"}, ts=3000
        )

        result = get_opencode_latest_timestamp(self.db_path, "ses_1")
        self.assertEqual(result, 5000)

    def test_empty_session(self):
        result = get_opencode_latest_timestamp(self.db_path, "ses_nonexistent")
        self.assertEqual(result, 0)

    def test_db_not_found(self):
        result = get_opencode_latest_timestamp("/nonexistent/db.db", "ses_1")
        self.assertEqual(result, 0)


class TestScanOpenCodeTranscriptIncremental(unittest.TestCase):
    """Test incremental scanning of OpenCode transcripts."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "opencode.db")
        self.conn = _create_test_db(self.db_path)
        _insert_session(self.conn, "ses_scan1")
        _insert_message(self.conn, "msg_1", "ses_scan1", ts=1000)

        self.state_dir = tempfile.mkdtemp()
        self.env_patcher = mock.patch.dict(
            os.environ,
            {
                "AI_GUARDIAN_STATE_DIR": self.state_dir,
                "AI_GUARDIAN_CONFIG_DIR": self.tmpdir,
            },
        )
        self.env_patcher.start()

    def tearDown(self):
        self.conn.close()
        self.env_patcher.stop()
        import shutil

        shutil.rmtree(self.tmpdir, ignore_errors=True)
        shutil.rmtree(self.state_dir, ignore_errors=True)

    def test_first_scan_skips_to_end(self):
        from ai_guardian.scanners.transcript import scan_opencode_transcript_incremental

        _insert_part(
            self.conn,
            "p1",
            "msg_1",
            "ses_scan1",
            {"type": "text", "text": "existing"},
            ts=1000,
        )

        result = scan_opencode_transcript_incremental(
            self.db_path,
            "ses_scan1",
            secret_config={"enabled": False},
            pii_config={"enabled": False},
        )
        self.assertEqual(result, [])

        positions_file = Path(self.state_dir) / "transcript_positions.json"
        self.assertTrue(positions_file.exists())
        import json

        positions = json.loads(positions_file.read_text())
        self.assertEqual(positions.get("opencode:ses_scan1"), 1000)

    def test_second_scan_reads_new_parts(self):
        from ai_guardian.scanners.transcript import scan_opencode_transcript_incremental

        _insert_part(
            self.conn,
            "p1",
            "msg_1",
            "ses_scan1",
            {"type": "text", "text": "old text"},
            ts=1000,
        )

        scan_opencode_transcript_incremental(
            self.db_path,
            "ses_scan1",
            secret_config={"enabled": False},
            pii_config={"enabled": False},
        )

        _insert_part(
            self.conn,
            "p2",
            "msg_1",
            "ses_scan1",
            {"type": "text", "text": "new text"},
            ts=2000,
        )

        with mock.patch(
            "ai_guardian.scanners.transcript.opencode._scan_transcript_text"
        ) as mock_scan:
            mock_scan.return_value = []
            scan_opencode_transcript_incremental(
                self.db_path,
                "ses_scan1",
                secret_config={"enabled": False},
                pii_config={"enabled": False},
            )
            mock_scan.assert_called_once()
            call_args = mock_scan.call_args
            self.assertIn("new text", call_args[0][0])

    def test_nothing_new_returns_empty(self):
        from ai_guardian.scanners.transcript import scan_opencode_transcript_incremental

        _insert_part(
            self.conn,
            "p1",
            "msg_1",
            "ses_scan1",
            {"type": "text", "text": "old"},
            ts=1000,
        )

        scan_opencode_transcript_incremental(
            self.db_path,
            "ses_scan1",
            secret_config={"enabled": False},
            pii_config={"enabled": False},
        )

        result = scan_opencode_transcript_incremental(
            self.db_path,
            "ses_scan1",
            secret_config={"enabled": False},
            pii_config={"enabled": False},
        )
        self.assertEqual(result, [])


class TestScanTranscriptText(unittest.TestCase):
    """Test the shared _scan_transcript_text function."""

    def setUp(self):
        self.state_dir = tempfile.mkdtemp()
        self.env_patcher = mock.patch.dict(
            os.environ,
            {
                "AI_GUARDIAN_STATE_DIR": self.state_dir,
                "AI_GUARDIAN_CONFIG_DIR": self.state_dir,
            },
        )
        self.env_patcher.start()

    def tearDown(self):
        self.env_patcher.stop()
        import shutil

        shutil.rmtree(self.state_dir, ignore_errors=True)

    def test_both_disabled_returns_empty(self):
        from ai_guardian.scanners.transcript import _scan_transcript_text

        result = _scan_transcript_text(
            "some text",
            "test_key",
            secret_config={"enabled": False},
            pii_config={"enabled": False},
        )
        self.assertEqual(result, [])

    def test_empty_text_returns_empty(self):
        from ai_guardian.scanners.transcript import _scan_transcript_text

        result = _scan_transcript_text(
            "",
            "test_key",
            secret_config={"enabled": True},
            pii_config={"enabled": True},
        )
        self.assertEqual(result, [])

    @mock.patch("ai_guardian.scanners.transcript.common.check_secrets")
    def test_secret_detection(self, mock_gitleaks):
        from ai_guardian.scanners.transcript import _scan_transcript_text

        mock_gitleaks.return_value = (
            True,
            "Secret Type: generic-api-key\nLine: api_key=abc123",
        )

        result = _scan_transcript_text(
            "api_key=abc123",
            "test_key",
            secret_config={"enabled": True},
            pii_config={"enabled": False},
        )
        self.assertEqual(len(result), 1)
        self.assertIn("SECRET DETECTED", result[0])

    @mock.patch("ai_guardian.scanners.transcript.common.check_secrets")
    def test_dedup_same_secret(self, mock_gitleaks):
        from ai_guardian.scanners.transcript import _scan_transcript_text

        mock_gitleaks.return_value = (
            True,
            "Secret Type: generic-api-key\nLine: key=xyz",
        )

        result1 = _scan_transcript_text(
            "key=xyz",
            "opencode:ses_dedup",
            secret_config={"enabled": True},
            pii_config={"enabled": False},
        )
        self.assertEqual(len(result1), 1)

        result2 = _scan_transcript_text(
            "key=xyz",
            "opencode:ses_dedup",
            secret_config={"enabled": True},
            pii_config={"enabled": False},
        )
        self.assertEqual(len(result2), 0)
