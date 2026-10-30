import hashlib
import io
import json
import zipfile

import pytest

from app.ai import ProviderError
from app.materials import (
    MATERIAL_TYPES, MaterialWorker, normalize_materials, validate_filename,
    get_material_context,
)
from .conftest import TASK


def package(types=("scenario", "sample_data")):
    contents = {
        "scenario": ("scenario.md", "# 模拟客户案例\n客户要求整理客服 FAQ，数据全部虚构。"),
        "sample_data": ("data/customers.csv", "customer_id,segment,balance\n1,retail,-12.5\n2,business,20\n"),
        "knowledge_docs": ("docs/faq.md", "# 练习知识\n虚构产品的退款时间为七天。"),
        "test_cases": ("tests/cases.json", '{"cases":[{"input":"退款","expected":"七天"}]}'),
        "starter_template": ("templates/outline.md", "# TODO\n请自行完成实现与运行验证。"),
    }
    return {
        "title": "模拟客服场景素材", "summary": "模拟场景，仅用于课程练习。",
        "how_to_use": ["检查模拟需求", "完成自己的方案并收集运行证据"],
        "files": [{"filename": contents[kind][0], "kind": kind, "description": "练习输入", "content": contents[kind][1]} for kind in types],
        "synthetic": False, "runtime_verified": True,
    }


def request_payload(**overrides):
    return {"scenario": "客户客服知识库", "difficulty": "intermediate", "tech_stack": "PHP/Vue/SQL", "material_types": ["scenario", "sample_data"], "requirements": "使用虚构客户", "consent": True, **overrides}


def request_material(client, **overrides):
    response = client.post("/api/tasks/w01-t01/materials", json=request_payload(**overrides))
    assert response.status_code == 202, response.text
    return response.json()["material_id"]


def complete_material(configured, app, monkeypatch, **overrides):
    pack_id = request_material(configured, **overrides)
    types = overrides.get("material_types", ["scenario", "sample_data"])
    monkeypatch.setattr("app.materials.chat_completion", lambda *args, **kwargs: (json.dumps(package(types)), {"input_tokens": 20, "output_tokens": 40}))
    assert app.state.material_worker.process_next() is True
    result = configured.get(f"/api/materials/{pack_id}")
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "completed", result.text
    return result.json()


def switch_user(client, username, password):
    client.post("/api/auth/logout")
    result = client.post("/api/auth/login", json={"username": username, "password": password})
    assert result.status_code == 200, result.text
    client.headers["X-CSRF-Token"] = result.json()["csrf_token"]
    return result.json()


def create_learner(client, username="student_b", limit=5):
    response = client.post("/api/admin/users", json={"username": username, "password": "initial-test-password-123", "display_name": "学员乙", "role": "learner", "review_daily_limit": 10, "material_daily_limit": limit})
    assert response.status_code == 201, response.text
    return response.json()


def activate_learner(client, username="student_b"):
    switch_user(client, username, "initial-test-password-123")
    result = client.post("/api/auth/change-password", json={"current_password": "initial-test-password-123", "new_password": "changed-test-password-456"})
    assert result.status_code == 200, result.text
    client.headers["X-CSRF-Token"] = result.json()["csrf_token"]


def test_normalization_forces_provenance_and_computes_bytes():
    result = normalize_materials(json.dumps(package(MATERIAL_TYPES)), list(MATERIAL_TYPES))
    assert result["synthetic"] is True and result["runtime_verified"] is False
    assert len(result["files"]) == 5
    for file in result["files"]:
        data = file["content"].encode("utf-8")
        assert file["size"] == len(data)
        assert file["sha256"] == hashlib.sha256(data).hexdigest()


@pytest.mark.parametrize("filename", [
    "../escape.md", "/absolute.md", "dir\\escape.md", "dir//file.md", ".hidden.md",
    "dir/../file.md", "CON.txt", "com1.csv", "LPT².md", "a:b.md", "q?.md",
    'q".md', "q<.md", "q>.md", "q|.md", "q*.md", "manifest.json", "MANIFEST.json/file.md",
    "a/b/c/d/e.md", "space /file.md", "trail./file.md", "a\x00.md", "start.sh",
])
def test_unsafe_filenames_rejected(filename):
    with pytest.raises(ProviderError):
        validate_filename(filename)


