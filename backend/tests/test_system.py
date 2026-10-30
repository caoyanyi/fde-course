import json
import socket

import pytest
from fastapi.testclient import TestClient

from app.ai import ProviderError, normalize_report, resolve_endpoint
from app.config import Settings
from app.main import create_app
from .conftest import TASK


def good_report():
    return {
        "rubric": [
            {"id": "problem", "score": 48, "feedback": "需求已描述，建议明确范围", "evidence": ["客户需求"]},
            {"id": "evidence", "score": 24, "feedback": "验收标准可继续量化", "evidence": ["验收标准"]},
        ],
        "summary": "已形成基础交付定义", "strengths": ["结构完整"],
        "improvements": ["补充成本边界"], "missing_evidence": ["运行日志"],
        "next_steps": ["补充可观察指标"], "confidence": "medium",
        "total_score": 100, "runtime_verified": True,
    }


def submit(client, text="客户需求与验收标准"):
    response = client.post("/api/tasks/w01-t01/submissions", data={"content": text, "evidence_notes": "人工提交"})
    assert response.status_code == 201, response.text
    return response.json()


def test_setup_login_csrf_and_logout(client):
    assert client.get("/api/course").status_code == 401
    assert client.get("/api/auth/status").json()["initialized"] is False
    payload = {"username": "learner", "password": "a-strong-test-password", "setup_token": "test-setup-token"}
    assert client.post("/api/auth/setup", json=payload).status_code == 403
    assert client.post("/api/auth/setup", headers={"X-FDE-Client": "web", "Origin": "https://evil.example"}, json=payload).status_code == 403
    wrong = dict(payload, setup_token="incorrect-token")
    assert client.post("/api/auth/setup", headers={"X-FDE-Client": "web"}, json=wrong).status_code == 403
    response = client.post("/api/auth/setup", headers={"X-FDE-Client": "web"}, json=payload)
    assert response.status_code == 201
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "SameSite=strict" in response.headers["set-cookie"]
    csrf = response.json()["csrf_token"]
    assert client.post("/api/auth/setup", headers={"X-FDE-Client": "web"}, json=payload).status_code == 409
    assert client.patch("/api/tasks/w01-t01/progress", headers={"X-FDE-Client": "web"}, json={"status": "completed"}).status_code == 403
    client.headers.update({"X-FDE-Client": "web", "X-CSRF-Token": csrf})
    assert client.patch("/api/tasks/w01-t01/progress", json={"status": "completed", "actual_hours": 3}).status_code == 200
    assert client.post("/api/auth/logout").status_code == 200
    assert client.get("/api/course").status_code == 401
    assert client.post("/api/auth/login", json={"username": "learner", "password": "wrong-but-long-password"}).status_code == 401
    response = client.post("/api/auth/login", json={"username": "learner", "password": payload["password"]})
    assert response.status_code == 200
    assert response.json()["csrf_token"] != csrf
    assert client.get("/api/course").json()["progress"]["w01-t01"]["status"] == "completed"


def test_setup_disabled_without_env_token(app):
    app.state.config.setup_token = ""
    with TestClient(app) as client:
        result = client.post("/api/auth/setup", headers={"X-FDE-Client": "web"}, json={"username": "learner", "password": "a-strong-test-password", "setup_token": "anything"})
        assert result.status_code == 503
        assert client.get("/api/auth/status").json()["initialized"] is False


def test_malformed_origin_is_rejected_without_server_error(client):
    result = client.post("/api/auth/login", headers={"X-FDE-Client": "web", "Origin": "https://["}, json={"username": "learner", "password": "a-strong-test-password"})
    assert result.status_code == 403


def test_unicode_setup_token_is_rejected_without_server_error(client):
    result = client.post("/api/auth/setup", headers={"X-FDE-Client": "web"}, json={"username": "learner", "password": "a-strong-test-password", "setup_token": "错误口令"})
    assert result.status_code == 403


