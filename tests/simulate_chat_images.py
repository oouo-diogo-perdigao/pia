"""Run the actual ChatTools HTTP client through the saved local Postman simulation."""

from pathlib import Path
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.chat_tools import ChatTools

ROOT = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory() as temporary:
    log = Path(temporary) / "simulation.ndjson"
    errors = Path(temporary) / "simulation.err"
    with log.open("w") as stdout, errors.open("w") as stderr:
        flags = (
            subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
            if os.name == "nt"
            else 0
        )
        process = subprocess.Popen(
            [
                shutil.which("postman"),
                "simulation",
                "run",
                "postman/simulations/chat-images.sim.yaml",
                "--port",
                "4903",
                "--output",
                "ndjson",
                "--no-history",
            ],
            cwd=ROOT,
            stdout=stdout,
            stderr=stderr,
            creationflags=flags,
        )
        try:
            for _ in range(150):
                if "listening" in log.read_text(encoding="utf-8", errors="replace"):
                    break
                if process.poll() is not None:
                    raise RuntimeError(errors.read_text())
                time.sleep(0.1)
            else:
                raise RuntimeError("Simulation did not start: " + errors.read_text())
            tools = ChatTools(
                root=Path(temporary) / "images", base_url="http://127.0.0.1:4903/pia"
            )
            result = tools.execute("Gere uma imagem de um quadrado azul")
            assert "/api/pia/chat/assets/" in result
            try:
                tools.execute("Gere uma imagem __fail__")
            except RuntimeError as error:
                assert "503" in str(error)
            else:
                raise AssertionError("Provider failure was not surfaced")
            time.sleep(0.1)
            events = [
                json.loads(line)
                for line in log.read_text(encoding="utf-8").splitlines()
                if line.startswith("{")
            ]
            requests = [
                event
                for event in events
                if event.get("type") == "request" or event.get("event") == "request"
            ]
            if len(requests) < 2:
                raise AssertionError(
                    "Expected two HTTP requests in simulation log: " + log.read_text()
                )
            print(
                "Postman simulation: image route requested, asset saved, 503 propagated; 2 HTTP requests verified."
            )
        finally:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            else:
                process.terminate()
            process.wait(timeout=10)
