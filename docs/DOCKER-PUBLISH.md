# 创建 Git tag 后自动发布 Docker Hub 镜像

工作流文件：`.github/workflows/docker-publish.yml`。GitHub Actions 中显示为 **Publish Docker images**。

| 服务 | Dockerfile | Docker Hub 镜像 |
| --- | --- | --- |
| 后端 `app` | `deploy/backend.Dockerfile` | `caoethan/fde-learning-app` |
| 前端 `web` | `deploy/web.Dockerfile` | `caoethan/fde-learning-web` |

两个镜像均从仓库根目录构建，目标平台为 `linux/amd64` 和 `linux/arm64`。服务器拉取同一个镜像标签时，Docker 会选择与本机架构匹配的版本。工作流使用 QEMU 和 Buildx；首次双架构构建可能比后续构建耗时更长，实际构建和推送结果以 GitHub Actions 为准。

## 1. 配置 Docker Hub 凭据

在 Docker 账号 `caoethan` 下创建用于本仓库发布的 Personal Access Token，仓库权限选择 **Repo Read & Write**。

打开仓库的 [Actions secrets 设置](https://github.com/caoyanyi/fde-course/settings/secrets/actions)，点击 **New repository secret**，填写：

| Name | Secret |
| --- | --- |
| `DOCKERHUB_TOKEN` | 上一步生成的 Docker Hub Personal Access Token |

工作流的登录用户名已固定为 `caoethan`，不需要再创建用户名 secret。Token 填入 GitHub 的 Secret 输入框，不要写入工作流、源码、`.env.example` 或提交记录。服务器的 AI Key、`APP_MASTER_KEY` 等运行配置不参与镜像构建。

若 Actions 提示缺少 `DOCKERHUB_TOKEN` 或 Docker Hub 认证失败，先核对 secret 名称、Token 是否过期，以及是否具有这两个仓库的推送权限，再重新运行失败任务。

## 2. 创建版本 tag 触发发布

先更新本地 `master`，确保新 tag 指向的提交已经包含工作流，然后创建并推送一个尚未使用的版本号。例如：

```bash
git switch master
git pull --ff-only origin master
git tag -a v1.1.1 -m "Release v1.1.1"
git push origin v1.1.1
```

`v1.1.1` 是示例；发布时换成实际版本号。也可以在 GitHub 创建 Release 时新建指向最新 `master` 的 tag。每次推送一个 tag，等待该轮发布完成后再发布下一个版本。

### 镜像标签规则

**Git tag 原样作为 Docker 镜像标签，不去掉 `v` 前缀。** 自动触发时，正式版本同时更新 `latest`；其他合法的 Docker 标签只发布对应版本。

| Git tag 示例 | 两个仓库中生成的镜像标签 | 自动更新 `latest` |
| --- | --- | --- |
| `v1.1.1` | `v1.1.1`、`latest` | 是 |
| `1.1.1` | `1.1.1`、`latest` | 是 |
| `1.1` | `1.1`、`latest` | 是 |
| `v1.2.0-rc.1` | `v1.2.0-rc.1` | 否 |
| `test-20261030` | `test-20261030` | 否 |

这里的正式版本指可选 `v` 前缀，加上纯数字的 `主版本.次版本` 或 `主版本.次版本.修订号`。Docker 标签最长 128 个字符，只能包含英文字母、数字、下划线、点和短横线，且首字符不能是点或短横线。含 `/`、`+` 等不合法字符的 Git tag 会在发布检查阶段被拒绝。`latest` 是工作流保留的镜像标签，不能用作发布输入的 Git tag 名。

例如推送 `v1.1.1` 后，成功结果包括：

```text
caoethan/fde-learning-app:v1.1.1
caoethan/fde-learning-web:v1.1.1
caoethan/fde-learning-app:latest
caoethan/fde-learning-web:latest
```

工作流先完成两个版本镜像的构建和推送，成功后再按镜像 digest 更新两个 `latest`。Docker Hub 的两次标签更新不是原子事务；若更新 `latest` 的阶段失败，可能只有其中一个仓库已更新。此时在 Actions 重新运行失败任务，直到整轮发布成功，再在服务器更新镜像。需要固定版本时，两个服务使用相同的版本标签。

### 手动补发已有 tag

历史 `1.0` 等已存在的 tag 不会因为新增工作流而自动补推。需要补发时：

1. 打开 [GitHub Actions](https://github.com/caoyanyi/fde-course/actions)，选择 **Publish Docker images**。
2. 点击 **Run workflow**，工作流分支选择 `master`。
3. `tag` 填写仓库中已经存在的 tag 名，例如 `1.0`。
4. `update_latest` 默认关闭。补发历史版本时保持关闭；只有明确要将该版本作为 `latest` 时才打开。此开关只对上述正式数字版本生效，预发布版本即使打开也不会更新 `latest`。
5. 执行后查看两个镜像的构建推送步骤及最终状态。

手动执行会按输入的已有 tag 取得源码，不会创建或移动 Git tag。`latest` 表示最近被提升的发布结果，不会自动比较哪个版本号最大；补发旧版本应使用上述手动方式并保持 `update_latest` 关闭。

工作流通过全局 concurrency 避免两轮同时修改发布标签，并且不会主动取消正在执行的一轮。仍应逐个发布并等待结束，避免连续提交多个待发布 tag。

## 3. 服务器改用 Docker Hub 镜像

仓库的 `compose.yaml` 保持原有源码构建方式。若服务器希望直接拉取发布好的镜像，编辑服务器上的现有文件：删除 `app`、`web` 各自的 `build` 配置块，增加对应的 `image` 行。

下面仅展示两处需要修改的字段，**不是完整 Compose 文件**。保留现有项目名、环境变量、端口、健康检查、服务依赖，以及 `fde_data` 数据卷配置。

```yaml
services:
  app:
    image: caoethan/fde-learning-app:${FDE_IMAGE_TAG:-latest}
    # 其余现有 app 配置继续保留
  web:
    image: caoethan/fde-learning-web:${FDE_IMAGE_TAG:-latest}
    # 其余现有 web 配置继续保留
```

在原 `.env` 中新增或更新这一项，可以让两个服务固定到同一已发布版本：

```dotenv
FDE_IMAGE_TAG=v1.1.1
```

在原部署目录执行，镜像拉取成功后再启动：

```bash
docker compose pull app web
docker compose up -d --no-build
docker compose ps
```

希望跟随最近发布的正式版本时，将 `FDE_IMAGE_TAG` 设为 `latest`，再运行相同命令。若 Docker Hub 仓库为私有，服务器还需要先使用具有拉取权限的凭据执行 `docker login`。

沿用原 `.env` 和原 Compose 项目名后，已有账号、课程进度、作业和 AI 配置继续使用原数据卷。从 v1.0 首次升级仍应先按 [v1.1 升级指南](UPGRADE-v1.1.md) 备份并完成数据库迁移，拉取镜像不替代这一步。

## 4. 首次发布验收

本次配置已通过 actionlint v1.7.12 语法检查，并直接运行了工作流中的 shell 校验步骤：18 个 tag / 正式版本 / 手动发布边界用例和 2 个凭据检查用例通过；同时检查了两个 Dockerfile 的构建路径、固定 Action SHA、平台与 `latest` 提升顺序。本地环境没有 Docker 引擎，尚未执行真实镜像构建或 Docker Hub 推送。

配置 secret 后创建新 tag，在 Actions 确认整个 **Publish Docker images** 任务成功，再检查两个 Docker Hub 仓库中的同名版本标签：

- [caoethan/fde-learning-app](https://hub.docker.com/r/caoethan/fde-learning-app/tags)
- [caoethan/fde-learning-web](https://hub.docker.com/r/caoethan/fde-learning-web/tags)

确认该版本包含 `linux/amd64` 和 `linux/arm64`，并按标签规则检查 `latest` 是否更新。首次真实的双架构构建和 Docker Hub 推送需要通过这轮 Actions 验证；本说明不表示已在用户服务器完成更新。

## 官方参考

- [GitHub Actions 触发条件与 tag 过滤](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax)
- [GitHub Actions 工作流触发说明](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow)
- [Docker GitHub Actions](https://docs.docker.com/build/ci/github-actions/)
- [Docker GitHub Actions 多架构构建](https://docs.docker.com/build/ci/github-actions/multi-platform/)
- [Docker Access Token 权限](https://docs.docker.com/security/access-tokens/reference/)
