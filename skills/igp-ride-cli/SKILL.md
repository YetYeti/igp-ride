---
name: igp-ride-cli
description: 使用 igp-ride 命令行安装、登录并同步 IGPSPORT/iGPSPORT 骑行记录到本地 SQLite，同时下载或修复 FIT 文件、查看活动详情、统计骑行数据、启停后台同步守护进程。只要用户提到 IGPSPORT 骑行记录同步、FIT 导出、本地备份骑行活动、查看最近一次骑行、月度/年度骑行统计、后台自动同步或守护进程，就应该使用这个技能，即使用户没有明确说“igp-ride”。
---

# igp-ride CLI 技能

帮助代理正确安装并使用当前仓库提供的 `igp-ride` 命令行工具，完成 IGPSPORT 骑行活动同步、本地查询和后台轮询。

## 这个技能的定位

这个技能不是给最终用户阅读的产品说明，而是给代理执行任务时使用的操作说明。

区分方式：

- `README.md` 面向 GitHub 上的人类读者，负责介绍项目、安装方法和常用命令
- 这个 `SKILL.md` 面向会实际执行命令的代理，重点是触发时机、命令选择、非交互执行、风险边界和结果汇报方式

当用户只是想了解项目、看安装步骤或浏览功能，优先参考 `README.md`。
当用户要求代理实际去安装、登录、同步、修复 FIT、查看活动、统计数据或管理守护进程时，优先遵循本技能。

## 适用场景

- 安装或验证 `igp-ride` CLI
- 登录 IGPSPORT 账号并保存本地凭据
- 同步最新骑行记录到本地 SQLite
- 下载缺失的 FIT 文件，或修复无效 FIT 文件
- 查看最近一次或指定活动的详细指标
- 输出按月或按年的骑行统计
- 开启、查看或停止后台自动同步守护进程
- 排查认证失败、网络失败、缺失本地数据等问题

## 平台支持边界

- macOS：完整支持 `login`、`logout`、`reset`、`update`、`list`、`show`、`stats`、`daemon start/stop/status/run`
- Windows：支持 `login`、`logout`、`reset`、`update`、`list`、`show`、`stats`、`daemon run --once`
- Windows 当前不支持 `daemon start`、`daemon stop`、`daemon status`
- macOS 的后台定时同步由 `LaunchAgent` 托管；Windows 当前只有前台单次执行入口，不要假设存在系统级后台调度

## 安装与验证

优先在当前仓库根目录安装，不要默认用 `uv run` 代替正式工具安装。

```bash
uv tool install --editable .
igp-ride --help
```

已知前提：

- Python 版本要求为 `>=3.14`
- 依赖包括 `requests`、`keyring`、`fitparse`
- 命令入口为 `igp-ride`
- 基础站点固定为 `https://my.igpsport.com`，不要引导用户通过 `IGP_BASE_URL` 覆盖它

如果用户明确要从源码仓库试用最新版本，继续使用 `uv tool install --editable .`。如果只是验证当前仓库功能，安装后先运行 `igp-ride --help`，确认子命令存在。

## 运行时数据位置

默认使用当前平台对应的配置、数据和日志目录，不要自行发明其他目录。

macOS 默认路径：

- 配置目录：`~/.config/igp-ride`
- 会话文件：`~/.config/igp-ride/session.json`
- 数据目录：`~/.local/share/igp-ride`
- SQLite 数据库：`~/.local/share/igp-ride/rides.db`
- FIT 文件目录：`~/.local/share/igp-ride/fit`
- 普通日志：`~/.local/share/igp-ride/logs/igp-ride.log`
- 守护进程日志：`~/.local/share/igp-ride/logs/daemon.log`
- macOS LaunchAgent：`~/Library/LaunchAgents/com.yetyeti.igp-ride.daemon.plist`

Windows 默认路径：

- 配置目录：`%APPDATA%\igp-ride`
- 会话文件：`%APPDATA%\igp-ride\session.json`
- 会话数据文件：`%APPDATA%\igp-ride\session_data.json`
- 数据目录：`%LOCALAPPDATA%\igp-ride`
- SQLite 数据库：`%LOCALAPPDATA%\igp-ride\rides.db`
- FIT 文件目录：`%LOCALAPPDATA%\igp-ride\fit`
- 普通日志：`%LOCALAPPDATA%\igp-ride\Logs\igp-ride.log`
- 守护进程日志：`%LOCALAPPDATA%\igp-ride\Logs\daemon.log`

