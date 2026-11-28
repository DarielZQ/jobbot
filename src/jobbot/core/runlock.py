"""One search at a time across processes (ADR-035).

The scheduled run and the panel's «Buscar ahora» are separate processes: at the same time they
would both insert the same new job, and the second insert fails as if the site had changed.
The second search waits for the first instead. The operating system releases the lock when the
process that holds it ends, even if it crashed, so a stale lock never blocks the searches.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import IO


def _try_lock(handle: IO[bytes]) -> bool:
    try:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


def _unlock(handle: IO[bytes]) -> None:
    if os.name == "nt":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle, fcntl.LOCK_UN)


@contextmanager
def exclusive(
    path: Path | None,
    wait_s: float = 30 * 60,
    poll_s: float = 2.0,
    sleep: Callable[[float], None] = time.sleep,
) -> Iterator[bool]:
    """Hold `path` as a lock; yields whether it was held. After `wait_s` without it the search
    goes ahead anyway: a search that hangs must not stop every later one. `path` None: no lock
    (an in-memory database)."""
    if path is None:
        yield True
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        deadline = time.monotonic() + wait_s
        locked = _try_lock(handle)
        while not locked and time.monotonic() < deadline:
            sleep(poll_s)
            locked = _try_lock(handle)
        try:
            yield locked
        finally:
            if locked:
                _unlock(handle)
