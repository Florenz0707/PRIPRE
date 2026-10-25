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

不使用 `down -v` 作为日常停止命令。宿主机 `data/` 已持久化，备份与恢复方式见后文。

## PostgreSQL 与其他中间件

本机已有 PostgreSQL，当前版本不连接它，也不修改其配置或数据。后续确需关系数据库时，优先复用本机实例，并使用独立应用数据库及最小权限账户。

Linux 容器访问宿主机 PostgreSQL 时，可在实际需要的服务中配置 `host.docker.internal:host-gateway` 映射，再通过环境变量提供连接信息。宿主机 PostgreSQL 的监听地址、`pg_hba.conf` 和网络访问规则需结合实际部署单独配置；容器中的 `localhost` 指向容器自身，不能用于访问宿主机数据库。当前代码尚未实现数据库连接，不能仅通过添加连接变量启用。

如后续需要 Redis、消息队列等其他中间件，必须添加为 Compose 服务，配置健康检查、持久化及必要的备份策略，不要求宿主机手动安装。

## 研究数据与实时开关

`.env` 的额外参数：`PRIPRE_DATA_DIR`（默认 `./data`，必须已存在）、`PRIPRE_UID`/`PRIPRE_GID`（默认 1000）、`PRIPRE_LIVE_ENABLED`（默认 false）。实时开关显式为 true 才会连接 Binance；数据目录须对后端运行用户可读写。

可在宿主机按 README 采集，也可使用构建后的镜像：

```bash
docker compose run --rm backend /app/.venv/bin/python -m pripre.cli collect --config config/config.toml
docker compose run --rm backend /app/.venv/bin/python -m pripre.cli backtest --config config/config.toml
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

## 时钟漂移修复的部署检查

前后端应一起更新镜像，让前端使用新增的帧进度字段。宿主机时钟和 NTP 配置不需要由本项目修改。升级后检查 `/api/matrix` 中 `elapsed_clock` 为 `monotonic_raw`、`clock_syncs` 持续增加、`clock_sync_age_ms` 周期回落；超过校准有效期时应显示校时失效而不是有效概率。

本次修复在隔离 worktree 的 `idle` 集成，主目录 `dev` 按协作约束不自动合并。运行实例若由该 worktree 的验证镜像更新，之后从 `dev` 执行 `--build` 前，应先按分支流程合入修复，防止重新构建旧代码。保留当前本地配置、数据目录及 `.env`；新增校时参数可省略以采用默认值。

2026-10-25 的时钟修复已更新至当前 `pripre-dev` 实例（`127.0.0.1:8020`），沿用 `/home/florenz/PRIPRE/data`。运行配置从原容器保留，新增参数使用后端默认值；主目录 `dev` 未自动合并。旧镜像保留为 `pripre-clockfix-backend:before-20261025` 和 `pripre-clockfix-frontend:before-20261025`。已打开的页面须刷新以加载新前端；仅后端更新不足以修复旧页面中的固定 UTC 锚点逻辑。

## 数据源代理与 Docker 网络

代理只注入 `backend` 的 `PRIPRE_SOURCE_PROXY`，不为前端、健康检查或本地 API 设置全局 HTTP 代理。保留默认 bridge 网络及 `backend` 服务名解析，不切换到 host 网络。该设置是运行期数据源代理，与 Docker daemon 拉镜像、BuildKit 下载依赖的代理配置分开。

在本地、未提交的 `.env` 中配置，然后重新创建后端（单纯 restart 不会加载新环境变量）：

```dotenv
PRIPRE_SOURCE_PROXY=http://host.docker.internal:7077
```

### Docker Desktop（包括当前实例）

Docker Desktop 自带 `host.docker.internal`，当前环境已经验证容器能够连接其 7077 端口。直接使用上述地址，**不要叠加**原生 Linux 的 `host-gateway` 覆盖文件，避免覆盖 Docker Desktop 的宿主机 DNS 路由。

```bash
docker compose up -d --build --wait
docker compose exec backend /app/.venv/bin/python -m pripre.cli source-check --config config/config.toml
```

若代理运行在 Windows，而项目运行在 WSL，不能仅把 WSL 终端的 `127.0.0.1` 原样写入容器；应从容器验证 Docker Desktop 宿主机地址对应的端口。代理自身的分流规则决定最终出口，本项目不修改它的规则。

### 原生 Linux Docker Engine

原生 Linux 可叠加已提供的映射文件：

```bash
docker compose -f compose.yaml -f deploy/compose.proxy-host.yaml up -d --build --wait
docker compose -f compose.yaml -f deploy/compose.proxy-host.yaml exec backend /app/.venv/bin/python -m pripre.cli source-check --config config/config.toml
```

它仅为后端添加 `host.docker.internal:host-gateway`。代理须监听 Docker 可达的宿主机地址；只监听 `127.0.0.1` 的 Linux 宿主机代理，不能仅靠这个映射从 bridge 容器访问。按实际网络绑定代理的 bridge 地址并限制可访问范围，本项目不自动修改代理监听或宿主机防火墙。

若代理本身是另一个容器，将双方加入同一 Docker 网络，并填写 `http://代理服务名:容器内端口`，使用服务名而不是容器 IP 或宿主机发布端口。无需将应用切换到 host 网络，也无需为占位架构增加代理中间件。

