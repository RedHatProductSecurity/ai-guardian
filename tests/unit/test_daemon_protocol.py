"""Tests for daemon wire protocol."""

import json
import socket
import struct

import pytest

from ai_guardian.daemon.protocol import (
    HEADER_SIZE,
    MAX_MESSAGE_SIZE,
    PROTOCOL_VERSION,
    decode_message,
    encode_message,
    make_engine_test,
    make_event,
    make_hook_request,
    make_pause_dir,
    make_ping,
    make_pong,
    make_reload_config,
    make_response,
    make_resume_dir,
    make_shutdown,
    make_status_request,
    make_subscribe,
)


class TestEncodeMessage:
    def test_encode_simple_dict(self):
        data = {"type": "ping"}
        result = encode_message(data)
        assert len(result) > HEADER_SIZE
        length = struct.unpack("!I", result[:HEADER_SIZE])[0]
        payload = result[HEADER_SIZE:]
        assert len(payload) == length
        assert json.loads(payload) == data

    def test_encode_nested_dict(self):
        data = {"type": "hook", "data": {"tool_name": "Bash", "input": "ls"}}
        result = encode_message(data)
        length = struct.unpack("!I", result[:HEADER_SIZE])[0]
        payload = result[HEADER_SIZE:]
        assert json.loads(payload) == data

    def test_encode_empty_dict(self):
        data = {}
        result = encode_message(data)
        assert len(result) > HEADER_SIZE

    def test_encode_rejects_oversized_message(self):
        data = {"data": "x" * (MAX_MESSAGE_SIZE + 1)}
        with pytest.raises(ValueError, match="too large"):
            encode_message(data)


class TestDecodeMessage:
    def _make_socket_pair(self):
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        port = server.getsockname()[1]

        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client.connect(("127.0.0.1", port))
        peer, _ = server.accept()
        server.close()
        return client, peer

    def test_roundtrip(self):
        client, peer = self._make_socket_pair()
        try:
            data = {"type": "pong", "version": 1}
            encoded = encode_message(data)
            client.sendall(encoded)
            result = decode_message(peer, timeout=2.0)
            assert result == data
        finally:
            client.close()
            peer.close()

    def test_roundtrip_large_payload(self):
        client, peer = self._make_socket_pair()
        try:
            data = {"data": "x" * 100000}
            client.sendall(encode_message(data))
            result = decode_message(peer, timeout=2.0)
            assert result == data
        finally:
            client.close()
            peer.close()

    def test_decode_connection_closed(self):
        client, peer = self._make_socket_pair()
        client.close()
        with pytest.raises(ConnectionError):
            decode_message(peer, timeout=1.0)
        peer.close()

    def test_decode_oversized_header(self):
        client, peer = self._make_socket_pair()
        try:
            header = struct.pack("!I", MAX_MESSAGE_SIZE + 1)
            client.sendall(header)
            with pytest.raises(ValueError, match="too large"):
                decode_message(peer, timeout=1.0)
        finally:
            client.close()
            peer.close()

    def test_decode_empty_message(self):
        client, peer = self._make_socket_pair()
        try:
            header = struct.pack("!I", 0)
            client.sendall(header)
            with pytest.raises(ValueError, match="Empty"):
                decode_message(peer, timeout=1.0)
        finally:
            client.close()
            peer.close()

    def test_decode_timeout(self):
        client, peer = self._make_socket_pair()
        try:
            with pytest.raises((socket.timeout, OSError)):
                decode_message(peer, timeout=0.1)
        finally:
            client.close()
            peer.close()


class TestMessageFactories:
    def test_make_hook_request(self):
        data = {"tool_name": "Bash"}
        msg = make_hook_request(data)
        assert msg["version"] == PROTOCOL_VERSION
        assert msg["type"] == "hook"
        assert msg["data"] == data

    def test_make_response(self):
        data = {"output": None, "exit_code": 0}
        msg = make_response(data)
        assert msg["version"] == PROTOCOL_VERSION
        assert msg["type"] == "response"
        assert msg["data"] == data

    def test_make_ping(self):
        msg = make_ping()
        assert msg["type"] == "ping"
        assert msg["version"] == PROTOCOL_VERSION

    def test_make_pong(self):
        msg = make_pong()
        assert msg["type"] == "pong"

    def test_make_shutdown(self):
        msg = make_shutdown()
        assert msg["type"] == "shutdown"

    def test_make_status_request(self):
        msg = make_status_request()
        assert msg["type"] == "status"

    def test_make_reload_config(self):
        msg = make_reload_config()
        assert msg["type"] == "reload_config"

    def test_make_pause_dir(self):
        msg = make_pause_dir("/project/a", minutes=30)
        assert msg["version"] == PROTOCOL_VERSION
        assert msg["type"] == "pause_dir"
        assert msg["data"]["dir"] == "/project/a"
        assert msg["data"]["minutes"] == 30

    def test_make_pause_dir_indefinite(self):
        msg = make_pause_dir("/project/a")
        assert msg["data"]["minutes"] == 0

    def test_make_resume_dir(self):
        msg = make_resume_dir("/project/a")
        assert msg["version"] == PROTOCOL_VERSION
        assert msg["type"] == "resume_dir"
        assert msg["data"]["dir"] == "/project/a"

    def test_make_subscribe(self):
        msg = make_subscribe()
        assert msg["version"] == PROTOCOL_VERSION
        assert msg["type"] == "subscribe"

    def test_make_event_with_data(self):
        msg = make_event("paused", {"minutes": 5})
        assert msg["version"] == PROTOCOL_VERSION
        assert msg["type"] == "event"
        assert msg["event"] == "paused"
        assert msg["data"]["minutes"] == 5

    def test_make_event_without_data(self):
        msg = make_event("resumed")
        assert msg["version"] == PROTOCOL_VERSION
        assert msg["type"] == "event"
        assert msg["event"] == "resumed"
        assert "data" not in msg

    def test_make_engine_test(self):
        msg = make_engine_test("leaktk", "secret text", use_pattern_server=True)
        assert msg["version"] == PROTOCOL_VERSION
        assert msg["type"] == "engine_test"
        assert msg["data"]["engine"] == "leaktk"
        assert msg["data"]["text"] == "secret text"
        assert msg["data"]["use_pattern_server"] is True

    def test_make_engine_test_defaults(self):
        msg = make_engine_test("gitleaks", "test")
        assert msg["data"]["use_pattern_server"] is False
