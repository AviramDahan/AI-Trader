"""Supervise this checkout's local API, Ollama and free HTTPS tunnel.

No promise of uptime when the computer sleeps, is off, or the provider is down.
GitHub Pages stays fixed; tunnel rotations redeploy a public runtime manifest.
"""
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import requests
import psutil

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / ".runtime"
REPO = "AviramDahan/AI-Trader"
PAGES_RUNTIME_CONFIG = "https://aviramdahan.github.io/AI-Trader/runtime-config.json"
CLOUDFLARED = ROOT / ".local-tools" / ("cloudflared.exe" if os.name == "nt" else "cloudflared")
TUNNEL_URL_RE = re.compile(
    r"https://(?:[a-z0-9-]+\.trycloudflare\.com|[a-z0-9-]+\.serveousercontent\.com)"
)
STOP = RUNTIME / "stop.request"
FLAGS = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def log(message):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), message, flush=True)


def spawn(name, args, cwd=ROOT):
    # Old log kept once, bounded disk usage between restarts.
    logfile = RUNTIME / f"{name}.log"
    if logfile.exists():
        logfile.replace(RUNTIME / f"{name}.previous.log")
    with logfile.open("w", encoding="utf-8") as output:
        process = subprocess.Popen(args, cwd=cwd, stdout=output, stderr=subprocess.STDOUT,
                                   creationflags=FLAGS)
    (RUNTIME / f"{name}.pid").write_text(str(process.pid), encoding="ascii")
    try:
        created = psutil.Process(process.pid).create_time()
        (RUNTIME / f"{name}.process.json").write_text(json.dumps({"pid": process.pid, "created": created}), encoding="utf-8")
    except psutil.NoSuchProcess:
        pass
    return process


def cleanup_orphans():
    """After a supervisor crash, recover only our exact recorded process instances."""
    for name in ("backend", "tunnel", "ollama"):
        file = RUNTIME / f"{name}.process.json"
        try:
            identity = json.loads(file.read_text(encoding="utf-8"))
            process = psutil.Process(identity["pid"])
            if abs(process.create_time() - identity["created"]) < .001:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except psutil.TimeoutExpired:
                    process.kill()
                log(f"Recovered owned orphan: {name}")
        except (OSError, ValueError, KeyError, psutil.Error):
            pass


def terminate(process):
    if process and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()


def health(url):
    try:
        response = requests.get(url + "/health", timeout=8, headers={"serveo-skip-browser-warning": "true"})
        return response.ok and response.json().get("status") == "ok"
    except (requests.RequestException, ValueError):
        return False


def tunnel_command():
    """Prefer the more stable local Cloudflare connector; keep Serveo as a free fallback."""
    cloudflared = CLOUDFLARED if CLOUDFLARED.is_file() else shutil.which("cloudflared")
    if cloudflared:
        return ([str(cloudflared), "tunnel", "--url", "http://127.0.0.1:8000",
                 "--no-autoupdate", "--loglevel", "info"], "cloudflare-quick")
    return (["ssh.exe", "-T", "-o", "StrictHostKeyChecking=accept-new",
             "-o", "ServerAliveInterval=20", "-o", "ServerAliveCountMax=3",
             "-o", "ConnectTimeout=10", "-o", "ExitOnForwardFailure=yes",
             "-R", "80:127.0.0.1:8000", "serveo.net"], "serveo")


def valid_tunnel_url(value):
    return bool(TUNNEL_URL_RE.fullmatch(value))


def publish(url):
    gh = shutil.which("gh")
    if not gh:
        return False
    for args in (["variable", "set", "BACKEND_URL", "--body", url],
                 ["workflow", "run", "deploy-pages.yml"]):
        try:
            result = subprocess.run([gh, *args, "--repo", REPO], capture_output=True, timeout=45, creationflags=FLAGS)
        except (OSError, subprocess.TimeoutExpired):
            return False
        if result.returncode:
            log("Pages endpoint update failed; will retry (no credentials logged)")
            return False
    log("Pages deployment requested for recovered endpoint")
    return True


