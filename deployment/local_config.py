"""Loopback-only configuration for the PlatformUI UniLab domain facade.

Real credentials and hardware endpoints remain owned by the PlatformUI
deployment.  The UniLab Workbench process only projects the typed catalog and
delegates operations through ``PtlcRuntimePort``.
"""


class BasicConfig:
    ak = ""
    sk = ""
    disable_browser = True
    no_update_feedback = True
    log_level = "INFO"


class WSConfig:
    reconnect_interval = 5
    max_reconnect_attempts = 999
    ws_ping_interval = 5
    ws_ping_timeout = 8


class MoveItConfig:
    """Planning retries only; dispatched physical operations are never replayed."""

    plan_retry_attempts = 10
    num_planning_attempts = 10
