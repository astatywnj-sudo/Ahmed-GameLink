"""Cancellation: cooperative + aggressive, so Cancel really is immediate.

Two layers (Spec §5: Cancel button must work instantly):
1. Cooperative — the orchestrator checks `is_cancelled()` between steps
   and between endpoints.
2. Aggressive — the UI thread calls cancel() while the worker may be
   BLOCKED inside connect()/recv()/recvfrom(). We close the registered
   socket from the cancelling thread; CPython then raises OSError in the
   blocked call within ~100 ms. The engine maps that to 'cancelled'.

No polling loops, no timers: registration is push-based, and only the
socket that is actually blocking gets closed.
"""

import threading
from contextlib import contextmanager


class OperationCancelled(Exception):
    """Raised/converted to the 'cancelled' error code by the engine."""


CANCELLED = "cancelled"          # shared error code used across the engine


class CancelContext:
    def __init__(self) -> None:
        self._event = threading.Event()
        self._lock = threading.Lock()
        self._sockets: list = []          # sockets possibly blocking right now

    # ------------------------------------------------------------- control
    def cancel(self) -> None:
        """Immediate: sets the flag AND unblocks any stuck socket I/O."""
        self._event.set()
        with self._lock:
            targets = list(self._sockets)
        for sock in targets:
            try:
                sock.close()
            except OSError:
                pass

    def is_cancelled(self) -> bool:
        return self._event.is_set()

    # ------------------------------------------------------- registration
    @contextmanager
    def register(self, sock):
        """Mark `sock` as 'may block right now'. While registered, cancel()
        closes it to break the block. Unregistered automatically."""
        with self._lock:
            self._sockets.append(sock)
        try:
            yield sock
        finally:
            with self._lock:
                try:
                    self._sockets.remove(sock)
                except ValueError:
                    pass

    def check(self) -> None:
        """Raise immediately when cancelled (used between steps)."""
        if self._event.is_set():
            raise OperationCancelled()
