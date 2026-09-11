# MemWeave P0 端到端走查清单（tasks.md 11.2）

> 走查视角：评委。走查路径对应 spec §5 核心闭环与 design §2.10.2 P0验收标准。
> 状态标记：✅ 已通过（自动化测试/容器链路验证）；⏳ 待部署环境复核（需 MySQL+MaaS 实连的演示环境）。

## A. 演示账号路径

| # | 步骤 | 预期 | 状态 |
|---|------|------|------|
| A1 | 登录页点击"演示账号快捷填入"→登录 | 进入工作台，侧边栏出现待复习徽标 | ⏳ |
| A2 | 浏览"读书笔记/Python入门"示例库 | 卡片五字段齐全（标题/摘要/要点/问答/标签） | ✅ 单测覆盖数据结构（test_map_service/test_review_flow） |
| A3 | 打开库→切换导图视图 | compactBox 树渲染，叶子节点带卡片标识 | ⏳ |
| A4 | 点击叶子节点 | 跳转 `/card/:id` 卡片详情 | ⏳ |
| A5 | 回顾中心完成一条复习（先问题后揭示答案→三档自评） | 清单数量减少；后端生成下次任务（间隔表核对） | ✅ test_review_flow 三档全覆盖 |
| A6 | 新建沉淀：粘贴≤5000字符文本→一键导入 | 202受理→"解析中"→完成无刷新可见新卡片 | ⏳（MaaS实连） |
| A7 | 解析期间切换页面 | 不阻塞，返回后状态已更新（SSE/轮询降级） | ✅ taskWatcher 降级逻辑；⏳ 实连 |
| A8 | 退出→重新登录 | 会话保持数据一致；登出已删除 Redis 会话 | ✅ test_auth；⏳ 实连 |

## B. 新注册用户闭环

| # | 步骤 | 预期 | 状态 |
|---|------|------|------|
| B1 | 注册新账号 | 自动登录；名下自动出现"默认知识库" | ✅ test_auth（同事务预建默认库） |
| B2 | 弱密码/重复邮箱 | 422 字段级提示 / 409 引导去登录 | ✅ test_auth |
| B3 | 导入→卡片→生成导图→复习 | 完整闭环可走通 | ✅ 单测链路（import→structure→map_gen→review）；⏳ 实连 |
| B4 | 空库点"生成导图" | 任务失败提示"该知识库暂无知识卡片" | ✅ test_map_service::test_empty_kb_fails_with_hint |

## C. 数据隔离抽查

| # | 步骤 | 预期 | 状态 |
|---|------|------|------|
| C1 | 用户B访问用户A的任务/素材/卡片/导图/知识库 | 全部 404（不泄露存在性） | ✅ test_isolation |
| C2 | 双账号各自今日清单互不可见 | 列表仅含本人任务 | ✅ test_review_flow::test_other_users_task_404 |

## D. 可靠性抽查

| # | 步骤 | 预期 | 状态 |
|---|------|------|------|
| D1 | `docker compose restart backend` | 未完成任务恢复执行（t_async_task 扫描重提交） | ✅ test_task_runner::test_startup_recovery_*；⏳ 容器复核 |
| D2 | MaaS 失败 | 指数退避重试≤2后 failed，素材保留，前端"一键重试" | ✅ test_task_runner::test_retry_then_failed；⏳ 实连 |
| D3 | 连续第3个导入任务 | 429"已有任务解析中，请稍候" | ✅ test_import_gate |

## E. 容器链路（11.1）

| # | 步骤 | 预期 | 状态 |
|---|------|------|------|
| E1 | `docker compose up -d --build` | 三容器 healthy（nginx 多阶段构建含前端产物） | ⏳ |
| E2 | `curl http://localhost/health` | 经 Nginx 反代返回 code=0 | ⏳ |
| E3 | SSE 状态推送经 Nginx | `proxy_buffering off` 下实时到达 | ⏳（配置已就位：deploy/nginx.conf） |
| E4 | 多 worker 启动 | 调度器仅 1 实例激活（SETNX 锁+周期续期） | ✅ test_scheduler；⏳ 容器复核 |

> ⏳ 项在华为云 ECS 部署演示环境后按本清单逐项复核并勾选归档。
