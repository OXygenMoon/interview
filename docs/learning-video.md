# 学习模块视频管理

管理员入口：**教学管理 → 课程内容管理**（`/admin/learning`）。

1. 选择或新建分类，点击「添加内容」。
2. 内容类型选择「视频课程」，填写标题和可选课程说明。
3. 视频来源二选一：
   - 上传 MP4、M4V、WebM 文件，默认每个文件最大 200 MB。推荐 H.264 编码的 MP4。
   - 粘贴 B 站 iframe 代码、`player.bilibili.com/player.html` 链接或完整视频页面链接。支持 BV、av 和分 P 参数；短链接请先在浏览器打开并复制完整地址。
4. 保存后点击「预览」检查学生页面。学生从「学习资料」进入课程，可以播放视频并标记本节已学完。

已有内容支持编辑。编辑上传视频时，不选择新文件会保留当前视频。替换视频、切换到 B 站来源或删除没有学习记录的内容后，会清理旧文件。有学习记录的内容不可删除或变更内容类型。

上传进度显示在保存弹窗中。上传视频仅允许管理员写入；视频文件通过登录后的课程接口播放，支持 Range 请求和拖动进度条。B 站 iframe 仅提取并校验官方来源，重新生成播放器 URL，不执行用户粘贴的 HTML 属性。参数参考 [B 站外链播放器官方说明](https://player.bilibili.com/)。B 站内容能否实际播放取决于站方对相应视频的可用性与访问限制。

## 运行与部署

更新代码后，先备份数据库，再执行：

```sh
.venv/bin/python -m flask --app run.py bootstrap-db
```

该迁移为已有课程增加两个可空视频字段，保留文章、测验及学习记录。

上传文件默认存放在 `instance/uploads/learning/`；可通过 `LEARNING_VIDEO_UPLOAD_DIR` 指定持久化目录，运行用户需要读写权限。备份或迁移服务器时，应同时保留数据库和该目录；多台应用实例需要共享同一存储目录。

`LEARNING_VIDEO_MAX_BYTES` 控制单文件大小，默认 `209715200`（200 MB）。其他 API 保持原有请求大小限制。两份 Nginx 示例已将请求上限更新为 `201m`，为 multipart 数据预留空间；部署时需要同步生效并重启应用。若提高单文件大小，请同步提高 Nginx 请求上限。

## 验证

```sh
.venv/bin/python -m pytest tests/test_learning_video.py tests/test_migration_guard.py tests/test_learning_achievements.py tests/test_regressions.py -q
.venv/bin/python -m pytest tests/e2e/test_learning_video.py -q
```

浏览器测试通过 ffmpeg 生成真实 MP4，覆盖管理员上传、学生实际播放、学习完成、编辑为 B 站来源及手机布局。B 站第三方请求在浏览器测试中使用测试响应，不依赖公网视频播放。
