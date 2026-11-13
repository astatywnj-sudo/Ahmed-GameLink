"""Final idle-resource measurement (Spec §8.1) — headless."""
import ctypes
import ctypes.wintypes as wt
import os
import sys
import threading
import time

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PySide6.QtWidgets import QApplication

import i18n
from app_state import AppState
from ui.main_window import MainWindow

app = QApplication([])
i18n.load("ar")
w = MainWindow(AppState())
w.show()
for _ in range(10):
    app.processEvents()
time.sleep(0.3)


class PMC(ctypes.Structure):
    _fields_ = [("cb", wt.DWORD), ("PageFaultCount", wt.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t)]


pmc = PMC()
pmc.cb = ctypes.sizeof(PMC)
k32 = ctypes.WinDLL("kernel32")
k32.GetCurrentProcess.restype = wt.HANDLE
h = k32.GetCurrentProcess()
psapi = ctypes.WinDLL("psapi")
psapi.GetProcessMemoryInfo.argtypes = [wt.HANDLE, ctypes.POINTER(PMC), wt.DWORD]
psapi.GetProcessMemoryInfo.restype = wt.BOOL
psapi.GetProcessMemoryInfo(h, ctypes.byref(pmc), pmc.cb)

print(f"FINAL idle RAM: {pmc.WorkingSetSize / 1048576:.1f} MB  (limit 80 MB)")
print(f"threads alive: {threading.active_count()}  (limit 1)")
w.close()
