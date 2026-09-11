# MemWeave（忆织）

> 第十一届华为ICT大赛创新赛 · 赛道一（赛题1：基于华为云产品打造AI创新应用）参赛作品

**作品全称**：MemWeave（忆织）：基于华为云MaaS大模型的多源知识编织与抗遗忘记忆系统

**命名内涵**：Weave（编织）精准对应"多源素材→卡片→导图"的核心动作，Mem 对应抗遗忘记忆；中文"忆织"谐音"一织即成"。

## 1. 项目介绍

MemWeave（忆织）是一款**个人专属的知识/人生经验图库**——把你看过的书、领悟到的人生知识、现实生活中的亲身体悟，以及学习笔记、错题复盘，都一键沉淀为独属于你自己的结构化知识图库，解决"学过/悟过的东西随时间流逝而遗忘"的真实痛点。

**多源知识一键转化 → 结构化沉淀 → 思维导图呈现 → 抗遗忘复习** 完整闭环。

每个用户均为独立个体，知识数据严格隔离。错题本只是众多沉淀场景之一（学习场景），产品本质是覆盖学习、读书、生活体悟等广义个人知识沉淀的图库。

### 核心功能

| 优先级 | 功能 | 说明 |
|--------|------|------|
| **P0** | 多源知识导入 | 粘贴文本一键转化（文档/图片导入为P1） |
| **P0** | AI 结构化卡片 | 大模型生成"标题-摘要-要点-问答-标签"知识卡片，可溯源、可编辑 |
| **P0** | 思维导图 | 基于知识卡片自动生成层级导图，叶子节点可跳转对应卡片 |
| **P0** | 抗遗忘复习 | 基于遗忘曲线（1/2/4/7/15/30天间隔）排定复习任务，三档自评驱动间隔动态调整 |
| P1 | 错题本与测验 / 知识搜索 / 文档图片导入 | 迭代规划中 |
| P2 | 知识分享论坛 / 导图拼图自测 / 语义搜索 | 决赛冲分规划中 |

> 产品截图占位：演示环境部署后补充工作台/导图/复习页截图。

## 2. 技术栈

**AI 能力**
- 华为云 MaaS 大模型：文本结构化转换、思维导图层级提炼（P1 起多模态图片识别）

**后端**（`backend/`，Python 3.11+）
- FastAPI 0.110+ / SQLAlchemy 2.x（async）+ aiomysql / Alembic 数据库迁移
- 任务表 + ThreadPoolExecutor(8) + SSE 推送（异步任务链，禁止 Celery）
- MySQL 8 FULLTEXT + ngram + STORED GENERATED 生成列（禁止 Elasticsearch）
- bcrypt + Redis 会话（httpOnly Cookie，禁止 JWT）
- APScheduler + Redis SETNX 启动锁（多 worker 单实例调度）

**前端**（`frontend/`，Node 20+）
- Vue 3.4 + TypeScript + Vite 5
- Element Plus 2.7 + Pinia + AntV G6 v5（思维导图渲染）

**华为云服务**
- ECS（部署）、RDS for MySQL 8（持久化）、分布式缓存 Redis（会话/缓存）、OBS（对象存储，P1 接入）、MaaS（大模型服务）

## 3. 华为云资源开通

| 资源 | 建议规格 | 用途 | 配置要点 |
|------|---------|------|---------|
| ECS | 4核8G Ubuntu 22.04 | 应用部署载体 | 安全组开放 80/443，安装 Docker 与 Docker Compose |
| RDS for MySQL 8 | 2核4G 100GB SSD | 业务数据持久化 | 字符集 utf8mb4；**参数 `ngram_token_size=2`**（中文全文检索必需，修改后需重启实例）；开启每日备份 |
| Redis | 2G | 会话与热点缓存 | 内网访问，记录连接地址 |
| MaaS | 大模型服务 | 结构化/导图层级提炼 | 开通服务、创建部署任务、获取 API Key 与服务端点 |
| OBS（P1 接入） | 标准桶 | 原始文件存储 | 创建桶并记录 AK/SK（P0 阶段可不开通） |

