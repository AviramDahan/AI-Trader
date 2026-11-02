"""Model-free subprocess contract doubles, not live GPU generation proof."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import pytest

def module():
    p=Path(__file__).resolve().parents[3]/'scripts/ollama_gpu_environment.py'
    spec=importlib.util.spec_from_file_location('gpu_env',p)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def test_per_process_environment_preserves_all_existing_guards(tmp_path):
    m=module();root=tmp_path/'lib'/'ollama';(root/'cuda_v13').mkdir(parents=True)
    (root/'cuda_v13/ggml-cuda.dll').touch();(root/'llama-server.exe').touch()
    original={'PATH':'old','OLLAMA_NUM_PARALLEL':'1','OLLAMA_MAX_LOADED_MODELS':'1',
              'CUDA_VISIBLE_DEVICES':'0','LLAMA_ARG_CACHE_RAM':'1024'}
    run=Mock(return_value=SimpleNamespace(returncode=0,stdout='Available devices:\n CUDA0: NVIDIA RTX\n'))
    result=m.environment(tmp_path/'ollama.exe',original,run=run)
    assert original['PATH']=='old' and 'GGML_BACKEND_PATH' not in original
    assert all(result[k]==v for k,v in original.items() if k!='PATH')
    assert run.call_args.args[0][-1]=='--list-devices'
    assert run.call_args.kwargs['timeout']==15
    run.return_value.stdout='Available devices:\n (none)'
    with pytest.raises(ValueError,match='not_verified'):m.environment(tmp_path/'ollama.exe',original,run=run)
