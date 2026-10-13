"""Fetch the pinned, hash-verified CPU sensor library used in builds."""
from __future__ import annotations

import hashlib
import io
from pathlib import Path
import urllib.request
import zipfile

VERSION = "0.9.6"
URL = ("https://github.com/LibreHardwareMonitor/LibreHardwareMonitor/"
       f"releases/download/v{VERSION}/LibreHardwareMonitor.zip")
SHA256 = "086d9f1b5a99e643edc2cfaaac16051685b551e4c5ac0b32a57c58c0e529c001"
DEST = Path(__file__).resolve().parents[1] / "assets" / "hardware-monitor"
# Exclude the standalone monitor's executable and GUI assemblies.
LIBRARIES = (
    "LibreHardwareMonitorLib.dll", "HidSharp.dll", "RAMSPDToolkit-NDD.dll",
    "DiskInfoToolkit.dll", "BlackSharp.Core.dll", "System.Memory.dll",
    "System.Runtime.CompilerServices.Unsafe.dll", "System.Buffers.dll",
    "System.Numerics.Vectors.dll",
)
NOTICES = {
    "LICENSE": "1f256ecad192880510e84ad60474eab7589218784b9a50bc7ceee34c2b91f1d5",
    "THIRD-PARTY-NOTICES.txt": "a60d5ee62f4d700caff38566f42874d554b8b530437c72804fb28b958cfbda9b",
}


def fetch() -> None:
    with urllib.request.urlopen(URL, timeout=60) as response:
        data = response.read()
    if hashlib.sha256(data).hexdigest() != SHA256:
        raise RuntimeError("SHA-256 da biblioteca de hardware não confere")
    DEST.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for name in LIBRARIES:
            (DEST / name).write_bytes(archive.read(name))
    for name, digest in NOTICES.items():
        notice_url = ("https://raw.githubusercontent.com/LibreHardwareMonitor/"
                      f"LibreHardwareMonitor/v{VERSION}/{name}")
        with urllib.request.urlopen(notice_url, timeout=30) as response:
            notice = response.read()
        if hashlib.sha256(notice).hexdigest() != digest:
            raise RuntimeError(f"SHA-256 da licença {name} não confere")
        (DEST / name).write_bytes(notice)
    print(f"LibreHardwareMonitor {VERSION}: {len(LIBRARIES)} bibliotecas verificadas")


if __name__ == "__main__":
    fetch()
