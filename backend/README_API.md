# FDE Learning API · v1

Python 3.12，FastAPI，SQLite。启动目录为 `backend`，入口为 `uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1`。只运行一个 worker；评审使用一个后台线程和持久化 SQLite 队列。

## 环境变量

| 变量 | 默认值 / 说明 |
| --- | --- |
| `DATA_DIR` | `./data`；数据库 `learning.sqlite3`、附件 `uploads/` |
| `COURSE_PATH` | `../course/curriculum.json`；Docker 中 `/app/course/curriculum.json` |
| `APP_SETUP_TOKEN` | 必须设置才能初始化；初始化口令只从服务器环境读取 |
| `APP_MASTER_KEY` | 建议设置 32 字符以上随机值；不设置时生成 `DATA_DIR/master.key` |
| `PUBLIC_ORIGIN` | 生产设为 `https://你的域名`；为空时按请求 Host 核对 Origin，适配保留 Host 的本地代理 |
| `SESSION_COOKIE_SECURE` | `true`；仅本地 HTTP 调试时设 `false` |
| `AI_PRIVATE_HOST_ALLOWLIST` | 默认空；逗号分隔的精确 hostname，只有显式列入的主机可访问私网/HTTP |
| `MAX_REVIEWS_PER_DAY` | `30`，UTC 日历日计数，失败请求也计入以约束费用 |

`APP_MASTER_KEY`/自动生成的 master.key 必须随数据备份，否则保存的第三方密钥不能解密。数据库与附件只用于此单用户账号。SQLite 使用 WAL；备份须使用 SQLite backup API 或停止应用后复制完整数据目录。

## 认证、CSRF 与错误

所有写请求包含 `X-FDE-Client: web`。登录后所有写请求还包含 `X-CSRF-Token: <csrf_token>`。浏览器使用 `credentials: include`；前后端同源 `/api`。Session cookie 为 HttpOnly、SameSite=Strict，生产为 Secure，7 天过期。没有开放跨域 CORS。

提供 Origin 时必须匹配本站。生产严格匹配 `PUBLIC_ORIGIN`；预览不设置该值时比较 Origin 的 host:port 与请求 Host（允许 http/https 代理协议差异）。不使用用户可控的 X-Forwarded-Host 判定。无 Origin 的脚本客户端仍必须携带上述标记和 CSRF。

普通错误为 HTTP 非 2xx、`{"detail":"中文说明"}`。输入字段校验错误可能返回 Pydantic `detail` 数组。401 表示需登录，403 表示口令/来源/CSRF 错误，409 表示重复初始化，413 表示大小超限，422 表示输入或模型配置问题，429 表示限流，502 表示第三方连接失败。

## Auth

- `GET /api/health`：公开健康检查，`{status:"ok",version,review_mode:"ai_review",runtime_execution:false}`。
- `GET /api/auth/status`：`{initialized,authenticated,user:{id,username}|null,csrf_token:string|null,setup_token_configured}`。
- `POST /api/auth/setup`：JSON `{username,password,setup_token}`，成功 201 并登录，返回 auth/status 同结构。用户名 3–40 位英文字母/数字/下划线/短横线，密码 12–128 字符。单用户初始化只允许一次。
- `POST /api/auth/login`：JSON `{username,password}`，返回同上。
- `POST /api/auth/logout`：清除当前会话，返回 `{ok:true}`。

登录和初始化每个连接来源最多 10 次尝试/15 分钟；生产反向代理还可配置自己的限流。

## 课程、进度

- `GET /api/course`：`{course:<原始课程 JSON>,progress:{[task_id]:{status,actual_hours,notes,updated_at}}}`。
- `PATCH /api/tasks/{task_id}/progress`：JSON `{status:"not_started"|"in_progress"|"completed",actual_hours:number|null,notes:string}`，返回 `{task_id,...上述字段,updated_at}`。实际时数 0–10000，备注最多 5000 字符。完成是学习者手动标记，不等于 AI 或运行验收。
- `GET /api/dashboard`：`{total_tasks,completed_tasks,in_progress_tasks,submitted_tasks,total_hours,actual_hours,next_task_id,latest_submissions:[Submission],recent_reviews:[Review]}`。

课程使用内置的 10 周 JSON schema，启动时校验任务 id 唯一、rubric id 唯一且权重和 100。提交时保存该任务和课程版本快照，避免未来改课影响旧作业评审。

## 提交与文件

- `POST /api/tasks/{task_id}/submissions`：multipart 文本 `content`、`evidence_notes` 和重复的 `files`（兼容 `files[]`）；成功 201，返回包含空 reviews 数组的 Submission。正文最多 60000 字符，证据说明最多 10000 字符。至少有正文或一个附件。保存不自动调用第三方。
- `GET /api/submissions?task_id=<可选>&limit=100&offset=0`：`{items:[Submission],total,limit,offset}`；limit 1–200。
- `GET /api/submissions/{id}`：返回 Submission，额外包含 `reviews:[Review]`，按新到旧排列。
- `GET /api/files/{id}`：登录后附件下载，固定 `application/octet-stream`、attachment，不在服务器执行或作为网页渲染。

