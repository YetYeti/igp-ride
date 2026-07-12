# IGPSPORT 接口变更计划

日期：2026-05-09
分支：`codex/igpsport-api-update-plan`
基线分支：`dev`

## 背景

当前 CLI 仍在使用 IGPSPORT 旧版 Web 站点接口：

- `POST https://my.igpsport.com/Auth/Login`
- `GET https://my.igpsport.com/Activity/ActivityList`
- 通过 `loginTicket` 和 `loginToken` 从 Cookie 中发现登录会话

2026-05-09 的手动验证结果显示，旧版 HTTPS 主机在本地环境中会在 TLS 握手阶段失败。旧版 HTTP 入口访问 `/Auth/Login` 返回 IIS 404。

较新的开源 IGPSPORT 集成项目已经改用当前服务接口：

- `https://prod.zh.igpsport.com/service/`

本次验证只使用本机已保存的凭据确认状态码和响应结构。本文档没有记录密码、access token 或骑行详情。

## 已验证的新接口

### 登录

接口：

```text
POST https://prod.zh.igpsport.com/service/auth/account/login
Content-Type: application/json
```

请求体：

```json
{
  "appId": "igpsport-web",
  "username": "<username>",
  "password": "<password>"
}
```

观察到的成功响应结构：

```json
{
  "code": 0,
  "message": "",
  "data": {
    "access_token": "...",
    "refresh_token": "...",
    "expires_in": 604800
  }
}
```

观察到的密码错误响应：

```json
{
  "code": 1002,
  "message": "Password error"
}
```

验证时，JSON 登录接口不需要验证码。验证码出现在浏览器 OAuth 登录页，不在这个 service 登录接口上。

### 活动列表

接口：

```text
GET https://prod.zh.igpsport.com/service/web-gateway/web-analyze/activity/queryMyActivity
Authorization: Bearer <access_token>
```

公开项目使用的查询参数：

```text
pageNo=1
pageSize=20
reqType=0
sort=1
```

观察到的成功响应结构：

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "rows": [],
    "totalPage": 160,
    "totalRows": 160,
    "pageNo": 1,
    "pageSize": 1
  }
}
```

说明：

- `running_page` 使用 `reqType=0` 获取 FIT 记录。
- 公开代码显示 `reqType=1` 可能对应 GPX，`reqType=2` 可能对应 TCX；当前项目只下载 FIT，因此第一阶段只需要 `reqType=0`。
- 分页结构从旧版 `pageIndex`/`item`/`total` 变为 `pageNo`/`data.rows`/`data.totalRows`。

### 活动详情

接口：

```text
GET https://prod.zh.igpsport.com/service/web-gateway/web-analyze/activity/queryActivityDetail/{rideId}
Authorization: Bearer <access_token>
```

真实 ride ID 验证时返回 `code=0` 和 `message=success`。当前代码的最小迁移不一定需要这个接口，因为活动记录主要通过下载后的 FIT 文件补全；如果列表行缺少足够元数据，可以再接入详情接口。

### FIT 下载地址

接口：

```text
GET https://prod.zh.igpsport.com/service/web-gateway/web-analyze/activity/getDownloadUrl/{rideId}
Authorization: Bearer <access_token>
```

真实 ride ID 验证时返回 `code=0`、`message=success`，并且 `data` 是 HTTPS 下载 URL。当前项目已经调用这个新接口，但它依赖旧登录流程来设置 Authorization header。

## 已参考的外部实现

- `yihong0618/running_page`：
  `run_page/igpsport_sync.py` 使用 `auth/account/login`、`queryMyActivity` 和 `getDownloadUrl`。
- `NenoSann/igpsport_sync`：
  Go 版实现，端点常量和 token 登录流程与 `running_page` 一致。
- Greasy Fork 脚本 `iGPSPORT运动记录下载助手`：
  在 `https://app.zh.igpsport.com/sport/history/list` 页面中从 `localStorage["persist:redux-state"]` 读取 `global.token`，然后调用 `queryMyActivity`、`queryActivityDetail` 和 `getDownloadUrl`。
