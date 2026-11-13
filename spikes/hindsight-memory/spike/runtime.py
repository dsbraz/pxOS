import argparse
import asyncio
import json
import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import asyncpg
import httpx

from spike.settings import API_URL, DB_PORT, ROOT, configure


def wait_port(port, child, seconds=90):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if child.poll() is not None:
            raise RuntimeError("Serviço encerrou; consulte runs/services")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return
        except OSError:
            time.sleep(1)
    raise TimeoutError("Serviço não abriu a porta no prazo")


async def create_database(dsn):
    connection = await asyncpg.connect(dsn.rsplit("/", 1)[0] + "/postgres", timeout=60)
    try:
        if not await connection.fetchval(
            "SELECT 1 FROM pg_database WHERE datname='hindsight_spike'"
        ):
            await connection.execute("CREATE DATABASE hindsight_spike")
    finally:
        await connection.close()


def start():
    dsn = configure()
    directory = ROOT / "runs/services"
    directory.mkdir(parents=True, exist_ok=True)
    for port in (DB_PORT, 18888):
        with socket.socket() as test:
            if test.connect_ex(("127.0.0.1", port)) == 0:
                raise RuntimeError(f"Porta {port} ocupada; não iniciar outro serviço")
    cloud = json.loads((ROOT / "cloud.json").read_text())
    with (directory / "proxy.log").open("a") as log:
        proxy = subprocess.Popen(
            [
                str(ROOT / ".tools/alloydb-auth-proxy"),
                cloud["instance_uri"],
                "--public-ip",
                "--address=127.0.0.1",
                f"--port={DB_PORT}",
                "--credentials-file=" + str(ROOT / ".secrets/adc.json"),
            ],
            stdout=log,
            stderr=log,
            start_new_session=True,
        )
    state = {"proxy": proxy.pid}
    (directory / "pids.json").write_text(json.dumps(state))
    wait_port(DB_PORT, proxy)
    asyncio.run(create_database(dsn))
    with (directory / "api.log").open("a") as log:
        api = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "hindsight_api.server:app",
                "--host=127.0.0.1",
                "--port=18888",
            ],
            cwd=ROOT,
            env=os.environ.copy(),
            stdout=log,
            stderr=log,
            start_new_session=True,
        )
    state["api"] = api.pid
    (directory / "pids.json").write_text(json.dumps(state))
    wait_port(18888, api, seconds=300)
    response = httpx.get(API_URL + "/health", timeout=60)
    response.raise_for_status()
    print("Hindsight e Auth Proxy prontos; backend AlloyDB real.")


def stop():
    path = ROOT / "runs/services/pids.json"
    state = json.loads(path.read_text())
    for name in ("api", "proxy"):
        pid = state.get(name)
        if not pid:
            continue
        command = Path(f"/proc/{pid}/cmdline")
        if not command.exists():
            continue
        cmd = command.read_bytes()
        expected = (
            b"hindsight_api.server:app"
            if name == "api"
            else str(ROOT / ".tools/alloydb-auth-proxy").encode()
        )
        if expected not in cmd:
            raise RuntimeError("PID foi reutilizado; processo não pertence ao spike")
        os.kill(pid, signal.SIGTERM)
    print("Serviços locais encerrados. AlloyDB permanece provisionado.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["start", "stop"])
    args = parser.parse_args()
    start() if args.action == "start" else stop()
