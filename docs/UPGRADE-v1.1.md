# 从 v1.0 升级到 v1.1

本说明用于已经运行的 Vue + FastAPI + SQLite + Docker Compose 部署。v1.1 增加管理员创建账号、按用户隔离学习数据、按任务生成 AI 素材和素材版本管理。首次启动会自动迁移 v1.0 数据库。

## 升级前需要保留的内容

- 原始 `.env`，特别是 `APP_MASTER_KEY`。修改这个密钥会导致已有 AI Key 无法解密。
- 原 Docker Compose 项目名及其数据卷。默认项目名为 `fde-learning`，默认卷为 `fde-learning_fde_data`。
- 原 v1.0 源码及完整升级前备份，供需要时回退。
- 你自行修改的 `course/curriculum.json`。把修改合并到新版课程文件中，并保留已有任务 ID。

不要执行 `docker compose down -v`，不要删除数据卷，也不要用 `.env.example` 覆盖已有 `.env`。本次升级无需再次执行账号初始化。

## 推荐流程：新目录构建，继续使用原数据卷

以下示例假设原部署目录是 `/opt/fde-learning-system`，新版源码 ZIP 已上传到 `/tmp/fde-learning-system-v1.1.0.zip`。请按实际情况替换路径。

### 1. 核对原部署

在原代码目录运行：

```bash
cd /opt/fde-learning-system
docker compose ps
docker compose ls --all
```

确认原 `app` 和 `web` 容器所属项目名。若以前一直用 `docker compose -p 自定义项目名`，新版目录也必须使用那个名字。只有目录名变化并不意味着需要新的数据卷。

### 2. 解压并复制原配置

```bash
mkdir -p /opt/fde-releases/v1.1.0
unzip /tmp/fde-learning-system-v1.1.0.zip -d /opt/fde-releases/v1.1.0
cd /opt/fde-releases/v1.1.0/fde-learning-system
cp /opt/fde-learning-system/.env .env
chmod 600 .env
```

如果使用 GitHub 自动生成的源码 ZIP，顶层目录名称可能不同；进入包含 `compose.yaml` 的目录即可。

也可以从仓库主干取得新版源码，替代上面的解压步骤：

```bash
git clone --branch master --single-branch https://github.com/caoyanyi/fde-course.git /opt/fde-releases/v1.1.0/fde-learning-system
cd /opt/fde-releases/v1.1.0/fde-learning-system
cp /opt/fde-learning-system/.env .env
chmod 600 .env
```

解压与克隆选择一种即可。目标目录应是新的目录，仓库 `1.0` 标签保留 v1.0 基线，`master` 分支已包含 v1.1；`upgrade/v1.1.0` 分支继续保留。

若原项目名不是 `fde-learning`，在新版 `.env` 中设置 `COMPOSE_PROJECT_NAME=原项目名`。不要修改原密钥、域名或端口。若修改过课程，在此时合并课程内容。

全站每日评审 `MAX_REVIEWS_PER_DAY` 和素材生成 `MAX_MATERIALS_PER_DAY` 的新默认值均为 100。已有 `.env` 中显式设置的值会继续保留；例如原来写了 30，仅更新源码不会把它改成 100。两者都按 UTC 日统计，在北京时间每天 08:00 重置。完成下面的新版启动与数据库迁移后，可以按“多用户与额度”一节的命令同时调整全站和原管理员额度。

### 3. 先构建镜像，再停止和备份

以下命令都在新版代码目录执行：

```bash
docker compose build
python3 scripts/backup.py --keep-stopped
```

构建镜像不会替换正在运行的旧容器。新版备份脚本会确认当前项目已有 `app` 容器，短暂停止后端，并用 Python 归档整个数据卷。归档过程不运行应用启动逻辑，因此不会提前迁移数据库。

**只有两条命令都成功，才继续下一步。** 记录脚本打印的备份目录，它应包含 `data.tar.gz` 和 `.env`。将整个目录复制到服务器之外保管。成功后后端保持停止，以确保升级前备份之后没有新的写入。

普通备份不加 `--keep-stopped`，会恢复原有运行状态。备份失败时也会尝试重新启动原有容器，且不会通过 `up` 意外切换到刚构建的镜像。

### 4. 启动新版

```bash
docker compose up -d
docker compose ps
docker compose logs --tail=100 app web
curl -fsS http://127.0.0.1:18080/api/health
```

如果原 `WEB_PORT` 不是 18080，请把健康检查端口替换为原端口。首次启动会把旧账号变为管理员，并给已有进度和提交补上所属用户；附件、评审、密码哈希、AI Key 和课程快照继续保留。旧会话失效，请使用原账号密码重新登录。

迁移前，应用还会在数据卷的 `migration-backups/` 中建立数据库备份；这份备份不含 `.env` 和完整附件，不能替代第 3 步的完整备份。迁移失败会回滚数据库事务，不会故意重置或清空学习数据。

### 5. 升级后验收

