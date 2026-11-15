import hashlib
import json
import os
from pathlib import Path
from typing import Callable, TypeVar
from pydantic import BaseModel

T = TypeVar('T', bound=BaseModel)

def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_bytes(data)
    os.replace(tmp, path)

def cached_model(path: Path, model: type[T], inputs: object, generate: Callable[[], T]) -> T:
    digest = hashlib.sha256(json.dumps(inputs, sort_keys=True, default=str).encode()).hexdigest()
    meta = path.with_suffix(path.suffix + '.sha256')
    if path.exists() and meta.exists() and meta.read_text() == digest:
        return model.model_validate_json(path.read_text())
    result = generate()
    atomic_write(path, result.model_dump_json(indent=2).encode())
    atomic_write(meta, digest.encode())
    return result
