"""
One-command launcher for WASTEX.

    python run.py                 # auto: real Kafka if reachable on localhost:9092, else embedded broker
    python run.py --kafka         # require the Docker Kafka broker (docker compose up -d)
    python run.py --embedded      # force the in-process broker (no Docker needed)
    python run.py --docker        # start the Docker Kafka stack first, fall back to embedded if Docker is missing
    python run.py --port 8000 --no-browser
"""
import argparse
import os
import socket
import sys
import threading
import urllib.request
import webbrowser

ROOT = os.path.dirname(os.path.abspath(__file__))


def port_busy(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def is_wastex(port):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def start_docker_kafka():
    """Bring up the Kafka containers and wait until the broker is healthy. Returns True on success."""
    import subprocess
    import time

    def run(cmd, timeout):
        try:
            return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=timeout)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return None

    print("  Checking Docker ...")
    info = run(["docker", "info", "--format", "{{.ServerVersion}}"], 25)
    if info is None or info.returncode != 0:
        print("  Docker is not installed or not running -> using the embedded Kafka-compatible broker.")
        print("  (Start Docker Desktop and run again to use real Apache Kafka.)")
        return False
    print(f"  Docker {info.stdout.strip()} found. Starting Apache Kafka + Kafka UI (first run downloads ~700 MB) ...")
    up = run(["docker", "compose", "up", "-d"], 900)
    if up is None or up.returncode != 0:
        print("  'docker compose up' failed -> using the embedded broker.\n" + (up.stderr[-800:] if up else ""))
        return False
    for i in range(90):
        st = run(["docker", "inspect", "-f", "{{.State.Health.Status}}", "wastex-kafka"], 15)
        if st is not None and st.stdout.strip() == "healthy":
            print("  Kafka broker is healthy (localhost:9092). Kafka UI: http://localhost:8080")
            return True
        time.sleep(2)
    print("  Kafka did not become healthy in 3 minutes -> using the embedded broker.")
    return False


def main():
    os.chdir(ROOT)  # works no matter where the script is launched from
    sys.path.insert(0, ROOT)
    if sys.version_info < (3, 10):
        sys.exit("WASTEX needs Python 3.10 or newer (found %s)." % sys.version.split()[0])
    try:
        import fastapi  # noqa: F401
        import kafka  # noqa: F401
        import uvicorn  # noqa: F401
    except ImportError as e:
        sys.exit(f"Missing dependency ({e.name}). Run:  python -m pip install -r requirements.txt")

    ap = argparse.ArgumentParser(description="WASTEX - Intelligent Multi-Agent Waste Collection Optimization")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--kafka", action="store_true", help="use the real Kafka broker (fail if unreachable)")
    mode.add_argument("--embedded", action="store_true", help="use the embedded Kafka-compatible broker")
    ap.add_argument("--docker", action="store_true", help="start Kafka in Docker first (used by start.bat / start.sh)")
    ap.add_argument("--bootstrap", default=None, help="Kafka bootstrap servers (default localhost:9092)")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()

    url = f"http://127.0.0.1:{args.port}"
    if port_busy(args.port):
        if is_wastex(args.port):
            # a second copy would join the same consumer groups and split the stream in half
            print(f"\n  WASTEX is already running at {url} - opening it instead of starting a second copy.\n")
            if not args.no_browser:
                webbrowser.open(url)
            return
        sys.exit(f"Port {args.port} is used by another program. Start WASTEX on another port:  python run.py --port 8010")

    if args.docker:
        os.environ["WASTEX_BUS"] = "kafka" if start_docker_kafka() else "embedded"
    elif args.kafka:
        os.environ["WASTEX_BUS"] = "kafka"
    elif args.embedded:
        os.environ["WASTEX_BUS"] = "embedded"
    if args.bootstrap:
        os.environ["WASTEX_KAFKA"] = args.bootstrap
    os.environ["WASTEX_PORT"] = str(args.port)

    import uvicorn

    if not args.no_browser:
        threading.Timer(6.0, lambda: webbrowser.open(url)).start()
    print(f"\n  WASTEX dashboard -> {url}   (press Ctrl+C to stop)\n")
    uvicorn.run("backend.app:app", host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