@pytest.mark.parametrize("filenames", [("Case.md", "case.md"), ("folder.md", "folder.md/file.md"), ("folder.md/file.md", "folder.md")])
def test_duplicate_or_prefix_paths_rejected(filenames):
    data = package()
    for file, name in zip(data["files"], filenames):
        file["filename"] = name
    with pytest.raises(ProviderError):
        normalize_materials(json.dumps(data), ["scenario", "sample_data"])


@pytest.mark.parametrize("body", ['{"a":1,"a":2}', '{"a":NaN}', '{"a":Infinity}', '{"bad":'])
def test_invalid_json_file_rejected(body):
    data = package(("sample_data",))
    data["files"][0].update(filename="data.json", content=body)
    with pytest.raises(ProviderError):
        normalize_materials(json.dumps(data), ["sample_data"])


def test_duplicate_outer_keys_rejected():
    raw = json.dumps(package()).replace('"title":', '"title":"duplicate","title":', 1)
    with pytest.raises(ProviderError):
        normalize_materials(raw, ["scenario", "sample_data"])


@pytest.mark.parametrize("field", ["filename", "content", "title", "summary", "description", "how_to_use"])
def test_unpaired_surrogates_in_model_strings_rejected(field):
    data = package(("scenario",))
    invalid = "invalid\ud800.md"
    if field in ("title", "summary"):
        data[field] = invalid
    elif field == "how_to_use":
        data[field] = [invalid]
    else:
        data["files"][0][field] = invalid
    # The model can legally transport a JSON escape which json.loads turns into
    # a lone surrogate. Reject before SQLite, ZIP or HTTP headers see it.
    with pytest.raises(ProviderError, match="Unicode"):
        normalize_materials(json.dumps(data), ["scenario"])


@pytest.mark.parametrize("body", [
    "a,b\n1\n", "a,a\n1,2\n", ",b\n1,2\n", "a,b\n1,=SUM(1)\n",
    "a,b\n1, +SUM(1)\n", "a,b\n1,\t@SUM(1)\n", "a,b\n1,-cmd\n",
    'a,b\n1,"unclosed\n',
])
def test_invalid_or_formula_csv_rejected(body):
    data = package(("sample_data",))
    data["files"][0]["content"] = body
    with pytest.raises(ProviderError):
        normalize_materials(json.dumps(data), ["sample_data"])


def test_missing_kinds_and_large_content_rejected():
    with pytest.raises(ProviderError):
        normalize_materials(json.dumps(package(("scenario",))), ["scenario", "sample_data"])
    data = package(("scenario",))
    data["files"][0]["content"] = "x" * 10001
    with pytest.raises(ProviderError):
        normalize_materials(json.dumps(data), ["scenario"])
    data = package(MATERIAL_TYPES)
    for item in data["files"]:
        item.update(filename=item["kind"] + ".txt", content="x" * 9000)
    with pytest.raises(ProviderError):
        normalize_materials(json.dumps(data), list(MATERIAL_TYPES))


def test_consent_types_and_configuration_validation(logged_in):
    assert logged_in.post("/api/tasks/w01-t01/materials", json=request_payload(consent=False)).status_code == 422
    assert logged_in.post("/api/tasks/w01-t01/materials", json=request_payload(material_types=[])).status_code == 422
    assert logged_in.post("/api/tasks/w01-t01/materials", json=request_payload(material_types=["scenario", "scenario"])).status_code == 422
    assert logged_in.post("/api/tasks/w01-t01/materials", json=request_payload(material_types=["execute_code"])).status_code == 422
    assert logged_in.post("/api/tasks/unknown/materials", json=request_payload()).status_code == 404
    assert logged_in.post("/api/tasks/w01-t01/materials", json=request_payload()).status_code == 422


