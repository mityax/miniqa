import asyncio
import io
import json
import logging
import os
import webbrowser
from pathlib import Path

from PIL import Image
from quart import Quart, abort, websocket, jsonify, render_template, request, Response

from .config import TEMPLATES_PATH, STATIC_PATH
from .helpers import list_tests
from .setup import setup_dependencies
from .state import AppState
from .websocket import handle_websocket_message
from ..config import CONFIG
from ..test_case.test_case_file import TestCase

app = Quart(
    __name__,
    template_folder=TEMPLATES_PATH,
    static_folder=STATIC_PATH,
)

# Module-level state singleton; survives page refreshes.
_state: AppState = AppState()


# === Image helpers ===

async def _to_png_bytes(path: Path) -> tuple[bytes, str]:
    """
    Return (bytes, mime_type) for the given image path.
    PPM files are converted to PNG in-memory via Pillow (in a thread to avoid blocking
    the event loop). All other formats are returned as-is.
    """

    ext = path.suffix.lower()

    if ext == ".ppm":
        def _convert():
            with Image.open(str(path)) as img:
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                return buf.getvalue()

        data = await asyncio.to_thread(_convert)

        return data, "image/png"

    data = path.read_bytes()
    mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg"}.get(ext.lstrip("."), "application/octet-stream")

    return data, mime


# === HTTP Routes ===

@app.route("/")
async def index():
    return await render_template("index.html")


@app.route("/api/tests")
async def api_tests():
    """Return all test files with their YAML content."""

    return jsonify(list_tests())


@app.route("/api/schema")
async def api_schema():
    """Return the JSON schema for TestCase (used by the frontends yaml editor for autocompletion)."""

    schema = TestCase.model_json_schema()
    return jsonify(schema)


@app.route("/api/screenshot/<path:rel_path>")
async def api_screenshot(rel_path: str):
    """Serve a reference screenshot as base64 JSON for the frontend (PPM auto-converted to PNG)."""

    full = Path(CONFIG.refs_directory) / rel_path

    if not full.resolve().is_relative_to(Path(CONFIG.refs_directory).resolve()):
        abort(403)

    if not full.exists():
        abort(404)

    data, mime = await _to_png_bytes(full)

    return Response(data, mimetype=mime)


@app.route("/api/img")
async def api_img():
    """
    Serve screenshot from the previous pipeline run, or from `out` or `refs` directories as a raw
    image (PPM auto-converted to PNG).
    Accepts: ?path=<absolute-or-refs-relative path>
    """

    path_str = request.args.get("path", "")

    if not path_str: abort(400)

    full = Path(path_str)

    if not full.is_absolute():
        if (Path(CONFIG.out_directory).parent / full).is_file():  # just check if file exists, permission check is below
            full = Path(CONFIG.out_directory).parent / path_str
        elif (Path(CONFIG.refs_directory).parent / full).is_file():  # just check if file exists, permission check is below
            full = Path(CONFIG.refs_directory).parent / path_str
        else:
            abort(400)

    resolved = full.resolve()

    allowed = (
        resolved.is_relative_to(Path(CONFIG.out_directory).resolve())
        or resolved.is_relative_to(Path(CONFIG.refs_directory).resolve())
        or resolved.is_relative_to(Path(CONFIG.cache_directory).resolve())
    )

    if not allowed: abort(403)
    if not full.exists(): abort(404)

    data, mime = await _to_png_bytes(full)

    return Response(data, mimetype=mime)


@app.route("/api/screenshots")
async def api_screenshots():
    """List all reference screenshots (relative paths without extension)."""

    results = []

    if Path(CONFIG.refs_directory).exists():
        for f in sorted(Path(CONFIG.refs_directory).rglob("*.ppm")) + sorted(Path(CONFIG.refs_directory).rglob("*.png")):
            rel = f.relative_to(Path(CONFIG.refs_directory))
            results.append(str(rel))

    return jsonify(results)


# === WebSocket ===

@app.websocket("/ws")
async def ws():
    """
    Single persistent WebSocket connection. Only one browser tab allowed at a time.
    Messages are in {"type": "...", "payload": {...}} format.
    """

    # Reject a second tab
    if _state.active_ws_queue is not None:
        await websocket.send_json({"type": "tab_conflict", "payload": {}})
        return

    outbox: asyncio.Queue = asyncio.Queue()
    _state.active_ws_queue = outbox

    async def _sender():
        """Forward outbox messages to the WebSocket."""

        while True:
            msg = await outbox.get()

            if msg is None:
                break

            try:
                await websocket.send_json(msg)
            except TypeError as e:
                print("[webui] Cannot send websocket message; not JSON-serializable: ", msg)
                print(repr(e))
            except Exception as e:
                logging.warning("Breaking send loop due to unexpected error: ", e, type(e))
                break

    sender_task = asyncio.create_task(_sender())

    try:
        # Send full state on connect so a refreshed page re-hydrates
        await _state.send("state", _state.full_snapshot())
        await _state.send("tests", list_tests())

        while True:
            raw = await websocket.receive()
            try:
                msg = json.loads(raw)
                await handle_websocket_message(msg, _state)
            except Exception as e:
                logging.exception("Unexpected error while receiving message: ", exc_info=e, stack_info=True)
                await _state.send("error", {"message": str(e)})
    except asyncio.CancelledError:
        pass
    finally:
        _state.active_ws_queue = None
        outbox.put_nowait(None)  # unblock sender
        sender_task.cancel()


# === Disable Client-Side Caching ===

@app.after_request
async def add_header(response):
    # Deaktiviert das Caching vollständig
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, public, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


# === Entry point ===

async def run_webui(
    vnc_target_port: int = 5900,
    novnc_listen_port: int = 6080,
    host: str = os.environ.get("MINIQA_WEBUI_HOST", "127.0.0.1"),
    port: int = int(os.environ.get("MINIQA_WEBUI_PORT", 8080)),
    pipeline_max_workers: int = 1,
    open_browser: bool = True,
) -> None:
    """Start the WebUI server."""

    global _state
    _state.pipeline_max_jobs = pipeline_max_workers
    _state.novnc_port = novnc_listen_port

    from hypercorn.asyncio import serve
    from hypercorn.config import Config

    cfg = Config()
    cfg.bind = [f"{host}:{port}"]
    cfg.loglevel = "WARNING"

    setup_dependencies()

    print(f"[webui] Starting at http://{host}:{port}")

    async def _open_browser():
        if open_browser:
            await asyncio.sleep(1)
            webbrowser.open(f"http://{host}:{port}")

    try:
        await asyncio.gather(
            serve(app, cfg),
            _open_browser(),
        )
    finally:
        # Clean up on shutdown
        await _state.websockify_manager.stop()
        if _state.edit_worker is not None:
            try:
                await _state.edit_worker.stop()
            except Exception:
                pass
