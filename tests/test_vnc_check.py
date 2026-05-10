"""
Unit tests for vnc_check.check_vnc().

All tests use unittest.mock to patch socket.create_connection so no real
network connections are made.
"""

import socket
from unittest.mock import MagicMock, patch

import pytest
from src.central_monitor.vnc_check import check_vnc


def _mock_socket(recv_data: bytes | None = None, recv_exc=None):
    """Return a context-manager-compatible mock socket."""
    sock = MagicMock()
    sock.__enter__ = MagicMock(return_value=sock)
    sock.__exit__ = MagicMock(return_value=False)

    if recv_exc is not None:
        sock.recv.side_effect = recv_exc
    elif recv_data is not None:
        sock.recv.return_value = recv_data

    return sock


# ── Port closed / unreachable ─────────────────────────────────────────────────

def test_connection_refused():
    with patch("socket.create_connection", side_effect=ConnectionRefusedError):
        r = check_vnc("host-01", 5900)

    assert not r.vnc_port_ok
    assert not r.vnc_banner_ok
    assert r.vnc_port_error is not None
    assert r.vnc_banner_text is None


def test_connection_timeout():
    with patch("socket.create_connection", side_effect=socket.timeout):
        r = check_vnc("host-01", 5900)

    assert not r.vnc_port_ok
    assert r.vnc_port_error is not None


def test_os_error_on_connect():
    with patch("socket.create_connection", side_effect=OSError("Network unreachable")):
        r = check_vnc("host-01", 5900)

    assert not r.vnc_port_ok
    assert "Network unreachable" in (r.vnc_port_error or "")


# ── Valid RFB banner ──────────────────────────────────────────────────────────

def test_valid_rfb_banner():
    sock = _mock_socket(recv_data=b"RFB 003.008\n")
    with patch("socket.create_connection", return_value=sock):
        r = check_vnc("host-01", 5900)

    assert r.vnc_port_ok
    assert r.vnc_banner_ok
    assert r.vnc_banner_text is not None
    assert r.vnc_banner_text.startswith("RFB")
    assert r.vnc_banner_error is None


def test_rfb_version_003_003():
    sock = _mock_socket(recv_data=b"RFB 003.003\n")
    with patch("socket.create_connection", return_value=sock):
        r = check_vnc("host-01", 5900)

    assert r.vnc_port_ok
    assert r.vnc_banner_ok


# ── Unexpected banner ─────────────────────────────────────────────────────────

def test_unexpected_banner():
    sock = _mock_socket(recv_data=b"HTTP/1.1 200 OK\r\n")
    with patch("socket.create_connection", return_value=sock):
        r = check_vnc("host-01", 5900)

    assert r.vnc_port_ok          # TCP port accepted the connection
    assert not r.vnc_banner_ok    # but banner is wrong
    assert r.vnc_banner_error is not None


def test_empty_banner():
    sock = _mock_socket(recv_data=b"")
    with patch("socket.create_connection", return_value=sock):
        r = check_vnc("host-01", 5900)

    assert r.vnc_port_ok
    assert not r.vnc_banner_ok


# ── Banner read timeout ───────────────────────────────────────────────────────

def test_banner_read_timeout():
    sock = _mock_socket(recv_exc=socket.timeout)
    with patch("socket.create_connection", return_value=sock):
        r = check_vnc("host-01", 5900)

    assert r.vnc_port_ok           # connection succeeded
    assert not r.vnc_banner_ok     # but banner timed out
    assert r.vnc_banner_error is not None


# ── Custom port ───────────────────────────────────────────────────────────────

def test_custom_port():
    sock = _mock_socket(recv_data=b"RFB 003.008\n")
    with patch("socket.create_connection", return_value=sock) as mock_conn:
        r = check_vnc("host-01", 5910)

    # Verify the custom port was actually passed to create_connection
    mock_conn.assert_called_once()
    call_args = mock_conn.call_args[0][0]   # first positional arg is (host, port)
    assert call_args[1] == 5910
    assert r.vnc_port_ok
