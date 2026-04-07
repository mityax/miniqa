import asyncio
import glob
import logging
import os
import shutil
import sys
import time
from asyncio.subprocess import Process
from typing import Any, IO

from miniqa.lib.config import CONFIG, RUNTIME_TMPDIR
from miniqa.lib.qemu.qemu_utils import detect_disk_image_format, convert_raw_image_to_qcow2, create_overlay_qcow2_image, \
    list_image_snapshots, check_kvm
from miniqa.lib.qemu.qmp import QMP


class QEMUWorker:
    _kvm_ok = check_kvm()
    _wid_counter = 0

    def __init__(self, use_overlay: bool = True):
        # Ensure we get a unique integer worker id, not used by another worker:
        while glob.glob(os.path.join(os.path.dirname(RUNTIME_TMPDIR), '*', f'worker-{QEMUWorker._wid_counter}-*')):
            QEMUWorker._wid_counter += 1

        self.wid = QEMUWorker._wid_counter
        self.use_overlay = use_overlay
        self.image = CONFIG.image
        self.qmp_port = 4444 + self.wid

        self.priv_tmpdir = os.path.join(RUNTIME_TMPDIR, f"worker-{self.wid}-{time.time()}")
        self.disks_dir = os.path.join(self.priv_tmpdir, "disks")

        self.overlay = os.path.join(self.disks_dir, "overlay.qcow2")
        self.ovmf_vars = os.path.join(self.disks_dir, 'OVMF_VARS.qcow2')

        self.proc: Process | None = None
        self.qmp: QMP | None = None

        self.snapshots = set()

        self.__create_dirs()

    async def start(self,
                    initial_snapshot: str | None = None,
                    enable_vnc: bool = False,
                    stdout: int | IO[Any] | None = asyncio.subprocess.PIPE,
                    stderr: int | IO[Any] | None = None):
        self.__create_dirs()

        if self.use_overlay:
            await self.__create_overlay()

        # In case the overlay existed already (i.e. was created before start externally), check existing snapshots:
        self.snapshots = set(await list_image_snapshots(self.overlay))

        cmd = [
            "qemu-system-x86_64",
            "-m", "4G",
            "-smp", "4",
            "-cpu", f"{'host' if QEMUWorker._kvm_ok else 'max'}",
            "-machine", f"q35,accel={'kvm' if QEMUWorker._kvm_ok else 'tcg'}",
            "-drive", f"file={self.overlay if self.use_overlay else self.image},if=virtio",  # ,format={'qcow2' if self.use_overlay else await detect_disk_image_format(self.image)}
            "-qmp", f"tcp:127.0.0.1:{self.qmp_port},server,nowait",
            "-display", "none" if CONFIG.headless or enable_vnc else "gtk",
            *CONFIG.qemu_args,
        ]

        if CONFIG.use_ovmf:
            code_pth, vars_pth = await self._setup_ovmf()
            cmd.extend((
                "-drive", f"if=pflash,format=raw,readonly=on,file={code_pth}",
                "-drive", f"if=pflash,format=qcow2,file={vars_pth}",
            ))

        if initial_snapshot:
            cmd.extend(("-loadvm", initial_snapshot))

        if enable_vnc:
            cmd.extend(('-vnc', f':0,to=99'))

        logging.info(f"[Worker {self.wid}] Booting{' using snapshot ' + initial_snapshot if initial_snapshot else ''}: `{' '.join(cmd)}`")

        self.proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=stdout or sys.stdout,
            stderr=stderr or sys.stderr,
        )

        asyncio.create_task(self.__stop_when_process_completed(self.proc))

        await asyncio.sleep(1)

        self.qmp = await QMP.connect(port=self.qmp_port)

    async def _setup_ovmf(self) -> str | None:
        code_pth = (
            next((f for f in CONFIG.use_ovmf.code_path if os.path.isfile(f)), None)
            if isinstance(CONFIG.use_ovmf.code_path, list)
            else CONFIG.use_ovmf.code_path
        )
        vars_src_pth = (
            next((f for f in CONFIG.use_ovmf.vars_path if os.path.isfile(f)), None)
            if isinstance(CONFIG.use_ovmf.vars_path, list)
            else CONFIG.use_ovmf.vars_path
        )

        if code_pth is None:
            raise RuntimeError(f"Could not find OVMF code at {CONFIG.use_ovmf.code_path}")
        if vars_src_pth is None:
            raise RuntimeError(f"Could not find OVMF code at {CONFIG.use_ovmf.vars_path}")

        if not os.path.exists(self.ovmf_vars):
            if await detect_disk_image_format(vars_src_pth) != 'qcow2':
                await convert_raw_image_to_qcow2(vars_src_pth, self.ovmf_vars)
            else:
                await asyncio.to_thread(shutil.copy, vars_src_pth, self.ovmf_vars)

        return code_pth, self.ovmf_vars

    def __create_dirs(self):
        os.makedirs(self.priv_tmpdir, exist_ok=True)
        os.makedirs(self.disks_dir, exist_ok=True)

    async def __create_overlay(self):
        if os.path.exists(self.overlay):
            return

        await create_overlay_qcow2_image(
            pth=self.overlay,
            backing_img=os.path.abspath(self.image),
        )

    async def save_snapshot(self, tag: str):
        res = await self.qmp.cmd("human-monitor-command", {"command-line": f"savevm {tag}"})

        if 'error' in res:
            raise RuntimeError(f"Failed to create snapshot {tag}: ", res)

        self.snapshots.add(tag)

    async def load_snapshot(self, tag: str):
        res = await self.qmp.cmd("human-monitor-command", {"command-line": f"loadvm {tag}"})
        await asyncio.sleep(1)

    async def clone(self):
        worker = self.__class__()
        worker.snapshots = self.snapshots.copy()

        await asyncio.to_thread(shutil.copy, self.overlay, worker.overlay)

        if CONFIG.use_ovmf:
            await asyncio.to_thread(shutil.copy, self.ovmf_vars, worker.ovmf_vars)

        return worker

    @property
    def is_ready(self):
        return self.proc is not None and self.qmp is not None and self.proc.returncode is None

    async def query_vnc_port(self) -> int | None:
        res = await self.qmp.cmd("query-vnc")
        port = res.get('return', {}).get('service')
        return int(port)

    async def stop(self):
        """Shut down a worker"""
        if self.qmp:
            self.qmp.stop()

        if self.proc:
            self.proc.terminate()
            await self.proc.wait()
            self.proc = None

    async def destroy(self):
        """Stops the worker and deletes its temporary files (notably the disk, including snapshots)"""
        await self.stop()
        self.snapshots.clear()
        await asyncio.to_thread(shutil.rmtree, self.priv_tmpdir, ignore_errors=True)

    async def __stop_when_process_completed(self, proc):
        await proc.wait()
        if proc.returncode == 0:
            logging.debug(f"[Worker {self.wid}] QEMU exited normally: {proc.returncode}")
        else:
            logging.warning(f"[Worker {self.wid}] QEMU exited with nonzero exit code: {proc.returncode}")

        self.proc = None

        if self.qmp is not None:
            self.qmp.stop()

    async def wait_exit(self):
        await self.proc.wait()

