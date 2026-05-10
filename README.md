# igp-ride

`igp-ride` 是一个简洁的命令行工具，用于把 IGPSPORT 骑行活动同步到本地 SQLite 数据库，下载对应 FIT 文件，并可选择将本地 FIT 文件上传到 Intervals.icu。

## 功能概览

- 登录 IGPSPORT 账号
- 同步 IGPSPORT 骑行活动
- 下载活动对应的 FIT 文件
- 查看本地活动列表
- 查看单条活动详情
- 上传活动到 Intervals.icu
- 预览将要上传到 Intervals.icu 的活动
- 重新执行同步时自动处理上次失败的上传

## 环境要求

- Python 3.14 或更新版本
- 可用的系统 keyring
- IGPSPORT 账号
- 如需同步到 Intervals.icu，需要 Intervals.icu API key

## 安装

### 远程安装

安装 `main` 分支：

```bash
uv tool install git+https://github.com/YetYeti/igp-ride@main
```

升级已安装版本：

```bash
uv tool install --upgrade git+https://github.com/YetYeti/igp-ride@main
```

安装后确认命令可用：

```bash
igp-ride --help
```

### 本地开发安装

在本仓库目录中安装为本地工具：

```bash
uv tool install .
```

或者直接在开发环境中运行：

```bash
uv sync
uv run igp-ride --help
```

## 基本流程

登录 IGPSPORT：

```bash
igp-ride login
```

该命令会交互输入用户名和密码，并把凭据保存到系统 keyring。

同步活动和 FIT 文件：

```bash
igp-ride update
```

查看本地活动列表：

```bash
igp-ride list
```

查看最新活动：

```bash
igp-ride show last
```

按 IGPSPORT ride ID 查看指定活动：

```bash
igp-ride show 123456
```

## 命令

### `login`

```bash
igp-ride login
```

登录 IGPSPORT，并保存本地凭据和 session 数据。

无参数。

### `logout`

```bash
igp-ride logout
igp-ride logout --yes
```

清除本地 IGPSPORT 凭据和 session 数据。

不加 `--yes` 时会要求确认，只有输入 `LOGOUT` 才会继续执行。

参数：

- `--yes`：跳过确认。

### `reset`

```bash
igp-ride reset
igp-ride reset --yes
```

删除本地 `igp-ride` 数据，包括 SQLite 数据库、已下载 FIT 文件、IGPSPORT 凭据和 session 数据。

不加 `--yes` 时会要求确认，只有输入 `RESET` 才会继续执行。

参数：

- `--yes`：跳过确认。

### `update`

```bash
igp-ride update
igp-ride update --all
```

从 IGPSPORT 拉取活动，写入本地 SQLite 数据库，下载 FIT 文件，并自动修复缺失或无效的 FIT 文件。

默认执行增量同步。使用 `--all` 可强制全量刷新活动。

参数：

- `--all`：强制全量更新所有可用活动。

### `list`

```bash
igp-ride list
igp-ride list --limit 10
igp-ride list --sort distance --desc
igp-ride list --sort power --asc --limit 10
```

列出本地数据库中已有的活动。该命令不会连接 IGPSPORT。

参数：

- `--limit N`：最多显示 `N` 条活动。
- `--sort date|distance|time|speed|elev|power`：选择排序字段，默认是 `date`。
- `--asc`：升序排序。
- `--desc`：降序排序。

如果没有指定 `--asc` 或 `--desc`，默认使用降序。

### `show`

```bash
igp-ride show last
igp-ride show 123456
```

显示一条本地活动的详情。使用 `last` 查看最新活动，也可以传入 ride ID。

该命令不会连接 IGPSPORT。

## Intervals.icu

### `icu login`

```bash
igp-ride icu login
igp-ride icu login --api-key YOUR_API_KEY
```

保存 Intervals.icu API key。不传 `--api-key` 时会安全地交互输入。

参数：

- `--api-key API_KEY`：非交互式传入 API key。

### `icu logout`

```bash
igp-ride icu logout
igp-ride icu logout --yes
```

清除保存的 Intervals.icu API key 和本地 ICU 配置文件。该命令不会删除本地活动，也不会删除本地数据库中的 ICU 同步历史。

不加 `--yes` 时会要求确认，只有输入 `LOGOUT` 才会继续执行。

参数：

- `--yes`：跳过确认。

### `icu status`

```bash
igp-ride icu status
```

显示 Intervals.icu API key 是否已配置，并检查该 key 是否能通过 Intervals.icu 认证。

无参数。

### `icu sync`

```bash
igp-ride icu sync --dry-run
igp-ride icu sync
```

将本地已下载的 FIT 文件上传到 Intervals.icu。

同步时使用 `external_id=igp-<ride_id>`，因此重复执行时可以识别远端已存在的活动。之前同步失败的活动会在下一次 `igp-ride icu sync` 中自动重试。

参数：

- `--dry-run`：只显示将要同步的内容，不上传，也不修改本地同步状态。

## 配置与数据位置

`igp-ride` 使用当前平台对应的用户目录。

macOS 和 Linux 默认路径：

- 配置目录：`~/.config/igp-ride`
- Session 文件：`~/.config/igp-ride/session.json`
- ICU 配置文件：`~/.config/igp-ride/icu.json`
- 数据目录：`~/.local/share/igp-ride`
- SQLite 数据库：`~/.local/share/igp-ride/rides.db`
- FIT 文件目录：`~/.local/share/igp-ride/fit`
- 日志文件：`~/.local/share/igp-ride/logs/igp-ride.log`

Windows 路径由 `platformdirs` 解析：

- 配置目录：`%APPDATA%\igp-ride`
- Session 文件：`%APPDATA%\igp-ride\session.json`
- Session 数据文件：`%APPDATA%\igp-ride\session_data.json`
- ICU 配置文件：`%APPDATA%\igp-ride\icu.json`
- 数据目录：`%LOCALAPPDATA%\igp-ride`
- SQLite 数据库：`%LOCALAPPDATA%\igp-ride\rides.db`
- FIT 文件目录：`%LOCALAPPDATA%\igp-ride\fit`

## 环境变量

IGPSPORT：

- `IGP_USERNAME`：需要 IGPSPORT 凭据的命令会读取该用户名。
- `IGP_PASSWORD`：需要 IGPSPORT 凭据的命令会读取该密码。

Intervals.icu：

- `IGP_RIDE_ICU_API_KEY`：Intervals.icu API key。
- `INTERVALS_ICU_API_KEY`：备用 Intervals.icu API key 环境变量。
- `IGP_RIDE_ICU_ATHLETE_ID`：可选 athlete ID 覆盖值。
- `INTERVALS_ICU_ATHLETE_ID`：备用 athlete ID 环境变量。
- `IGP_RIDE_ICU_BASE_URL`：可选 Intervals.icu API base URL 覆盖值。

CLI 不暴露 athlete ID 或 base URL 参数。默认 Intervals.icu athlete 为 `0`，表示 API key 对应的当前用户。

## 退出码

- `0`：成功，或用户取消确认。
- `2`：配置错误或参数值错误。
- `3`：IGPSPORT 认证错误。
- `4`：网络错误。
- `5`：数据库错误。
- `6`：数据同步错误。
- `7`：文件错误。
- `8`：请求的活动不存在。
- `10`：`reset` 执行完成，但至少有一项删除失败。

## 开发检查

```bash
uv run pytest
uv run ruff check
uv run basedpyright
```

## License

MIT
