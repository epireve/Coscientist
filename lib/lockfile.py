"""v0.13 — fcntl-based artifact lock for concurrency control.

Two skills running concurrently against the same paper artifact (or
manuscript) can race on manifest.json or other writes. This module
provides a context manager that acquires an exclusive flock on a
sidecar `.lock` file in the artifact directory.

Usage:
    from lib.lockfile import artifact_lock
    with artifact_lock(art.root):
        # exclusive access; other holders block here
        m = art.load_manifest()
        m.state = State.acquired
        art.save_manifest(m)

If the OS lacks fcntl (Windows), the lock falls back to a polling
loop on a marker file with the same blocking semantics.
"""

from __future__ import annotations

import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

try:
    import fcntl
    _HAVE_FCNTL = True
except ImportError:
    _HAVE_FCNTL = False


class LockTimeout(Exception):
    """Raised when waiting for an artifact lock exceeds the timeout."""


@contextmanager
def artifact_lock(artifact_dir: Path, timeout: float = 60.0,
                  poll_interval: float = 0.1) -> Iterator[Path]:
    """Acquire an exclusive lock on an artifact directory.

    Blocks up to `timeout` seconds. Raises LockTimeout if the lock
    can't be obtained.
    """
    artifact_dir = Path(artifact_dir)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    lock_path = artifact_dir / ".lock"

    if _HAVE_FCNTL:
        # fcntl path: open the lockfile, request exclusive non-blocking
        # lock, retry until timeout if held.
        deadline = time.monotonic() + timeout
        fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o644)
        try:
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise LockTimeout(
                            f"timeout acquiring lock on {artifact_dir}"
                        )
                    time.sleep(poll_interval)
            try:
                # Record holder PID for debug
                os.write(fd, f"{os.getpid()}\n".encode())
                yield lock_path
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)
    else:
        # Fallback: marker file with mtime-based polling
        deadline = time.monotonic() + timeout
        while lock_path.exists():
            if time.monotonic() >= deadline:
                raise LockTimeout(f"timeout acquiring lock on {artifact_dir}")
            time.sleep(poll_interval)
        lock_path.write_text(f"{os.getpid()}\n")
        try:
            yield lock_path
        finally:
            try:
                lock_path.unlink()
            except FileNotFoundError:
                pass
