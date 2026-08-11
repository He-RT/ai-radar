# 震幅 AI Radar

> AMPLITUDE — 持续追踪 AI 世界真实发生的变化，并把证据、影响与下一步放在同一处。

震幅不是把新闻复制到网页上的日报站。它把原始来源整理为可追溯的主张、持续更新的事件、可解释的评分和有边界的行动建议。

## 当前状态

仓库处于公开 Beta 的工程建设阶段。核心事实、证据、更正、日报和 API 将免费开放；当前不包含价格、套餐或支付功能。

## 仓库结构

```text
apps/web/       Next.js 公共网站、个人/团队空间与编辑后台
apps/api/       FastAPI、领域模型、采集处理与异步任务
infra/          Docker Compose、Caddy、监控、备份和部署
docs/           ADR、产品设计、运行手册和开发说明
daily/          已有日报样例；自动归档最终写入 archive 分支
```

## 本地启动

前置条件：Node.js 24、pnpm 11、Python 3.13、uv，以及支持 Compose v2 的 Docker 运行时。

```bash
cp .env.example .env
pnpm bootstrap
pnpm dev
```

没有 Docker 时仍可运行使用合成数据的前端和 API：

```bash
pnpm install
pnpm --filter @amplitude/web dev
pnpm api:dev
```

## 质量门禁

```bash
pnpm check
pnpm test
pnpm build
```

这些命令会逐步覆盖 TypeScript、Python、OpenAPI 契约、数据库迁移、领域规则、可访问性和生产构建。

## 许可证

- 程序代码：AGPL-3.0-only，见 [LICENSE](./LICENSE)。
- 原创日报、摘要和结构化数据：CC BY 4.0，见 [CONTENT_LICENSE.md](./CONTENT_LICENSE.md)。
- 第三方文章、图片、摘录和商标仍归各自权利人所有。

安全问题请不要提交公开 Issue，见 [SECURITY.md](./SECURITY.md)。
