"""
Checks whether a Windows service is running using the 'sc query' command.

check_service() is the only public function.  It never raises.
"""

import logging
import subprocess
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

_SC_TIMEOUT_S = 10


@dataclass
class ServiceResult:
    service_running: bool
    service_name: str
    error: Optional[str] = None


def check_service(service_name: str = "tvnserver") -> ServiceResult:
    """
    Query a Windows service by name with 'sc query <name>'.

    Returns ServiceResult with service_running=True when the output contains
    "RUNNING".  Any other state (STOPPED, PAUSED, not found) is treated as
    not running and the raw state is stored in error for logging.
    """
    try:
        result = subprocess.run(
            ["sc", "query", service_name],
            capture_output=True,
            text=True,
            timeout=_SC_TIMEOUT_S,
        )
        stdout = result.stdout

        if "RUNNING" in stdout:
            return ServiceResult(service_running=True, service_name=service_name)

        # Extract the STATE line for a useful error message
        state_line = next(
            (line.strip() for line in stdout.splitlines() if "STATE" in line), None
        )
        error_msg = state_line or result.stderr.strip() or "Service not found or not queryable"
        return ServiceResult(service_running=False, service_name=service_name, error=error_msg)

    except subprocess.TimeoutExpired:
        return ServiceResult(
            service_running=False,
            service_name=service_name,
            error="sc query timed out",
        )
    except FileNotFoundError:
        return ServiceResult(
            service_running=False,
            service_name=service_name,
            error="sc command not found — is this a Windows host?",
        )
    except Exception as exc:
        logger.error("Service check failed for '%s': %s", service_name, exc)
        return ServiceResult(service_running=False, service_name=service_name, error=str(exc))
