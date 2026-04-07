import asyncio
import json
import os
from typing import Literal


async def detect_disk_image_format(image: str) -> Literal['raw', 'qcow2'] | str:
    proc = await asyncio.create_subprocess_exec(
        "qemu-img", "info", "--output=json", image,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        raise RuntimeError(f"qemu-img info failed ({proc.returncode}): {stderr.decode().strip()}")

    return json.loads(stdout)["format"]


async def convert_raw_image_to_qcow2(image: str, dst: str) -> None:
    proc = await asyncio.create_subprocess_exec(
        "qemu-img", "convert", "-f", "raw", "-O", "qcow2", image, dst
    )
    await proc.wait()

    if proc.returncode != 0:
        raise RuntimeError(f"qemu-img convert failed with exit code: {proc.returncode}")


async def create_overlay_qcow2_image(pth: str, backing_img: str) -> None:
    proc = await asyncio.create_subprocess_exec(
        "qemu-img",
        "create",
        "--format", "qcow2",
        "--backing", backing_img,
        "--backing-format", await detect_disk_image_format(backing_img),
        pth,
        stdout=asyncio.subprocess.DEVNULL,
    )

    await proc.wait()

    if proc.returncode != 0:
        raise RuntimeError(f"qemu-img create failed with exit code: {proc.returncode}")


async def list_image_snapshots(image: str) -> list[str]:
    proc = await asyncio.create_subprocess_exec(
        "qemu-img", "info", "--output=json", image,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        raise RuntimeError(f"qemu-img info failed ({proc.returncode}): {stderr.decode().strip()}")

    return [sc["name"] for sc in json.loads(stdout).get("snapshots", ())]


def check_kvm():
    kvm_path = os.environ.get("KVM_PATH", "/dev/kvm")
    return os.path.exists(kvm_path) and os.access(kvm_path, os.R_OK | os.W_OK)
