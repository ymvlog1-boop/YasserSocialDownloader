"""Windows job objects keep FFmpeg children inside the task lifetime."""
import ctypes,os
from ctypes import wintypes

class ProcessTree:
    def __init__(self,pid):
        self.handle=None
        if os.name!='nt':return
        k=ctypes.WinDLL('kernel32',use_last_error=True);self.k=k
        k.CreateJobObjectW.restype=wintypes.HANDLE;k.CreateJobObjectW.argtypes=[ctypes.c_void_p,wintypes.LPCWSTR]
        k.OpenProcess.restype=wintypes.HANDLE;k.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
        k.CloseHandle.argtypes=[wintypes.HANDLE]
        k.AssignProcessToJobObject.argtypes=[wintypes.HANDLE,wintypes.HANDLE]
        k.SetInformationJobObject.argtypes=[wintypes.HANDLE,ctypes.c_int,ctypes.c_void_p,wintypes.DWORD]
        class Basic(ctypes.Structure):
            _fields_=[('per_process',ctypes.c_int64),('per_job',ctypes.c_int64),('flags',wintypes.DWORD),('minimum',ctypes.c_size_t),('maximum',ctypes.c_size_t),('active',wintypes.DWORD),('affinity',ctypes.c_size_t),('priority',wintypes.DWORD),('scheduling',wintypes.DWORD)]
        class IO(ctypes.Structure):_fields_=[(n,ctypes.c_uint64) for n in ['read_ops','write_ops','other_ops','read_bytes','write_bytes','other_bytes']]
        class Extended(ctypes.Structure):_fields_=[('basic',Basic),('io',IO),('process_memory',ctypes.c_size_t),('job_memory',ctypes.c_size_t),('peak_process',ctypes.c_size_t),('peak_job',ctypes.c_size_t)]
        job=k.CreateJobObjectW(None,None);info=Extended();info.basic.flags=0x2000
        process=k.OpenProcess(0x0100|0x0001,False,pid)
        try:
            if job and process and k.SetInformationJobObject(job,9,ctypes.byref(info),ctypes.sizeof(info)) and k.AssignProcessToJobObject(job,process):self.handle=job
            elif job:k.CloseHandle(job)
        finally:
            if process:k.CloseHandle(process)
    def close(self):
        if self.handle:self.k.CloseHandle(self.handle);self.handle=None
