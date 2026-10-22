# 第 226 场报告生成恢复

2026-10-09，账号本人最新一场标准模式技术员面试的报告三次失败。

## 原因

RQ 任务 `interview-report-226-3` 的异常链显示 `_aggregate_question_scores` 抛出
`ValueError: question scored an untested dimension`，随后包装为“整体报告评分失败”。
工作队列和两个 worker 正常；失败来自逐题评分校验，而非报告任务未启动。

实际对话中的“离提交只剩半小时”抗压题被归到专业技能。
“喂喂喂”还被当作有效作答，提前消耗了待答题目，随后模型改写的抗压题被重复提问。

## 修复

- 增加剩余时间情境识别，正确归入抗压能力。
- 连接测试、已回答提示不计作能力答案，后续实质补充保留原题关联。
- 逐题评分先校验维度名和分值，只保留主考维度以及表达、礼仪；忽略模型额外维度，不让其影响平均分或阻断报告。
- 澄清等非作答即使被模型附上分数也不纳入汇总；真正“不会”、答错仍正常计分。
- 已考察主维度缺失、问题索引错位、非法分值仍拒绝，不用猜测分数填补错误。

报告版本 `interview-report-v10-question-evidence`，提问版本 `interview-chat-v9-coverage-recognition`。

## 验证与恢复

`test_interview_ai`、`test_interview_coverage`、`test_interview_evaluation`、`test_regressions` 共 125 项通过。
覆盖本场实际的时限题、连接测试、后续回答和额外模型维度。

服务器部署三份服务模块并核对 SHA-256；重启两个 RQ worker，平滑重载 Web 服务。
使用原始面试问答通过正常报告重试入口重新生成，未手工设定分数。

已恢复第 226 场：总分 87，专业 88、逻辑 88、表达 85、抗压 88、礼仪 88。
数据库、队列任务及本人报告页面均确认完成。
部署前后备份保存在服务器 `/root/interview-deployment-backups/20261009-report226-v10/`。
