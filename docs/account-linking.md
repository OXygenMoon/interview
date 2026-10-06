# Interview 与 WikiBook 账号关联

点击两站右上角个人头像，在下拉菜单中选择「关联 WikiBook 账号」或「关联 Interview 账号」发起关联，也可进入「账号关联设置」管理已有关系。浏览器会前往对方站点；尚未登录时，先在该站点登录，再确认页面展示的两个账号。每个账号只允许关联一个对方账号，账号数据与权限分别保留，不会根据同名账号或学号自动合并。

关联后，两站右上角头像下拉菜单分别提供「切换 WikiBook」与「切换 Interview」，账号关联设置中也保留切换按钮。切换会登录已关联的目标账号，即使目标站点原先登录了另一个账号。解除关联前会显示确认提示，解除后双向切换立即失效。解除关联不会退出已建立的登录会话，也不会删除任何业务数据。

## 部署配置

当前本地开发地址为 Interview `http://127.0.0.1:5008`、WikiBook `http://127.0.0.1:5180`。Interview 使用本机 `.env`，WikiBook 的本地关联配置放在被 Git 忽略的 `.env.local`，由 `run_local.sh` 加载。WikiBook 的后端仍运行在 `5009`，关联跳转使用浏览器访问的 `5180`。

两边服务器的 `.env` 均配置以下三个变量。密钥只用于服务器间认证，**不要使用任意一方的 Flask SECRET_KEY，也不要放入 VITE_ 前端变量**。使用密码生成器或 `python -c 'import secrets; print(secrets.token_urlsafe(48))'` 生成随机值，两边保存相同的值。

```dotenv
ACCOUNT_LINK_INTERVIEW_URL=http://211.154.20.65:20018
ACCOUNT_LINK_WIKIBOOK_URL=https://wikibook.example.com
ACCOUNT_LINK_SECRET=<两边相同的随机密钥，至少32个字符>
```

`SESSION_COOKIE_SECURE` 按各站实际协议设置：上述 HTTP Interview 为 `false`，HTTPS WikiBook 为 `true`。

URL 必须是浏览器可以访问的完整站点 origin，不包含路径、查询参数或片段。用户指定的线上 Interview 地址为 `http://211.154.20.65:20018`，协议对此精确 origin 允许 HTTP；其他公网地址要求 HTTPS。两边服务器均需能访问对方的上述地址。本地开发允许 `http://127.0.0.1:<不同端口>`；WikiBook 使用 Vite 时可以配置其前端 origin，Vite 配置已将 `/api/`、`/account-link/` 与 `/internal/account-link/` 转发到后端。`VITE_BACKEND_ORIGIN` 应指向 WikiBook 后端。生产 Nginx 的默认后端路由可处理 `/account-link/` 和 `/internal/account-link/`。

配置未完整提供或密钥不足 32 字符时，功能保持关闭，界面显示「尚未配置」。启用时，默认 Cookie 名称分别为 `interview_session` / `wikibook_session` 和 `interview_remember` / `wikibook_remember`，避免本机不同端口覆盖会话；可通过环境变量覆盖，但同一 hostname 上必须保持两站名称不同。首次启用会要求已有浏览器会话重新登录。

Interview 是关联关系与凭证的唯一存储服务。先备份 Interview 数据库，再执行迁移：

```bash
# Interview
flask --app run.py bootstrap-db
npm run build:assets

# WikiBook
cd frontend
npm run build
```

本功能不需要 WikiBook 数据库迁移。重启两边 Web 服务，加载新的配置与路由。Interview 不可用时，账号关联和切换将显示错误；两站原有的账号密码登录仍独立运行。不要把 shared secret、完整 Authorization 头或授权凭证写入日志；反向代理应避免记录这些回调路由的查询参数。

## 接口

两边提供相同的浏览器接口，响应为 `{ "ok": true, "data": ... }`；错误为 `{ "ok": false, "error": { "code": "account_link_error", "message": ... } }`。

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/api/account-link` | 返回 `enabled`、`linked`、`peer`、关联的 `username`、会话的 `csrfToken` |
| POST | `/api/account-link/start` | 生成关联请求，返回对方确认页的 `url` |
| POST | `/api/account-link/switch` | 发起双向登录切换，返回浏览器跳转的 `url` |
| DELETE | `/api/account-link` | 解除当前账号的关联 |

所有浏览器写操作均要求本地登录，并提供 `X-Account-Link-CSRF` 头，值来自 GET 接口。Interview 还沿用全站 `X-CSRF-Token`。确认表单和取消表单使用本地 CSRF 字段。

服务器接口 `/internal/account-link`（仅 Interview）与 `/internal/account-link/user`（两站）使用独立的 `Authorization: Bearer <ACCOUNT_LINK_SECRET>` 认证，不接受浏览器 Cookie 作为认证方式，也不开放 CORS。

2026-10-06 新增学习成果联动：Interview 的 `/internal/account-link` 支持 `action=learning_achievements`，按权威关联返回模拟面试、测验聚合进度；WikiBook 的 `/internal/account-link/reward-scan` 接收服务器通知并排队检查奖励。详细条件、统计口径、时区配置与部署说明见 [WikiBook 接入文档](/Users/laozhenyu/Project/wikibook/docs/interview-sticker-conditions.md)。

## 安全与数据模型

- Interview 的 `account_links` 使用双侧用户 ID 的唯一约束，保证一对一关系；角色与管理员权限来自目标站点现有用户，不从源站同步。
- 关联请求有效期 5 分钟，必须在目标站点明确确认双方账号。新请求替换该源账号的旧请求，过期或取消的请求不能持续干扰后续登录。
- 切换先完成浏览器握手：源站验证自己会话中发起请求的 nonce 与账号，目标站验证自己会话中的 state。登录凭证有效期 60 秒，仅存储 SHA-256 摘要，并通过数据库原子 UPDATE 消费一次。
- 登录凭证绑定关联 ID、双方账号和密码版本（含 WikiBook 的 session_version）。停用账号、强制改密、密码更新、会话版本更新或解除关联会拒绝相关凭证。目标站点在实际登录前再次检查本地账号版本。
- 切换清除旧目标会话与 remember cookie，再创建 fresh 登录会话。关联与切换响应均设置 no-store、no-referrer 与禁止 iframe 嵌入。
- 两个独立部署中的协议模块和确认模板保持相同，集成测试会验证副本一致。修改协议时同步更新两边。

实现参考 [OWASP OAuth2 安全指南](https://cheatsheetseries.owasp.org/cheatsheets/OAuth2_Cheat_Sheet.html) 对浏览器 state、固定回调地址与凭证重放防护的建议；这里实现的是两个可信站点之间的专用协议，不是通用 OAuth/OIDC 提供商。

## 验证

```bash
# Interview：接口、迁移与业务回归
.venv/bin/python -m pytest -q tests/test_account_link.py tests/test_regressions.py
# 双站真实 HTTP / Chromium 流程；需要同级 WikiBook 项目、npm 和 Playwright
.venv/bin/python -m pytest -q tests/e2e/test_account_links.py

# WikiBook：真实用户模型与设置接口
.venv/bin/python -m pytest -q tests/test_account_link.py tests/test_account_settings_blueprint.py
```

所有测试使用临时数据库，不会关联或修改真实用户账号。浏览器测试使用真实 WikiBook User 模型和 Vue AccountLinkPanel，验证登录后的关联确认、双向切换、清除旧会话与解除关联；WikiBook 其他页面用最小测试外壳承载。
