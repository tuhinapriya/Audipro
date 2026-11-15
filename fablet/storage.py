"""Immutable attempt-scoped storage."""
import re
from pathlib import Path
import boto3


def asset_keys(job_id: str, attempt_id: str) -> tuple[str, str]:
    for value in (job_id, attempt_id):
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', value):
            raise ValueError('Invalid job or attempt identifier')
    prefix = f'productions/{job_id}/{attempt_id}'
    return f'{prefix}/master.mp3', f'{prefix}/cover.webp'


class Storage:
    def __init__(self, endpoint: str, key: str, secret: str, bucket: str):
        self.bucket = bucket
        self.client = boto3.client('s3', endpoint_url=endpoint, aws_access_key_id=key, aws_secret_access_key=secret, region_name='auto')

    def upload(self, key: str, path: Path, content_type: str):
        size = path.stat().st_size
        if not size:
            raise ValueError('Cannot upload empty file')
        # Conditional writes enforce immutability even for duplicate requests.
        with path.open('rb') as body:
            self.client.put_object(Bucket=self.bucket, Key=key, Body=body, ContentType=content_type, IfNoneMatch='*')
        info = self.client.head_object(Bucket=self.bucket, Key=key)
        if info['ContentLength'] != size:
            raise RuntimeError('Uploaded object length mismatch')


class LocalStorage:
    def __init__(self, root: Path):
        self.root = root

    def upload(self, key: str, path: Path, content_type: str):
        target = (self.root / key).resolve()
        if not target.is_relative_to(self.root.resolve()):
            raise ValueError('Invalid key')
        data = path.read_bytes()
        if not data:
            raise ValueError('Cannot upload empty file')
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('xb') as output:
            output.write(data)
        if target.stat().st_size != len(data):
            raise RuntimeError('Uploaded object length mismatch')
