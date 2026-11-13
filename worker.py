"""DiagnosticsWorker(QThread) — the ONLY thread the app ever creates,
and only while a check runs (Spec §8.1: zero idle threads).

Lifecycle:
- created when the user presses Start Diagnostics;
- cancel() → CancelContext closes the blocked socket → run() returns
  quickly with cancelled=True;
- MainWindow.closeEvent() cancels + wait()s so nothing outlives the app
  (Spec §8.2).
"""

from PySide6.QtCore import QThread, Signal

from core.cancel import CancelContext
from core.diagnostics import run_diagnostics
from core.netdiag import run_network_diagnostics
from core.data_counter import SESSION_COUNTER


class DiagnosticsWorker(QThread):
    step_started = Signal(str)
    step_finished = Signal(object)     # StepResult
    progress_changed = Signal(int)     # 0..100
    report_ready = Signal(object)      # DiagnosticResult
    engine_error = Signal(str)         # unexpected internal failure

    def __init__(self, parent=None) -> None:
        QThread.__init__(self, parent)
        self._cancel = CancelContext()

    # -------------------------------------------------------------- cancel
    def cancel(self) -> None:
        """Immediate: closes the socket the worker is blocked on."""
        self._cancel.cancel()

    @property
    def is_cancel_requested(self) -> bool:
        return self._cancel.is_cancelled()

    # ----------------------------------------------------------------- run
    def run(self) -> None:
        try:
            result = run_diagnostics(
                self._cancel,
                counter=SESSION_COUNTER,
                on_step=lambda step_id: self.step_started.emit(step_id),
                on_step_done=lambda step: self.step_finished.emit(step),
                on_progress=lambda pct: self.progress_changed.emit(pct),
            )
            self.report_ready.emit(result)
        except Exception as exc:            # defensive: never crash the thread
            self.engine_error.emit(f"{type(exc).__name__}: {exc}")


class NetDiagWorker(QThread):
    """Runs core.run_network_diagnostics in a worker thread. Same lifecycle
    rules as DiagnosticsWorker: created on demand, killed on close."""
    target_started = Signal(str, str)     # (id, host)
    target_finished = Signal(object)      # TargetResult
    result_ready = Signal(object)         # NetDiagResult
    engine_error = Signal(str)

    def __init__(self, parent=None) -> None:
        QThread.__init__(self, parent)
        self._cancel = CancelContext()

    def cancel(self) -> None:
        self._cancel.cancel()

    def run(self) -> None:
        try:
            result = run_network_diagnostics(
                self._cancel,
                counter=SESSION_COUNTER,
                on_target=lambda tid, host: self.target_started.emit(tid, host),
                on_target_done=lambda t: self.target_finished.emit(t),
            )
            self.result_ready.emit(result)
        except Exception as exc:
            self.engine_error.emit(f"{type(exc).__name__}: {exc}")
