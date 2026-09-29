"""Thread-local progress reporting for long-running ingestion steps (video analysis, repo scans).
The job runner installs a callback; adapters just call report("...")."""
from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Callable, Optional

_local = threading.local()


@contextmanager
def progress_to(cb: Callable[[str], None]):
    prev = getattr(_local, "cb", None)
    _local.cb = cb
    try:
        yield
    finally:
        _local.cb = prev


def report(message: str) -> None:
    cb: Optional[Callable[[str], None]] = getattr(_local, "cb", None)
    if cb:
        try:
            cb(message)
        except Exception:
            pass