def test_versions_files_static_checks_and_auth(logged_in, app):
    first = submit(logged_in)
    # Safe AST parsing must never run this program.
    marker = app.state.config.data_dir / "must-not-exist"
    code = f"from pathlib import Path\nPath({str(marker)!r}).write_text('executed')\n"
    response = logged_in.post("/api/tasks/w01-t01/submissions", data={"content": "second version"}, files=[
        ("files", ("../../evidence.py", code.encode(), "text/plain")),
        ("files[]", ("broken.json", b'{"not valid":', "application/json")),
    ])
    assert response.status_code == 201, response.text
    second = response.json()
    assert second["version"] == 2 and first["version"] == 1
    assert second["files"][0]["filename"] == "evidence.py"
    assert not marker.exists()
    assert any(item["status"] == "failed" and "JSON" in item["name"] for item in second["static_checks"])
    assert any(item["status"] == "passed" and "Python" in item["name"] for item in second["static_checks"])
    attachment = logged_in.get(second["files"][0]["download_url"])
    assert attachment.content == code.encode()
    assert attachment.headers["content-type"] == "application/octet-stream"
    assert "attachment" in attachment.headers["content-disposition"]
    assert len(logged_in.get("/api/submissions?task_id=w01-t01").json()["items"]) == 2
    assert logged_in.get(f"/api/submissions/{first['id']}").json()["reviews"] == []
    logged_in.post("/api/auth/logout")
    assert logged_in.get(second["files"][0]["download_url"]).status_code == 401


@pytest.mark.parametrize("filename,data", [("payload.exe", b"MZ"), ("secret.txt", b"x\x00y"), ("not-utf8.md", b"\xff\xfe")])
def test_reject_unsafe_attachments(logged_in, app, filename, data):
    response = logged_in.post("/api/tasks/w01-t01/submissions", files={"files": (filename, data)})
    assert response.status_code == 422
    assert logged_in.get("/api/submissions").json()["items"] == []
    assert list(app.state.config.upload_dir.iterdir()) == []


def test_attachment_size_and_count(logged_in):
    assert logged_in.post("/api/tasks/w01-t01/submissions", files={"files": ("big.md", b"a" * (2 * 1024 * 1024 + 1))}).status_code == 413
    too_many = [("files", (f"file-{i}.md", b"hello")) for i in range(6)]
    assert logged_in.post("/api/tasks/w01-t01/submissions", files=too_many).status_code == 400
    assert logged_in.post("/api/tasks/w01-t01/submissions", data={"content": ""}).status_code == 422


def test_settings_never_expose_key_and_encrypt_at_rest(configured, app):
    result = configured.get("/api/settings/ai")
    assert result.json()["api_key_set"] is True
    assert "sk-unit-test-not-a-real-key" not in result.text
    with app.state.db.connect() as conn:
        row = conn.execute("SELECT * FROM ai_settings").fetchone()
        assert "sk-unit-test-not-a-real-key" not in row["api_key_cipher"]
        assert app.state.cipher.decrypt(row["api_key_cipher"].encode()).decode() == "sk-unit-test-not-a-real-key"
    saved = configured.put("/api/settings/ai", json={"base_url": "https://provider.example/v1", "model": "new-model", "api_key": ""})
    assert saved.json()["api_key_set"] is True
    saved = configured.put("/api/settings/ai", json={"base_url": "https://provider.example/v1", "model": "new-model", "clear_api_key": True})
    assert saved.json()["api_key_set"] is False


@pytest.mark.parametrize("url", ["http://public.example/v1", "https://user:password@public.example/v1", "https://public.example/v1?token=secret", "https://public.example/v1#fragment"])
def test_unsafe_provider_url_rejected(url):
    with pytest.raises(ProviderError):
        resolve_endpoint(url, Settings(), resolve=False)


@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.1", "169.254.169.254", "::1", "192.168.1.8", "0.0.0.0"])
def test_private_dns_rejected(monkeypatch, address):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: [(2, 1, 6, "", (address, 443))])
    with pytest.raises(ProviderError):
        resolve_endpoint("https://public.example/v1", Settings())