账号密码会写入系统 keyring。macOS 会话令牌写入系统 keyring；Windows 会话令牌写入 `session_data.json`。`session.json` 只保存用户名和保存时间。

## 命令选择

### 1. 首次登录

```bash
igp-ride login
igp-ride login --username <用户名>
IGP_USERNAME=<用户名> IGP_PASSWORD=<密码> igp-ride login
IGP_PASSWORD=<密码> igp-ride login --username <用户名>
```

适用场景：

- 用户首次配置工具
- 认证失效后重新登录
- 想切换账号

执行方式说明：

- `igp-ride login` 默认是交互式命令，会提示输入用户名和密码
- 如果代理当前拿到的是可交互 TTY，会话里可以直接输入密码
- 如果当前执行环境不适合交互输入，优先通过环境变量提供凭据，再执行 `igp-ride login`
- 这个 CLI 没有 `--password` 参数，不要编造不存在的命令行选项
- 如果只提供了 `--username`，密码仍然会通过安全提示输入；如果同时提供了 `IGP_PASSWORD`，则不会再提示输入密码
- 在 Windows 上，登录成功后会把会话数据写入 `%APPDATA%\\igp-ride\\session_data.json`，不要再假设它保存在系统 keyring

推荐规则：

- 能安全交互时，用 `igp-ride login` 或 `igp-ride login --username <用户名>`
- 自动化、无 TTY、或用户明确要求非交互执行时，用环境变量方式
- 回答用户时不要回显密码；如果需要展示命令，优先把密码写成占位符

登录成功后，下一步通常是 `igp-ride update`。

### 2. 同步活动

```bash
igp-ride update
igp-ride update --all
igp-ride update --repair
igp-ride update --progress plain
```

命令选择规则：

- 默认用 `igp-ride update` 做增量同步
- 只有用户明确要求“全量重拉历史数据”或怀疑本地历史严重缺失时，才用 `--all`
- 只有本地 FIT 缺失或损坏时，才用 `--repair`
- 需要在非交互环境中稳定读取进度时，用 `--progress plain`

同步逻辑要点：

- 增量同步会根据 `last_sync_time` 计算抓取页大小，并只请求 1 页远端活动
- 全量同步会以 `page_size=200` 抓取历史数据，最多 1000 页
- 已存在且本地 FIT 正常的活动会被跳过
- 新下载的 FIT 会被解析并补充功率、心率、踏频、速度、TSS 等指标

### 3. 列表与详情

```bash
igp-ride list
igp-ride list --limit 20
igp-ride list --sort distance --desc
igp-ride list --sort power --asc --limit 10
igp-ride list --update

igp-ride show last
igp-ride show <ride_id>
igp-ride show last --update
```

使用规则：

- 用户只想看本地已有数据，用 `list` / `show`
- 用户强调“先同步最新再看”，用 `--update` 或先执行 `igp-ride update`
- `list --update` 和 `show --update` 都要求本地已有可用登录凭据
- `list` 支持 `--sort date|distance|time|speed|elev|power`
- `list` 支持 `--asc` 和 `--desc`；默认等价于 `--sort date --desc`
- `--limit` 作用在排序后的结果上
- `power` 排序时，没有功率数据的活动会排在最后
- “最新一条活动”优先使用 `igp-ride show last`
- 需要可浏览的总览时优先 `list`，需要完整指标时优先 `show`

### 4. 统计

```bash
igp-ride stats
igp-ride stats --by year
igp-ride stats --year 2026
igp-ride stats --type 户外骑行
igp-ride stats --update
```

适用场景：

- 按月或按年汇总骑行次数、距离、时长、平均速度、平均功率、爬升
- 按年份过滤
- 按活动标题过滤，例如 `户外骑行`
- 如果使用 `--update`，同样要求本地已有可用登录凭据

### 5. 守护进程

```bash
igp-ride daemon start --interval 30m
igp-ride daemon start --interval 1h --hook "<shell-command>"
igp-ride daemon status
igp-ride daemon stop
igp-ride daemon run --once
```