Submission：

```json
{
  "id": "32-char-id", "task_id": "w01-t01", "version": 1,
  "content": "...", "evidence_notes": "...", "created_at": "UTC ISO8601",
  "course_version": "1.0",
  "files": [{"id":"...","filename":"report.md","size":120,"sha256":"...","extracted_chars":100,"truncated":false,"extraction_note":"...","download_url":"/api/files/..."}],
  "static_checks": [{"name":"...","status":"passed|warning|failed","message":"..."}],
  "latest_review": null
}
```

每次最多 5 文件，每文件 2 MiB，总附件 8 MiB，总请求体 9 MiB。允许：`.txt .md .py .php .js .ts .tsx .jsx .vue .json .csv .yaml .yml .sql .sh .html .css .log .pdf .docx`。文本必须 UTF-8；不接受 ZIP、二进制可执行文件。存储名称随机，原文件名只作展示。所有提交保留历史版本。

每附件最多提取 30000 字符；模型总证据最多 90000 字符，截断会明确记录。PDF 只读取前 30 页可复制文本，不做 OCR，解析在 CPU/内存受限的独立进程中进行；DOCX 只提取正文文本并限制解压总大小。JSON 和 Python 做解析级语法检查；没有执行任何上传代码、命令或测试，也不会访问作业里的 URL。

## 第三方 AI

- `GET /api/settings/ai`：`{provider_label,base_url,model,api_key_set,max_tokens,timeout_seconds,temperature}`，从不返回明文/加密密钥。
- `PUT /api/settings/ai`：上述配置字段，额外可给 `api_key`、`clear_api_key`。空/缺省 key 保留原值；clear=true 删除设置中的 key。返回公开配置。max_tokens 256–8192，timeout_seconds 10–180，temperature 0–1。
- `POST /api/settings/ai/test`：对已保存配置发一个最多 32 output token 的测试请求。成功 `{ok:true,message,model,latency_ms,usage}`。这会产生少量服务方费用。

Base URL 可写 `https://provider.example/v1` 或完整 `.../chat/completions`。发送非流式 OpenAI-compatible Chat Completions，使用 `max_tokens`/`temperature`；不同服务支持参数不同，需要连接测试确认。无需 OpenAI SDK，不支持 Responses API 专用端点。

默认公网 HTTPS；拒绝 URL 凭据、query/fragment、私网/回环/保留 IP，调用前重新检查 DNS，将 TCP 连接固定到已验证 IP，TLS 验证原域名，不跟随 redirect、不读取环境代理，响应最多 1 MiB，调用有总期限。私网模型须由服务器操作者通过环境变量显式允许 exact hostname；该例外不能通过网页设置开启。

API Key 用 Fernet 加密存储；队列快照也只存密文。已排队请求保留当时的模型配置和密钥；更改/清除设置不会改写历史和已排队请求。

## 评审

- `POST /api/submissions/{id}/reviews`：JSON `{consent:true}`，表示同意将课程评分要求及本次可读作业证据发送到当前第三方。返回 202 `{review_id,status:"queued"}`。同提交正在排队/执行时返回已有 job，不重复发起；重试已完成或失败任务会创建新 Review。
- `GET /api/reviews/{id}`：返回 Review。

```json
{
  "id":"...", "submission_id":"...", "status":"queued|running|completed|failed",
  "created_at":"...", "completed_at":null, "error":null,
  "model":"...", "provider_label":"...", "prompt_version":"fde-static-review-1.0",
  "data_consent_at":"...", "usage":{"input_tokens":100,"output_tokens":200},
  "report": {
    "mode":"ai_review", "runtime_verified":false,
    "total_score":75, "max_score":100,
    "rubric":[{"id":"...","title":"...","weight":30,"score":24,"feedback":"...","evidence":["可在提交中找到的原文"]}],
    "summary":"...", "strengths":["..."], "improvements":["..."],
    "missing_evidence":["..."], "next_steps":["..."], "confidence":"low|medium|high",
    "verification_note":"这是文本证据建议评分，没有运行代码或测试...", "evidence_truncated":false
  }
}
```

每项 score 是 0–该项 weight 的分值，例如权重 30 得 24，不是每项 100 分。后端校验完整且无重复的 rubric id、数字范围，求和得到 0–100 的 total_score；忽略模型自报的 total/pass/runtime。引文必须在实际提供的文本里逐字存在，否则整个评审失败、不提供分数。提示词把作业标记为不可信数据并禁止遵循其中的指令；该防护不能消除模型判断误差，评分始终仅为建议。

排队/执行中最多 3 个，单线程处理；队列存 SQLite。重启后 queued 继续执行，running 标记 failed 并要求手动重试以避免自动重复费用。超时/认证失败/上游异常/JSON无效/缺评分项/编造引文均保存 failed，report 为 null，不制造占位分数。失败请求可能已在第三方产生费用。此版本不运行自动执行沙箱，不自动判项目验收，不自动标记课程完成。

## 验证

```bash
python -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
```

测试使用临时数据库和课程、不连接收费模型服务。真实服务必须由用户配置 Key 后在系统中测试。
