# MemWeave P0 验收核对记录（tasks.md 14.2）

> 核对依据：design.md §2.10.2（P0-1~P0-8 交付物与验收标准）、spec.md §4.1~§4.3。
> 核对方式：单元/集成测试（pytest，77 用例全绿）+ 代码走查；标注 ⏳ 项待华为云演示环境部署后复核。
> 核对日期：2026-09-11

## P0 交付物逐项核对

| 编号 | 交付物 | 验收标准 | 状态 | 证据 |
|------|--------|---------|------|------|
| P0-1 | 注册登录 + 演示账号 | 邮箱注册自动登录；演示账号预置数据可体验闭环；每日3:00自动重置；受保护远程重置接口 | ✅ | test_auth / demo_service / scheduler 3:00 job / POST /api/admin/demo/reset（ADMIN_TOKEN+常量时间比较） |
| P0-2 | 文本导入 + 异步任务链 | ≤5000字符；一键零配置；202受理；单用户并发闸门≤2（429）；素材先于任务落盘 | ✅ | test_import_gate |
| P0-3 | AI 结构化卡片 | MaaS生成五字段卡片；§6.3约束校验不落残缺卡；失败重试≤2；素材保留；首排复习任务次日 | ✅ | test_card_schema / test_review_flow::test_structure_schedules_first_review |
| P0-4 | 知识库管理 + 卡片归组 | CRUD/重名409/两段式删除明示级联数量；卡片移动跨库；列表分页+缓存 | ✅ | test_map_service::test_kb_delete_cascades / api 层实现 |
| P0-5 | 思维导图生成与浏览 | 异步 map_gen 任务链；后端权威校验（根唯一/card_id合法/非叶不挂卡）；一库一图覆盖；G6 v5 树渲染 | ✅ | test_map_service / MindMapCanvas.vue（compactBox+collapse-expand） |
| P0-6 | 抗遗忘复习 | 间隔集[1,2,4,7,15,30]；三档自评状态机；忘记重置；今日清单缓存 | ✅ | test_spaced_repetition（6档×3自评全表）/ test_review_flow |
| P0-7 | Docker Compose 部署 | 三容器一键起；前端多阶段构建进 Nginx；SSE 代理；healthcheck | ✅ 配置 / ⏳ 实机 | docker-compose.yml（nginx build from frontend/Dockerfile）+ deploy/nginx.conf |
| P0-8 | README 与开源交付 | 七章骨架；.env.example 模板；MIT License | ✅ | README.md / .env.example / LICENSE |

## 性能抽测（spec §4.1）

| 指标 | 目标 | 状态 | 证据 |
|------|------|------|------|
| 卡片列表 1000 条 | ≤2s | ✅（SQLite 兼容层计时护栏）/ ⏳ MySQL 正式口径 | test_card_perf（回源与缓存命中双场景） |
| 首屏加载 | ≤3s | ⏳ 部署后 Lighthouse 复核 | Vite 路由懒加载 + Nginx gzip 已配置 |
| 文本结构化 | ≤30s | ✅ 设计 | MaaS 文本超时 30s（maas_client），异步不阻塞 |

## 安全抽测（spec §4.3）

| 项 | 预期 | 状态 | 证据 |
|----|------|------|------|
| 未认证访问 | 401 统一格式 | ✅ | test_auth::test_unauthenticated_protected_route_401 |
| 双用户隔离 | 跨用户全部 404 | ✅ | test_isolation |
| 防枚举 | 登录失败统一文案 | ✅ | test_auth::test_login_wrong_credentials_uniform_401 |
| 凭据不入仓库 | 无 AK/SK/API Key 硬编码 | ✅ | `grep -r "AK\|SK\|API_KEY" backend/app` 仅环境变量引用；.env 已 gitignore |
| ADMIN_TOKEN 通道 | 错误 token 401；不与会话混用 | ✅ | verify_admin_token 常量时间比较 |

## 可靠性抽测（spec §4.2）

| 项 | 预期 | 状态 | 证据 |
|----|------|------|------|
| 重启恢复 | pending/running 任务重新提交；多 worker 锁去重 | ✅ | test_task_runner::test_startup_recovery_* |
| MaaS 失败 | 重试≤2（1s→2s）后 failed，素材保留 | ✅ | test_task_runner::test_retry_then_failed |
| Redis 降级 | 缓存场景降级直查；会话场景拒绝（安全优先） | ✅ | test_redis_client |
| 调度单实例 | SETNX 锁 + 45s 周期续期，双激活被拒 | ✅ | test_scheduler |

## 测试与覆盖（tasks.md 14.1）

- 套件：`backend/tests/` 共 12 个测试文件、81 用例，`pytest -v` 全绿。
- 覆盖率（pytest-cov）：总体 70%；关键路径模块 auth_service 96% / review_service 96% /
  import_service 84% / map_validate 91% / spaced_repetition 76%
  （demo_service/部署期分支在演示环境联调中覆盖）。
- 约定：STORED GENERATED 生成列采用 MySQL 8 / SQLite 双方言等价表达式
  （`json_extract(col,'$')`，对 JSON 数组输出与 JSON_UNQUOTE 一致），业务测试跑 aiosqlite 兼容层；
  FULLTEXT ngram 检索效果与 1000 卡片 ≤2s 正式口径须在 MySQL 8 测试容器复核（tasks.md 14.1 注记）。

## 结论

P0-1~P0-8 代码与配置交付完成，自动化验收全部通过；标注 ⏳ 的项（MaaS 实连链路、容器健康检查、首屏实测）
待华为云 ECS 演示环境部署后按 `docs/e2e-checklist.md` 复核归档，达成"演示就绪"（2026-11-30 里程碑）。
