import json
import time
import urllib.error
import urllib.request


class APIError(Exception):
    pass


class LeaseLost(APIError):
    pass


class PayloadRejected(APIError):
    pass


def utf16_length(value):
    return len(value.encode("utf-16-le", errors="surrogatepass")) // 2


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class WorkerAPI:
    def __init__(self, base_url, api_key, timeout=20, attempts=3):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.attempts = attempts
        self.opener = urllib.request.build_opener(NoRedirect())

    def post(self, endpoint, payload):
        raw = json.dumps(payload, ensure_ascii=False)
        if utf16_length(raw) > 16384:
            raise PayloadRejected("Worker API payload too large")
        try:
            data = raw.encode("utf-8")
        except UnicodeEncodeError:
            raise PayloadRejected("Worker API payload is not valid UTF-8") from None
        attempts = self.attempts if endpoint == "heartbeat" else 1
        for attempt in range(attempts):
            request = urllib.request.Request(
                f"{self.base_url}/{endpoint}", data=data, method="POST",
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            )
            try:
                with self.opener.open(request, timeout=self.timeout) as response:
                    if response.status == 204:
                        return None
                    return json.loads(response.read())
            except urllib.error.HTTPError as error:
                if error.code == 409:
                    raise LeaseLost("Lease rejected or job state invalid") from None
                if error.code == 400:
                    raise PayloadRejected("Worker API rejected payload") from None
                if error.code < 500 or attempt == attempts - 1:
                    raise APIError(f"Worker API returned HTTP {error.code}") from None
            except (urllib.error.URLError, TimeoutError, OSError, ValueError):
                if attempt == attempts - 1:
                    raise APIError("Worker API request failed") from None
            if attempt + 1 < attempts:
                time.sleep(min(2 ** attempt, 4))
        raise APIError("Worker API request failed")

    def claim(self, worker_id):
        return self.post("claim", {"worker_id": worker_id})

    def heartbeat(self, job_id, lease_token):
        return self.post("heartbeat", {"job_id": job_id, "lease_token": lease_token})

    def progress(self, job_id, lease_token, status, percent, message):
        return self.post("progress", {"job_id": job_id, "lease_token": lease_token,
                                      "status": status, "progress_percent": percent, "stage_message": message})

    def complete(self, job_id, lease_token, manifest):
        return self.post("complete", {"job_id": job_id, "lease_token": lease_token, "manifest": manifest})

    def fail(self, job_id, lease_token, code, message):
        return self.post("fail", {"job_id": job_id, "lease_token": lease_token,
                                  "error_code": code, "error_message": message})