import asyncio
import json
import logging
import os
import random
import time
from typing import Coroutine, Any, Callable

from miniqa.lib.config import RUNTIME_TMPDIR
from miniqa.lib.utils import timed_cached_property


class QMP:
    """
    A QMP protocol handler along with some basic QMP-powered VM utilities.
    """

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self.reader = reader
        self.writer = writer

        self._recv_task: Coroutine[Any, Any, Any | None]
        self._recv_callbacks: dict[str, Callable[[dict], None]] = {}

        self._recv_loop_task = asyncio.create_task(self._recv_loop())

    @staticmethod
    async def connect(host="127.0.0.1", port=4444, max_attempts: int = 5) -> 'QMP':
        for i in range(max_attempts):
            try:
                reader, writer = await asyncio.open_connection(host, port)
                break
            except ConnectionRefusedError as e:
                if i == max_attempts - 1:
                    raise ConnectionRefusedError(f"Could not connect to QMP at port {host}:{port} after {i+1} retries") from e
                time.sleep(i + 1)  # primitive exponential-backoff-style retries

        logging.debug(f"QEMU greeting: {await reader.readline()}")

        qmp = QMP(reader, writer)
        await qmp.cmd("qmp_capabilities")

        return qmp

    async def cmd(self, command: str, arguments: dict[str, Any] | None = None):
        return await self.send_raw({
            "execute": command,
            "arguments": arguments or {},
        })

    async def input(self, events):
        await self.cmd("input-send-event", {
            "events": events,
        })

    async def screendump(self, path: str | None = None):
        path = path or os.path.join(RUNTIME_TMPDIR, f'qmp-screendump-{time.time()}-{random.random()}.ppm')
        await self.cmd("screendump", {"filename": path})
        return path

    async def query_screen_size(self):
        fn = os.path.join(RUNTIME_TMPDIR, f"query-screensize-{time.time()}.ppm")
        await self.screendump(fn)
        with open(fn, 'rb') as f:
            if f.readline().strip() != b"P6": raise RuntimeError(f"QEMU created a non-PPM screenshot: {fn}")
            w, h = f.readline().strip().split()
        os.remove(fn)
        return int(w), int(h)

    @timed_cached_property(ttl=5)
    async def screen_size(self):
        return await self.query_screen_size()

    async def send_raw(self, obj: dict):
        id_ = obj.get('id', f'{obj.get('execute', 'cmd')}_{time.time()}_{random.random()}')

        payload = json.dumps({
            'id': id_,
            **obj,
        }).encode() + b"\n"

        logging.debug(f"[QMP] -> {payload.decode().strip()}")
        self.writer.write(payload)

        future = asyncio.get_running_loop().create_future()

        self._recv_callbacks[id_] = future.set_result

        result = await future

        if 'error' in result:
            raise QMPError(f"QMP returned an error:\nCommand: {obj}\n{result['error']['class']}: {result['error']['desc']}")
        else:
            logging.debug(f"[QMP] <- {result}")
        return result

    async def _recv(self):
        # QMP makes no guarantees about when a message ends, so we just read until there's a
        # valid JSON object in the buffer.

        msg = b""

        while len(msg) < 65536:  # set a hard limit for message length; just in case
            try:
                char = await self.reader.read(1)
            except ConnectionResetError:
                return None

            if not char:
                return None

            msg += char
            try:
                return json.loads(msg.strip())
            except json.JSONDecodeError:
                continue

        logging.warning("Warning: Received more than 65536 chars from QEMU without a valid JSON object: ", msg)
        return None

    async def _recv_loop(self):
        while True:
            recv = self._recv()
            self._recv_task = asyncio.create_task(recv)

            try:
                msg = await self._recv_task
            except asyncio.CancelledError:
                self.writer.close()
                break

            if not msg:
                break

            # Handle expected responses (e.g. command results):
            if 'id' in msg and msg['id'] in self._recv_callbacks:
                self._recv_callbacks.pop(msg['id'])(msg)
            # Handle QMP events (sent on QEMU's initiative):
            elif 'event' in msg:
                logging.debug(f"QEMU Event: {msg}")
            else:
                logging.debug(f"Received an unexpected message from QMP: {msg}")

    def stop(self):
        self._recv_loop_task.cancel()
        self.writer.close()
        self.reader.feed_eof()


class QMPError(RuntimeError):
    pass
