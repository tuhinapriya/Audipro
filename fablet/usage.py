"""Append metadata for provider calls without recording credentials or prompts."""
import json
from datetime import datetime, timezone
from pathlib import Path

class UsageLog:
    def __init__(self, path: Path):
        self.path = path

    def record(self, provider: str, operation: str, **details):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open('a', encoding='utf-8') as output:
            output.write(json.dumps({'timestamp': datetime.now(timezone.utc).isoformat(), 'provider': provider, 'operation': operation, **details}, default=str) + '\n')
