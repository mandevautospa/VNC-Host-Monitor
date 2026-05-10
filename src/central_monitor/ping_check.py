"""
ICMP ping check using the Windows built-in ping command.

ping_host() is the only public function.  It never raises — all errors
are captured in the returned PingResult.

Windows ping exit code:
  0 = success
  1 = host unreachable / timeout
"""

import re
import subprocess
import logging
from src.common.models import PingResult

logger = logging.getLogger(__name__)

# How long (ms) to wait for each ping reply before giving up
_PING_WAIT_MS = 1000

# Hard cap on the subprocess itself so a frozen ping can't stall the loop
_SUBPROCESS_TIMEOUT_S = 8


def ping_host(address: str, timeout_ms: int = _PING_WAIT_MS) -> PingResult:
    """
    Ping *address* once and return a PingResult.

    Args:
        address:    Hostname or IP to ping (e.g. "host-01" or "192.168.1.10").
        timeout_ms: Per-reply wait in milliseconds (passed to ping -w).

    Returns:
        PingResult with ping_ok=True and ping_latency_ms set on success,
        or ping_ok=False and ping_error describing the failure.
    """
    try:
        result = subprocess.run(
            ["ping", "-n", "1", "-w", str(timeout_ms), address],
            capture_output=True,
            text=True,
            timeout=_SUBPROCESS_TIMEOUT_S,
        )
        if result.returncode == 0:
            # Windows ping output example: "Reply from 192.168.1.10: bytes=32 time=2ms TTL=128"
            # Also handles "time<1ms"
            match = re.search(r"time[=<](\d+)ms", result.stdout, re.IGNORECASE)
            latency = float(match.group(1)) if match else None
            return PingResult(ping_ok=True, ping_latency_ms=latency)

        return PingResult(
            ping_ok=False,
            ping_error=_extract_ping_error(result.stdout),
        )

    except subprocess.TimeoutExpired:
        return PingResult(ping_ok=False, ping_error="Ping subprocess timed out")
    except FileNotFoundError:
        return PingResult(ping_ok=False, ping_error="ping command not found")
    except Exception as exc:
        logger.error("Unexpected error pinging %s: %s", address, exc)
        return PingResult(ping_ok=False, ping_error=str(exc))


def _extract_ping_error(stdout: str) -> str:
    """Pull a short human-readable error from ping stdout."""
    for keyword in ("Request timed out", "Destination host unreachable", "could not find host"):
        if keyword.lower() in stdout.lower():
            return keyword
    return "Host did not respond to ping"
