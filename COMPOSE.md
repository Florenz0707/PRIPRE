# Docker Compose 部署

## 部署结构

- `backend`：Python 3.12 + uv 构建的 FastAPI 服务，容器内端口 8000，以非 root 用户运行。
- `frontend`：Node.js 24 + pnpm 构建 Vue 静态资源，由 Nginx 提供页面并代理 `/api/`；代理保留 WebSocket 升级能力。
- 后端仅在 Compose 网络内可访问；宿主机默认仅发布 `127.0.0.1:8080`。
- 当前版本没有数据库依赖，也没有持久化业务数据，因此不创建数据库容器或数据卷。

镜像中 Python 使用 `uv sync --locked --no-dev --no-editable`，前端使用 `pnpm install --frozen-lockfile`。部署构建与开发环境共用锁文件。镜像基础版本在 Dockerfile 中指定，发布前应重新构建并验证。

## 启动

需要可访问的 Docker daemon、Docker Compose 插件，以及拉取镜像和下载依赖的网络。以下命令在包含 `compose.yaml` 的已验收 checkout 中执行，例如 `/tmp/pripre-agent-worktree` 的 `idle` 分支。

```bash
cp .env.example .env
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

健康接口应返回 `status: ok`、`service: pripre-api`、`stage: scaffold`；首页显示研究流程和后端连接状态。健康检查不代表行情新鲜度或模型可用性。`docker compose config` 通过仅代表配置有效，不能代替镜像构建和运行验证。

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