使用规则：

- 在 macOS 下，`daemon start` / `daemon stop` / `daemon status` 负责管理 `LaunchAgent`
- `daemon start` 会安装并加载 `LaunchAgent`，加载后先执行一轮同步，之后按 `--interval` 周期运行；重新登录后会自动恢复
- `daemon run --once` 是 `LaunchAgent` 实际调用的一次同步入口，也可用于前台手动跑一轮并返回结构化结果
- 用户要检查运行状态、最近一次同步结果、日志位置时，用 `daemon status`
- `--interval` 支持 `30m`、`1h`、`45` 这类写法；纯数字默认按分钟解释
- 只有检测到新活动时，`--hook` 才会触发
- Windows 当前不支持 `daemon start` / `daemon stop` / `daemon status`
- Windows 上如需执行一轮前台同步，可继续使用 `igp-ride daemon run --once`
- Windows 上不要建议用户配置 `LaunchAgent`、检查 plist，或查找 `daemon status` 输出

hook 环境变量包括：

- `IGP_RIDE_REMOTE_FETCHED`
- `IGP_RIDE_NEW_ACTIVITIES`
- `IGP_RIDE_UPDATED_ACTIVITIES`
- `IGP_RIDE_ACTIVITIES_SKIPPED`
- `IGP_RIDE_FIT_FILES_FAILED`
- `IGP_RIDE_INTERVAL_SECONDS`

## 破坏性操作边界

```bash
igp-ride logout
igp-ride reset
igp-ride reset --yes
```

区分规则：

- `logout` 只清理本地凭据和会话
- `reset` 会删除数据库、FIT 文件、凭据和会话，属于破坏性操作

除非用户已经明确授权，否则不要主动执行 `igp-ride reset --yes`。用户只说“重新登录”“清掉登录态”时，优先用 `logout`，不要升级成 `reset`。

## 结果解读

CLI 输出是结构化文本，优先提炼这些字段：

- 标题块：`== Update ==`、`== Activity Details ==`
- 结果字段：`Result: success|error|partial|no-op`
- 汇总字段：`Summary: remote=... new=... updated=... skipped=... fit_failed=...`
- 下一步建议：`Next: igp-ride list`

常见退出码：

- `0`：成功
- `2`：配置错误或参数错误
- `3`：认证失败
- `4`：网络错误
- `5`：数据库错误
- `6`：同步或 FIT 下载错误
- `7`：文件错误
- `8`：活动不存在
- `9`：守护进程错误
- `10`：`reset` 部分失败

如果命令失败，先根据退出码和错误文案给出下一步，例如重新登录、检查网络、查看日志，避免只转述报错。

## 推荐工作流

### 首次使用

1. 在仓库根目录执行 `uv tool install --editable .`
2. 运行 `igp-ride --help` 验证安装
3. 运行 `igp-ride login`
4. 运行 `igp-ride update`
5. 运行 `igp-ride list` 或 `igp-ride show last`

### 日常同步

1. 先判断用户是要最新数据还是本地只读查询
2. 需要最新数据时执行 `igp-ride update`
3. 再用 `list`、`show`、`stats` 输出结果
4. 回答时优先总结新增/更新/跳过/失败数量

### 修复缺失 FIT

1. 仅在用户提到“缺少 FIT”“FIT 损坏”“历史记录有条目但没有文件”时用 `igp-ride update --repair`
2. 说明它只重试缺失或无效 FIT，不会强制全量重拉所有活动

## 回答要求

协助用户时，尽量按这个顺序组织回复：

1. 说明将执行的命令及原因
2. 执行命令并读取结构化输出
3. 用简洁中文总结结果
4. 如果合适，给出下一步命令

不要默认直接读取 SQLite 或手工改写会话文件来替代 CLI，除非用户明确要求做底层排查。

## 示例触发语句

- “帮我把 IGPSPORT 的骑行记录同步到本地”
- “用这个项目装一下命令行工具，然后看看最近一次骑行”
- “我想把缺失的 FIT 文件补下来”
- “每 30 分钟自动同步一次，有新活动就执行脚本”
- “按月份统计我今年的户外骑行”
