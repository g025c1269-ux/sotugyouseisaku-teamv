"""Append only timing/configuration metadata; no prompts or generated text."""
import json
from pathlib import Path
from threading import Lock

_LOCK = Lock()


def write_diagnostics(path, diagnostics):
    try:
        path = Path(path)
        with _LOCK:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('a', encoding='utf-8') as output:
                output.write(json.dumps(diagnostics, ensure_ascii=False, allow_nan=False) + '\n')
    except (OSError, ValueError):
        diagnostics['log_error'] = '診断ログを保存できませんでした。'
