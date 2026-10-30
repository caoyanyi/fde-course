from __future__ import annotations

import hmac
import json
import math
import secrets
import sqlite3
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from cryptography.fernet import InvalidToken
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException as StarletteHTTPException

from .ai import PROMPT_VERSION, ProviderError, ReviewWorker, chat_completion, resolve_endpoint
from .config import Settings
from .db import Database, encode, now
from .security import COOKIE_NAME, LoginLimiter, check_password, encryption, hash_password, token_hash
from .uploads import MAX_FILE_BYTES, MAX_FILES, MAX_TOTAL_BYTES, extract_file, safe_filename, sha256


MUTATIONS = {"POST", "PUT", "PATCH", "DELETE"}
MAX_REQUEST_BYTES = 9 * 1024 * 1024


class RequestTooLarge(Exception):
    pass


class BodySizeLimit:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope["headers"])
        try:
            length = int(headers.get(b"content-length", b"0"))
        except ValueError:
            length = MAX_REQUEST_BYTES + 1
        if length > MAX_REQUEST_BYTES:
            return await JSONResponse({"detail": "请求超过 9 MiB 总大小上限"}, status_code=413)(scope, receive, send)
        size = 0

        async def limited_receive():
            nonlocal size
            message = await receive()
            if message["type"] == "http.request":
                size += len(message.get("body", b""))
                if size > MAX_REQUEST_BYTES:
                    raise RequestTooLarge()
            return message

        try:
            await self.app(scope, limited_receive, send)
        except RequestTooLarge:
            await JSONResponse({"detail": "请求超过 9 MiB 总大小上限"}, status_code=413)(scope, receive, send)


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=40, pattern=r"^[A-Za-z0-9_-]+$")
    password: str = Field(min_length=12, max_length=128)


class SetupCredentials(Credentials):
    setup_token: str = Field(min_length=1, max_length=512)


class ProgressUpdate(BaseModel):
    status: Literal["not_started", "in_progress", "completed"]
    actual_hours: float | None = Field(default=None, ge=0, le=10_000, allow_inf_nan=False)
    notes: str = Field(default="", max_length=5000)


class AISettingsUpdate(BaseModel):
    provider_label: str = Field(default="自定义模型服务", min_length=1, max_length=80)
    base_url: str = Field(min_length=8, max_length=500)
    model: str = Field(min_length=1, max_length=120, pattern=r"^[^\s\x00-\x1f]+$")
    api_key: str | None = Field(default=None, max_length=4096)
    clear_api_key: bool = False
    max_tokens: int = Field(default=3000, ge=256, le=8192)
    timeout_seconds: int = Field(default=90, ge=10, le=180)
    temperature: float = Field(default=0.2, ge=0, le=1, allow_inf_nan=False)


class ReviewRequest(BaseModel):
    consent: Literal[True]


def load_course(path: Path) -> tuple[dict, dict[str, dict]]:
    course = json.loads(path.read_text(encoding="utf-8"))
    tasks: dict[str, dict] = {}
    for week in course["weeks"]:
        for task in week["tasks"]:
            if task["id"] in tasks:
                raise ValueError("课程存在重复 task id")
            rubric = task["rubric"]
            if not rubric or len({item["id"] for item in rubric}) != len(rubric):
                raise ValueError("课程 rubric id 缺失或重复")
            if any(not isinstance(item["weight"], (int, float)) or isinstance(item["weight"], bool) or not math.isfinite(item["weight"]) or item["weight"] <= 0 or item["weight"] > 100 for item in rubric):
                raise ValueError("课程 rubric 权重无效")
            if abs(sum(item["weight"] for item in rubric) - 100) > 0.001:
                raise ValueError("每个任务的 rubric 权重之和必须为 100")
            tasks[task["id"]] = task
    if not tasks:
        raise ValueError("课程中没有任务")
    return course, tasks


def review_public(row) -> dict | None:
    if row is None:
        return None
    return {
        "id": row["id"], "submission_id": row["submission_id"], "status": row["status"],
        "created_at": row["created_at"], "completed_at": row["completed_at"], "error": row["error"],
        "model": row["model"], "provider_label": row["provider_label"],
        "report": json.loads(row["report"]) if row["report"] else None,
        "usage": json.loads(row["usage"]) if row["usage"] else None,
        "prompt_version": row["prompt_version"], "data_consent_at": row["data_consent_at"],
    }


