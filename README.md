# igp-ride

`igp-ride` 是一个面向 IGPSPORT 平台的轻量命令行工具，用于把骑行活动同步到本地 SQLite，并下载对应的 FIT 文件，方便后续查询、统计和备份。

## 功能概览

- 登录 IGPSPORT 账号并缓存本地会话
- 增量同步活动到本地 SQLite
- 全量拉取历史活动
- 下载或修复缺失、损坏的 FIT 文件
- 查看活动列表与活动详情
- 生成按月或按年的骑行统计
- 在 macOS 下以守护进程方式定时同步

## 安装

```bash
# main 分支
uv tool install git+https://github.com/YetYeti/igp-ride@main

# 使用 dev 分支最新代码
uv tool install git+https://github.com/YetYeti/igp-ride@dev

igp-ride --help
```

更新或在稳定版与 `dev` 分支之间切换时，给安装命令增加 `--upgrade` 即可。

## 快速开始

### 1. 登录

交互式登录：

```bash
igp-ride login
```

如果你在无交互环境中运行，可以通过环境变量传入凭据：

```bash
IGP_USERNAME=<你的用户名> IGP_PASSWORD=<你的密码> igp-ride login
```

说明：

- 该工具没有 `--password` 参数
- 默认会把密码写入系统 keyring
- Linux / macOS 会把会话数据写入系统 keyring
- Windows 会把会话数据写入本地会话文件
- 登录后会在本地保存用户名和会话时间戳

### 2. 同步活动

默认增量同步：

```bash
igp-ride update
```

全量同步历史活动：

```bash
igp-ride update --all
```

### 3. 查看活动

查看最近一次活动：

```bash
igp-ride show last
```

查看指定活动：

```bash
igp-ride show <ride_id>
```

### 4. 查看统计

按月统计：

```bash
igp-ride stats
```

按年统计：

```bash
igp-ride stats --by year
```

## 守护进程模式

在 macOS 下，`daemon start` 会安装并加载 `LaunchAgent`。加载后会先执行一轮同步，之后按 `--interval` 周期运行；重启并重新登录后会自动恢复。

Windows 当前支持 `login/logout/reset/update/list/show/stats`，`daemon start/stop/status` 暂不支持；如需前台执行一轮同步，可继续使用 `igp-ride daemon run --once`。

启动后台定时同步：

```bash
igp-ride daemon start --interval 30m
```

每次发现新活动后执行 hook：

```bash
igp-ride daemon start --interval 1h --hook "echo new rides"
```

查看守护进程状态：

```bash
igp-ride daemon status
```

停止守护进程：

```bash
igp-ride daemon stop
```

手动前台执行一轮守护进程同步：

```bash
igp-ride daemon run --once
```

## 数据存储位置

工具会按当前平台使用对应的配置、数据和日志目录。

Linux / macOS 默认使用 XDG 目录：

- 配置目录：`~/.config/igp-ride`
- 会话文件：`~/.config/igp-ride/session.json`
- 数据目录：`~/.local/share/igp-ride`
- SQLite 数据库：`~/.local/share/igp-ride/rides.db`
- FIT 文件目录：`~/.local/share/igp-ride/fit`
- 日志目录：`~/.local/share/igp-ride/logs`
- LaunchAgent：`~/Library/LaunchAgents/com.yetyeti.igp-ride.daemon.plist`

Windows 默认目录：

- 配置目录：`%APPDATA%\igp-ride`
- 会话文件：`%APPDATA%\igp-ride\session.json`
- 会话数据文件：`%APPDATA%\igp-ride\session_data.json`
- 数据目录：`%LOCALAPPDATA%\igp-ride`
- SQLite 数据库：`%LOCALAPPDATA%\igp-ride\rides.db`
- FIT 文件目录：`%LOCALAPPDATA%\igp-ride\fit`
- 日志目录：`%LOCALAPPDATA%\igp-ride\Logs`

## 认证与安全

- 默认站点为 `https://my.igpsport.com`
- 用户名和密码通过系统 keyring 保存
- Linux / macOS 会话数据通过系统 keyring 保存
- Windows 会话数据保存在 `%APPDATA%\igp-ride\session_data.json`
- `session.json` 不直接保存密码
- `logout` 只清理本地凭据和会话
- `reset` 会删除数据库、FIT 文件、凭据和会话，请谨慎使用

## License

MIT
