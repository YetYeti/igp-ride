---
name: igp-ride
description: 使用 igp-ride 命令行工具同步 IGPSPORT 骑行活动到本地 SQLite 数据库，下载 FIT 文件，并可选择上传到 Intervals.icu。
---

# igp-ride Skill

## 适用场景

当用户需要管理 IGPSPORT 骑行活动数据时，使用本 Skill。

适合处理的问题包括：

- 登录或退出 IGPSPORT 账号
- 同步 IGPSPORT 骑行活动
- 下载活动对应的 FIT 文件
- 查看本地活动列表
- 查看单条活动详情
- 将本地 FIT 文件上传到 Intervals.icu
- 预览 Intervals.icu 上传内容
- 检查 Intervals.icu API key 状态
- 清空本地 igp-ride 数据
- 排查 igp-ride 常见命令、路径、环境变量和退出码问题

## 工具概览

`igp-ride` 是一个命令行工具，用于：

1. 从 IGPSPORT 拉取骑行活动；
2. 将活动元数据保存到本地 SQLite 数据库；
3. 下载活动对应的 FIT 文件；
4. 可选地将 FIT 文件上传到 Intervals.icu。

它默认采用增量同步方式，重复执行时会自动补齐缺失或无效的 FIT 文件，并会自动重试上次失败的 Intervals.icu 上传任务。

## 环境要求

使用前确认环境满足：

- Python 3.14 或更新版本
- IGPSPORT 账号
- 如需上传到 Intervals.icu，需要 Intervals.icu API key

## 安装方式

### 从 GitHub main 分支安装

