import asyncio
import sys
import signal
from pathlib import Path


def _venv_python() -> str:
    script_dir = Path(__file__).resolve().parent
    candidates = [
        script_dir / ".venv" / "Scripts" / "python.exe",
        script_dir / ".venv" / "bin" / "python",
    ]
    for p in candidates:
        if p.exists():
            return str(p)
    return sys.executable


PYTHON = _venv_python()

COMMANDS = [
    ("django", [PYTHON, "manage.py", "runserver", "0.0.0.0:8000"]),
    ("celery", [PYTHON, "-m", "celery", "-A", "config", "worker", "--loglevel=info", "--pool=threads", "--concurrency=4"]),
    ("celery-beat", [PYTHON, "-m", "celery", "-A", "config", "beat", "--loglevel=info"]),
    ("poll_telegram", [PYTHON, "manage.py", "poll_telegram_updates"]),
]


async def stream_output(name, stream, forward):
    while True:
        line = await stream.readline()
        if not line:
            break
        try:
            text = line.decode(errors="replace").rstrip()
        except Exception:
            text = str(line)
        print(f"[{name}] {text}")
        if forward:
            sys.stdout.flush()


async def run_process(name, cmd):
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )

    tasks = [
        asyncio.create_task(stream_output(name, proc.stdout, True)),
        asyncio.create_task(stream_output(name + "-ERR", proc.stderr, True)),
    ]

    await asyncio.wait(tasks)
    return await proc.wait()


async def main():
    loop = asyncio.get_running_loop()

    stop_event = asyncio.Event()

    def _signal_handler():
        stop_event.set()

    for s in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(s, _signal_handler)
        except NotImplementedError:
            pass

    tasks = {}
    for name, cmd in COMMANDS:
        tasks[name] = asyncio.create_task(run_process(name, cmd))

    done, pending = await asyncio.wait(tasks.values(), return_when=asyncio.FIRST_COMPLETED)

    if pending:
        for t in pending:
            t.cancel()

    await asyncio.sleep(0.3)

    if stop_event.is_set():
        for t in tasks.values():
            if not t.done():
                t.cancel()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Interrupted, exiting.")