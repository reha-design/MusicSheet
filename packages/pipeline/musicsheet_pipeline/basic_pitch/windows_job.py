"""Windows process ownership through a private, non-inheritable Job Object."""
import ctypes as C
import os
from ctypes import wintypes as W


class _Limits(C.Structure):
    _fields_ = [("user", C.c_int64), ("job_user", C.c_int64), ("flags", W.DWORD),
        ("min_ws", C.c_size_t), ("max_ws", C.c_size_t), ("active", W.DWORD),
        ("affinity", C.c_size_t), ("priority", W.DWORD), ("scheduling", W.DWORD)]


class _IO(C.Structure):
    _fields_ = [(name, C.c_uint64) for name in ("read", "write", "other", "read_bytes", "write_bytes", "other_bytes")]


class _ExtendedLimits(C.Structure):
    _fields_ = [("basic", _Limits), ("io", _IO), ("process_memory", C.c_size_t),
        ("job_memory", C.c_size_t), ("peak_process", C.c_size_t), ("peak_job", C.c_size_t)]


class _Accounting(C.Structure):
    _fields_ = [("user", C.c_int64), ("kernel", C.c_int64), ("period_user", C.c_int64),
        ("period_kernel", C.c_int64), ("faults", W.DWORD), ("total", W.DWORD),
        ("active", W.DWORD), ("terminated", W.DWORD)]


class WindowsJob:
    def __init__(self):
        if os.name != "nt":
            raise OSError("Process ownership is unavailable")
        self.kernel = C.WinDLL("kernel32", use_last_error=True)
        signatures = {
            "CreateJobObjectW": ([C.c_void_p, W.LPCWSTR], W.HANDLE),
            "SetInformationJobObject": ([W.HANDLE, C.c_int, C.c_void_p, W.DWORD], W.BOOL),
            "OpenProcess": ([W.DWORD, W.BOOL, W.DWORD], W.HANDLE),
            "AssignProcessToJobObject": ([W.HANDLE, W.HANDLE], W.BOOL),
            "TerminateJobObject": ([W.HANDLE, W.UINT], W.BOOL),
            "QueryInformationJobObject": ([W.HANDLE, C.c_int, C.c_void_p, W.DWORD, C.c_void_p], W.BOOL),
            "CloseHandle": ([W.HANDLE], W.BOOL),
        }
        for name, (args, result) in signatures.items():
            function = getattr(self.kernel, name)
            function.argtypes, function.restype = args, result
        self.handle = self.kernel.CreateJobObjectW(None, None)
        if not self.handle:
            raise OSError("Process ownership is unavailable")
        limits = _ExtendedLimits()
        limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE; no breakaway.
        if not self.kernel.SetInformationJobObject(self.handle, 9, C.byref(limits), C.sizeof(limits)):
            self.close()
            raise OSError("Process ownership is unavailable")

    def assign(self, pid):
        process = self.kernel.OpenProcess(0x0101, False, pid)  # SET_QUOTA | TERMINATE
        if not process:
            raise OSError("Process ownership is unavailable")
        try:
            if not self.kernel.AssignProcessToJobObject(self.handle, process):
                raise OSError("Process ownership is unavailable")
        finally:
            self.kernel.CloseHandle(process)

    def terminate(self):
        if not self.kernel.TerminateJobObject(self.handle, 1):
            raise OSError("Process cleanup failed")

    def active_process_count(self):
        accounting = _Accounting()
        if not self.kernel.QueryInformationJobObject(self.handle, 1, C.byref(accounting), C.sizeof(accounting), None):
            raise OSError("Process cleanup failed")
        return accounting.active

    def close(self):
        if self.handle:
            handle, self.handle = self.handle, None
            if not self.kernel.CloseHandle(handle):
                raise OSError("Process cleanup failed")
