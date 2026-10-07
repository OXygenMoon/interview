# 前端深度美化与优化（2026-10-07）

本次应用 hallmark 与 design-taste-frontend，对现有 Flask/Jinja 前端进行就地优化。设计方向为亲和、克制的学习与面试工作台。保留品牌、导航名称、路由、字段顺序、账号偏好和打印文档，沿用 Tailwind 3 / DaisyUI，没有新增浏览器运行时依赖。

## 审查与设计决定

原有 Avenir Next / PingFang SC 字体栈与柔彩色板已有明确品牌识别。亮色色调与暗色模式在公共外壳中实现，已有跳转主内容、手机记录详情、Escape 关闭菜单与原生 dialog。这些能力继续沿用。

主要优化点是：导航、按钮、输入、弹窗使用较多不同圆角；部分暗色表头仍呈浅底；管理动作采用低透明度文字。面试配置中的原生 alert/confirm 会打断填写流程。

参数：`DESIGN_VARIANCE: 5`、`MOTION_INTENSITY: 3`、`VISUAL_DENSITY: 5`。采用 Workbench 的功能优先原则，N1b 顶部导航和 Ft2 简洁页脚。此处是现有产品界面的演进，不套用营销页的客户墙、定价、滚动演出或假产品预览。

## 已完成修改

- 新增根目录 `tokens.css`：语义颜色引用已有 `--ui-*` 色板，统一四点间距、字体角色、字号、圆角、时长和层级。新增状态色使用 OKLCH。`scripts/build-design-tokens.cjs` 生成 Flask 提供的本地副本，集成进 `npm run build:css`。
- 新增 `app/static/css/refinement.css`：通过公共外壳加载，保留原样式入口与 Tailwind 指令；全站按钮、表单、表格、聊天气泡、弹窗和导航采用统一视觉规则。
- 顶部导航采用 76px 桌面 / 72px 手机高度，始终固定在 body 根部。延续导航名称、个人账号菜单、手机菜单与主题控件。
- 根据用户对原排版的偏好，学生首页恢复左侧介绍、右侧纸张插画、三张柔彩统计卡、学习入口与原近期记录标题栏。手机沿用原来的单列首屏与双列统计卡（第三张跨两列）；保留面试配置的错误恢复、可访问性与样式加载优化。教学首页的新布局保持独立。
- 教学首页将装饰插画改为指导入口，弱化统计卡的多色背景，保留完整记录、排名和快捷操作。
- 登录页使用专属 AI 生成静物视觉，WebP 为 30,554 字节、960×640；注明宽高、优先加载和异步解码。手机隐藏装饰视觉，优先显示表单。新增密码显隐、原生登录提交反馈和返回页面时的状态恢复。
- 为注册字段补齐 label/for 关联，保留字段名称与顺序。
- 面试创建的岗位校验、网络失败、服务失败和冷却提示在 dialog 内展示；保留已选值、可重试，支持明确的复盘/继续链接。提交期间拦截重复请求，并为状态设置 `aria-busy` / `aria-invalid` / `role="alert"`。
- 调整低对比的管理动作，并使隐藏操作在键盘进入其行时可见。聚焦环即时显示，减少动态效果设置得到保留。
- 新增入口专用 Tailwind 构建与样式合并脚本。登录/注册加载约 97 KiB 的专用 CSS，完整产品页加载约 288 KiB；每页公共样式合并为一次请求。源文件及其级联顺序保持一致。
- 面试配置的公司、岗位与简历控件补齐可访问标签，难度与面试官选择采用具名 radio group，移除装饰性 emoji 并统一选中状态。
- Markdown 渲染脚本只在面试大厅与面试房间加载，其余页面减少不需要的脚本。
- 新样式限于 screen 媒体，简历编辑和预览的打印几何保持原规则。

## 验证

```sh
npm run build:css
node --check app/static/js/app-shell.js
git diff --check
.venv/bin/python -m pytest -q tests/e2e/test_frontend_refinement.py tests/e2e/test_playful_ui.py tests/e2e/test_theme_switcher.py
.venv/bin/python -m pytest -q tests/e2e/test_mobile_layout.py tests/e2e/test_core_flows.py
```

以上两组浏览器回归分别为 56 与 37 项，共 93 项通过。覆盖学生/教师/管理员全部页面族，320/375/414/768/1024/1440 像素布局、六种主题与持久化、键盘导航、手机记录详情、简历打印、登录、测验和面试创建。

按用户要求恢复 index 原布局后，重新构建样式并运行入口交互、全页面响应式与手机布局回归，65 项通过；检查了恢复后的桌面、手机和暗色模式截图（`restored-home*.png`）。

新增回归验证：登录图片实际载入、密码显隐保持值、面试缺少岗位的就地错误、网络失败后保留选择、冷却复盘链接、提交中重复请求拦截。表单保留原生账号验证与后端业务校验。

对登录、教学概览、企业管理、组织管理与系统设置的可见按钮及新文本，在亮/暗主题下计算实际前景与合成背景的 WCAG 对比度，所检查的可用控件均达到 4.5:1。

桌面登录、学生首页、教学首页，手机 320/375 页面与暗色学生首页的实页截图位于 `test-results/design-review/`。数据来自隔离测试数据库；未操作正式数据库。

Hallmark 的排版、颜色、形状、真实内容、键盘、移动端与减少动态效果检查按实际产品范围执行。营销页专属的客户墙、定价、长滚动、testimonial、宏结构轮换条目不适用。原有图表和表格保持真实业务数据，不增加虚构指标。

## 性能检查

本地隔离服务器下的 Lighthouse 默认移动端模拟：性能 99，可访问性 100，最佳实践 100。LCP 2.0 秒，FCP 1.5 秒，CLS 0，TBT 0 毫秒。首轮新界面尚未拆分入口样式时性能为 88、LCP 3.2 秒；减小入口 CSS 并合并请求后获得上述结果。报告位于 `test-results/design-review/lighthouse-login-final.json`。这些是本地模拟测试数据，不能代表正式环境或真实用户 INP。

## 维护说明

- 根目录 `tokens.css` 是新增设计 token 的源文件；不要直接编辑生成副本 `app/static/css/tokens.css`。
- 业务模板继续由现有路由拥有。新视觉规则放在 `refinement.css`，打印文档不在本次覆盖范围。
- `tailwind.auth.config.cjs` 复用原 Tailwind 配置，只缩小登录/注册的扫描范围；DaisyUI 与品牌主题不另建体系。
- `app.bundle.css`、`auth.bundle.css`、`auth-ui.css`、`auth-theme-utilities.css` 为生成文件，由 `npm run build:css` 重建，不直接编辑。
- 修改 utility 类后执行 `npm run build:css`，提交生成的 CSS。
- `.hallmark/preflight.json` 记录审查结果，`.hallmark/log.json` 记录本次整站设计方向。