```bash
uv tool install git+https://github.com/YetYeti/igp-ride@main


### 升级已安装版本

```bash
uv tool install --upgrade git+https://github.com/YetYeti/igp-ride@main
```

### 检查命令是否可用

```bash
igp-ride --help
```

### 本地开发安装

在项目仓库目录中执行：

```bash
uv tool install .
```

或者在开发环境中直接运行：

```bash
uv sync
uv run igp-ride --help
```

## 基本使用流程

### 1. 登录 IGPSPORT

```bash
igp-ride login
```

该命令会交互输入 IGPSPORT 用户名和密码，并将凭据加密保存到本地文件。

也可以通过环境变量提供凭据：

```bash
export IGP_USERNAME="your_username"
export IGP_PASSWORD="your_password"
```

### 2. 同步活动和 FIT 文件

```bash
igp-ride update
```

默认执行增量同步，只同步新增或需要修复的数据。

如果需要强制全量刷新：

```bash
igp-ride update --all
```

### 3. 查看本地活动列表

```bash
igp-ride list
```

常用示例：

```bash
igp-ride list --limit 10
igp-ride list --sort distance --desc
igp-ride list --sort power --asc --limit 10
```

### 4. 查看单条活动详情

查看最新活动：

```bash
igp-ride show last
```

按 IGPSPORT ride ID 查看指定活动：

```bash
igp-ride show 123456
```

## IGPSPORT 账号相关命令

### 登录

```bash
igp-ride login
```

用途：

* 登录 IGPSPORT；
* 保存本地凭据；
* 保存 session 数据。

无参数。

### 退出登录

```bash
igp-ride logout
```

该命令会清除本地 IGPSPORT 凭据和 session 数据。

默认需要确认，用户必须输入：

```text
LOGOUT
```

跳过确认：

```bash
igp-ride logout --yes
```

## 本地数据管理

### 重置全部本地数据

```bash
igp-ride reset
```

该命令会删除：

* 本地 SQLite 数据库
* 已下载的 FIT 文件
* IGPSPORT 凭据
* session 数据

默认需要确认，用户必须输入：

```text
RESET
```

跳过确认：

```bash
igp-ride reset --yes
```

注意：这是危险操作。除非用户明确要求清空本地数据，否则不要主动建议执行。

## 同步命令

### 增量同步

```bash
igp-ride update
```

用途：

* 从 IGPSPORT 拉取活动；
* 写入本地 SQLite 数据库；
* 下载 FIT 文件；
* 自动修复缺失或无效的 FIT 文件。

默认行为是增量同步。

### 全量同步

```bash
igp-ride update --all
```

用途：

* 强制刷新所有可用活动；
* 适合本地数据异常、缺失较多、需要重新扫描远端数据时使用。

## 查看活动

### 列出本地活动

```bash
igp-ride list
```

该命令只读取本地数据库，不会连接 IGPSPORT。

可用参数：

```bash
--limit N
--sort date|distance|time|speed|elev|power
--asc
--desc
```

默认排序字段是：

```text
date
```

如果没有指定 `--asc` 或 `--desc`，默认使用降序。

示例：

```bash
igp-ride list --limit 20
igp-ride list --sort distance --desc
igp-ride list --sort power --asc --limit 10
```

### 查看活动详情

```bash
igp-ride show last
igp-ride show 123456
```

说明：

* `last` 表示最新活动；
* 数字参数表示 IGPSPORT ride ID；
* 该命令只读取本地数据库，不会连接 IGPSPORT。

如果活动不存在，程序会返回退出码 `8`。

## Intervals.icu 相关命令

### 登录 Intervals.icu

交互式输入 API key：

```bash
igp-ride icu login
```

非交互式传入 API key：

```bash
igp-ride icu login --api-key YOUR_API_KEY
```

也可以使用环境变量：

```bash
export IGP_RIDE_ICU_API_KEY="your_api_key"
```

备用环境变量：

```bash
export INTERVALS_ICU_API_KEY="your_api_key"
```

### 退出 Intervals.icu

```bash
igp-ride icu logout
```

该命令会清除：

* 保存的 Intervals.icu API key
* 本地 ICU 配置文件

不会删除：

* 本地活动
* 本地 SQLite 数据库中的 ICU 同步历史

默认需要确认，用户必须输入：

```text
LOGOUT
```

跳过确认：

```bash
igp-ride icu logout --yes
```

### 检查 Intervals.icu 状态

```bash
igp-ride icu status
```

用途：

* 显示 Intervals.icu API key 是否已配置；
* 检查该 key 是否能通过 Intervals.icu 认证。

### 预览将要上传的活动

```bash
igp-ride icu sync --dry-run
```

说明：

* 只显示将要同步的内容；
* 不上传；
* 不修改本地同步状态。

### 上传 FIT 文件到 Intervals.icu

```bash
igp-ride icu sync
```

同步规则：

* 上传本地已下载的 FIT 文件；
* 使用 `external_id=igp-<ride_id>`；
* 重复执行时可以识别远端已存在的活动；
* 之前同步失败的活动会在下一次同步时自动重试。

## 配置与数据目录

`igp-ride` 使用平台对应的用户目录，主要分为：

* 配置目录
* 数据目录
* 日志目录

### 凭证安全

* 密码和 Intervals.icu API Key 使用 Fernet 对称加密存储在本地文件中
* 加密密钥由机器信息（主机名 + 用户名）通过 PBKDF2 派生
* Session 数据以明文 JSON 存储，文件权限 `0o600`，token 过期后自动重新认证

### macOS / Linux 默认路径

配置目录：

```bash
~/.config/igp-ride
```

数据目录：

```bash
~/.local/share/igp-ride
```

日志目录：

```bash
~/.local/share/igp-ride/logs
```

### Windows 默认路径

Windows 路径由 `platformdirs` 解析，通常位于：

```text
%APPDATA%
%LOCALAPPDATA%
```

下的 `igp-ride` 目录。

## 环境变量

### IGPSPORT

```bash
IGP_USERNAME
IGP_PASSWORD
```

说明：

* `IGP_USERNAME`：需要 IGPSPORT 凭据的命令会读取该用户名；
* `IGP_PASSWORD`：需要 IGPSPORT 凭据的命令会读取该密码。

### Intervals.icu

```bash
IGP_RIDE_ICU_API_KEY
INTERVALS_ICU_API_KEY
```

说明：

* `IGP_RIDE_ICU_API_KEY`：Intervals.icu API key；
* `INTERVALS_ICU_API_KEY`：备用 Intervals.icu API key 环境变量。

Intervals.icu 同步默认使用 API key 对应的当前用户。

## 退出码

当命令失败时，根据退出码判断问题类型：

```text
0   成功，或用户取消确认
2   配置错误或参数值错误
3   IGPSPORT 认证错误
4   网络错误
5   数据库错误
6   数据同步错误
7   文件错误
8   请求的活动不存在
10  reset 执行完成，但至少有一项删除失败
```

## 常见任务处理方式

### 用户想第一次使用

推荐流程：

```bash
igp-ride login
igp-ride update
igp-ride list
igp-ride show last
```

### 用户想重新同步新增活动

使用：

```bash
igp-ride update
```

不要默认建议 `--all`，因为普通情况下增量同步已经足够。

### 用户说活动缺 FIT 文件

优先建议：

```bash
igp-ride update
```

因为 update 会自动修复缺失或无效的 FIT 文件。

如果问题仍然存在，再考虑：

```bash
igp-ride update --all
```

### 用户想上传到 Intervals.icu

推荐流程：

```bash
igp-ride icu login
igp-ride icu status
igp-ride icu sync --dry-run
igp-ride icu sync
```

### 用户只想预览，不想上传

使用：

```bash
igp-ride icu sync --dry-run
```

### 用户想清除 IGPSPORT 登录状态

使用：

```bash
igp-ride logout
```

如用户明确要求跳过确认：

```bash
igp-ride logout --yes
```

### 用户想清除 Intervals.icu 配置

使用：

```bash
igp-ride icu logout
```

如用户明确要求跳过确认：

```bash
igp-ride icu logout --yes
```

### 用户想彻底删除本地数据

只有在用户明确要求时才使用：

```bash
igp-ride reset
```

如用户明确要求跳过确认：

```bash
igp-ride reset --yes
```

## 操作原则

* 优先使用增量同步：`igp-ride update`
* 只有在用户明确需要全量刷新时，才使用：`igp-ride update --all`
* 查看类命令 `list` 和 `show` 只读取本地数据库，不会连接 IGPSPORT
* Intervals.icu 上传前，优先建议用户先执行 `--dry-run`
* 对 `reset`、`logout`、`icu logout` 等破坏性或清理类操作，要提醒用户影响范围
* 不要直接要求用户删除配置目录或数据库文件，除非 CLI 命令无法解决问题
* 遇到错误时，优先根据退出码判断问题类型