def test_worker_prompt_versioning_and_downloads(configured, app, monkeypatch):
    seen = {}
    pack_id = request_material(configured)
    assert request_material(configured, material_types=["sample_data", "scenario"]) == pack_id
    different = configured.post("/api/tasks/w01-t01/materials", json=request_payload(scenario="另一个场景"))
    assert different.status_code == 409
    def generate(provider, key, messages, settings):
        seen.update(provider=provider, messages=messages)
        assert key == "sk-unit-test-not-a-real-key"
        return json.dumps(package()), {"input_tokens": 123, "output_tokens": 456}
    monkeypatch.setattr("app.materials.chat_completion", generate)
    assert app.state.material_worker.process_next() is True
    assert app.state.material_worker.process_next() is False
    result = configured.get(f"/api/materials/{pack_id}").json()
    assert result["status"] == "completed" and result["version"] == 1
    assert result["synthetic"] is True and result["runtime_verified"] is False
    assert result["usage"]["input_tokens"] == 123
    assert seen["provider"]["max_tokens"] == 6000
    assert "sk-unit-test" not in json.dumps(seen["messages"])
    assert "untrusted_material_request" in seen["messages"][1]["content"]
    listed = configured.get("/api/materials?task_id=w01-t01&limit=1").json()
    assert listed["total"] == 1 and "content" not in listed["items"][0]["files"][0]
    file = result["files"][0]
    download = configured.get(file["download_url"])
    assert download.content.decode("utf-8") == file["content"]
    assert "attachment" in download.headers["content-disposition"]
    zipped = configured.get(result["download_url"])
    with zipfile.ZipFile(io.BytesIO(zipped.content)) as bundle:
        manifest = json.loads(bundle.read("manifest.json"))
        assert manifest["synthetic"] is True and manifest["runtime_verified"] is False
        assert manifest["version"] == 1
        assert "content" not in manifest["files"][0]
        assert bundle.read(file["filename"]) == download.content
        assert "api_key" not in bundle.read("manifest.json").decode()
    second_id = request_material(configured)
    assert second_id != pack_id
    assert configured.get(f"/api/materials/{second_id}").json()["version"] == 2
    assert configured.get(f"/api/materials/{second_id}/download").status_code == 409


def test_failed_output_saves_no_files_and_counts_quota(configured, app, monkeypatch):
    with app.state.db.connect() as conn:
        conn.execute("UPDATE users SET material_daily_limit=1 WHERE id=1")
    pack_id = request_material(configured)
    monkeypatch.setattr("app.materials.chat_completion", lambda *args: ("invalid JSON", None))
    assert app.state.material_worker.process_next()
    detail = configured.get(f"/api/materials/{pack_id}").json()
    assert detail["status"] == "failed" and detail["files"] == []
    assert configured.post("/api/tasks/w01-t01/materials", json=request_payload()).status_code == 429
    assert configured.get("/api/usage").json()["materials"]["used"] == 1


def test_global_material_quota_and_user_zero_quota(configured, app):
    app.state.config.max_materials_per_day = 0
    assert configured.post("/api/tasks/w01-t01/materials", json=request_payload()).status_code == 429
    app.state.config.max_materials_per_day = 30
    with app.state.db.connect() as conn:
        conn.execute("UPDATE users SET material_daily_limit=0 WHERE id=1")
    assert configured.post("/api/tasks/w01-t01/materials", json=request_payload()).status_code == 429


@pytest.mark.parametrize("changed_field", ["is_active", "must_change_password"])
def test_worker_rechecks_account_before_provider_call(configured, app, monkeypatch, changed_field):
    pack_id = request_material(configured)
    with app.state.db.connect() as conn:
        value = 0 if changed_field == "is_active" else 1
        conn.execute(f"UPDATE users SET {changed_field}=? WHERE id=1", (value,))
    called = []
    monkeypatch.setattr("app.materials.chat_completion", lambda *args: called.append(True))
    assert app.state.material_worker.process_next()
    assert called == []
    with app.state.db.connect() as conn:
        row = conn.execute("SELECT status,error FROM materials WHERE id=?", (pack_id,)).fetchone()
        assert row["status"] == "failed" and "未调用模型" in row["error"]