### 认证、直连和验证边界

需要认证时可在本机 `.env` 使用 `http://用户名:密码@代理地址:端口`，特殊字符需 URL 编码；不要提交或在聊天、日志中粘贴凭据。环境变量会存在于容器配置中，拥有 Docker 管理权限的账户仍可读取它。`docker compose config --quiet` 可检查配置而不打印展开后的代理值。

清空 `PRIPRE_SOURCE_PROXY` 并重新创建后端即可恢复显式直连。`/api/health` 成功只表示本地服务正常；应使用 `source-check` 确认 HTTP 和 WebSocket 均成功，实时矩阵仍需经过行情预热。该检查不代表归档一定已发布、历史数据完整或概率准确。

官方参考：[Docker Compose 网络](https://docs.docker.com/compose/how-tos/networking/)、[Docker Desktop 宿主机访问](https://docs.docker.com/desktop/features/networking/networking-how-tos/)、[websockets 显式代理配置](https://websockets.readthedocs.io/en/stable/topics/proxies.html)。

若源返回 418/-1003，表示该出口被 Binance 自动封禁，应遵守 `Retry-After`，不能靠重试或静默直连绕过。具体含义见 [Binance 官方 HTTP 状态说明](https://developers.binance.com/en/docs/products/spot/rest-api)。更换节点还需确认该域名的分流规则确实采用新出口；项目不自动修改共享代理的节点与规则。

原生 Docker Engine 若运行在 WSL，而代理运行在 Windows，`host-gateway` 只代表 Docker Engine 所在宿主网络，不保证对应 Windows。应填写并验证容器实际可达的 Windows 地址，不能套用 Docker Desktop 的拓扑。

本次为 `pripre-dev` 配置了隔离 worktree 中的私有文件 `.env.pripre-dev`（权限 0600，Git 与镜像构建均忽略），目标为 `http://host.docker.internal:7077`。原出口封禁及第一次切换的高延迟均未通过验收；第二次切换后 HTTP/WebSocket 双链路成功，隔离实时运行 135 秒完成 5 次校时且无失败，已使用验证镜像恢复 8020 实例并启用该代理。

后续从隔离 worktree 的最新 `idle` 操作此实例：

```bash
# 不下载历史数据，只检查一次 HTTP 和一次 WebSocket
docker compose --env-file .env.pripre-dev -p pripre-dev exec -T backend /app/.venv/bin/python -m pripre.cli source-check --config config/config.toml
# 修改私有环境文件后重新创建；确认本地镜像版本再使用 --no-build
docker compose --env-file .env.pripre-dev -p pripre-dev up -d --no-build --wait
```

原实例镜像保留为 `pripre-dev-backend:before-proxy-20261025` 和 `pripre-dev-frontend:before-proxy-20261025`。代理启用不代表长期零暂停；节点延迟过高时仍会正常触发校时失效保护。主目录 `dev` 未自动合并，避免从旧代码重建覆盖当前镜像。
