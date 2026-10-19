"""Reviewer-owned native Linux process/FD controls; no Docker/network/service IO.

CI runs as an unprivileged user. Only the root-owned-file precondition is
doubled; device/inode, open file descriptions, flock, signals and children are
real. Windows skips these controls rather than claiming native flock evidence.
"""
import importlib.util
import json
import os
from pathlib import Path
import select
import stat
import subprocess
import sys
from types import SimpleNamespace

import pytest


pytestmark = pytest.mark.skipif(os.name == "nt", reason="Native Linux flock/FD/signal evidence requires Linux CI")
ROOT = Path(__file__).resolve().parents[3]
PULL = ROOT / "deploy/hetzner-pull.py"
SHA = "a" * 40
IMAGE = "sha256:" + "b" * 64


class RootOwnedLockPrecondition:
    def __init__(self, path):
        self.path = Path(path)

    def __fspath__(self):
        return str(self.path)

    def lstat(self):
        row = self.path.lstat()
        return SimpleNamespace(st_mode=stat.S_IFREG | 0o600, st_uid=0,
                               st_dev=row.st_dev, st_ino=row.st_ino)


def load_pull(tmp_path):
    spec = importlib.util.spec_from_file_location("reviewer_native_pull", PULL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.ROOT = tmp_path
    module.WORK_PARENT = tmp_path
    module.LOCK = RootOwnedLockPrecondition(tmp_path / "release.lock")
    return module


CHILD_PREFIX = r'''
import importlib.util,json,os,signal,stat,sys,time
from pathlib import Path
from types import SimpleNamespace
source,workspace=sys.argv[1:3]
spec=importlib.util.spec_from_file_location('reviewer_child_pull',source)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
root=Path(workspace);m.ROOT=root;m.WORK_PARENT=root
class RootOwned:
 def __fspath__(self):return str(root/'release.lock')
 def lstat(self):
  row=(root/'release.lock').lstat()
  return SimpleNamespace(st_mode=stat.S_IFREG|0o600,st_uid=0,st_dev=row.st_dev,st_ino=row.st_ino)
m.LOCK=RootOwned()
'''


def child_command(tmp_path, body):
    return [sys.executable, "-B", "-c", CHILD_PREFIX + body, str(PULL), str(tmp_path)]


def child_env():
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    env.pop("AI_TRADER_DEPLOY_LOCK_FD", None)
    return env


def test_real_parent_child_inherited_description_and_competing_open(tmp_path, monkeypatch):
    pull = load_pull(tmp_path)
    monkeypatch.delenv("AI_TRADER_DEPLOY_LOCK_FD", raising=False)
    real_popen = subprocess.Popen
    launches = []

    def synthetic_deploy(command, *, pass_fds, start_new_session, env):
        assert command == ["/usr/local/sbin/ai-trader-deploy", SHA]
        assert len(pass_fds) == 1 and env["AI_TRADER_DEPLOY_LOCK_FD"] == str(pass_fds[0])
        assert start_new_session is True
        launches.append(command)
        return real_popen(child_command(tmp_path, "\nwith m.deployment_lock():\n print('INHERITED_LOCK_VERIFIED',flush=True)\n"),
                          pass_fds=pass_fds, start_new_session=start_new_session, env=env,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    with pull.deployment_lock() as descriptor:
        monkeypatch.setattr(pull.subprocess, "Popen", synthetic_deploy)
        assert pull.launch_deploy(SHA, descriptor) == 0
        monkeypatch.setattr(pull.subprocess, "Popen", real_popen)
        result = subprocess.run(child_command(tmp_path, "\ntry:\n with m.deployment_lock():raise AssertionError('separate description entered')\nexcept m.Busy:sys.exit(75)\n"),
                                env=child_env(), capture_output=True, timeout=10)
        assert result.returncode == 75, result.stderr.decode()
    assert len(launches) == 1
    result = subprocess.run(child_command(tmp_path, "\nwith m.deployment_lock():print('RELEASED_LOCK_AVAILABLE')\n"),
                            env=child_env(), capture_output=True, timeout=10)
    assert result.returncode == 0 and b"RELEASED_LOCK_AVAILABLE" in result.stdout


@pytest.mark.parametrize("target_sha", [SHA, "c" * 40])
def test_real_contenders_same_and_different_sha_cannot_enter_or_latch(tmp_path, monkeypatch, target_sha):
    pull = load_pull(tmp_path)
    monkeypatch.delenv("AI_TRADER_DEPLOY_LOCK_FD", raising=False)
    original = "d" * 40 + "\n"
    (tmp_path / "failed-release").write_text(original)
    body = "\ndef forbidden_poll(fd):\n (root/'failed-release').write_text(" + repr(target_sha) + ")\n raise AssertionError('contender entered poll')\nm.poll=forbidden_poll\nm.main([])\n"
    with pull.deployment_lock():
        result = subprocess.run(child_command(tmp_path, body), env=child_env(), capture_output=True, timeout=10)
    assert result.returncode == 75, result.stderr.decode()
    assert (tmp_path / "failed-release").read_text() == original
    assert not (tmp_path / "deployment-attempt.json").exists()
    assert not (tmp_path / "last-release").exists()


@pytest.mark.parametrize("invalid_fd", ["closed", "unrelated", "separate_contended"])
def test_real_inherited_fd_cannot_bypass_identity_or_lock(tmp_path, monkeypatch, invalid_fd):
    pull = load_pull(tmp_path)
    monkeypatch.delenv("AI_TRADER_DEPLOY_LOCK_FD", raising=False)
    with pull.deployment_lock():
        if invalid_fd == "closed":
            closed = os.open(tmp_path / "closed.lock", os.O_RDWR | os.O_CREAT, 0o600)
            os.close(closed)
            monkeypatch.setenv("AI_TRADER_DEPLOY_LOCK_FD", str(closed))
            with pytest.raises(OSError):
                with pull.deployment_lock():
                    pytest.fail("closed descriptor accepted")
        else:
            path = tmp_path / ("unrelated.lock" if invalid_fd == "unrelated" else "release.lock")
            descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
            try:
                monkeypatch.setenv("AI_TRADER_DEPLOY_LOCK_FD", str(descriptor))
                expected = ValueError if invalid_fd == "unrelated" else pull.Busy
                with pytest.raises(expected):
                    with pull.deployment_lock():
                        pytest.fail("forged or contending descriptor accepted")
            finally:
                os.close(descriptor)


def test_real_hard_kill_keeps_attempt_and_refuses_blind_retry(tmp_path, monkeypatch):
    pull = load_pull(tmp_path)
    monkeypatch.delenv("AI_TRADER_DEPLOY_LOCK_FD", raising=False)
    # Only Docker IO is synthetic. Canonical verify_container, durable journal,
    # inherited lock/inode operations and real SIGKILL remain actual code.
    proof = dict(version=1, kind='classic', runnable_ref=IMAGE, platform='linux/amd64',
                 platform_manifest=None, config_digest=IMAGE, build_sha=SHA, user='10001:10001')
    row = dict(Image=IMAGE, Config=dict(Env=['BUILD_SHA=' + SHA], User='10001:10001'),
               State=dict(Running=True, Health=dict(Status='healthy'), OOMKilled=False))
    monkeypatch.setattr(pull, "image_identity", lambda *a, **k: proof)
    monkeypatch.setattr(pull, "inspect", lambda *a, **k: row)
    body = ("\nm.image_identity=lambda *a,**k:" + repr(proof)
            + "\nm.inspect=lambda *a,**k:" + repr(row)
            + "\nwith m.deployment_lock():\n value=m.journal_begin(" + repr(SHA) + "," + repr(IMAGE)
            + ")\n print(json.dumps({'ready':value['attempt_id']}),flush=True)\n signal.pause()\n")
    process = subprocess.Popen(child_command(tmp_path, body), env=child_env(), stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE)
    try:
        ready, _, _ = select.select([process.stdout], [], [], 10)
        assert ready, "Isolated child did not reach durable journal"
        message = json.loads(process.stdout.readline())
        assert len(message["ready"]) == 32
        process.kill()
        process.wait(timeout=10)
        saved = json.loads((tmp_path / "deployment-attempt.json").read_text())
        assert saved["sha"] == SHA and saved["attempt_id"] == message["ready"]
        assert saved["phase"] == "STARTED"
        assert not (tmp_path / "last-release").exists()
        with pull.deployment_lock():
            with pytest.raises(ValueError, match="interrupted_release_requires_operator_review"):
                pull.journal_begin(SHA, IMAGE)
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=10)