开通步骤（以控制台为例）：
1. **RDS**：购买实例 → 设置 root 密码 → 参数组中修改 `ngram_token_size=2` 并应用 → 创建库 `memweave` → 记录连接串；
2. **Redis**：购买实例 → 设置访问密码（或免密白名单）→ 记录 `redis://host:6379/0`；
3. **MaaS**：进入 MaaS 控制台 → 订阅/部署文本大模型 → 创建 API Key → 记录服务端点（OpenAI 兼容 `chat/completions` 地址）；
4. **ECS**：购买 → 安装 Docker（`curl -fsSL https://get.docker.com | bash`）→ 将仓库克隆/上传至 ECS → 按 §5 完成 `.env` 配置与启动。

## 4. 本地开发运行

**后端**（先准备本地 MySQL 8 与 Redis，或先仅体验接口层）：

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate        # Windows；Linux/Mac 为 source .venv/bin/activate
pip install -r requirements.txt
# 复制 .env.example 为 backend/.env 并填入本地 MySQL/Redis 连接
alembic upgrade head          # 初始化数据库表结构
uvicorn app.main:app --reload
# 验证：curl http://127.0.0.1:8000/health 返回 code=0；/docs 查看 OpenAPI
```

**前端**：

```bash
cd frontend
npm install
npm run dev
# 访问 http://localhost:5173（Vite 已配置 /api 代理到 127.0.0.1:8000，本地开发免CORS）
```

**后端测试**：

```bash
cd backend
.venv\Scripts\python -m pytest tests/ -v          # 全量回归（业务逻辑层）
.venv\Scripts\python -m pytest tests/ --cov=app   # 附覆盖率报告
```

> 说明：业务逻辑测试默认跑 aiosqlite 兼容层；涉及 FULLTEXT ngram 检索效果的验证须在 MySQL 8 测试容器复核。

## 5. Docker 一键部署

```bash
# 1. 在仓库根目录准备环境变量（参考 .env.example，仅含变量名模板）
cp .env.example .env
# 编辑 .env：填入 DATABASE_URL / REDIS_URL / MAAS_API_KEY / MAAS_ENDPOINT /
#            ADMIN_TOKEN / DEMO_ACCOUNT_EMAIL / DEMO_ACCOUNT_PASSWORD

# 2. 初始化数据库（首次部署执行一次；也可在 backend/.env 配好后于本机执行）
cd backend && alembic upgrade head && cd ..

# 3. 一键构建并启动（前端多阶段构建进 Nginx，无宿主机 Node 依赖）
docker compose up -d --build

# 4. 验证
docker compose ps                 # nginx / backend / redis 三容器 healthy
curl http://localhost/health      # 经 Nginx 反代返回 code=0
```

浏览器访问 **http://localhost** 进入应用。部署完成后执行一次演示数据预置：

```bash
docker exec memweave-backend python -m app.scripts.seed_demo
```

## 6. 演示账号

| 项 | 值 |
|----|----|
| 邮箱 | `.env` 中 `DEMO_ACCOUNT_EMAIL`（默认 demo@memweave.cn） |
| 密码 | `.env` 中 `DEMO_ACCOUNT_PASSWORD`（部署时自行设定） |
| 预置数据 | 2个示例知识库（读书笔记/Python入门）+ 结构化卡片 + 思维导图 + 今日待复习任务 |
| 每日重置 | 每日 3:00 自动重置为预置状态（APScheduler 定时任务） |

**体验路径（评委走查）**：登录页点击演示账号快捷填入 → 登录 → 浏览工作台与知识库 → 打开"读书笔记"查看思维导图（叶子节点可跳转卡片）→ 回顾中心完成一条复习自评 → 新建沉淀粘贴一段文本 → 等待 AI 生成卡片 → 退出重新登录。

**运维通道**（演示当天数据被改动时可远程一键恢复）：

```bash
curl -X POST http://<服务器IP>/api/admin/demo/reset \
     -H "Authorization: Bearer ${ADMIN_TOKEN}"
```

## 7. 开源协议

本项目基于 [MIT License](LICENSE) 开源。

---

*第十一届华为ICT大赛创新赛参赛项目 · 2026*
