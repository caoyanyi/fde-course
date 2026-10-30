import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.ai import MAX_PROVIDER_RESPONSE, ProviderError, chat_completion
from app.config import Settings


@contextmanager
def mock_provider(status=200, payload=None, headers=None):
    received = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            # Test payloads and Authorization must not appear in logs.
            pass

        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            received.append({"path": self.path, "authorization": self.headers.get("Authorization"), "body": json.loads(body)})
            response_body = json.dumps(payload if payload is not None else {
                "choices": [{"message": {"content": "已收到中文证据"}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 7},
            }, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            supplied = headers or {}
            if "Content-Length" not in supplied:
                self.send_header("Content-Length", str(len(response_body)))
            for key, value in supplied.items():
                self.send_header(key, value)
            self.end_headers()
            try:
                self.wfile.write(response_body)
            except (BrokenPipeError, ConnectionResetError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield {
            "base_url": f"http://127.0.0.1:{server.server_port}/v1", "model": "local-test-model",
            "max_tokens": 256, "temperature": 0.2, "timeout_seconds": 10,
        }, received
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


SETTINGS = Settings(private_host_allowlist=("127.0.0.1",))


def test_real_transport_posts_utf8_and_auth_header():
    with mock_provider() as (provider, received):
        content, usage = chat_completion(provider, "test-key-never-real", [
            {"role": "system", "content": "仅审查文本证据"},
            {"role": "user", "content": "客户需求：工单分类。验收标准：可以追溯。"},
        ], SETTINGS)
    assert content == "已收到中文证据"
    assert usage == {"input_tokens": 12, "output_tokens": 7}
    assert len(received) == 1
    assert received[0]["path"] == "/v1/chat/completions"
    assert received[0]["authorization"] == "Bearer test-key-never-real"
    assert received[0]["body"]["messages"][1]["content"].startswith("客户需求")
    assert received[0]["body"]["stream"] is False


@pytest.mark.parametrize("status,match", [(401, "认证"), (429, "限流"), (500, "HTTP 500"), (302, "重定向")])
def test_real_transport_failure_does_not_retry_or_expose_body(status, match):
    with mock_provider(status=status, payload={"error": "SENSITIVE_UPSTREAM_MESSAGE"}, headers={"Location": "http://169.254.169.254/metadata"}) as (provider, received):
        with pytest.raises(ProviderError, match=match) as error:
            chat_completion(provider, "secret-test-value", [{"role": "user", "content": "中文"}], SETTINGS)
    assert "SENSITIVE_UPSTREAM_MESSAGE" not in str(error.value)
    assert "secret-test-value" not in str(error.value)
    assert len(received) == 1


def test_real_transport_rejects_oversize_and_invalid_choices():
    with mock_provider(headers={"Content-Length": str(MAX_PROVIDER_RESPONSE + 1)}) as (provider, _):
        with pytest.raises(ProviderError, match="过大"):
            chat_completion(provider, "test-key", [{"role": "user", "content": "中文"}], SETTINGS)
    with mock_provider(payload={"choices": []}) as (provider, _):
        with pytest.raises(ProviderError, match="兼容"):
            chat_completion(provider, "test-key", [{"role": "user", "content": "中文"}], SETTINGS)
