import asyncio
import sys
import signal
import re
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

ANSI = {
    "reset": "\033[0m",
    "dim": "\033[2m",
    "red": "\033[31m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "blue": "\033[34m",
    "magenta": "\033[35m",
    "cyan": "\033[36m",
}

SERVICE_COLOR = {
    "django": ANSI["green"],
    "celery": ANSI["cyan"],
    "celery-beat": ANSI["blue"],
    "poll_telegram": ANSI["magenta"],
}


def _decode_escaped_unicode(text: str) -> str:
    if "\\u" not in text:
        return text
    try:
        return bytes(text, "utf-8").decode("unicode_escape")
    except Exception:
        return text


def _beautify_line(text: str) -> str:
    text = _decode_escaped_unicode(text)

    m = re.search(r"fetch_vacancy_description: vacancy (\d+) .*?desc=(\d+) branded=(\d+)", text)
    if m:
        vid, desc_len, branded_len = m.groups()
        return f"Описание HH: id={vid}, desc={desc_len}, branded={branded_len}"

    m = re.search(r"Task vacancies\.tasks\.fetch_vacancy_description\[[^\]]+\] succeeded.*'ok:desc=(\d+),branded=(\d+)'", text)
    if m:
        desc_len, branded_len = m.groups()
        return f"Описание HH: задача выполнена (desc={desc_len}, branded={branded_len})"

    if "Task accounts.tasks.notify_interview_reminders_task" in text and "succeeded" in text:
        return "Напоминания о собеседованиях: задача выполнена"
    if "Task accounts.tasks.notify_calendar_note_reminders_task" in text and "succeeded" in text:
        return "Напоминания календаря: задача выполнена"

    return text


def _format_prefix(name: str) -> str:
    is_err = name.endswith("-ERR")
    base = name[:-4] if is_err else name
    color = ANSI["red"] if is_err else SERVICE_COLOR.get(base, ANSI["dim"])
    return f"{color}[{name}]{ANSI['reset']}"


async def stream_output(name, stream, forward):
    while True:
        line = await stream.readline()
        if not line:
            break
        try:
            text = line.decode(errors="replace").rstrip()
        except Exception:
            text = str(line)
        text = _beautify_line(text)
        print(f"{_format_prefix(name)} {text}")
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