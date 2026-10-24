# PRIPRE

价格区间触达概率研究项目。以当前成交价为中心，将价格区间与未来时间窗组成概率矩阵，估计窗口内至少一次成交触达的概率，并通过历史实际频率检验校准效果。完整需求见 [TASK.md](TASK.md)。

## 当前功能

- FastAPI 后端及 `/api/health` 健康接口。
- Vue 3 + TypeScript 前端，展示连接状态、错误重试和研究流程。
- 数据、特征、概率模型、回测模块边界。
- Python/前端测试、格式化、lint、严格类型检查及统一质量检查入口。
- Docker Compose 双服务部署，Nginx 提供静态资源并代理 `/api/`。

当前为 `0.1.0` 框架版本，尚未接入行情、模型、概率矩阵或真实回测。健康接口仅说明 API 可响应，不代表数据或模型就绪。

## 开发环境

需要 Python 3.12、uv、Node.js 24、pnpm 11.24.0、全局 pre-commit、Docker Compose。依赖以锁文件为准。

本项目在隔离 worktree 开发，完整分支约束见 [AGENTS.md](AGENTS.md)。主目录保留 `dev` 基线，验收代码位于隔离 worktree 的 `idle` 分支。

在隔离 worktree 根目录执行：

```bash
uv sync --locked
pnpm install --frozen-lockfile
pre-commit install
```

分别打开两个终端：

```bash
# 后端：http://127.0.0.1:8000，接口文档：http://127.0.0.1:8000/docs
uv run --locked uvicorn pripre.api:app --reload --host 127.0.0.1 --port 8000
```

```bash
# 前端：http://127.0.0.1:5173；/api 请求由 Vite 代理到后端
pnpm dev
```

## 质量检查

```bash
# 新文件必须先暂存，确保 pre-commit 纳入检查
uv run --locked python scripts/check.py
```

统一入口运行锁文件检查、全部后端/前端测试、前端生产构建、`pre-commit run --all-files` 和 Compose 配置校验。配置校验不需要 Docker daemon，但容器构建和运行需要。

单独运行测试和质量工具：

```bash
uv run --locked pytest
pnpm test
pnpm build
pre-commit run --all-files
```

hooks 使用 uv/pnpm 锁定的本地工具，覆盖 Ruff、mypy、ESLint、vue-tsc、Prettier、TOML 格式化、配置语法、冲突标记和私钥检查。格式化造成修改后需重新暂存并重跑全量检查。

## 目录

```text
backend/src/pripre/
  api.py           HTTP 应用边界
  data/            成交接入与质量检查（待实现）
  features/        市场状态特征（待实现）
  models/          共享概率估计引擎（待实现）
  backtesting/     回放、标签与校准（待实现）
backend/tests/     后端测试
frontend/          Vue 页面与前端测试
scripts/check.py   统一质量检查入口
deploy/            Dockerfile 与 Nginx 配置
compose.yaml       部署入口
```

框架仅安装实际需要的依赖。NumPy、Polars、SciPy、DuckDB、ECharts 等研究与可视化依赖在对应功能实现时通过 uv/pnpm 添加，不在当前版本引入空服务。

## 部署与后续工作

部署、端口设置、运行验证和中间件约束见 [COMPOSE.md](COMPOSE.md)。变更记录见 [CHANGE.md](CHANGE.md)。

后续按 `TASK.md` 执行：固定事件口径 → 数据链路 → 基准回测 → 主模型 → 实时矩阵与研究面板 → 全周期验收。

## 阶段 1：事件与扩展接口

`config/default.toml` 提供 BTC/Binance、价格网格、历史范围、下载预算及最多 50 个客户端的默认配置。Python 调用 `load_config(path)` 加载并校验，未知键和无效组合会报错。

品种通过 `Instrument` 描述，来源通过 `MarketSource` 接口与 `SourceRegistry` 注册；新适配器无需修改网格与标签模块。报价源必须显式声明能力，不能替代成交证据。

`touch_labels` 使用冻结网格和真实成交判定；完整但无成交记为未触达，缺失数据下未观察到的事件记为未知，已观察到的触达仍可确认。