- 较旧的 `igpsport2xingzhe-java`：
  仍在使用 `my.igpsport.com/Auth/Login`，与当前项目一致，应视为旧方案。

## 代码影响排查

### `src/igp_ride/config.py`

当前依赖：

- `DEFAULT_BASE_URL` 是 `https://my.igpsport.com`。
- `AppConfig.load()` 有意忽略 `IGP_BASE_URL`。
- session 存储目前保存通用的 `cookies` 和 `authorization`。

需要修改：

- 将默认 service base URL 改为 `https://prod.zh.igpsport.com/service`。
- 考虑命名或文档说明：这里是 service API base，不再是旧 Web host。
- 除非明确新增调试开关，否则继续忽略 `IGP_BASE_URL`。
- 扩展 session data，支持保存 token 元数据：`access_token`、`refresh_token`、`expires_at` 或 `expires_in`。
- 尽量保留对已有 `authorization` 字段的读取兼容。

### `src/igp_ride/client.py`

当前依赖：

- `login()` 向 `{base_url}/Auth/Login` 提交 form data。
- 登录成功依赖 `Set-Cookie` 中包含 `loginTicket`。
- 从 `loginToken` Cookie 中提取 Authorization。
- `get_activity_page()` 调用 `{base_url}/Activity/ActivityList`。
- 列表解析依赖顶层 `item` 和 `total`。
- `download_fit_file()` 已经使用新的 `getDownloadUrl/{ride_id}` host。
- `_load_session()` 恢复旧 cookie 状态和 `authorization`。
- `_save_session()` 保存 cookies 和 Authorization header。

需要修改：

- 将登录替换为 JSON POST `{base_url}/auth/account/login`。
- 同时校验 HTTP 状态和业务响应：`code == 0` 且 `data.access_token` 存在。
- 登录后设置 `Authorization: Bearer <access_token>`。
- 将 token 元数据保存到 keyring/session data，优先不再保存 cookies。
- 更新 `_load_session()`，恢复 bearer token 元数据，并从有效 token 判断 `_authenticated`。
- session 过期判断从固定 12 小时改为优先使用 token 过期时间。已观察到的 `expires_in` 是 604800 秒，应预留少量安全余量。
- 将 `get_activity_page()` 改为调用 `web-gateway/web-analyze/activity/queryMyActivity`。
- 请求参数改为 `pageNo`、`pageSize`、`reqType=0`、`sort=1`。
- 解析 `data.rows` 和 `data.totalRows`。
- 在返回前规范化 row 字段，或者同步更新下游代码来消费新的 lower camelCase 字段。
- 即使 HTTP 状态为 200，只要 IGPSPORT 业务响应 `code != 0`，也要给出明确错误。

### `src/igp_ride/service.py`

当前依赖：

- 同步和增量边界逻辑调用 `client.get_activity_page()`。
- 活动 ID 读取 `RideId`。
- 构建活动时使用旧字段：`RideId`、`MemberId`、`Title`、`TotalAscent`、`RideDistance`。
- `_parse_start_time()` 已经同时检查大写字段和 lower camelCase 字段。

需要修改：

- 决定由 `client.get_activity_page()` 将新 rows 规范化为旧字段，还是让 service 同时兼容两套 schema。
- 推荐最小改法：在 client 层规范化，尽量保持 service 逻辑稳定。
- 如果不在 client 层规范化，则需要更新这些 service 读取点：
  - `RideId` -> `rideId`
  - `MemberId` -> `memberId`
  - `Title` -> `title`
  - `TotalAscent` -> `totalAscent`，或继续依赖 FIT 解析
  - `RideDistance` -> `rideDistance`
- 增量同步里的 page ID 提取也要改为读取规范化 ID 或同时兼容两种 key。
- 保留 FIT 优先解析策略，降低对列表/详情字段完整性的依赖。

### `src/igp_ride/cli.py`

当前依赖：

- `login` 命令输出只假设保存了 session 文件路径，不直接依赖具体接口。
- 错误处理已经区分网络错误和认证错误。

需要修改：

