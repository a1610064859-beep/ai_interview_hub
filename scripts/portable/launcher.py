"""Windows entry point for the bundled, installer-free retest package."""

from __future__ import annotations

import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser


ROOT = Path(sys.executable).resolve().parent
API_PORT = 8000
WEB_PORT = 3000
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr, flush=True)
    if sys.stdin and sys.stdin.isatty():
        try:
            input("Press Enter to close...")
        except EOFError:
            pass
    raise SystemExit(1)


def require_file(relative: str) -> Path:
    path = ROOT / relative
    if not path.is_file():
        fail(f"The package is incomplete: {relative} is missing. Extract the whole ZIP first.")
    return path


def port_is_taken(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
        connection.settimeout(0.5)
        return connection.connect_ex(("127.0.0.1", port)) == 0


def relocate_python(base_python: Path, venv_python: Path) -> None:
    config = ROOT / ".venv" / "pyvenv.cfg"
    require_file(str(config.relative_to(ROOT)))
    lines = config.read_text(encoding="utf-8").splitlines()
    updates = {
        "home": str(base_python.parent),
        "executable": str(base_python),
    }
    result: list[str] = []
    for line in lines:
        name = line.partition("=")[0].strip().lower()
        result.append(f"{name} = {updates[name]}" if name in updates else line)
    for name, value in updates.items():
        if not any(line.partition("=")[0].strip().lower() == name for line in lines):
            result.append(f"{name} = {value}")
    config.write_text("\n".join(result) + "\n", encoding="utf-8")
    probe = subprocess.run(
        [str(venv_python), "-c", "import sys, torch, funasr; assert sys.prefix != sys.base_prefix"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=90,
        env=runtime_env(),
        creationflags=CREATE_NO_WINDOW,
    )
    if probe.returncode:
        fail(f"The bundled Python environment could not start (exit {probe.returncode}).")


def runtime_env() -> dict[str, str]:
    env = os.environ.copy()
    runtime_paths = [
        ROOT / ".venv" / "Scripts",
        ROOT / "runtime" / "python",
        ROOT / "runtime" / "node",
        ROOT / "runtime" / "ffmpeg" / "bin",
    ]
    env["PATH"] = os.pathsep.join(str(path) for path in runtime_paths) + os.pathsep + env.get("PATH", "")
    env["PYTHONNOUSERSITE"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["MODELSCOPE_CACHE"] = str(ROOT / "models" / "funasr")
    env["NEXT_TELEMETRY_DISABLED"] = "1"
    env["NODE_ENV"] = "production"
    env["BACKEND_URL"] = f"http://127.0.0.1:{API_PORT}"
    env["API_PROXY_TIMEOUT_MS"] = "360000"
    env["HOSTNAME"] = "127.0.0.1"
    env["PORT"] = str(WEB_PORT)
    return env


def wait_for(url: str, process: subprocess.Popen[bytes], timeout_s: int, name: str) -> None:
    started = time.monotonic()
    next_notice = started + 10
    while time.monotonic() - started < timeout_s:
        if process.poll() is not None:
            fail(f"{name} exited during startup (code {process.returncode}). See logs/portable-{name}.err.txt.")
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if 200 <= response.status < 400:
                    return
        except (urllib.error.URLError, TimeoutError, OSError):
            pass
        now = time.monotonic()
        if now >= next_notice:
            print(f"Waiting for {name}...", flush=True)
            next_notice = now + 10
        time.sleep(1)
    fail(f"Timed out starting {name}. See logs/portable-{name}.err.txt.")


def start_process(command: list[str], name: str, cwd: Path, env: dict[str, str]) -> subprocess.Popen[bytes]:
    logs = ROOT / "logs"
    logs.mkdir(exist_ok=True)
    output = (logs / f"portable-{name}.out.txt").open("ab")
    errors = (logs / f"portable-{name}.err.txt").open("ab")
    try:
        return subprocess.Popen(command, cwd=cwd, env=env, stdout=output, stderr=errors)
    finally:
        output.close()
        errors.close()


def stop_process(process: subprocess.Popen[bytes] | None) -> None:
    if process is not None and process.poll() is None:
        subprocess.run(
            ["taskkill.exe", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=CREATE_NO_WINDOW,
            check=False,
        )


def main() -> None:
    base_python = require_file("runtime/python/python.exe")
    venv_python = require_file(".venv/Scripts/python.exe")
    node = require_file("runtime/node/node.exe")
    require_file("runtime/ffmpeg/bin/ffmpeg.exe")
    require_file("runtime/ffmpeg/bin/ffprobe.exe")
    require_file("web/server.js")
    require_file(".env")
    require_file("scripts/import_seeds.py")
    model_snapshot = ROOT / "models" / "funasr" / "snapshot"
    if not model_snapshot.is_dir() or not (model_snapshot / "model.pt").is_file():
        fail("The bundled speech model is missing.")
    os.chdir(ROOT)
    relocate_python(base_python, venv_python)
    if "--check" in sys.argv:
        print("Bundled runtime and speech model are ready.", flush=True)
        return
    if port_is_taken(API_PORT) or port_is_taken(WEB_PORT):
        fail("Ports 8000 or 3000 are in use. Close the other copy of this app and retry.")
    env = runtime_env()
    (ROOT / "data").mkdir(exist_ok=True)
    print("Preparing seed jobs...", flush=True)
    seed = subprocess.run(
        [str(venv_python), str(ROOT / "scripts" / "import_seeds.py")],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        creationflags=CREATE_NO_WINDOW,
    )
    if seed.returncode:
        fail(f"Seed import failed (exit {seed.returncode}).")

    backend: subprocess.Popen[bytes] | None = None
    frontend: subprocess.Popen[bytes] | None = None
    try:
        print("Starting API and bundled speech recognition...", flush=True)
        backend = start_process(
            [str(venv_python), "-m", "uvicorn", "server.main:app", "--host", "127.0.0.1", "--port", str(API_PORT)],
            "api",
            ROOT,
            env,
        )
        wait_for(f"http://127.0.0.1:{API_PORT}/api/jobs", backend, 1200, "api")
        print("Starting website...", flush=True)
        frontend = start_process([str(node), "server.js"], "web", ROOT / "web", env)
        wait_for(f"http://127.0.0.1:{WEB_PORT}/", frontend, 120, "web")
        url = f"http://127.0.0.1:{WEB_PORT}/"
        print(f"Ready: {url}", flush=True)
        if os.environ.get("AIH_NO_BROWSER") != "1":
            webbrowser.open(url)
        if os.environ.get("AIH_EXIT_AFTER_READY") == "1":
            return
        print("Keep this window open. Press Enter to stop both services.", flush=True)
        input()
    except KeyboardInterrupt:
        pass
    finally:
        stop_process(frontend)
        stop_process(backend)


if __name__ == "__main__":
    main()
