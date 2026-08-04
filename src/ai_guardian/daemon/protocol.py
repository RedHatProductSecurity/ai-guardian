"""
Length-prefixed JSON wire protocol for daemon IPC.

Messages are framed as: 4-byte big-endian length prefix + UTF-8 JSON payload.
This avoids newline-delimiter issues since hook JSON payloads can contain
embedded newlines.
"""

import json
import struct

HEADER_SIZE = 4
MAX_MESSAGE_SIZE = 10 * 1024 * 1024  # 10 MB
PROTOCOL_VERSION = 1


def encode_message(data):
    """Encode a dict as a length-prefixed JSON message.

    Args:
        data: Dict to encode

    Returns:
        bytes: 4-byte length prefix + UTF-8 JSON payload
    """
    payload = json.dumps(data, separators=(",", ":")).encode("utf-8")
    if len(payload) > MAX_MESSAGE_SIZE:
        raise ValueError(
            f"Message too large: {len(payload)} bytes (max {MAX_MESSAGE_SIZE})"
        )
    header = struct.pack("!I", len(payload))
    return header + payload


def decode_message(sock, timeout=5.0):
    """Read a length-prefixed JSON message from a socket.

    Args:
        sock: Connected socket to read from
        timeout: Read timeout in seconds

    Returns:
        dict: Decoded JSON message

    Raises:
        ConnectionError: On socket disconnect or timeout
        ValueError: On invalid message format
    """
    old_timeout = sock.gettimeout()
    try:
        sock.settimeout(timeout)
        header = _recv_exact(sock, HEADER_SIZE)
        length = struct.unpack("!I", header)[0]

        if length > MAX_MESSAGE_SIZE:
            raise ValueError(
                f"Message too large: {length} bytes (max {MAX_MESSAGE_SIZE})"
            )
        if length == 0:
            raise ValueError("Empty message")

        payload = _recv_exact(sock, length)
        return json.loads(payload.decode("utf-8"))
    finally:
        sock.settimeout(old_timeout)


def _recv_exact(sock, n):
    """Read exactly n bytes from socket, handling partial reads.

    Args:
        sock: Connected socket
        n: Number of bytes to read

    Returns:
        bytes: Exactly n bytes

    Raises:
        ConnectionError: On disconnect before n bytes received
    """
    chunks = []
    received = 0
    while received < n:
        chunk = sock.recv(n - received)
        if not chunk:
            raise ConnectionError(f"Connection closed after {received}/{n} bytes")
        chunks.append(chunk)
        received += len(chunk)
    return b"".join(chunks)


def make_hook_request(hook_data):
    """Create a hook request message envelope.

    Args:
        hook_data: Hook data dict from IDE

    Returns:
        dict: Request envelope with version, type, and data
    """
    return {
        "version": PROTOCOL_VERSION,
        "type": "hook",
        "data": hook_data,
    }


def make_response(data):
    """Create a response message envelope.

    Args:
        data: Response data dict (output + exit_code)

    Returns:
        dict: Response envelope with version, type, and data
    """
    return {
        "version": PROTOCOL_VERSION,
        "type": "response",
        "data": data,
    }


def make_ping():
    """Create a ping message for health checking."""
    return {"version": PROTOCOL_VERSION, "type": "ping"}


def make_pong():
    """Create a pong response to a ping."""
    return {"version": PROTOCOL_VERSION, "type": "pong"}


def make_shutdown():
    """Create a shutdown request message."""
    return {"version": PROTOCOL_VERSION, "type": "shutdown"}


def make_status_request():
    """Create a status request message."""
    return {"version": PROTOCOL_VERSION, "type": "status"}


def make_reload_config():
    """Create a config reload request message."""
    return {"version": PROTOCOL_VERSION, "type": "reload_config"}


def make_pause_dir(directory, minutes=0):
    """Create a per-directory pause request message.

    Args:
        directory: Absolute path of the project directory to pause
        minutes: Pause duration in minutes. 0 = indefinite.

    Returns:
        dict: Request envelope with version, type, and data
    """
    return {
        "version": PROTOCOL_VERSION,
        "type": "pause_dir",
        "data": {"dir": directory, "minutes": minutes},
    }


def make_resume_dir(directory):
    """Create a per-directory resume request message.

    Args:
        directory: Absolute path of the project directory to resume

    Returns:
        dict: Request envelope with version, type, and data
    """
    return {
        "version": PROTOCOL_VERSION,
        "type": "resume_dir",
        "data": {"dir": directory},
    }


def make_sdk_check(check_type, data):
    """Create an SDK security check request message.

    Args:
        check_type: "content", "file", "command", "sanitize", or "violations"
        data: Check-specific parameters

    Returns:
        dict: Request envelope with version, type, and data
    """
    return {
        "version": PROTOCOL_VERSION,
        "type": "sdk_check",
        "data": {"check_type": check_type, **data},
    }


def make_engine_test(engine_name, text, use_pattern_server=False):
    """Create an engine test request message.

    Args:
        engine_name: Scanner engine preset name (e.g. ``"leaktk"``)
        text: Content string to scan
        use_pattern_server: Resolve pattern-server config path

    Returns:
        dict: Request envelope with version, type, and data
    """
    return {
        "version": PROTOCOL_VERSION,
        "type": "engine_test",
        "data": {
            "engine": engine_name,
            "text": text,
            "use_pattern_server": use_pattern_server,
        },
    }


def make_subscribe():
    """Create a subscribe message — client opts into push event notifications."""
    return {"version": PROTOCOL_VERSION, "type": "subscribe"}


def make_event(event_type, data=None):
    """Create a push event notification (daemon → subscriber).

    Args:
        event_type: Event name, e.g. "state_changed", "paused", "resumed"
        data: Optional dict with event details
    """
    msg = {"version": PROTOCOL_VERSION, "type": "event", "event": event_type}
    if data is not None:
        msg["data"] = data
    return msg


def make_ml_detect_request(content, source_type="user_prompt"):
    """Create an ML detection request message.

    Args:
        content: Text to classify for prompt injection
        source_type: "user_prompt" or "file_content"

    Returns:
        dict: Request envelope with version, type, and data
    """
    return {
        "version": PROTOCOL_VERSION,
        "type": "ml_detect",
        "data": {"content": content, "source_type": source_type},
    }
