"""
TightVNC reachability checks performed from the central monitor.

Two checks are combined in a single TCP connection:
  1. TCP port open?       → vnc_port_ok
  2. RFB banner starts with "RFB"? → vnc_banner_ok

check_vnc() is the only public function.  It never raises.
"""

import logging
import socket
from src.common.models import VncResult

logger = logging.getLogger(__name__)

_CONNECT_TIMEOUT_S = 3.0   # seconds to wait for the TCP handshake
_BANNER_TIMEOUT_S  = 3.0   # seconds to wait for the server to send its banner
_BANNER_READ_BYTES = 64    # RFB banner is short (e.g. "RFB 003.008\n")
_EXPECTED_PREFIX   = b"RFB"


def check_vnc(address: str, port: int = 5900) -> VncResult:
    """
    Open a TCP connection to *address:port* and attempt to read the VNC/RFB banner.

    Args:
        address: Hostname or IP of the P3D host.
        port:    VNC TCP port (default 5900).

    Returns:
        VncResult with detailed port and banner outcome fields.
    """
    port_ok = False
    port_error: str | None = None
    banner_ok = False
    banner_text: str | None = None
    banner_error: str | None = None

    try:
        with socket.create_connection((address, port), timeout=_CONNECT_TIMEOUT_S) as sock:
            port_ok = True
            sock.settimeout(_BANNER_TIMEOUT_S)
            try:
                raw = sock.recv(_BANNER_READ_BYTES)
                if raw.startswith(_EXPECTED_PREFIX):
                    banner_ok = True
                    banner_text = raw.decode("ascii", errors="replace").strip()
                else:
                    banner_error = f"Unexpected banner: {raw[:24]!r}"
            except socket.timeout:
                banner_error = "Timed out waiting for VNC banner"
            except Exception as exc:
                banner_error = f"Banner read error: {exc}"

    except ConnectionRefusedError:
        port_error = f"Connection refused on port {port}"
    except socket.timeout:
        port_error = f"Connection timed out on port {port}"
    except OSError as exc:
        port_error = str(exc)
    except Exception as exc:
        logger.error("Unexpected error checking VNC on %s:%s — %s", address, port, exc)
        port_error = str(exc)

    return VncResult(
        vnc_port_ok=port_ok,
        vnc_banner_ok=banner_ok,
        vnc_banner_text=banner_text,
        vnc_port_error=port_error,
        vnc_banner_error=banner_error,
    )
