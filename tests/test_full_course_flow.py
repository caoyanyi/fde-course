"""Check the real 30-task curriculum against the actual authenticated API."""
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.main import create_app


def test_full_curriculum_submission_and_progress_persist(tmp_path):
    config = Settings(
        course_path=Path(__file__).resolve().parents[1] / "course" / "curriculum.json",
        data_dir=tmp_path / "data",
        setup_token="local-integration-setup-only",
        master_key="local-integration-master-key-32-characters",
        public_origin="http://testserver",
        secure_cookie=False,
        start_worker=False,
    )
    with TestClient(create_app(config)) as client:
        created = client.post("/api/auth/setup", headers={"X-FDE-Client": "web"}, json={
            "username": "course_qa", "password": "local-test-password-only",
            "setup_token": config.setup_token,
        })
        assert created.status_code == 201
        client.headers.update({"X-FDE-Client": "web", "X-CSRF-Token": created.json()["csrf_token"]})
        course = client.get("/api/course").json()["course"]
        assert len(course["weeks"]) == 10
        assert sum(len(week["tasks"]) for week in course["weeks"]) == 30
        first = course["weeks"][0]["tasks"][0]
        response = client.post(f"/api/tasks/{first['id']}/submissions", data={
            "content": "本地集成检查：提交目标场景、边界、验收清单。",
            "evidence_notes": "仅检查保存流程，不作为真实客户成果。",
        }, files=[("files", ("evidence.json", b'{"test_fixture":true}', "application/json"))])
        assert response.status_code == 201
        submission = response.json()
        assert submission["course_version"] == course["version"]
        assert submission["files"][0]["extracted_chars"] > 0
        assert client.get(submission["files"][0]["download_url"]).content == b'{"test_fixture":true}'
        result = client.post(f"/api/submissions/{submission['id']}/reviews", json={"consent": True})
        assert result.status_code == 422  # No provider: no fabricated score.
        progress = client.patch(f"/api/tasks/{first['id']}/progress", json={
            "status": "in_progress", "actual_hours": 1.5, "notes": "集成验证记录",
        })
        assert progress.status_code == 200
        assert client.get("/api/dashboard").json()["submitted_tasks"] == 1

    with TestClient(create_app(config)) as client:
        signed_in = client.post("/api/auth/login", headers={"X-FDE-Client": "web"}, json={
            "username": "course_qa", "password": "local-test-password-only",
        })
        assert signed_in.status_code == 200
        assert client.get("/api/course").json()["progress"][first["id"]]["actual_hours"] == 1.5
        assert client.get(f"/api/submissions/{submission['id']}").json()["version"] == 1
