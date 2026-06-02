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

- Python 3.12 或更新版本
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

直接运行 `igp-ride` 会显示欢迎信息和 quick start。

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

首次登录时，该命令会交互输入用户名和密码，并把凭据加密保存到本地文件。已保存凭据后再次执行 `igp-ride login` 会复用已保存的账号密码重新登录。

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

全局参数需放在子命令前：

- `--format text|json`：选择输出格式，默认 `text`。JSON 模式下 stdout 只输出 JSON，进度和警告输出到 stderr。
- `--no-input`：禁止交互输入。缺少必要凭据或确认参数时直接失败。

示例：

```bash
igp-ride --format json list
igp-ride --no-input update
```

### `login`

```bash
igp-ride login
igp-ride login --username YOUR_USERNAME --password-stdin
```

登录 IGPSPORT，并保存本地凭据和 session 数据。

已保存账号后，`igp-ride login` 会复用已保存的 username/password。使用 `--username` 指定同一账号时也会复用已保存密码。

如果 `--username` 与已保存 username 不同，`igp-ride` 会把它视为切换账号：不会复用旧账号密码，必须通过 `--password-stdin`、`IGP_PASSWORD` 或交互输入提供新密码。新账号登录成功后才会覆盖本地凭据和 session；如果密码错误或网络失败，旧账号的本地状态会保留。

参数：

- `--username USERNAME`：指定 IGPSPORT 用户名。
- `--password-stdin`：从标准输入读取 IGPSPORT 密码，适合自动化和 agent 调用。

非交互示例：

```bash
printf '%s' "$IGP_PASSWORD" | igp-ride --no-input login --username "$IGP_USERNAME" --password-stdin
```

### `logout`

```bash
igp-ride logout
igp-ride logout --yes
```

清除本地 IGPSPORT 凭据和 session 数据。

不加 `--yes` 时会要求确认，只有输入 `LOGOUT` 才会继续执行。

参数：

- `--yes`：跳过确认。

### `status`

```bash
igp-ride status
```

显示 IGPSPORT 本地凭据是否存在、session 文件是否存在，并检查当前凭据/session 是否能通过 IGPSPORT 认证。

无参数。

### `reset`

```bash
igp-ride reset
igp-ride reset --yes
```

删除本地 `igp-ride` 数据，包括 SQLite 数据库、已下载 FIT 文件、IGPSPORT 凭据、session 数据和 Intervals.icu 配置。

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
igp-ride list --since 2026-03-01
igp-ride list --sort distance --desc
igp-ride list --sort power --asc --limit 10
```

列出本地数据库中已有的活动。该命令不会连接 IGPSPORT。

参数：

- `--limit N`：最多显示 `N` 条活动。
- `--since YYYY-MM-DD`：只显示该日期及之后的活动。
- `--sort date|distance|time|speed|elev|power`：选择排序字段，默认是 `date`。
- `--asc`：升序排序。
- `--desc`：降序排序。

如果没有指定 `--asc` 或 `--desc`，默认使用降序。

### `show`

```bash
igp-ride show last
igp-ride show 123456
```

显示一条本地活动的详情。使用 `last` 查看最新活动，也可以传入纯数字 ride ID。如果该活动有本地备注，详情中会显示 `Note`。

该命令不会连接 IGPSPORT。

### `note`

```bash
igp-ride note set last --text "今天腿感不错"
igp-ride note set 123456 --stdin
igp-ride note show last
igp-ride note clear 123456
```

管理本地活动备注。每条活动保留一条备注，`note set` 会覆盖已有备注。使用 `last` 表示最新活动，也可以传入纯数字 ride ID。

该命令只修改本地 SQLite 数据库，不会连接 IGPSPORT 或 Intervals.icu。备注会在下一次 `igp-ride icu sync` 时同步到 Intervals.icu 活动评论中。

参数：

- `--text TEXT`：直接传入备注文本。
- `--stdin`：从标准输入读取备注文本，适合自动化和 agent 调用。

非交互示例：

```bash
printf '%s' "今天腿感不错，后半程风大" | igp-ride note set last --stdin
igp-ride icu sync
```

## Intervals.icu

### `icu login`

```bash
igp-ride icu login
igp-ride icu login --api-key-stdin
```

保存 Intervals.icu API key。不传 `--api-key-stdin` 时会安全地交互输入。

参数：

- `--api-key-stdin`：从标准输入读取 API key，避免 key 出现在 shell history 或进程参数中。

非交互示例：

```bash
printf '%s' "$IGP_RIDE_ICU_API_KEY" | igp-ride --no-input icu login --api-key-stdin
```

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
igp-ride icu sync --force
```

将本地已下载的 FIT 文件上传到 Intervals.icu，并同步待同步的本地活动备注。

同步时使用 `external_id=igp-<ride_id>`，因此重复执行时可以识别远端已存在的活动。之前同步失败的活动会在下一次 `igp-ride icu sync` 中自动重试。

如果活动已经同步到 Intervals.icu，之后新增或修改本地备注，再执行 `igp-ride icu sync` 也会把备注追加到对应的 Intervals.icu 活动评论中。每条活动本地只保留一条备注；修改备注后会在下次同步时追加一条新的远端评论，不会删除或编辑旧评论。

参数：

- `--dry-run`：只显示将要同步的内容，不上传，也不修改本地同步状态。
- `--force`：忽略本地 ICU 同步状态，重新按 `external_id=igp-<ride_id>` 检查远端；远端已存在则标记为已同步，远端不存在才重新上传。

## 配置与数据位置

`igp-ride` 使用当前平台对应的用户目录，主要分为三类：

- 配置目录：保存加密的登录凭证、session 数据、Intervals.icu 配置等。
- 数据目录：保存本地 SQLite 数据库和已下载的 FIT 文件。
- 日志目录：保存运行日志。

凭证安全说明：

- 密码和 Intervals.icu API Key 使用 Fernet 对称加密（基于 `cryptography` 库）存储在本地文件中。
- 加密密钥由机器信息（主机名 + 用户名）通过 PBKDF2 派生，无需额外管理密钥。
- Session 数据（cookies/tokens）以明文 JSON 存储，文件权限 `0o600`，token 过期后自动重新认证。

macOS 和 Linux 默认使用：

- 配置目录：`~/.config/igp-ride`
- 数据目录：`~/.local/share/igp-ride`
- 日志目录：`~/.local/share/igp-ride/logs`

Windows 路径由 `platformdirs` 解析，通常位于 `%APPDATA%`、`%LOCALAPPDATA%` 下的 `igp-ride` 目录。

## 环境变量

IGPSPORT：

- `IGP_USERNAME`：需要 IGPSPORT 凭据的命令会读取该用户名。
- `IGP_PASSWORD`：需要 IGPSPORT 凭据的命令会读取该密码。

Intervals.icu：

- `IGP_RIDE_ICU_API_KEY`：Intervals.icu API key。
- `INTERVALS_ICU_API_KEY`：备用 Intervals.icu API key 环境变量。

Intervals.icu 同步默认使用 API key 对应的当前用户。

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

## License

MIT
