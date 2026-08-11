# ADR 0001：模块化单体与异步工作流

- 状态：已接受
- 日期：2026-08-12

## 决策

首发采用一个公开 monorepo 和模块化单体，运行时拆分为 Web、API、Fetcher、Processor、Scheduler 与 Publisher。PostgreSQL 是唯一结构化事实源；Valkey 只承载队列、缓存和短期锁；对象使用 S3 兼容存储。

## 理由

单人维护、4 核/16GB 单机和完整审计需求不适合过早微服务化。独立进程保留资源隔离和后续迁出能力，领域契约、迁移和发布仍在同一版本中演进。

## 后果

- 通过 transactional outbox 和幂等回执衔接异步模块。
- 任何服务不得把 Valkey 当作不可恢复的事实源。
- CPU、队列或数据库达到扩容阈值时，先迁出 Worker，再迁出数据库。