1. 原账号登录，确认已有课程进度、学习时间、作业、附件和历史评分仍然可读。
2. 打开“用户管理”，创建学习者。新账号首次登录必须修改初始密码。
3. 两个账号分别提交一个测试作业，确认彼此看不到对方的提交、文件、素材和进度。
4. 管理员在 AI 设置确认原服务正常，调整“素材输出上限”；默认 6000 tokens。测试连接会产生一次小额服务商请求。
5. 进入某个任务的素材区域，选择业务场景、技术栈及素材种类，确认发送范围后生成。
6. 等待生成完成，预览文件并下载 ZIP。生成失败时应看到原因，不出现伪造的成功素材。
7. 提交作业时关联这个任务的素材版本，再发起评审，确认材料作为背景而非已完成的作业证据。
8. 重启应用，重新登录确认用户、作业和素材仍在。

## 多用户与额度

系统不开放公众自行注册。管理员创建管理员或学习者，设置显示名、状态、每日评审和素材额度，并可以重置密码。停用和重置密码会撤销用户的旧会话。管理员自己的学习页面也只显示自己的学习记录。

新账号和首次从 v1.0 迁移的原管理员，默认每天可评审 100 次、生成素材 100 次。两个额度分别计算。已有 v1.1 账号保留其现有额度，不会在重启时覆盖你设置的自定义值。实际可调用次数同时受全站剩余额度约束；全站默认的 100 次由所有账号共享。失败任务也计入当日调用额度，因为外部服务可能已经计费。正在运行的外部请求不能保证因账号停用而撤销，尚未开始的任务会在调用前检查账号状态。

### 将已有部署调整为每天 100 次

先完成新版启动及数据库迁移，再在包含 `compose.yaml` 和原 `.env` 的新版代码目录执行：

```bash
python3 scripts/set_daily_limits.py --limit 100
docker compose up -d
```

第一条命令同时将 `.env` 中的两类全站额度和原管理员（`id=1`，仍须为管理员）的两类用户额度设为 100。脚本保留其他账号的额度、原密钥及其他配置，不清空当天已用次数；第二条命令使新的全站环境配置生效。刷新页面后，未使用时会显示 `0 / 100 次`、`全站剩余 100 次`，已经使用的次数继续扣除。

若要选择另一个账号，使用 `python3 scripts/set_daily_limits.py --limit 100 --username 实际用户名`；若确定要统一调整所有已有账号，使用 `python3 scripts/set_daily_limits.py --limit 100 --all-users`。两个选项不能同时使用；无论选择哪个账号，脚本都会更新两类全站额度。

脚本要求当前 Compose 项目已有 `app` 容器，且数据卷内已有迁移完成的 v1.1 数据库。找不到原项目、数据库版本不匹配或目标账号不存在时会停止，不创建数据库、不运行迁移。若原来使用自定义项目名，先确认 `.env` 的 `COMPOSE_PROJECT_NAME` 与原项目一致。每次执行后都需要运行 `docker compose up -d`；已有用量按原来的 UTC 日界限恢复，无需等待次日才能使用新增额度。

AI 设置由管理员管理，学习者共享模型服务，但不会获取 Base URL 或密钥。本版面向你管理的个人及小团队学习使用，没有负载容量验证。

## 素材与课程数据的关系

素材是练习输入，不是标准答案。每次生成都保存不可变版本、参数、模型名、课程版本、文件哈希和合成来源标记。可以生成场景说明、样例数据、知识文档、测试用例和起步模板。

系统检查生成结果的结构、文件名、JSON/CSV 等基础格式，不执行其中的 SQL、代码或测试，不自动访问模型提供的链接。业务事实、测试正确性和运行结果仍需在练习项目中验证。将素材关联到作业后，评审可以理解输入背景，但素材本身不能代替你的实现、测试日志或分析结论。

## 回滚

**不要直接把 v1.0 代码连接到已经迁移的 v1.1 数据库。** v1.0 不理解多用户所有权，不能用它处理新版库。

回滚必须使用：原 v1.0 源码 + 第 3 步生成的升级前完整备份 + 备份里的原 `.env`。推荐恢复到新项目及空卷，验证后再切换反向代理：

```bash
cd /opt/fde-rollback/fde-learning-system
python3 scripts/restore_empty_volume.py /绝对路径/升级前备份目录 --project-name fde-learning-rollback
python3 scripts/configure.py --domain learn.example.com --port 18081
docker compose up -d
```

这里必须使用新解压的 **v1.0 目录**，且目录中尚无 `.env`。替换实际域名，确认 18081 未占用。验证登录、原有作业和模型配置后，再将反向代理切换到回滚服务。

升级后新增的用户、作业和素材不在升级前备份中。需要保留这些内容时，应先停止写入并另做新版完整备份，再决定是否回滚。

## 部署范围

保持一个应用实例、一个 Uvicorn 进程（Dockerfile 已如此配置）。应用内有独立的评审与素材后台线程，它们依次处理各自队列。不要直接把 `--workers` 调大或让多个应用实例共享此 SQLite 卷。扩展到多实例应另行改造任务领取和运行状态恢复机制。

实际已执行与未执行的检查见 [VERIFICATION.md](VERIFICATION.md)。真实 Docker 启动、域名代理和你所选第三方模型需要在目标服务器完成验收。
