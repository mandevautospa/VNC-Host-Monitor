"""
Queries recent Windows Application and System event logs for crash/hang
indicators using a PowerShell Get-WinEvent call.

Crash/hang indicators checked:
  Application log  — Event ID 1000/1001 crashes (filtered for Prepar3D.exe)
                   — Event ID 1002 hangs (filtered for Prepar3D.exe)
  System log       — Events whose provider or message mentions display-driver keywords

NOTE: P3D hang detection (Event ID 1002) is currently experimental/low-confidence.
      Rely primarily on crash detection (1000/1001).

check_event_logs() is the only public function.  It never raises.
"""

import json
import logging
import subprocess
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger(__name__)

_PS_TIMEOUT_S = 30
_P3D_EXE_NAME = "Prepar3D.exe"  # Exact executable name filter


@dataclass
class EventLogResult:
    recent_app_crash_count: int = 0
    recent_app_hang_count: int = 0
    recent_display_error_count: int = 0
    recent_events_summary: List[dict] = field(default_factory=list)
    error: Optional[str] = None


def check_event_logs(lookback_minutes: int = 10, p3d_exe: str = _P3D_EXE_NAME) -> EventLogResult:
    """
    Run a PowerShell query for Application and System events in the last
    *lookback_minutes* minutes and return structured counts + a summary.
    
    Crashes and hangs are filtered to only count those involving *p3d_exe*
    (default: Prepar3D.exe).

    Requires the script to run as a user with Event Log read permission
    (standard on Windows hosts when run under a local admin or SYSTEM account).
    """
    ps_script = _build_ps_script(lookback_minutes, p3d_exe)

    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
            capture_output=True,
            text=True,
            timeout=_PS_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired:
        return EventLogResult(error="Event log PowerShell query timed out")
    except FileNotFoundError:
        return EventLogResult(error="powershell not found — is this a Windows host?")
    except Exception as exc:
        logger.error("Event log check failed: %s", exc)
        return EventLogResult(error=str(exc))

    raw = result.stdout.strip()
    if not raw:
        # No events found in the window — that is the healthy case
        return EventLogResult()

    try:
        events = json.loads(raw)
        if isinstance(events, dict):
            events = [events]
    except json.JSONDecodeError as exc:
        logger.warning("Could not parse event log JSON output: %s", exc)
        return EventLogResult(error=f"JSON parse error: {exc}")

    # Count only P3D-related crashes and hangs
    crash_count = sum(
        1 for e in events
        if e.get("type") == "app_error"
        and e.get("id") in (1000, 1001)
        and p3d_exe.lower() in (e.get("source", "").lower() or "")
    )
    hang_count = sum(
        1 for e in events
        if e.get("type") == "app_hang"
        and e.get("id") == 1002
        and p3d_exe.lower() in (e.get("source", "").lower() or "")
    )
    display_count = sum(1 for e in events if e.get("type") == "display_error")

    summary = [
        {
            "time": e.get("time"),
            "id": e.get("id"),
            "source": e.get("source"),
            "message": (e.get("message") or "")[:120],
        }
        for e in events[:10]
    ]

    return EventLogResult(
        recent_app_crash_count=crash_count,
        recent_app_hang_count=hang_count,
        recent_display_error_count=display_count,
        recent_events_summary=summary,
    )


def _build_ps_script(lookback_minutes: int, p3d_exe: str) -> str:
    """Return a PowerShell one-shot script that outputs event data as JSON.
    
    Events include executable name in the 'source' field for filtering by P3D.
    """
    # Use raw f-string to avoid escape sequence warnings for PowerShell regex patterns
    return rf"""
$cutoff = (Get-Date).AddMinutes(-{lookback_minutes})
$events = [System.Collections.Generic.List[PSObject]]::new()

# Application Error (1000), Windows Error Reporting (1001)
try {{
    $appErrors = Get-WinEvent -FilterHashtable @{{
        LogName   = 'Application'
        Id        = 1000, 1001
        StartTime = $cutoff
    }} -ErrorAction SilentlyContinue
    foreach ($e in $appErrors) {{
        # Extract executable name: "faulting application path: C:\\Prepar3D.exe"
        $exeName = 'Unknown'
        if ($e.Message -match '(?:faulting application|Module|FileName)[^:]*:\s*([^\r\n]+\.exe)') {{
            $exeName = $matches[1] -split '\\' | Select-Object -Last 1
        }}
        $msg = if ($e.Message) {{ $e.Message.Substring(0, [Math]::Min(200, $e.Message.Length)) }} else {{ '' }}
        $events.Add([PSCustomObject]@{{
            time    = $e.TimeCreated.ToString('o')
            id      = $e.Id
            source  = $exeName
            message = $msg
            type    = 'app_error'
        }})
    }}
}} catch {{}}

# Application Hang (1002)
try {{
    $appHangs = Get-WinEvent -FilterHashtable @{{
        LogName   = 'Application'
        Id        = 1002
        StartTime = $cutoff
    }} -ErrorAction SilentlyContinue
    foreach ($e in $appHangs) {{
        # Extract executable name from hang event
        $exeName = 'Unknown'
        if ($e.Message -match '(?:Faulting application|application)[^:]*:\s*([^\r\n]+\.exe)') {{
            $exeName = $matches[1] -split '\\' | Select-Object -Last 1
        }}
        $msg = if ($e.Message) {{ $e.Message.Substring(0, [Math]::Min(200, $e.Message.Length)) }} else {{ '' }}
        $events.Add([PSCustomObject]@{{
            time    = $e.TimeCreated.ToString('o')
            id      = $e.Id
            source  = $exeName
            message = $msg
            type    = 'app_hang'
        }})
    }}
}} catch {{}}

# Display-driver errors in System log
try {{
    $sysAll = Get-WinEvent -FilterHashtable @{{
        LogName   = 'System'
        StartTime = $cutoff
    }} -ErrorAction SilentlyContinue
    $displayErrors = $sysAll | Where-Object {{
        $_.ProviderName -match 'nvlddmkm|atikmdag|igfx|dxgkrnl|display|video' -or
        ($_.Message -and $_.Message -match 'display driver')
    }} | Select-Object -First 20
    foreach ($e in $displayErrors) {{
        $msg = if ($e.Message) {{ $e.Message.Substring(0, [Math]::Min(200, $e.Message.Length)) }} else {{ '' }}
        $events.Add([PSCustomObject]@{{
            time    = $e.TimeCreated.ToString('o')
            id      = $e.Id
            source  = $e.ProviderName
            message = $msg
            type    = 'display_error'
        }})
    }}
}} catch {{}}

if ($events.Count -gt 0) {{
    $events | ConvertTo-Json -Depth 3
}}
"""
