"""
Central in-memory state for the WebUI.
The backend is the single source of truth; page refreshes restore from here.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from typing import Any, Literal

from miniqa.lib.runner.test_models import TestResult
from miniqa.lib.runner.test_models import TestStepResult
from miniqa.lib.runner.test_runner import TestRunner, TestWorker
from miniqa.lib.test_case.test_case_file import ParsedRegion
from miniqa.lib.webui.helpers import WebsockifyManager


@dataclass
class AppState:
    # === WebSocket (only one tab allowed) ===
    # Outbox queue; presence means a tab is connected.
    active_ws_queue: asyncio.Queue | None = None

    # === Test pipeline ===
    pipeline_running: bool = False
    pipeline_runner: TestRunner | None = None
    pipeline_max_jobs: int = 1

    # Keys are test-case filenames (stems), e.g. "000_base":
    test_statuses: dict[str, str] = field(default_factory=dict)
    test_results: dict[str, TestResult | None] = field(default_factory=dict)
    test_current_steps: dict[str, int | None] = field(default_factory=dict)
    test_start_time: dict[str, float | None] = field(default_factory=dict)

    # === Edit-view worker ===
    edit_worker: TestWorker | None = None # Instance is kept for the session lifetime
    # stopped | booting | loading_snapshot | ready | running | error | cancelled
    edit_worker_status: Literal['running', 'ready', 'error', 'booting', 'stopped', 'loading_snapshot'] = "stopped"
    edit_worker_message: str | None = None
    edit_worker_progress: tuple[int, int] | None = None  # (done, total) for snapshot chain

    # Currently open test in the edit view
    edit_test_stem: str | None = None   # file stem, e.g. "001_volume_down"
    edit_yaml: str | None = None        # live yaml content (may differ from saved file)
    edit_has_unsaved: bool = False

    # === NoVNC / websockify ===
    novnc_host: str = os.environ.get("MINIQA_WEBUI_VNC_HOST", "localhost")
    novnc_port: int = int(os.environ.get("MINIQA_WEBUI_VNC_PORT", 6080))
    websockify_manager: WebsockifyManager = WebsockifyManager()

    # === Async locks / tasks ===
    edit_worker_preparation_task: asyncio.Task | None = None        # currently running edit-view coroutine
    pipeline_task: asyncio.Task | None = None    # currently running pipeline coroutine

    # === Helpers ===

    async def send(self, msg_type: str, payload: Any = None) -> None:
        """Queue a JSON message for the active WebSocket client (fire-and-forget)."""

        if self.active_ws_queue is not None:
            await self.active_ws_queue.put({"type": msg_type, "payload": payload or {}})

    def full_snapshot(self) -> dict:
        """Serialize the entire state for an initial sync after (re-)connect."""

        return {
            "pipeline": {
                "running": self.pipeline_running,
                "statuses": self.test_statuses,
                "current_steps": self.test_current_steps,
                "test_start_time": self.test_start_time,
                "results": {
                    k: serialize_result(v) if v is not None else None
                    for k, v in self.test_results.items()
                },
            },
            "edit": {
                "test_stem": self.edit_test_stem,
                "yaml": self.edit_yaml,
                "has_unsaved": self.edit_has_unsaved,
                "worker_status": self.edit_worker_status,
                "worker_message": self.edit_worker_message,
                "worker_progress": list(self.edit_worker_progress) if self.edit_worker_progress else None,
            },
            "novnc_port": self.novnc_port,
        }


# === Serialization helpers ===

def serialize_result(result: TestResult) -> dict:
    exc = result.exception

    return {
        "success": result.success,
        "message": result.message,
        "exception_type": type(exc).__name__ if exc else None,
        "exception_msg": str(exc) if exc else None,
        "failed_step": result.failed_step_index,
        "step_results": [_serialize_step_result(sr) for sr in result.step_results],
    }


def _serialize_step_result(sr: TestStepResult) -> dict:
    exc = sr.exception

    return {
        "success": sr.success,
        "message": sr.message,
        "exception_type": type(exc).__name__ if exc else None,
        "exception_msg": str(exc) if exc else None,
        "exception_regions": [_serialize_region(r) for r in getattr(exc, "regions", None) or ()],
        "exception_ignore_regions": [_serialize_region(r) for r in getattr(exc, "ignore_regions", None) or ()],
        "screenshots": [s.model_dump() for s in sr.screenshots],
    }


def _serialize_region(r: ParsedRegion):
    return {
        "x":      {"value": r[0].value, "is_relative": r[0].is_relative},
        "y":      {"value": r[1].value, "is_relative": r[1].is_relative},
        "width":  {"value": r[2].value, "is_relative": r[2].is_relative},
        "height": {"value": r[3].value, "is_relative": r[3].is_relative},
    }
