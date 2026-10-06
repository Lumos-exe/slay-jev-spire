"""Provider capabilities and HTTP evidence, independent of game strategy."""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from hashlib import sha256
import time
from uuid import uuid4
from .records import append_record


@dataclass(frozen=True)
class ProviderCapabilities:
    max_choices: int
    source: str


JEV_CAPABILITIES = ProviderCapabilities(255, 'https://docs.typesafe.ai/primitives/choice')
_evidence = ContextVar('jev_request_evidence', default=None)


@contextmanager
def capture_http(output_dir, decision_id):
    token = _evidence.set((output_dir, decision_id))
    try:
        yield
    finally:
        _evidence.reset(token)


def recording_transport(directory, decision_id, aliases, delegate=None):
    """Capture actual HTTP bodies at the transport boundary. Never read headers."""
    import httpx2

    class RecordingTransport(httpx2.BaseTransport):
        def __init__(self):
            self.delegate = delegate or httpx2.HTTPTransport()

        def handle_request(self, request):
            request_id = uuid4().hex
            path = directory / 'requests' / sha256(decision_id.encode()).hexdigest() / (request_id + '.jsonl')
            common = dict(decision_id=decision_id, request_id=request_id, aliases=aliases)
            append_record(path, dict(common, event='http_request', body=request.read().decode('utf-8')))
            started = time.monotonic()
            try:
                response = self.delegate.handle_request(request)
                body = response.read().decode('utf-8', errors='replace')
            except Exception as error:
                append_record(path, dict(common, event='http_error', error_type=type(error).__name__,
                    latency_ms=round((time.monotonic()-started)*1000, 2)))
                raise
            append_record(path, dict(common, event='http_response', status_code=response.status_code,
                body=body, latency_ms=round((time.monotonic()-started)*1000, 2)))
            return response

        def close(self):
            self.delegate.close()

    return RecordingTransport()


def client_evidence_options(aliases):
    scope = _evidence.get()
    if scope is None:
        return {}
    directory, decision_id = scope
    return {'transport': recording_transport(directory, decision_id, aliases)}
