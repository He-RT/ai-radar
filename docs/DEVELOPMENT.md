# 开发环境

## 固定工具链

仓库通过 `mise.toml` 固定 Node.js 24、pnpm 11、Python 3.13 与 uv。不要使用系统 Node/Python 生成锁文件。

```bash
brew install mise
mise trust
./scripts/bootstrap.sh
```

当前开发机如果没有 Docker，仍可运行使用合成数据的 Web/API。完整数据库、队列、对象存储和邮件测试必须在 CI 或 Compose 环境执行。

## 运行单元

```bash
mise exec -- pnpm --filter @amplitude/web dev
mise exec -- pnpm api:dev
```

完整本地服务：

```bash
mise exec -- pnpm compose:up
mise exec -- pnpm dev
```

## 变更纪律

- API Schema 由 FastAPI/OpenAPI 产生，前端类型通过生成脚本更新；不得手写两个不一致的 DTO。
- 数据库迁移只增加新文件，已经合并的迁移不得改写。
- 领域规则、评分、提示词和数据 fixture 必须有版本。
- UI 必须同时实现真实、空、陈旧、错误、撤回和无 JavaScript状态。
- 任何外部网络、邮件和模型调用在测试中默认由 stub 替代。

## 提交前

```bash
./scripts/verify.sh
```

该脚本覆盖静态检查、测试、生产构建与 Compose 渲染。数据库迁移/恢复演练、浏览器无障碍复核、镜像扫描和签名验证必须另按 CI 与运行手册执行；本地脚本通过不等于发布门禁全部通过。
