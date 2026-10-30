import json

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


TASK = {
    "id": "w01-t01", "title": "客户需求与交付验收", "summary": "提交真实交付证据",
    "hours": 6, "deliverables": ["需求记录", "验收标准"],
    "acceptanceCriteria": ["能够将业务问题转为可验证需求"],
    "rubric": [
        {"id": "problem", "title": "问题定义", "weight": 60, "description": "边界明确"},
        {"id": "evidence", "title": "交付证据", "weight": 40, "description": "证据完整"},
    ],
    "submissionPrompt": "提交需求分析和证据",
}


@pytest.fixture
def app(tmp_path):
    course_path = tmp_path / "course.json"
    course_path.write_text(json.dumps({"version": "test-1", "title": "FDE", "totalHours": 200, "weeks": [{"id": "week-01", "tasks": [TASK]}]}), encoding="utf-8")
    settings = Settings(
        data_dir=tmp_path / "data", course_path=course_path,
        setup_token="test-setup-token", master_key="test-master-key-with-at-least-32-characters",
        secure_cookie=False, public_origin="http://testserver", start_worker=False,
    )
    return create_app(settings)


@pytest.fixture
def client(app):
    with TestClient(app) as client:
        yield client


@pytest.fixture
def logged_in(client):
    response = client.post("/api/auth/setup", headers={"X-FDE-Client": "web"}, json={
        "username": "learner", "password": "a-strong-test-password", "setup_token": "test-setup-token",
    })
    assert response.status_code == 201
    client.headers.update({"X-FDE-Client": "web", "X-CSRF-Token": response.json()["csrf_token"]})
    return client


@pytest.fixture
def public_dns(monkeypatch):
    monkeypatch.setattr("app.ai.socket.getaddrinfo", lambda *args, **kwargs: [(2, 1, 6, "", ("93.184.216.34", 443))])


@pytest.fixture
def configured(logged_in, public_dns):
    response = logged_in.put("/api/settings/ai", json={
        "provider_label": "Test Provider", "base_url": "https://provider.example/v1",
        "model": "test-model", "api_key": "sk-unit-test-not-a-real-key",
    })
    assert response.status_code == 200, response.text
    return logged_in
