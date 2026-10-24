# Docker Compose 部署

## 部署结构

- `backend`：Python 3.12 + uv 构建的 FastAPI 服务，容器内端口 8000，以非 root 用户运行。
- `frontend`：Node.js 24 + pnpm 构建 Vue 静态资源，由 Nginx 提供页面并代理 `/api/`；代理保留 WebSocket 升级能力。
- 后端仅在 Compose 网络内可访问；宿主机默认仅发布 `127.0.0.1:8080`。
- 本地 `data/` 挂载到 `/app/data`，保存分钟上下文、成交样本、回测报告及 SQLite 预测日志；不需要额外数据库服务。
- 后端默认以 UID/GID 1000 运行，可按宿主机目录所有者调整，不以 root 写入研究数据。

镜像中 Python 使用 `uv sync --locked --no-dev --no-editable --reinstall-package pripre`，前端使用 `pnpm install --frozen-lockfile`。部署构建与开发环境共用锁文件。镜像基础版本在 Dockerfile 中指定，发布前应重新构建并验证。

## 启动

需要可访问的 Docker daemon、Docker Compose 插件，以及拉取镜像和下载依赖的网络。以下命令在包含 `compose.yaml` 的已验收 checkout 中执行，例如 `/tmp/pripre-agent-worktree` 的 `idle` 分支。

```bash
mkdir -p data
cp .env.example .env
# 用 id -u、id -g 检查当前用户，将 .env 的 UID/GID 改为相同值
# 按需编辑 .env 中的绑定地址与端口
# .env 包含部署参数，不提交 Git
docker compose config --quiet
docker compose up -d --build --wait
```

访问 `http://127.0.0.1:8080`。前端等待后端健康后启动；前端容器的健康检查经 Nginx 访问后端，验证 API 代理链路。

| 参数                  | 默认值      | 含义                |
| --------------------- | ----------- | ------------------- |
| `PRIPRE_BIND_ADDRESS` | `127.0.0.1` | 宿主机监听地址      |
| `PRIPRE_PORT`         | `8080`      | 页面及 API 入口端口 |

需要外部访问时显式调整绑定地址；当前框架不含认证和 TLS，公网部署前需补充访问控制及 HTTPS。

## 验证与运维

```bash
docker compose ps
curl --fail http://127.0.0.1:8080/api/health
curl --fail http://127.0.0.1:8080/
docker compose logs --tail=100 backend frontend
```

健康接口应返回 `status: ok`、`service: pripre-api`、`stage: research`；首页显示实时状态和研究入口。健康检查不代表行情新鲜度或模型可用性。`docker compose config` 通过仅代表配置有效，不能代替镜像构建和运行验证。

更新代码后重建：

```bash
docker compose up -d --build --wait
```

停止并移除本项目容器与网络：

```bash
docker compose down
```

不使用 `down -v` 作为日常停止命令。后续引入持久化数据时，应补充卷、备份与恢复说明。

## PostgreSQL 与其他中间件

本机已有 PostgreSQL，当前版本不连接它，也不修改其配置或数据。后续确需关系数据库时，优先复用本机实例，并使用独立应用数据库及最小权限账户。

Linux 容器访问宿主机 PostgreSQL 时，可在实际需要的服务中配置 `host.docker.internal:host-gateway` 映射，再通过环境变量提供连接信息。宿主机 PostgreSQL 的监听地址、`pg_hba.conf` 和网络访问规则需结合实际部署单独配置；容器中的 `localhost` 指向容器自身，不能用于访问宿主机数据库。当前代码尚未实现数据库连接，不能仅通过添加连接变量启用。

如后续需要 Redis、消息队列等其他中间件，必须添加为 Compose 服务，配置健康检查、持久化及必要的备份策略，不要求宿主机手动安装。

## 研究数据与实时开关

`.env` 的额外参数：`PRIPRE_DATA_DIR`（默认 `./data`，必须已存在）、`PRIPRE_UID`/`PRIPRE_GID`（默认 1000）、`PRIPRE_LIVE_ENABLED`（默认 false）。实时开关显式为 true 才会连接 Binance；数据目录须对后端运行用户可读写。

可在宿主机按 README 采集，也可使用构建后的镜像：

```bash
docker compose run --rm backend /app/.venv/bin/python -m pripre.cli collect --config config/default.toml
docker compose run --rm backend /app/.venv/bin/python -m pripre.cli backtest --config config/default.toml
```

完成本地数据准备后，将 `.env` 中 `PRIPRE_LIVE_ENABLED` 改为 `true`，执行 `docker compose up -d --wait`。模型从当前本地样本训练；新增样本后重启后端以重建模型。WebSocket 使用同一入口 `/api/stream`，无需另开端口。

备份时保存整个宿主机数据目录。复制 SQLite 日志前先停止后端，避免复制正在写入的文件；原始成交样本和分钟分区通过临时文件原子替换写入。恢复时将备份放回数据目录并确认 UID/GID 权限，再启动服务。`docker compose down` 不删除宿主机数据，不手工清理研究目录作为部署步骤。

镜像构建缓存只用于加速依赖下载，应用本身每次强制重新安装。构建中运行 `scripts/verify_installed.py`，逐文件核对实际安装的应用包与复制到镜像的源码，防止修改源码后错误复用旧 wheel。该检查要求非 editable 安装，属于镜像构建门禁。

## 本次本地运行实例

2026-10-24 首次验收实例地址为 `http://127.0.0.1:8080`，Compose 项目名为 `pripre`，曾显式启用真实行情，随后已按用户要求停止前后端容器。数据来自隔离 worktree 的 `data/`；本机 PostgreSQL 未被使用或修改。

在隔离 worktree 根目录管理该实例：

```bash
docker compose -p pripre ps
PRIPRE_LIVE_ENABLED=true docker compose -p pripre up -d --build --wait
docker compose -p pripre logs --tail=100 backend frontend
# 需要停止时执行；保留宿主机研究数据
docker compose -p pripre down
```

## 冻结回测和开发实验数据

新版 backtest 同时生成 `research/report.json` 及 `research/runs/<run_id>/replay.npz`，experiments 生成 `research/experiments.json`。部署使用原有数据目录挂载，无须新增中间件。更新镜像后显式执行 backtest 才能使用历史复盘；仅重启后端不会自动生成或覆盖离线报告。

备份和恢复必须包含完整的 `research/` 子目录，保持报告与其运行 ID 对应的冻结证据一致；仅恢复 report.json 会导致日期指标和复盘接口不可用。旧运行不会自动删除。日常暂停可使用 `docker compose -p pripre stop`，保留容器与全部宿主机数据。
