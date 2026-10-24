# 项目协作约束

## 项目目标

以 `TASK.md` 为需求依据。当前是框架阶段；不能将占位页面、健康检查或模拟数据描述为真实行情接入、概率准确性或全周期回测验收。

## 环境与依赖

- Python 环境和依赖必须使用 **uv** 管理，使用 Python 3.12。禁止用 pip 手工修改项目环境。
- JavaScript/TypeScript 环境和依赖必须使用 **pnpm** 管理，使用 Node.js 24、项目 `packageManager` 指定的 pnpm 版本。禁止使用 npm/yarn 管理项目依赖。
- 提交 `uv.lock` 和 `pnpm-lock.yaml`；修改依赖后更新锁文件，复现环境使用 `uv sync --locked` 与 `pnpm install --frozen-lockfile`。
- `pre-commit` 已全局安装，直接使用，不重复安装到项目 Python 环境。
- 不提交凭据、`.env`、虚拟环境、依赖目录、行情原始数据或构建输出。

## 分支与隔离 worktree

- 始终保留 `main`、`dev`、`idle` 三个长期分支：`main` 为稳定基线，`dev` 为主工作目录分支，`idle` 为已验收工作的集成分支。
- 主目录 `/home/florenz/PRIPRE` 保持在 `dev`，不在主目录直接修改代码。
- 代码和项目文件修改均在隔离 worktree `/tmp/pripre-agent-worktree` 进行。先检查 `git status` 和 `git worktree list`，不得覆盖已有未提交工作。
- 每个功能从最新 `idle` 创建独立分支，例如 `feat/<name>`、`fix/<name>`、`docs/<name>`；在隔离 worktree 切换到该功能分支后工作。
- 完成全量测试、构建和 pre-commit，确认无误后提交功能分支，再将其合并到 `idle`。
- **工作结束时，隔离 worktree 必须处于 `idle` 分支，且工作区干净。** 工作期间允许切换到对应功能分支。
- 不自动将 `idle` 合并到 `dev` 或 `main`；不擅自删除未合并分支、worktree 或他人的文件，不强推、不使用破坏性重置清理现场。
- 若检查失败，先修复并重新执行完整检查；确实受外部条件阻塞时报告证据，不声称已验收或强行合并。

典型流程（首次 worktree 已由框架初始化完成）：

```bash
cd /tmp/pripre-agent-worktree
git status --short
git switch idle
git switch -c feat/example
# 实现功能，暂存需要纳入检查的文件
git add <files>
uv run --locked python scripts/check.py
# 若格式化修改了文件，重新暂存并重跑完整检查
git commit -m "feat: describe the change"
git switch idle
git merge --ff-only feat/example
```

若 `idle` 在开发期间已前进，先整合最新 `idle`，再执行全量检查；不得绕过冲突处理或验证。

## 每次改动后的必跑检查

每次完成一轮改动后，**必须执行全量测试及 `pre-commit run --all-files`**，不以仅运行相关测试或 `git commit` 的增量 hook 代替。统一入口：

```bash
uv sync --locked
pnpm install --frozen-lockfile
# 新文件先 git add，否则 pre-commit --all-files 不会检查未跟踪文件
uv run --locked python scripts/check.py
```

该入口依次检查锁文件、运行全部后端和前端测试、前端生产构建、全部 pre-commit hooks，以及 Compose 配置校验。pre-commit 包含 Python 格式化/lint/严格类型检查、JS/TS/Vue lint 和类型检查、JSON/YAML/Markdown/CSS 格式化、TOML 格式化与配置语法检查。

格式化工具若修改文件，本轮检查不算通过：重新暂存后重跑完整入口。修改 Dockerfile、Compose 或反向代理配置时，还需执行镜像构建和容器健康/HTTP 冒烟验证。部署验证与静态配置验证必须分别报告。

## 架构与测试边界

- 后端代码在 `backend/src/pripre`，前端在 `frontend`，部署配置在 `deploy`，公共检查入口在 `scripts`。
- 数据、特征、模型、回测模块保持清晰边界；实时和回测共用概率估计引擎。
- 单元测试默认不访问外部行情、不连接本机 PostgreSQL、不修改真实数据。外部服务验证必须显式执行。
- 测试验证公开行为、边界和错误路径，不为占位模块增加无意义测试，不以样本数量代替断言质量。
- 金融事件语义、防止未来信息泄漏、缺失数据处理遵循 `TASK.md`。

## 部署与文档

- 使用 Docker Compose 部署。当前框架不依赖数据库、Redis 或消息队列，不为占位架构引入服务。
- 本机已有 PostgreSQL；后续确需关系数据库时优先接入现有 PostgreSQL，并独立配置应用数据库和权限，不擅自更改实例配置或现有数据。
- 如需 PostgreSQL 以外的中间件，必须通过 Docker Compose 管理，不要求在宿主机手工安装。
- 持久化数据必须有明确的卷、备份和恢复方式；不得执行未经授权的数据卷删除。
- 功能或使用方式变化时更新 `README.md`，每个交付变更更新 `CHANGE.md`，部署变化更新 `COMPOSE.md`。
- 报告区分：已实现、自动测试通过、容器验证通过、真实数据验证通过；未执行的检查必须明确说明。
