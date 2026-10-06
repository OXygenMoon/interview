# 移动端适配

正式页面通过 `base.html` 加载 `responsive.css` 和 `app-responsive.js`，学生、教师和管理员共用一套响应式规则。

- 小屏标题和工具栏上下排列，操作区换行；课程管理侧栏和内容区在手机上改为单列，避免隐式跨列。
- 账号关联与切换登录入口随导航折叠，避免挤占手机顶部空间。
- 手机和平板（宽度不超过 1023px）将表格记录重排为两行摘要卡片：第一行显示岗位/姓名与得分等主要信息，第二行显示时间/归属和详情入口。长标题最多显示两行，不再显示横向滚动条或滑动提示。桌面和打印保留原始表格。
- 点击记录或“查看详情”打开完整字段与操作。详情中的查看报告、继续面试、重试和管理按钮沿用原有逻辑；关闭后回到原记录。支持键盘 Enter/空格打开、Escape 关闭。
- 异步加载的班级热力表、课程内容表和文章内表格使用相同规则。切换标签、筛选、分页或尺寸变化时摘要自动更新，不复制独立的数据列表。
- 手机和触屏按钮至少 44px 高，输入框文字至少 16px；管理操作在触屏上常显，不依赖悬停。
- 简历编辑器和管理员预览按可用宽度等比缩放 A4 页面，打印时恢复原始尺寸。

## 验证

```bash
npm run build:css
.venv/bin/python -m pytest -q tests/e2e/test_mobile_layout.py tests/e2e/test_playful_ui.py tests/e2e/test_core_flows.py tests/e2e/test_design_lab.py
```

移动端回归覆盖 320px、390px、768px 竖屏和 844×390 横屏，使用隔离的测试数据库及 Chromium 触屏模拟。检查各角色页面的整页溢出、无表格横向溢出、两行长标题、完整详情、长文本、动态内容、筛选与分页、管理弹窗、面试输入和八种简历模板的预览/打印。设计预览页面另覆盖 320px 至 1440px。

本轮新增记录详情、管理按钮、键盘返回焦点、桌面表格恢复和长标题换行回归。

本轮验证：`pytest -q tests/e2e/test_mobile_layout.py tests/e2e/test_playful_ui.py tests/e2e/test_core_flows.py` 共 52 项通过；JavaScript 语法检查、Python 致命错误检查和 `git diff --check` 通过。
