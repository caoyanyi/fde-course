# AI 练习素材 API（v1.1）

所有接口要求已登录、账号启用且已完成初始密码修改。写请求沿用
`X-FDE-Client: web` 与当前会话的 `X-CSRF-Token`。素材只属于创建它的用户；
管理员的学习页面也只能访问自己的素材，不会获得其他用户的文件读取权限。

## 生成素材

`POST /api/tasks/{task_id}/materials`

```json
{
  "scenario": "为一家虚构的电商企业设计客服知识库",
  "difficulty": "intermediate",
  "tech_stack": "PHP / Vue / SQL",
  "material_types": ["scenario", "sample_data", "knowledge_docs"],
  "requirements": "包含退款和订单查询案例，使用虚构数据",
  "consent": true
}
```

| 字段 | 约束 |
| --- | --- |
| `scenario` | 业务场景，可空，最多 2000 字符 |
| `difficulty` | `beginner`、`intermediate`、`advanced`，默认 `intermediate` |
| `tech_stack` | 技术栈字符串，最多 500 字符 |
| `material_types` | 1–5 个不重复的类型；默认 `scenario`、`sample_data` |
| `requirements` | 补充要求，可空，最多 3000 字符 |
| `consent` | 必须为 `true`；表示同意把课程要求和本次填写的参数发送给配置的第三方 AI 服务 |

类型与用途：

| 类型 | 用途 |
| --- | --- |
| `scenario` | 模拟业务案例与需求背景 |
| `sample_data` | JSON、CSV、SQL 或文本样例数据 |
| `knowledge_docs` | 练习知识文档，内容需使用者核对 |
| `test_cases` | 待执行的测试输入和预期结果 |
| `starter_template` | 保留 TODO 的起步模板，不是完整作业答案 |

返回 `202`：`{"material_id":"…","status":"queued"}`。前端轮询详情直到
`completed` 或 `failed`。同用户、同任务、同参数的重复待处理请求返回原任务；
同任务仍在生成时改变参数返回 `409`。生成完成后再次请求会创建新版本，不覆盖旧文件。

服务使用管理员保存的模型配置快照，API Key 保持加密。`material_max_tokens` 默认
6000，允许 256–8192，独立于作业评审的 `max_tokens`。模型输出被截断或结构不合格时，
整个素材包标记失败，不提供部分文件；请缩小素材类型或数据规模后手动生成。

## 查询、预览和下载

- `GET /api/materials?task_id=w01-t01&limit=100&offset=0`：按任务筛选；可省略任务。
  返回 `{items,total,limit,offset}`，`limit` 为 1–200，`offset >= 0`。
- `GET /api/materials/{material_id}`：详情，包含文件正文。
- `GET /api/materials/{material_id}/download`：ZIP 下载，包含 `manifest.json` 和全部素材。
- `GET /api/materials/{material_id}/files/{file_id}`：单个 UTF-8 文件，强制附件下载。

素材包公共字段：

```text
id, task_id, version, status,
title, summary, how_to_use: string[], params: object,
created_at, started_at, completed_at, error,
model, provider_label, usage, course_version, prompt_version, data_consent_at,
synthetic: true, runtime_verified: false, verification_note,
files: [{id,filename,kind,description,size,sha256,chars,download_url}],
download_url
```

详情的 `files[]` 额外包含 `content`。列表不返回文件正文。
`download_url` 在生成未完成时为 `null`。公共响应不包含 API Key、模型地址、加密密钥、
内部模型配置快照或其他用户的信息。无法访问的 ID 统一返回 `404`；自身未完成的包下载返回 `409`。

## 作业关联与评分边界

作业提交的 multipart 表单可增加 `material_pack_id`。
它必须属于当前用户、当前课程任务且已经完成，否则返回 `404` 或 `422`。
提交保留这一版本的 ID，后续生成新素材不改变旧作业的背景。

AI 评审接收素材作为单独的“模拟练习输入背景”，文件正文最多截取 20000 字符。
素材不拼入学习者证据文本，不能单凭它引用出一个作业分数。评审引用仍必须能在学员提交的
正文、证据说明或已提取附件中逐字找到。若学员把模拟素材复制到正文，系统无法自动判断
真实性，仍需人工检查真正的工作成果和运行记录。

## 格式检查与队列

- 每包 1–8 个文件，每文件最多 10000 字符，总正文最多 40000 字符。
- 仅支持 `md/txt/json/csv/yaml/yml/sql`。文件名必须为最多四层的安全相对路径。
  拒绝绝对路径、`..`、隐藏路径、控制字符、Windows 特殊字符/设备名、大小写重复及文件与目录冲突。
- JSON 拒绝无效语法、重复键、NaN 和 Infinity；CSV 检查表头、列数及潜在公式。
  YAML 和 SQL 仅作为文本保存，不进行语义验证和执行。
- 单用户最多 3 个待处理请求，全站最多 20 个；队列状态持久化到 SQLite。
- 全站 `MAX_MATERIALS_PER_DAY` 默认 100；新账号 `material_daily_limit` 默认 100，管理员可调整。
  两层额度同时生效，按 UTC 日期统计，中国时间每天 08:00 进入下一统计日。
  入队请求即占额度，失败和因账号变更取消的请求也占额度。
  已有明确额度不会因更新源码或重启而自动覆盖；部署者可以使用 `scripts/set_daily_limits.py` 显式调整，详见主 README。
- 服务重启时，`running` 请求标记失败；未开始的 `queued` 请求继续处理。
  没有自动重试，避免在无法确认上游是否计费时重复调用。
- 执行前再次检查账号状态。停用或等待修改密码的账号不再开始 AI 请求；若调用期间发生
  状态变更，返回结果不保存为可用素材，但此前发出的请求仍可能产生费用。

系统固定标记 `synthetic=true`、`runtime_verified=false`。第三方模型即便返回相反字段，
也不会改变这两个标记。系统不会抓取素材中的 URL，不运行任何上传/生成代码，不把生成的
测试用例视为执行通过。素材文件、ZIP 清单和预览均提示这一边界。

## 运行要求

使用一个应用进程（Uvicorn `--workers 1`），由独立的素材工作线程消费 SQLite 队列。
队列领取和额度/version 分配均使用 SQLite 写事务。若改为多应用实例部署，需要先改造
任务租约、共享队列和迁移协调；当前源码面向个人和小团队的单实例部署。
