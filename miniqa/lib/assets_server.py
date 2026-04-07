import asyncio
import atexit
import contextlib
import http.server
import logging
import os
import socketserver
from urllib.parse import unquote

PORT = 8000


class MultiFolderHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        path = unquote(self.path).lstrip("/")

        # Check floating assets first:
        if path in _floating_assets:
            content = _floating_assets[path].encode("utf-8")

            self.send_response(200)
            self.send_header("Content-type", "text/plain; charset=utf-8")
            self.send_header("Content-length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)
            return

        # Default to normal file serving:
        super().do_GET()

    def translate_path(self, path):
        path = unquote(path)
        for mount, folder in mounts.items():
            if path.lstrip("/").startswith(mount):
                rel = path.lstrip("/")[len(mount):].lstrip("/")
                return os.path.realpath(os.path.join(folder, rel))
        return str("nonexistent")  # 404

    def log_message(self, fmt: str, *args):
        logging.debug(f"[AssetServer] {fmt % args}")

    def log_error(self, fmt: str, *args):
        logging.debug(f"[AssetServer] {fmt % args}")


mounts: dict[str, str] | None = None
_floating_assets: dict[str, str] = {}
_server: socketserver.TCPServer | None = None
_server_task: asyncio.Task | None = None
_request_server_count: int = 0


async def request_asset_server():
    global _request_server_count

    _request_server_count += 1

    await _start_serving_assets()


async def unrequest_asset_server():
    global _request_server_count

    _request_server_count = max(0, _request_server_count - 1)

    if _request_server_count <= 0:
        _stop_serving_assets()


async def _start_serving_assets():
    """
    Starts serving assets as specified in CONFIG.serve_assets.

    The server is automatically shut down on interpreter exit, and can optionally
    be stopped earlier using `stop_serving_assets()`.
    """

    global _server, _server_task, mounts

    from miniqa.lib.config import CONFIG  # local import to avoid circular deps
    mounts = {
        pth.split(":", 1)[-1].lstrip("./"): pth.split(":", 1)[0]
        for pth in CONFIG.serve_assets
    }

    if _server is not None or not mounts:
        return

    _server = socketserver.TCPServer(("127.0.0.1", PORT), MultiFolderHandler, bind_and_activate=False)
    _server.allow_reuse_address = True
    _server.allow_reuse_port = True
    _server.server_bind()
    _server.server_activate()

    _server_task = asyncio.create_task(asyncio.to_thread(_server.serve_forever))
    logging.info(f"[AssetServer] Assets now accessible under http://10.0.2.2:{PORT} from guest.")

    atexit.register(_stop_serving_assets)


def _stop_serving_assets():
    global _server, _server_task

    if not _server:
        return

    _server.shutdown()
    _server_task.cancel()
    _server = None


@contextlib.contextmanager
def floating_assets(assets: dict[str, str]):
    """A context manager that registers floating assets and automatically unregisters them after exit"""

    global _floating_assets

    for pth, content in assets.items():
        if pth in _floating_assets:
            raise RuntimeError(f"Asset \"{pth}\" exists already; do not reuse asset identifiers across test cases if "
                               f"you use multiple workers, since there is no automatic per-test scoping.")
        _floating_assets[pth] = content

    try:
        yield
    finally:
        for pth in assets.keys():
            del _floating_assets[pth]