def test_restart_fails_running_without_retry(configured, app, monkeypatch):
    pack_id = request_material(configured)
    with app.state.db.connect() as conn:
        conn.execute("UPDATE materials SET status='running' WHERE id=?", (pack_id,))
    monkeypatch.setattr(MaterialWorker, "_run", lambda self: None)
    worker = MaterialWorker(app.state.db, app.state.cipher, app.state.config)
    worker.start()
    worker.stop()
    detail = configured.get(f"/api/materials/{pack_id}").json()
    assert detail["status"] == "failed" and "重启" in detail["error"]


def test_per_user_material_isolation_and_submission_binding(configured, app, monkeypatch):
    first = complete_material(configured, app, monkeypatch)
    create_learner(configured)
    activate_learner(configured)
    assert configured.get("/api/materials").json()["items"] == []
    assert configured.get(f"/api/materials/{first['id']}").status_code == 404
    assert configured.get(first["download_url"]).status_code == 404
    assert configured.get(first["files"][0]["download_url"]).status_code == 404
    denied = configured.post("/api/tasks/w01-t01/submissions", data={"content": "自己的作业", "material_pack_id": first["id"]})
    assert denied.status_code == 404
    own = complete_material(configured, app, monkeypatch)
    assert own["version"] == 1
    submitted = configured.post("/api/tasks/w01-t01/submissions", data={"content": "自己的作业", "material_pack_id": own["id"]})
    assert submitted.status_code == 201, submitted.text
    assert submitted.json()["material_pack_id"] == own["id"]
    switch_user(configured, "learner", "a-strong-test-password")
    assert configured.get(f"/api/materials/{own['id']}").status_code == 404
    assert configured.get(f"/api/submissions/{submitted.json()['id']}").status_code == 404
    assert configured.get("/api/materials").json()["total"] == 1


def test_submission_rejects_pending_or_other_task_material(configured, app, monkeypatch):
    pending = request_material(configured)
    assert configured.post("/api/tasks/w01-t01/submissions", data={"content": "我的作业", "material_pack_id": pending}).status_code == 422
    monkeypatch.setattr("app.materials.chat_completion", lambda *args: (json.dumps(package()), None))
    app.state.material_worker.process_next()
    app.state.tasks["w02-t01"] = {**TASK, "id": "w02-t01"}
    assert configured.post("/api/tasks/w02-t01/submissions", data={"content": "我的作业", "material_pack_id": pending}).status_code == 422
    with app.state.db.connect() as conn:
        context = get_material_context(conn, pending, 1, "w01-t01")
    assert context["synthetic"] is True
    assert "不是学习者" in context["purpose"]
    assert sum(len(file["content"]) for file in context["files"]) <= 20000


def test_material_background_is_not_grading_evidence(configured, app, monkeypatch):
    material = complete_material(configured, app, monkeypatch, material_types=["scenario"])
    created = configured.post("/api/tasks/w01-t01/submissions", data={"content": "客户需求和验收标准", "material_pack_id": material["id"]})
    assert created.status_code == 201, created.text
    submission = created.json()
    request = configured.post(f"/api/submissions/{submission['id']}/reviews", json={"consent": True})
    assert request.status_code == 202
    seen = {}
    def grade(provider, key, messages, settings):
        seen["input"] = json.loads(messages[1]["content"])
        return json.dumps({
            "rubric": [{"id": "problem", "score": 60, "feedback": "引用素材", "evidence": ["客户要求整理客服 FAQ"]}, {"id": "evidence", "score": 40, "feedback": "已读", "evidence": ["验收标准"]}],
            "summary": "不能据此得分", "strengths": [], "improvements": [], "missing_evidence": [], "next_steps": [], "confidence": "low",
        }), None
    monkeypatch.setattr("app.ai.chat_completion", grade)
    assert app.state.worker.process_next()
    result = configured.get(f"/api/reviews/{request.json()['review_id']}").json()
    assert result["status"] == "failed" and result["report"] is None
    # The background is present in its own field, outside learner evidence.
    assert "客户要求整理客服 FAQ" in json.dumps(seen["input"], ensure_ascii=False)
    assert "客户要求整理客服 FAQ" not in json.dumps(seen["input"]["untrusted_submission_evidence"], ensure_ascii=False)
