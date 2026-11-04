import json
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.ai import MAX_PROVIDER_RESPONSE, ProviderError, chat_completion
from app.config import Settings


@contextmanager
def mock_provider(status=200, payload=None, headers=None, response_delay=0, body_delay=0, raw_body=None, write_split=None, keep_open=False):
    received = []

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1" if keep_open else "HTTP/1.0"

        def log_message(self, *args):
            # Test payloads and Authorization must not appear in logs.
            pass

        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            received.append({"path": self.path, "authorization": self.headers.get("Authorization"), "body": json.loads(body)})
            time.sleep(response_delay)
            response_body = json.dumps(payload if payload is not None else {
                "choices": [{"message": {"content": "已收到中文证据"}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 7},
            }, ensure_ascii=False).encode()
            if raw_body is not None:
                response_body = raw_body
            self.send_response(status)
            supplied = headers or {}
            if "Content-Type" not in supplied:
                self.send_header("Content-Type", "application/json")
            if "Content-Length" not in supplied and not keep_open:
                self.send_header("Content-Length", str(len(response_body)))
            for key, value in supplied.items():
                self.send_header(key, value)
            self.end_headers()
            try:
                middle = len(response_body) // 2 if write_split is None else write_split
                self.wfile.write(response_body[:middle])
                self.wfile.flush()
                time.sleep(body_delay)
                self.wfile.write(response_body[middle:])
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
    assert received[0]["body"]["stream"] is True


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


def test_timeout_reports_wait_limit_without_scoring_language_or_retry():
    with mock_provider(response_delay=0.2) as (provider, received):
        provider["timeout_seconds"] = 0.05
        with pytest.raises(ProviderError, match="超时") as error:
            chat_completion(provider, "secret-test-value", [{"role": "user", "content": "素材请求"}], SETTINGS)
    message = str(error.value)
    assert "0.05 秒" in message
    assert "分数" not in message
    assert "服务方费用" in message
    assert "secret-test-value" not in message
    assert len(received) == 1


def test_zero_timeout_waits_for_slow_headers_and_body_without_retry(monkeypatch):
    from app.ai import PinnedHTTPConnection

    observed = {}

    class TrackingConnection(PinnedHTTPConnection):
        def connect(self):
            observed["connect_timeout"] = self.timeout
            super().connect()

        def getresponse(self):
            observed["response_timeout"] = self.sock.gettimeout()
            return super().getresponse()

    monkeypatch.setattr("app.ai.PinnedHTTPConnection", TrackingConnection)
    with mock_provider(response_delay=0.1, body_delay=0.1) as (provider, received):
        provider["timeout_seconds"] = 0
        content, usage = chat_completion(provider, "test-key", [{"role": "user", "content": "长素材"}], SETTINGS)
    assert content == "已收到中文证据"
    assert usage == {"input_tokens": 12, "output_tokens": 7}
    assert observed == {"connect_timeout": 10, "response_timeout": None}
    assert len(received) == 1


@pytest.mark.parametrize("seconds,expected_limit", [(0, 25), (10, 10), (600, 25)])
def test_connection_test_stays_bounded_when_generation_wait_is_unlimited(monkeypatch, seconds, expected_limit):
    from app.ai import PinnedHTTPConnection

    observed = []

    class TimeoutConnection(PinnedHTTPConnection):
        def getresponse(self):
            observed.append(self.sock.gettimeout())
            raise TimeoutError()

    monkeypatch.setattr("app.ai.PinnedHTTPConnection", TimeoutConnection)
    with mock_provider() as (provider, _):
        provider["timeout_seconds"] = seconds
        with pytest.raises(ProviderError, match=f"{expected_limit} 秒"):
            chat_completion(provider, "test-key", [{"role": "user", "content": "OK"}], SETTINGS, test=True)
    assert len(observed) == 1
    assert 0 < observed[0] <= expected_limit


def sse(*events):
    return b"".join(b"data: " + (event.encode() if isinstance(event, str) else json.dumps(event, ensure_ascii=False).encode()) + b"\n\n" for event in events)


def delta(content=None, finish=None, **extra):
    return {"choices": [{"index": 0, "delta": {"content": content, **extra}, "finish_reason": finish}]}


@pytest.mark.parametrize("line_ending", [b"\n", b"\r\n", b"\r"])
def test_stream_assembles_content_and_usage_with_heartbeat_and_unicode(line_ending):
    body = b": keep-alive\n\n" + sse(
        delta(None, role="assistant", reasoning_content="不得保存的思考"),
        delta('{"title":"中文'), delta('素材"}'), delta(finish="stop"),
        {"choices": [], "usage": {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20}},
        "[DONE]",
    )
    # Split a multibyte character across the two HTTP writes.
    body = body.replace(b"\n", line_ending)
    split = body.index("中文".encode()) + 1
    with mock_provider(raw_body=body, headers={"Content-Type": "text/event-stream; charset=utf-8"}, body_delay=0.05, write_split=split) as (provider, received):
        provider["timeout_seconds"] = 0
        content, usage = chat_completion(provider, "test-key", [], SETTINGS)
    assert content == '{"title":"中文素材"}'
    assert usage == {"input_tokens": 12, "output_tokens": 8}
    assert received[0]["body"]["stream"] is True
    assert len(received) == 1


@pytest.mark.parametrize("body,match", [
    (sse(delta('{"title":"partial"}')), "中断"),
    (sse(delta("partial"), {"error": {"message": "SENSITIVE_UPSTREAM_MESSAGE"}}), "错误"),
    (b"event: error\ndata: {\"message\":\"SENSITIVE_UPSTREAM_MESSAGE\"}\n\n", "错误"),
    (sse("invalid JSON", "[DONE]"), "格式"),
    (sse(delta("valid JSON", finish="length"), "[DONE]"), "截断"),
    (sse(delta("text", finish="content_filter"), "[DONE]"), "过滤"),
    (sse(delta(content=123), "[DONE]"), "格式"),
    (sse(delta(None, reasoning_content="reasoning only"), "[DONE]"), "文本"),
])
def test_stream_failure_keeps_no_partial_result_and_never_retries(body, match):
    with mock_provider(raw_body=body, headers={"Content-Type": "text/event-stream"}) as (provider, received):
        with pytest.raises(ProviderError, match=match) as error:
            chat_completion(provider, "secret-test-value", [], SETTINGS)
    assert "SENSITIVE_UPSTREAM_MESSAGE" not in str(error.value)
    assert "secret-test-value" not in str(error.value)
    assert len(received) == 1


def test_stream_can_be_disabled_and_connection_test_uses_json():
    for settings, test in [(Settings(private_host_allowlist=("127.0.0.1",), ai_stream_responses=False), False), (SETTINGS, True)]:
        with mock_provider() as (provider, received):
            content, _ = chat_completion(provider, "test-key", [], settings, test=test)
        assert content == "已收到中文证据"
        assert received[0]["body"]["stream"] is False


@pytest.mark.parametrize("status", [502, 503, 504, 524])
def test_upstream_gateway_failure_explains_cause_without_model_name_advice(status):
    with mock_provider(status=status, payload={"error": "SENSITIVE_UPSTREAM_MESSAGE"}) as (provider, received):
        with pytest.raises(ProviderError, match=f"HTTP {status}") as error:
            chat_completion(provider, "test-key", [], SETTINGS)
    message = str(error.value)
    assert "上游" in message and "费用" in message
    assert "核对模型名" not in message
    assert "SENSITIVE_UPSTREAM_MESSAGE" not in message
    assert len(received) == 1


def test_stream_rejects_oversized_content():
    with mock_provider(raw_body=sse(delta("x" * (MAX_PROVIDER_RESPONSE + 1)), "[DONE]"), headers={"Content-Type": "text/event-stream"}) as (provider, received):
        with pytest.raises(ProviderError, match="过大|超过"):
            chat_completion(provider, "test-key", [], SETTINGS)
    assert len(received) == 1


def test_stream_returns_at_done_and_closes_response_without_waiting_for_eof(monkeypatch):
    from app.ai import PinnedHTTPConnection
    responses = []

    class TrackingConnection(PinnedHTTPConnection):
        def getresponse(self):
            response = super().getresponse()
            responses.append(response)
            return response

    monkeypatch.setattr("app.ai.PinnedHTTPConnection", TrackingConnection)
    with mock_provider(raw_body=sse(delta("完整结果"), delta(finish="stop"), "[DONE]"), headers={"Content-Type": "text/event-stream"}, keep_open=True) as (provider, received):
        provider["timeout_seconds"] = 0.5
        content, usage = chat_completion(provider, "test-key", [], SETTINGS)
    assert content == "完整结果" and usage is None
    assert responses[0].isclosed()
    assert len(received) == 1


def test_stream_retains_configured_deadline_during_delayed_body():
    with mock_provider(raw_body=sse(delta("partial"), "[DONE]"), headers={"Content-Type": "text/event-stream"}, body_delay=0.2) as (provider, received):
        provider["timeout_seconds"] = 0.05
        with pytest.raises(ProviderError, match="0.05 秒"):
            chat_completion(provider, "test-key", [], SETTINGS)
    assert len(received) == 1


def test_stream_bounds_total_wire_bytes_even_for_heartbeat_only_stream(monkeypatch):
    monkeypatch.setattr("app.ai.MAX_PROVIDER_STREAM_RESPONSE", 64)
    with mock_provider(raw_body=b": heartbeat\n\n" * 20, headers={"Content-Type": "text/event-stream"}, keep_open=True) as (provider, received):
        with pytest.raises(ProviderError, match="过大"):
            chat_completion(provider, "test-key", [], SETTINGS)
    assert len(received) == 1


def test_sse_multiline_data_comments_and_byte_fragmentation():
    from app.ai import _stream_completion
    body = b'\xef\xbb\xbf: comment\r\nid: ignored\r\nevent: message\r\ndata: {"choices":\r\ndata: [{"delta":{"content":"hello"}}]}\r\n\r\n' + sse("[DONE]")
    assert _stream_completion(bytes([byte]) for byte in body) == ("hello", None)


def test_stream_environment_defaults_to_true_and_allows_opt_out(monkeypatch):
    monkeypatch.delenv("AI_STREAM_RESPONSES", raising=False)
    assert Settings().ai_stream_responses is True
    monkeypatch.setenv("AI_STREAM_RESPONSES", "false")
    assert Settings().ai_stream_responses is False
    monkeypatch.setenv("AI_STREAM_RESPONSES", "TRUE")
    assert Settings().ai_stream_responses is True