def submission_public(conn, row, include_reviews: bool = False) -> dict:
    files = []
    for file in conn.execute("SELECT * FROM files WHERE submission_id=? ORDER BY rowid", (row["id"],)):
        files.append({
            "id": file["id"], "filename": file["filename"], "size": file["size"],
            "sha256": file["sha256"], "extracted_chars": len(file["extracted_text"]),
            "truncated": bool(file["truncated"]), "extraction_note": file["extraction_note"],
            "download_url": f"/api/files/{file['id']}",
        })
    reviews = [review_public(item) for item in conn.execute("SELECT * FROM reviews WHERE submission_id=? ORDER BY rowid DESC", (row["id"],))]
    result = {
        "id": row["id"], "task_id": row["task_id"], "version": row["version"],
        "content": row["content"], "evidence_notes": row["evidence_notes"], "created_at": row["created_at"],
        "course_version": row["course_version"], "static_checks": json.loads(row["static_checks"]),
        "files": files, "latest_review": reviews[0] if reviews else None,
    }
    if include_reviews:
        result["reviews"] = reviews
    return result


def settings_public(row) -> dict:
    if row is None:
        return {"provider_label": "自定义模型服务", "base_url": "", "model": "", "api_key_set": False, "max_tokens": 3000, "timeout_seconds": 90, "temperature": 0.2}
    return {key: row[key] for key in ("provider_label", "base_url", "model", "max_tokens", "timeout_seconds", "temperature")} | {"api_key_set": bool(row["api_key_cipher"])}


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or Settings()
    db = Database(config.database_path)
    limiter = LoginLimiter()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        config.data_dir.mkdir(parents=True, exist_ok=True)
        config.data_dir.chmod(0o700)
        config.upload_dir.mkdir(parents=True, exist_ok=True)
        config.upload_dir.chmod(0o700)
        db.initialize()
        app.state.cipher = encryption(config)
        app.state.course, app.state.tasks = load_course(config.course_path)
        app.state.worker = ReviewWorker(db, app.state.cipher, config)
        app.state.db = db
        if config.start_worker:
            app.state.worker.start()
        yield
        app.state.worker.stop()

    app = FastAPI(title="FDE Learning API", version="1.0.0", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.config = config

    @app.middleware("http")
    async def request_security(request: Request, call_next):
        if request.method in MUTATIONS:
            if request.headers.get("x-fde-client") != "web":
                return JSONResponse({"detail": "缺少 X-FDE-Client 请求标记"}, status_code=403)
            origin = request.headers.get("origin")
            if origin:
                try:
                    parsed = urlsplit(origin)
                    valid = parsed.scheme in ("https", "http") and not parsed.username and not parsed.password and not parsed.query and not parsed.fragment and parsed.path in ("", "/")
                except ValueError:
                    return JSONResponse({"detail": "请求来源格式无效"}, status_code=403)
                if config.public_origin:
                    valid = valid and origin.rstrip("/") == config.public_origin
                else:
                    valid = valid and parsed.netloc.lower() == request.headers.get("host", "").lower()
                if not valid:
                    return JSONResponse({"detail": "请求来源与本站不一致"}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Cache-Control"] = "no-store"
        return response

    app.add_middleware(BodySizeLimit)

    def lookup_session(request: Request):
        cookie = request.cookies.get(COOKIE_NAME)
        if not cookie or len(cookie) > 200:
            return None
        with db.connect() as conn:
            return conn.execute(
                "SELECT sessions.*, users.username FROM sessions JOIN users ON users.id=sessions.user_id WHERE token_hash=? AND expires_at>?",
                (token_hash(cookie), int(time.time())),
            ).fetchone()

    def current_user(request: Request):
        session = lookup_session(request)
        if session is None:
            raise HTTPException(401, "请先登录")
        if request.method in MUTATIONS and not hmac.compare_digest(request.headers.get("x-csrf-token", "").encode(), session["csrf_token"].encode()):
            raise HTTPException(403, "CSRF 校验失败，请刷新页面后重试")
        return {"id": session["user_id"], "username": session["username"], "csrf_token": session["csrf_token"]}

    def auth_state(request: Request) -> dict:
        session = lookup_session(request)
        with db.connect() as conn:
            initialized = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] > 0
        return {
            "initialized": initialized, "authenticated": session is not None,
            "user": {"id": session["user_id"], "username": session["username"]} if session else None,
            "csrf_token": session["csrf_token"] if session else None,
            "setup_token_configured": bool(config.setup_token),
        }

    def create_session(response: Response, username: str) -> dict:
        cookie, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        ttl = config.session_days * 86400
        with db.connect() as conn:
            conn.execute("DELETE FROM sessions WHERE expires_at<=?", (int(time.time()),))
            conn.execute("INSERT INTO sessions(token_hash,user_id,csrf_token,expires_at) VALUES (?,1,?,?)", (token_hash(cookie), csrf, int(time.time()) + ttl))
            # Bound stale sessions for a single user without disrupting normal devices.
            conn.execute("DELETE FROM sessions WHERE token_hash NOT IN (SELECT token_hash FROM sessions ORDER BY expires_at DESC LIMIT 20)")
        response.set_cookie(COOKIE_NAME, cookie, max_age=ttl, httponly=True, secure=config.secure_cookie, samesite="strict", path="/")
        return {"initialized": True, "authenticated": True, "user": {"id": 1, "username": username}, "csrf_token": csrf, "setup_token_configured": bool(config.setup_token)}

    def require_task(task_id: str) -> dict:
        task = app.state.tasks.get(task_id)
        if task is None:
            raise HTTPException(404, "未找到课程任务")
        return task

    def ip_key(request: Request) -> str:
        return request.client.host if request.client else "unknown"

    @app.get("/api/health")
    def health():
        with db.connect() as conn:
            conn.execute("SELECT 1")
        return {"status": "ok", "version": "1.0.0", "review_mode": "ai_review", "runtime_execution": False}

    @app.get("/api/auth/status")
    def status(request: Request):
        return auth_state(request)

    @app.post("/api/auth/setup", status_code=201)
    def setup(payload: SetupCredentials, request: Request, response: Response):
        if not config.setup_token:
            raise HTTPException(503, "服务器未配置 APP_SETUP_TOKEN，初始化已关闭；请先在部署环境中设置")
        if not limiter.allow(ip_key(request)):
            raise HTTPException(429, "尝试过于频繁，请 15 分钟后重试")
        if not hmac.compare_digest(payload.setup_token.encode(), config.setup_token.encode()):
            raise HTTPException(403, "初始化口令不正确")
        with db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if conn.execute("SELECT 1 FROM users").fetchone():
                raise HTTPException(409, "系统已初始化，请登录")
            conn.execute("INSERT INTO users(id,username,password_hash,created_at) VALUES (1,?,?,?)", (payload.username, hash_password(payload.password), now()))
        limiter.clear(ip_key(request))
        return create_session(response, payload.username)

    @app.post("/api/auth/login")
    def login(payload: Credentials, request: Request, response: Response):
        if not limiter.allow(ip_key(request)):
            raise HTTPException(429, "登录尝试过于频繁，请 15 分钟后重试")
        with db.connect() as conn:
            user = conn.execute("SELECT * FROM users WHERE username=?", (payload.username,)).fetchone()
        # Equal-cost password work for unknown usernames.
        stored = user["password_hash"] if user else f"pbkdf2_sha256$600000${'00' * 16}${'00' * 32}"
        matches = check_password(payload.password, stored)
        if user is None or not matches:
            raise HTTPException(401, "用户名或密码不正确")
        limiter.clear(ip_key(request))
        return create_session(response, user["username"])

    @app.post("/api/auth/logout")
    def logout(request: Request, response: Response, user=Depends(current_user)):
        with db.connect() as conn:
            conn.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash(request.cookies.get(COOKIE_NAME, "")),))
        response.delete_cookie(COOKIE_NAME, path="/", secure=config.secure_cookie, httponly=True, samesite="strict")
        return {"ok": True}

    @app.get("/api/course")
    def course(user=Depends(current_user)):
        with db.connect() as conn:
            progress = {row["task_id"]: {key: row[key] for key in ("status", "actual_hours", "notes", "updated_at")} for row in conn.execute("SELECT * FROM progress")}
        return {"course": app.state.course, "progress": progress}

    @app.get("/api/dashboard")
    def dashboard(user=Depends(current_user)):
        with db.connect() as conn:
            progress = {row["task_id"]: dict(row) for row in conn.execute("SELECT * FROM progress")}
            submissions = [submission_public(conn, row) for row in conn.execute("SELECT * FROM submissions ORDER BY rowid DESC LIMIT 5")]
            reviews = [review_public(row) for row in conn.execute("SELECT * FROM reviews ORDER BY rowid DESC LIMIT 8")]
            submitted_tasks = conn.execute("SELECT COUNT(DISTINCT task_id) FROM submissions").fetchone()[0]
        return {
            "total_tasks": len(app.state.tasks),
            "completed_tasks": sum(item["status"] == "completed" for item in progress.values()),
            "in_progress_tasks": sum(item["status"] == "in_progress" for item in progress.values()),
            "submitted_tasks": submitted_tasks, "total_hours": app.state.course.get("totalHours", 200),
            "actual_hours": sum(item["actual_hours"] or 0 for item in progress.values()),
            "next_task_id": next((task_id for task_id in app.state.tasks if progress.get(task_id, {}).get("status") != "completed"), None),
            "latest_submissions": submissions, "recent_reviews": reviews,
        }

    @app.patch("/api/tasks/{task_id}/progress")
    def update_progress(task_id: str, payload: ProgressUpdate, user=Depends(current_user)):
        require_task(task_id)
        timestamp = now()
        with db.connect() as conn:
            conn.execute("INSERT INTO progress(task_id,status,actual_hours,notes,updated_at) VALUES (?,?,?,?,?) ON CONFLICT(task_id) DO UPDATE SET status=excluded.status,actual_hours=excluded.actual_hours,notes=excluded.notes,updated_at=excluded.updated_at", (task_id, payload.status, payload.actual_hours, payload.notes, timestamp))
        return {"task_id": task_id, **payload.model_dump(), "updated_at": timestamp}

    @app.post("/api/tasks/{task_id}/submissions", status_code=201)
    async def create_submission(task_id: str, request: Request, user=Depends(current_user)):
        task = require_task(task_id)
        paths = []
        try:
            async with request.form(max_files=MAX_FILES, max_fields=10, max_part_size=256_000) as form:
                content = form.get("content", "")
                evidence_notes = form.get("evidence_notes", "")
                if not isinstance(content, str) or not isinstance(evidence_notes, str):
                    raise HTTPException(422, "正文和证据说明必须是文本")
                if len(content) > 60_000 or len(evidence_notes) > 10_000:
                    raise HTTPException(422, "正文最多 60000 字符，证据说明最多 10000 字符")
                uploads = []
                for key, value in form.multi_items():
                    if isinstance(value, UploadFile):
                        if key not in ("files", "files[]"):
                            raise HTTPException(422, "附件字段名应为 files 或 files[]")
                        uploads.append(value)
                if len(uploads) > MAX_FILES:
                    raise HTTPException(422, "每次最多上传 5 个文件")
                if not content.strip() and not uploads:
                    raise HTTPException(422, "请填写作业正文或上传至少一个文件")
                submission_id = secrets.token_hex(16)
                files = []
                total = 0
                checks = [{"name": "静态检查范围", "status": "warning", "message": "系统只检查可读取文本、文件格式及有限语法；没有运行代码、测试、URL 或部署环境。"}]
                for upload in uploads:
                    try:
                        filename = safe_filename(upload.filename or "")
                    except ValueError as exc:
                        raise HTTPException(422, str(exc)) from exc
                    data = await upload.read(MAX_FILE_BYTES + 1)
                    total += len(data)
                    if len(data) > MAX_FILE_BYTES or total > MAX_TOTAL_BYTES:
                        raise HTTPException(413, "每个文件最多 2 MiB，附件总计最多 8 MiB")
                    file_id = secrets.token_hex(16)
                    stored_name = f"{file_id}.data"
                    path = config.upload_dir / stored_name
                    with path.open("xb") as handle:
                        handle.write(data)
                    path.chmod(0o600)
                    paths.append(path)
                    try:
                        # Parsing cannot execute uploaded code. PDF uses a resource-limited helper.
                        from starlette.concurrency import run_in_threadpool
                        text, truncated, note, file_checks = await run_in_threadpool(extract_file, path, filename, data)
                    except ValueError as exc:
                        raise HTTPException(422, str(exc)) from exc
                    checks.extend(file_checks)
                    files.append((file_id, submission_id, filename, stored_name, len(data), sha256(data), text, int(truncated), note))
                if any(file[7] for file in files):
                    checks.append({"name": "附件提取范围", "status": "warning", "message": "部分附件超过 30000 字符，只会评审已提取部分。"})
                checks.append({"name": "提交记录", "status": "passed", "message": "正文与附件已保存，附件已计算 SHA-256；尚未发起 AI 评审。"})
                with db.connect() as conn:
                    conn.execute("BEGIN IMMEDIATE")
                    version = conn.execute("SELECT COALESCE(MAX(version),0)+1 FROM submissions WHERE task_id=?", (task_id,)).fetchone()[0]
                    conn.execute("INSERT INTO submissions(id,task_id,version,content,evidence_notes,created_at,static_checks,course_version,task_snapshot) VALUES (?,?,?,?,?,?,?,?,?)", (submission_id, task_id, version, content, evidence_notes, now(), encode(checks), str(app.state.course.get("version", "1")), encode(task)))
                    conn.executemany("INSERT INTO files(id,submission_id,filename,stored_name,size,sha256,extracted_text,truncated,extraction_note) VALUES (?,?,?,?,?,?,?,?,?)", files)
                    row = conn.execute("SELECT * FROM submissions WHERE id=?", (submission_id,)).fetchone()
                    result = submission_public(conn, row, include_reviews=True)
                paths.clear()
                return result
        except StarletteHTTPException:
            raise
        finally:
            for path in paths:
                path.unlink(missing_ok=True)

    @app.get("/api/submissions")
    def submissions(task_id: str | None = None, limit: int = 100, offset: int = 0, user=Depends(current_user)):
        if not 1 <= limit <= 200 or offset < 0:
            raise HTTPException(422, "分页参数无效")
        if task_id:
            require_task(task_id)
        with db.connect() as conn:
            if task_id:
                rows = conn.execute("SELECT * FROM submissions WHERE task_id=? ORDER BY version DESC LIMIT ? OFFSET ?", (task_id, limit, offset)).fetchall()
                count = conn.execute("SELECT COUNT(*) FROM submissions WHERE task_id=?", (task_id,)).fetchone()[0]
            else:
                rows = conn.execute("SELECT * FROM submissions ORDER BY rowid DESC LIMIT ? OFFSET ?", (limit, offset)).fetchall()
                count = conn.execute("SELECT COUNT(*) FROM submissions").fetchone()[0]
            return {"items": [submission_public(conn, row) for row in rows], "total": count, "limit": limit, "offset": offset}

    @app.get("/api/submissions/{submission_id}")
    def submission(submission_id: str, user=Depends(current_user)):
        with db.connect() as conn:
            row = conn.execute("SELECT * FROM submissions WHERE id=?", (submission_id,)).fetchone()
            if row is None:
                raise HTTPException(404, "未找到提交")
            return submission_public(conn, row, include_reviews=True)

    @app.get("/api/files/{file_id}")
    def download(file_id: str, user=Depends(current_user)):
        with db.connect() as conn:
            row = conn.execute("SELECT * FROM files WHERE id=?", (file_id,)).fetchone()
        if row is None:
            raise HTTPException(404, "未找到附件")
        path = config.upload_dir / row["stored_name"]
        if path.parent.resolve() != config.upload_dir.resolve() or not path.is_file():
            raise HTTPException(404, "附件文件不存在")
        return FileResponse(path, filename=row["filename"], media_type="application/octet-stream", content_disposition_type="attachment")

    @app.get("/api/settings/ai")
    def get_ai_settings(user=Depends(current_user)):
        with db.connect() as conn:
            return settings_public(conn.execute("SELECT * FROM ai_settings WHERE id=1").fetchone())

    @app.put("/api/settings/ai")
    def update_ai_settings(payload: AISettingsUpdate, user=Depends(current_user)):
        try:
            # Re-resolve at execution as well. Save rejects private addresses early.
            resolve_endpoint(payload.base_url, config)
        except ProviderError as exc:
            raise HTTPException(422, str(exc)) from exc
        if payload.api_key and any(not 33 <= ord(char) <= 126 for char in payload.api_key.strip()):
            raise HTTPException(422, "API Key 包含无效字符")
        with db.connect() as conn:
            existing = conn.execute("SELECT * FROM ai_settings WHERE id=1").fetchone()
            key_cipher = existing["api_key_cipher"] if existing else None
            if payload.clear_api_key:
                key_cipher = None
            elif payload.api_key and payload.api_key.strip():
                key_cipher = app.state.cipher.encrypt(payload.api_key.strip().encode()).decode()
            conn.execute("INSERT INTO ai_settings(id,provider_label,base_url,model,api_key_cipher,max_tokens,timeout_seconds,temperature,updated_at) VALUES (1,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET provider_label=excluded.provider_label,base_url=excluded.base_url,model=excluded.model,api_key_cipher=excluded.api_key_cipher,max_tokens=excluded.max_tokens,timeout_seconds=excluded.timeout_seconds,temperature=excluded.temperature,updated_at=excluded.updated_at", (payload.provider_label, payload.base_url.rstrip("/"), payload.model, key_cipher, payload.max_tokens, payload.timeout_seconds, payload.temperature, now()))
            return settings_public(conn.execute("SELECT * FROM ai_settings WHERE id=1").fetchone())

    @app.post("/api/settings/ai/test")
    def test_ai_settings(user=Depends(current_user)):
        with db.connect() as conn:
            row = conn.execute("SELECT * FROM ai_settings WHERE id=1").fetchone()
        if row is None or not row["api_key_cipher"]:
            raise HTTPException(422, "请先保存模型配置与 API Key")
        try:
            key = app.state.cipher.decrypt(row["api_key_cipher"].encode()).decode()
            started = time.monotonic()
            _, usage = chat_completion(dict(row), key, [{"role": "user", "content": "Reply with OK."}], config, test=True)
            return {"ok": True, "message": "已收到模型服务的有效文本响应。测试请求可能产生少量服务方费用。", "model": row["model"], "latency_ms": round((time.monotonic() - started) * 1000), "usage": usage}
        except InvalidToken as exc:
            raise HTTPException(422, "API Key 无法解密，请重新保存 API Key") from exc
        except ProviderError as exc:
            raise HTTPException(502, str(exc)) from exc

    @app.post("/api/submissions/{submission_id}/reviews", status_code=202)
    def request_review(submission_id: str, payload: ReviewRequest, user=Depends(current_user)):
        with db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if conn.execute("SELECT 1 FROM submissions WHERE id=?", (submission_id,)).fetchone() is None:
                raise HTTPException(404, "未找到提交")
            provider = conn.execute("SELECT * FROM ai_settings WHERE id=1").fetchone()
            if provider is None or not provider["api_key_cipher"]:
                raise HTTPException(422, "请先在 AI 设置中保存模型服务与 API Key")
            existing = conn.execute("SELECT id,status FROM reviews WHERE submission_id=? AND status IN ('queued','running')", (submission_id,)).fetchone()
            if existing:
                return {"review_id": existing["id"], "status": existing["status"]}
            queue_count = conn.execute("SELECT COUNT(*) FROM reviews WHERE status IN ('queued','running')").fetchone()[0]
            if queue_count >= 3:
                raise HTTPException(429, "当前已有 3 个待处理评审，请等待完成后再提交")
            timestamp = now()
            daily = conn.execute("SELECT COUNT(*) FROM reviews WHERE created_at>=?", (timestamp[:10] + "T00:00:00+00:00",)).fetchone()[0]
            if daily >= config.max_reviews_per_day:
                raise HTTPException(429, "已达到服务器每日评审次数上限（UTC），请明天再试或调整服务器配置")
            review_id = secrets.token_hex(16)
            snapshot = {key: provider[key] for key in ("provider_label", "base_url", "model", "api_key_cipher", "max_tokens", "timeout_seconds", "temperature")}
            conn.execute("INSERT INTO reviews(id,submission_id,status,created_at,model,provider_label,settings_snapshot,prompt_version,data_consent_at) VALUES (?,?,'queued',?,?,?,?,?,?)", (review_id, submission_id, timestamp, provider["model"], provider["provider_label"], encode(snapshot), PROMPT_VERSION, timestamp))
        app.state.worker.notify()
        return {"review_id": review_id, "status": "queued"}

    @app.get("/api/reviews/{review_id}")
    def get_review(review_id: str, user=Depends(current_user)):
        with db.connect() as conn:
            row = conn.execute("SELECT * FROM reviews WHERE id=?", (review_id,)).fetchone()
            if row is None:
                raise HTTPException(404, "未找到评审")
            return review_public(row)

    return app


app = create_app()
