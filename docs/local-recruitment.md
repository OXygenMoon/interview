# 嘉善 / 嘉兴本地招聘

登录后访问 `/jobs`，或点击导航中的“本地招聘”（教师、管理员在“教学管理 / 更多分析”菜单内）。列表支持关键词、区县、平台、排序、分页；点击岗位名称进入详情，再跳转到具体原网站岗位。页面沿用平台主题，适配手机。

## 数据与合并

- 每个平台的原始链接唯一，重复采集更新原记录。
- 以规范化后的 **企业全称 + 岗位名称 + 区县** 精确合并。仅去除空格、统一全半角和英文大小写，不做模糊匹配。可能属于不同团队、同区县不同地址的相同职位也会归为一组，详情页保留所有来源记录以便核实；不同区县不合并。
- 岗位信息保存为纯文本，模板自动转义。仅允许来源白名单内的 HTTPS 具体岗位链接，拒绝平台首页、搜索页和其他域名。
- 每个来源保留独立薪资、描述、要求和采集时间。主摘要使用最近采集的有效来源，其他版本在详情页可展开。
- 超过 7 天未采集标为“信息待确认”，超过 30 天、已注明停止招聘、或超过来源明确截止时间的记录默认隐藏。可勾选查看历史记录。列表“最近采集”表示本站读取时间，不表示企业刚发布或确认在招；原站未公开发布时间时不推测。
- 来源失败、验证码、空响应、解析不到岗位都记录失败，保留已有岗位。首页/推荐页采集是有界的增量收录，不代表平台全部职位；未出现在本轮页面中的旧岗位不会直接删除。

## 首次运行 / 定时采集

```bash
# 在项目目录，使用项目虚拟环境。
flask --app run.py bootstrap-db
flask --app run.py sync-jobs --source jiaxing --limit 30
flask --app run.py sync-jobs --limit 30
```

默认尝试 BOSS直聘、拉勾网的公开 JSON-LD JobPosting，以及嘉兴人才网的嘉善 / 嘉兴公开推荐列表和详情。采集带明确 User-Agent，遵循 robots，限速、超时、限制页面体积，不携带用户登录 Cookie，不访问内部 API，不处理验证码。BOSS / 拉勾若只返回动态壳或验证页面，状态为“暂不可用”；当前网络实测两者不能直接获取岗位，不能保证采集成功。嘉兴人才网公开 HTML 已验证可读取。来源页面结构变化需要维护对应解析器。

管理员可在页面“来源与更新”点击“更新此来源”。普通用户只能查询。来源任务通过数据库租约防止重复执行，10 分钟过期可接管；所有网络请求在采集任务中完成，查询页面仅读数据库。

生产使用随仓库提供的 systemd 定时器，每 6 小时增量采集一次：

```bash
# 默认路径沿用 deploy/interview.service；路径不同时先修改 service 文件。
sudo cp deploy/interview-jobs.service deploy/interview-jobs.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now interview-jobs.timer
sudo systemctl start interview-jobs.service
sudo journalctl -u interview-jobs.service -n 50
```

先执行数据库迁移，再启动定时器。单个平台失败不会阻止其他平台同步，但命令最终返回非零退出码，方便监控发现问题。UI 保留各来源的真实状态。部署计时器未安装时不会自动定时运行，Flask/Gunicorn 进程内不会启动重复调度线程。

## 导入授权数据

若有平台授权的数据导出或合作接口，可将其转换为 JSON 数组，使用同一套合并规则导入。没有虚构或预置岗位数据。

```json
[
  {
    "title": "岗位名称",
    "company": "企业全称",
    "district": "嘉善",
    "url": "https://www.zhipin.com/job_detail/真实岗位ID.html",
    "salary": "8-13K",
    "experience": "1-3年",
    "education": "大专",
    "address": "嘉善县具体地址",
    "description": "岗位职责与要求",
    "published_at": "2026-10-25",
    "expires_at": "2026-11-30T23:59:59+08:00",
    "is_active": true
  }
]
```

上面仅是格式说明，`url` 必须替换成数据提供方的真实原始岗位链接。必填字段：title、company、district（或 location）、url。仅收录明确位于嘉兴全域的岗位，district 优先按工作地提供，不能用公司注册地址替代工作地。其他字段可选。日期须为 ISO 8601。每批最多 5000 条；整批验证失败则整批回滚，旧数据保留。

```bash
flask --app run.py sync-jobs --source boss --file /path/to/authorized-boss-jobs.json
flask --app run.py sync-jobs --source lagou --file /path/to/authorized-lagou-jobs.json
```

关闭已收录岗位可导入相同原始 URL 且 `is_active: false` 的记录。导入不是自动抓取权限或合作接口的替代品。要自动消费合作接口，可由授权的上游任务定期生成此 JSON，再调用上述导入命令。
