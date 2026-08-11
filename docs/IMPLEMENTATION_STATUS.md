# 实施状态与验收边界

更新时间：2026-08-12

本文件记录仓库中已经由代码、约束和测试实现的能力，以及仍需通过后续纵向切片交付的内容。产品目标只作为工程验收边界保存在这里，不会被复制成网站宣传口号。

## 当前纵向切片

首个基础版本已经建立：

- Node 24、Python 3.13、pnpm、uv、Turborepo 的固定版本 monorepo。
- Next.js SSR 公共雷达、事件、行动、故事线、日报、搜索、方法和设置页面；生产模式只读取 API。
- FastAPI 公共接口、证据约束、事件版本、确定性评分、发布门禁、SQL 事实仓储、持久身份与团队权限。
- 不可变日报内嵌完整事件公共快照；后续事件变化不会改写旧日报 JSON、Markdown、RSS、网页或 ETag。
- 500 条可审计来源目录：447 条具有运行时处理器，53 条因监管页面政策复核、TLS 或访问控制而禁用并进入明确的 `policy_skip`；目录校验器、SSRF DNS 固定抓取、安全响应限制和可测试的连接器调度边界已经存在。
- PostgreSQL 18/pgvector、Valkey、MinIO、Caddy、可观测性、备份恢复、只读非 root 容器和按角色拆分的 Secret。
- 精确源码 SHA、干净 runner 扫描、镜像扫描、SBOM、Cosign 签名、digest 部署、前向迁移和受保护环境。

## 本切片的可重复验收

~~~sh
./scripts/verify.sh
bash infra/scripts/test-restore-drill.sh
bash infra/scripts/test-worker-catalog-task-smoke.sh amplitude-radar-worker:final
bash infra/scripts/test-production-smoke.sh
actionlint
~~~

验收包含类型检查、单元/集成/契约测试、OpenAPI 漂移、Next 生产构建、500 来源目录及其运行时覆盖、开发/生产 Compose 渲染、PostgreSQL 与 MinIO 数据面真实恢复，以及本地不可变 registry digest 的生产核心容器冒烟。离线 worker 镜像测试会加载镜像内目录并执行一次已注册 Celery 任务边界，但不会访问真实信源。

## 尚未宣称完成

以下内容仍属于后续 28 周路线，不得因页面或接口占位而宣称完成：

- 53 条 `policy_skip` 的逐源 robots/条款/TLS/访问控制复核，以及 500 来源连续生产抓取的 99% 成功率与真实发现延迟；历史回填和来源值班。
- 300 组聚类黄金集、召回/错并/重复事件指标及模型新旧双跑。
- 完整编辑后台、自动发布 14 天或 500 事件影子验证、五分钟更正传播。
- 邮箱验证/重置、TOTP、私人 RSS、邮件、签名 Webhook、通知撤回与数据导出删除全流程。
- 混合搜索 NDCG@10、生产模型 Ask Radar、团队决策工作流和结构化社区贡献。
- 100 RPS、Core Web Vitals、全设备 WCAG 2.2 AA、RPO/RTO 全站恢复和 20 人真实用户验收。
- 公开 Beta 发布候选、四周稳定运行和 `v1.0.0`。

任何后续发布仍须逐项满足原计划的 Go/No-Go 门槛；不得通过隐藏失败、降低样本难度或修改目标文案替代验收。
