# 发布流程

本文档用于记录 `igp-ride` 的日常开发与版本发布流程。

## 分支约定

- `main`：稳定分支，只保留准备发布或已经发布的内容
- `dev`：日常开发分支，功能开发、文档调整、CI 修复等都先进入这里

推荐流程：

1. 在 `dev` 上开发和提交
2. 在 `dev` 上验证新增功能是否稳定
3. 稳定后，将 `dev` 合并到 `main`
4. 在 `main` 上确认版本号、CI 和发布内容
5. 打 tag 并推送，触发 GitHub Release

## 日常开发流程

如果还没有 `dev` 分支，先创建：

```bash
git checkout -b dev
git push -u origin dev
```

之后日常开发使用：

```bash
git checkout dev
```

如果需要做独立功能开发，也可以从 `dev` 再切功能分支，例如：

```bash
git checkout dev
git checkout -b feat/some-feature
```

功能完成后先合并回 `dev`，不要直接合并到 `main`。

提交代码前，建议先运行：

```bash
uv sync --group dev
uv run ruff check src tests
uv run pytest
uv run basedpyright --level error
```

开发完成后，将 `dev` 合并到 `main`：

```bash
git checkout main
git pull origin main
git merge --ff-only dev
git push origin main
```

如果 `--ff-only` 无法合并，先回到 `dev` 同步 `main` 后整理分支，再重新尝试。

## dev 分支版本策略

建议让 `dev` 的版本号始终领先 `main` 一个待发布版本，例如：

- `main`：`0.1.2`
- `dev`：`0.1.3`

这样有两个好处：

- 安装 `@dev` 后，`igp-ride --version` 能和正式版区分开
- 开发中的版本边界更清楚，不会和已发布版本混淆

推荐时机：

1. `main` 发布完 `v0.1.2` 后
2. 切回 `dev`
3. 立刻把 `dev` bump 到下一版本，例如 `0.1.3`

当前仓库已经有一键 bump 脚本：

```bash
./scripts/bump_version.sh patch
./scripts/bump_version.sh minor
./scripts/bump_version.sh major
```

这个脚本会同时：

- 更新 `pyproject.toml`
- 刷新 `uv.lock`

注意：

- `bump-my-version` 默认要求 Git 工作区干净
- 所以应先提交当前开发改动，再运行 bump 脚本
- 版本号更新必须通过 `./scripts/bump_version.sh patch|minor|major` 执行，不要直接运行 `uv run bump-my-version bump ...`
- 原因是当前 `bump-my-version` 只负责更新 `pyproject.toml`；`uv.lock` 需要由脚本中的 `uv sync --group dev` 刷新

如果 `dev` 只是刚进入下一轮开发，通常用一次 `patch` 或 `minor` 即可，按你的版本策略决定。

## 版本发布流程

当前项目版本号定义在：

- `pyproject.toml`

例如当前版本：

```toml
version = "0.1.2"
```

发布新版本时，使用以下顺序：

1. 在 `dev` 上完成开发并确认稳定
2. 切到 `main`
3. 合并 `dev` 到 `main`
4. 如果 `main` 还不是目标发布版本，先更新版本号
5. 提交版本变更
6. 推送 `main`
7. 创建对应 tag
8. 推送 tag

示例：发布 `v0.1.1`

```bash
git checkout dev
uv sync --group dev
uv run ruff check src tests
uv run pytest
uv run basedpyright --level error

git checkout main
git pull origin main
git merge --ff-only dev

# 如果 main 需要单独 bump，再执行版本更新
# 例如：./scripts/bump_version.sh patch

git push origin main

git tag v0.1.1
git push origin v0.1.1
```

发布完成后，回到 `dev` 开启下一轮开发：

```bash
git checkout dev
git pull origin dev

# 进入下一开发版本，例如从 0.1.1 到 0.1.2
./scripts/bump_version.sh patch
```

## GitHub Actions 与 Release

仓库中有两个相关工作流：

- `.github/workflows/ci.yml`
- `.github/workflows/release.yml`

说明：

- `ci.yml` 建议在 push 到 `main`、`dev` 或 pull request 时运行
- `release.yml` 会在推送 `v*` tag 时运行
- `release.yml` 会校验 tag 和 `pyproject.toml` 的版本号一致
- 校验通过后，会构建并上传 release 产物

## 发布前检查清单

在推送 tag 前，至少确认这些事项：

- 当前位于 `main`
- 工作区干净：`git status`
- `pyproject.toml` 的版本号已更新
- 本地 CI 已通过
- 准备创建的 tag 与版本号一致，例如 `version = "0.1.1"` 对应 `v0.1.1`

## 发布后检查清单

发布后建议检查：

1. GitHub Actions 中 `release` workflow 是否成功
2. GitHub Releases 页面是否出现新版本
3. release 附件中是否包含 `.whl` 和 `.tar.gz`
4. README 中的安装方式是否仍符合预期

## 回滚与修正

如果只是 release 说明写得不好，可以直接在 GitHub 页面编辑 Release 文案。

如果版本号或 tag 打错了，不要直接修改旧版本内容，建议：

1. 删除错误 tag
2. 修正 `pyproject.toml` 版本号
3. 重新提交
4. 重新打正确的 tag

## 当前推荐安装方式

README 当前使用 GitHub 安装：

```bash
uv tool install git+https://github.com/YetYeti/igp-ride@v0.1.2
```

如果希望试用开发分支，可以使用：

```bash
uv tool install git+https://github.com/YetYeti/igp-ride@dev
```
