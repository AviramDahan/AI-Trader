"""Prepare an explicitly probed per-process CUDA backend; never start a daemon.

For the shared daemon OWNER's next reviewed startup, not gateway health checks.
No model, driver, registry, Windows environment or resource-limit changes.
"""
import os
from pathlib import Path
import re
import subprocess


def environment(ollama_exe, original, *, backend='cuda_v13', run=subprocess.run):
    if backend not in {'cuda_v12','cuda_v13'}:
        raise ValueError('unsupported_cuda_backend')
    root=Path(ollama_exe).resolve().parent/'lib'/'ollama'
    library=root/backend/'ggml-cuda.dll'
    runner=root/'llama-server.exe'
    if not library.is_file() or not runner.is_file():
        raise ValueError('cuda_backend_files_missing')
    old=original.get('GGML_BACKEND_PATH')
    if old and Path(old).resolve()!=library.resolve():
        raise ValueError('existing_backend_override_conflict')
    candidate={**original,'GGML_BACKEND_PATH':str(library),
               'PATH':str(library.parent)+os.pathsep+str(root)+os.pathsep+original.get('PATH','')}
    # Device enumeration is model-free. Failure never silently starts CPU work.
    result=run([str(runner),'--list-devices'],env=candidate,capture_output=True,
               text=True,timeout=15)
    if result.returncode or not re.search(r'^\s*CUDA\d+:\s+\S',result.stdout,re.M):
        raise ValueError('explicit_cuda_device_not_verified')
    return candidate