def test_explicit_private_allowlist(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: [(2, 1, 6, "", ("127.0.0.1", 11434))])
    endpoint = resolve_endpoint("http://local-model:11434/v1", Settings(private_host_allowlist=("local-model",)))
    assert endpoint.addresses == ("127.0.0.1",)
    assert endpoint.path == "/v1/chat/completions"


def test_scores_are_recomputed_and_runtime_false():
    normalized = normalize_report(json.dumps(good_report()), TASK, "客户需求和验收标准", False)
    assert normalized["total_score"] == 72
    assert normalized["runtime_verified"] is False
    assert normalized["mode"] == "ai_review"


@pytest.mark.parametrize("failure", ["duplicate", "missing", "range", "fabricated_quote", "bad_json"])
def test_bad_ai_output_has_no_report(failure):
    report = good_report()
    if failure == "duplicate":
        report["rubric"][1]["id"] = "problem"
    elif failure == "missing":
        report["rubric"].pop()
    elif failure == "range":
        report["rubric"][0]["score"] = 99
    elif failure == "fabricated_quote":
        report["rubric"][0]["evidence"] = ["I invented this evidence"]
    content = "not JSON" if failure == "bad_json" else json.dumps(report)
    with pytest.raises(ProviderError):
        normalize_report(content, TASK, "客户需求和验收标准", False)


def test_review_queue_failure_retry_and_audit_history(configured, app, monkeypatch):
    submission = submit(configured)
    assert configured.post(f"/api/submissions/{submission['id']}/reviews", json={"consent": False}).status_code == 422
    first = configured.post(f"/api/submissions/{submission['id']}/reviews", json={"consent": True})
    assert first.status_code == 202
    first_id = first.json()["review_id"]
    assert configured.get(f"/api/reviews/{first_id}").json()["status"] == "queued"
    duplicate = configured.post(f"/api/submissions/{submission['id']}/reviews", json={"consent": True})
    assert duplicate.json()["review_id"] == first_id

    def fail(*args, **kwargs):
        raise ProviderError("测试上游暂时不可用")
    monkeypatch.setattr("app.ai.chat_completion", fail)
    assert app.state.worker.process_next() is True
    failed = configured.get(f"/api/reviews/{first_id}").json()
    assert failed["status"] == "failed" and failed["report"] is None

    seen = {}
    def success(provider, key, messages, settings):
        seen["messages"] = messages
        assert key == "sk-unit-test-not-a-real-key"
        return json.dumps(good_report()), {"input_tokens": 100, "output_tokens": 50}
    monkeypatch.setattr("app.ai.chat_completion", success)
    second = configured.post(f"/api/submissions/{submission['id']}/reviews", json={"consent": True}).json()
    assert second["review_id"] != first_id
    app.state.worker.process_next()
    reviewed = configured.get(f"/api/reviews/{second['review_id']}").json()
    assert reviewed["status"] == "completed"
    assert reviewed["report"]["total_score"] == 72
    assert reviewed["report"]["runtime_verified"] is False
    assert len(configured.get(f"/api/submissions/{submission['id']}").json()["reviews"]) == 2
    assert "untrusted_submission_evidence" in seen["messages"][1]["content"]
    assert "sk-unit-test" not in json.dumps(seen["messages"])
    assert configured.get("/api/course").json()["progress"] == {}


def test_data_persisted_after_new_app(logged_in, app):
    submitted = submit(logged_in)
    configured = app.state.config
    second_app = create_app(configured)
    with TestClient(second_app) as other:
        login = other.post("/api/auth/login", headers={"X-FDE-Client": "web"}, json={"username": "learner", "password": "a-strong-test-password"})
        assert login.status_code == 200
        assert other.get(f"/api/submissions/{submitted['id']}").json()["content"] == "客户需求与验收标准"