def deployed_backend_url():
    """Read the actual Pages manifest; workflow dispatch alone is not deployment confirmation."""
    try:
        response = requests.get(PAGES_RUNTIME_CONFIG, params={"t": int(time.time())}, timeout=8,
                                headers={"Cache-Control": "no-cache"})
        response.raise_for_status()
        value = str(response.json().get("backend_url") or "").strip().rstrip("/")
        return value if valid_tunnel_url(value) else ""
    except (requests.RequestException, ValueError):
        return ""


def main():
    RUNTIME.mkdir(exist_ok=True)
    # OS releases the lock on process exit. Do not kill arbitrary reused PIDs.
    lock = socket.socket()
    try:
        lock.bind(("127.0.0.1", 18765))
    except OSError:
        raise SystemExit("Supervisor already running or lock port is occupied")
    (RUNTIME / "supervisor.pid").write_text(str(os.getpid()), encoding="ascii")
    cleanup_orphans()
    backend = tunnel = ollama = None
    local_failures = public_failures = 0
    url = published = ""
    last_public = last_publish = last_manifest_check = 0
    manifest_url = tunnel_provider = ""
    try:
        while not STOP.exists():
            if backend is None or backend.poll() is not None or local_failures >= 3:
                terminate(backend)
                backend = spawn("backend", [sys.executable, "-u", "-m", "uvicorn", "main:app",
                                             "--host", "127.0.0.1", "--port", "8000"], ROOT / "service" / "server")
                local_failures = 0
                log("Backend started/recovered")
            local_ok = health("http://127.0.0.1:8000")
            local_failures = 0 if local_ok else local_failures + 1
            try:
                requests.get("http://127.0.0.1:11434/api/tags", timeout=4).raise_for_status()
            except requests.RequestException:
                executable = shutil.which("ollama")
                if executable and (ollama is None or ollama.poll() is not None):
                    ollama = spawn("ollama", [executable, "serve"])
                    log("Local Ollama recovery requested")
            if local_ok and (tunnel is None or tunnel.poll() is not None or public_failures >= 3):
                terminate(tunnel)
                command, tunnel_provider = tunnel_command()
                tunnel = spawn("tunnel", command)
                url = ""
                public_failures = 0
                last_public = 0
                log(f"HTTPS tunnel started/recovered ({tunnel_provider})")
            if tunnel and not url:
                contents = (RUNTIME / "tunnel.log").read_text(encoding="utf-8", errors="replace")
                match = TUNNEL_URL_RE.search(contents)
                if match:
                    url = match.group(0)
                    (RUNTIME / "backend-url.txt").write_text(url, encoding="utf-8")
                elif time.time() - (RUNTIME / "tunnel.log").stat().st_mtime > 90:
                    public_failures = 3
            public_ok = None
            if url and time.time() - last_public >= 60:
                last_public = time.time()
                public_ok = health(url)  # normal DNS and TLS, same path as visitors
                public_failures = 0 if public_ok else public_failures + 1
            if url and time.time() - last_manifest_check >= 30:
                last_manifest_check = time.time()
                manifest_url = deployed_backend_url()
                if manifest_url == url:
                    published = url
            if public_ok and published != url and time.time() - last_publish >= 120:
                last_publish = time.time()
                publish(url)
            state = {"heartbeat": time.time(), "backend": local_ok, "public_failures": public_failures,
                     "backend_url": url, "pages_manifest_url": manifest_url,
                     "tunnel_provider": tunnel_provider,
                     "pages_update_requested": published == url and bool(url)}
            (RUNTIME / "supervisor-status.json").write_text(json.dumps(state), encoding="utf-8")
            for _ in range(20):
                if STOP.exists():
                    break
                time.sleep(1)
    finally:
        terminate(tunnel)
        terminate(backend)
        terminate(ollama)  # only one we started, never an existing user Ollama process
        for name in ("backend", "tunnel", "supervisor"):
            (RUNTIME / f"{name}.pid").unlink(missing_ok=True)
        lock.close()
        log("Supervisor and owned children stopped")


if __name__ == "__main__":
    main()
