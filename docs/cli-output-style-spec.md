## CLI 输出规范

这份文档约束 `igp-ride` 当前公开命令的输出风格。目标是让人类扫读更快，也让自动化解析更稳定。

### 当前公开命令

```bash
igp-ride login
igp-ride logout [--yes]
igp-ride reset [--yes]
igp-ride update [--all]
igp-ride list [--limit N] [--sort date|distance|time|speed|elev|power] [--asc | --desc]
igp-ride show ACTIVITY_ID|last

igp-ride icu login [--api-key API_KEY]
igp-ride icu logout [--yes]
igp-ride icu status
igp-ride icu sync [--dry-run]
```

### 标准结构

每条命令按需使用这些区块，顺序固定：

1. 标题
2. 字段区
3. 摘要区
4. 表格区
5. 警告区
6. 提示区

标题格式固定：

```text
== <Title> ==
```

当前标题：

- `== Login ==`
- `== Logout ==`
- `== Reset ==`
- `== Update ==`
- `== Activity List ==`
- `== Activity Details ==`
- `== ICU Login ==`
- `== ICU Logout ==`
- `== ICU Status ==`
- `== ICU Sync ==`

### 字段

字段统一使用：

```text
Label: Value
```

常用字段：

- `Result`
- `Mode`
- `Account`
- `Path`
- `Count`
- `Limit`
- `Logged In`
- `Authenticated`
- `Remote Athlete ID`
- `Name`

布尔值统一输出为 `yes` 或 `no`。

### 摘要

`Summary` 用于一行计数摘要：

```text
Summary: key=value key=value ...
```

`update` 摘要键顺序：

```text
Summary: remote=57 new=1 updated=3 skipped=53 fit_failed=0
```

`reset` 摘要键顺序：

```text
Summary: deleted=3 not_found=1 failed=0
```

`icu sync` 摘要键顺序：

```text
Summary: candidates=3 uploaded=2 already_remote=1 skipped=0 failed=0 dry_run=no
```

### 表格

`list` 保留表格输出，表头稳定：

```text
RIDE_ID    DATE        DISTANCE     TIME     AVG_SPD       ELEV   AVG_PWR   TITLE
```

`show` 使用字段输出，不使用表格。

### 确认类命令

危险或清理类命令默认需要确认：

- `logout` 需要输入 `LOGOUT`
- `icu logout` 需要输入 `LOGOUT`
- `reset` 需要输入 `RESET`

对应的 `--yes` 用于跳过确认。