- 最小迁移不需要改变命令形态。
- 改进认证失败提示，明确展示 IGPSPORT 业务错误，例如 `Password error`。
- 保持现有输出格式稳定，避免破坏 CLI 测试。

### `src/igp_ride/daemon.py`

当前依赖：

- 使用 `AppConfig` 和 `RideSyncService`。
- 未发现直接引用接口地址。

需要修改：

- 预计不需要直接改动。
- daemon 会通过 service/client 自动继承新的 token 登录和列表接口。

### `README.md`

当前依赖：

- 文档中默认站点仍写为 `https://my.igpsport.com`。
- 登录示例概念上仍成立，但没有说明实际 service API。

需要修改：

- 将旧 host 描述替换为 `https://prod.zh.igpsport.com/service`。
- 说明 CLI 使用 IGPSPORT service token API，并将 bearer session 数据保存到 keyring/DPAPI 保护的 session store。
- 不在命令示例中暴露 token 或密码，沿用现有环境变量示例即可。

### 测试

需要更新或新增的文件：

- `tests/test_client.py`
- `tests/test_config.py`
- `tests/test_service.py`
- `tests/test_cli.py`

具体测试项：

- 新增 JSON token 登录成功测试。
- 新增登录业务错误测试：`code != 0`。
- 新增登录响应结构异常测试：缺少 `access_token`。
- 更新 session 持久化测试，检查 token 元数据。
- 如果保留兼容逻辑，新增或保留旧 `authorization` 加载测试。
- 新增活动分页解析测试：`data.rows` 和 `data.totalRows`。
- 新增活动分页业务错误测试。
- 更新 config 测试中的默认 base URL 断言。
- 新增 service 测试，覆盖新 lower camelCase 活动行，或覆盖 client 规范化后的活动行。
- 确认 `download_fit_file()` 仍然使用干净的非认证请求下载签名 CDN URL。

## 推荐实施计划

1. 更新配置常量和端点拼接。
   - 修改默认 base URL。
   - 保持签名 FIT 下载 URL 校验逻辑不变。

2. 将登录替换为 token 认证。
   - 使用 `appId=igpsport-web` 发送 JSON POST。
   - 解析 `access_token`、`refresh_token` 和 `expires_in`。
   - 设置 `Authorization: Bearer ...`。
   - 将 IGPSPORT 业务失败转换为 `AuthenticationError`。

3. 更新 session 持久化。
   - 将 token 元数据保存到 keyring/DPAPI storage。
   - `session.json` 只保存 username、保存时间等非敏感元数据。
   - 尽量读取旧 `authorization` 字段，避免已有 session 不必要地失效。

4. 更新活动列表获取。
   - 切换到 `queryMyActivity`。
   - 使用 `pageNo`、`pageSize`、`reqType=0`、`sort=1`。
   - 解析 `data.rows` 和 `data.totalRows`。
   - 默认在 client 层把 rows 规范化为 service 现有的旧字段名，除非明确选择更大范围重构。

5. 保持 FIT 下载流程基本不变。
   - 继续使用带 bearer auth 的 `getDownloadUrl/{ride_id}`。
   - 继续用干净的 `requests.get` 下载返回的签名 URL。

6. 更新测试。
   - 覆盖 token 登录、新列表分页、token session 加载/保存和业务错误处理。
   - 运行 `uv run pytest`。

7. 更新 README。
   - 替换旧 host 说明。
   - 高层说明当前 token-based session 行为。

## 风险和待确认问题

- JSON 登录接口是非官方接口，未来可能加入验证码、限流或额外 headers。
- refresh token 行为尚未验证。第一版可以沿用当前策略，在 session 过期时重新登录，暂缓接入 refresh token。
- 完整列表 row schema 需要通过 fixture 或脱敏真实响应固化后，再依赖除 `rideId` 之外的列表元数据。
- `reqType` 语义来自公开项目推断。当前项目只需要 FIT，因此只依赖 `reqType=0`。
- 已安装用户的 session 可能只含旧 cookies。迁移路径应能干净地重新登录，而不是把旧 cookies 当作有效会话。
