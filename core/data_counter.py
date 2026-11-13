"""Data usage accounting (Spec section 8.3 — the project's top priority).

Counts ONLY the bytes produced by Ahmed GameLink itself during checks
(requests + responses), measured at the real socket level by
core.counting_socket.

Guarantees:
- Never measures Roblox traffic or any other application.
- No Npcap, no WinDivert, no WMI network counters, no admin rights.
- Thread-safe: increments come from worker threads during diagnostics.
- `reset_check()` is called at the START of every check (8.3) while the
  session totals keep accumulating, so the UI can show both
  "last check" and "session total" separately.

Transparency note (documented, no estimation):
- TCP/TLS counts are the exact payload bytes that crossed the socket API.
  IP/TCP frame headers (~40–60 B per packet) are invisible to the socket
  API and therefore not counted — a constant, documented gap.
- ICMP counts the echo payload only (headers not exposed by IcmpSendEcho).
"""

import threading


class DataCounter:
    """Per-check + per-session byte counters, all thread-safe."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._check_sent = 0
        self._check_received = 0
        self._session_sent = 0
        self._session_received = 0

    # ----------------------------------------------------------- recording
    def add_sent(self, n: int) -> None:
        if n <= 0:
            return
        with self._lock:
            self._check_sent += n
            self._session_sent += n

    def add_received(self, n: int) -> None:
        if n <= 0:
            return
        with self._lock:
            self._check_received += n
            self._session_received += n

    # ------------------------------------------------------------- control
    def reset_check(self) -> None:
        """Spec 8.3: called at the start of EVERY check. Session totals
        are never touched here."""
        with self._lock:
            self._check_sent = 0
            self._check_received = 0

    def reset_session(self) -> None:
        with self._lock:
            self._check_sent = 0
            self._check_received = 0
            self._session_sent = 0
            self._session_received = 0

    # ------------------------------------------------------------ snapshot
    def snapshot(self) -> dict:
        """Keys are UI-facing (Spec 8.3): 'last check' + 'session total'."""
        with self._lock:
            return {
                "last_check_sent": self._check_sent,
                "last_check_received": self._check_received,
                "session_sent": self._session_sent,
                "session_received": self._session_received,
            }

    def last_check_total(self) -> int:
        with self._lock:
            return self._check_sent + self._check_received

    def session_total(self) -> int:
        with self._lock:
            return self._session_sent + self._session_received


# One process-wide counter shared by every engine module. The diagnostics
# orchestrator (Phase 3) calls reset_check() on it when a check starts.
SESSION_COUNTER = DataCounter()
