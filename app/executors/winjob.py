"""Windows Job Objects: a handle on a process and everything it starts.

A plain process handle only reaches the shell. Its children survive `taskkill`
once the shell has exited, and survive this server crashing. A job with
kill-on-close ends them all when it is terminated or when its last handle
closes, which happens by itself when this process dies.
"""

import ctypes
import sys
from ctypes import wintypes

_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
_KILL_ON_JOB_CLOSE = 0x2000


class _BasicLimits(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _IoCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint64) for name in (
        "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
        "ReadTransferCount", "WriteTransferCount", "OtherTransferCount",
    )]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _BasicLimits),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


class Job:
    """A kill-on-close job holding one process tree."""

    def __init__(self, handle: int):
        self._handle: int | None = handle

    @classmethod
    def for_process(cls, process_handle: int) -> "Job | None":
        """Put a running process into a new job; None if Windows refuses."""
        if sys.platform != "win32":
            return None
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel32.SetInformationJobObject.argtypes = [
            wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel32.CreateJobObjectW(None, None)
        if not handle:
            return None
        limits = _ExtendedLimits()
        limits.BasicLimitInformation.LimitFlags = _KILL_ON_JOB_CLOSE
        configured = kernel32.SetInformationJobObject(
            handle, _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(limits), ctypes.sizeof(limits))
        if not configured or not kernel32.AssignProcessToJobObject(handle, process_handle):
            kernel32.CloseHandle(handle)
            return None
        return cls(handle)

    def terminate(self) -> None:
        """End every process in the job and release it. Safe to call again."""
        if self._handle is None or sys.platform != "win32":
            return
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.TerminateJobObject(self._handle, 1)
        kernel32.CloseHandle(self._handle)
        self._handle = None


def resume(process_handle: int) -> bool:
    """Let a process started suspended (`host.SUSPENDED`) run; False if Windows refused. One
    that runs already is left as it is. (Popen keeps no handle on its first thread for
    ResumeThread; NtResumeProcess - as psutil's resume() - needs none.)"""
    ntdll = ctypes.WinDLL("ntdll")
    ntdll.NtResumeProcess.argtypes = [wintypes.HANDLE]
    return ntdll.NtResumeProcess(process_handle) == 0  # STATUS_SUCCESS
