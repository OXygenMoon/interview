from pathlib import Path
import json, math
from PIL import Image, ImageDraw
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.section import WD_ORIENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

ROOT=Path(__file__).resolve().parent
SHOTS=ROOT/'screenshots'
FIGS=ROOT/'figures'
FIGS.mkdir(exist_ok=True)
items=[]
def item(code,role,title,shot,entry,steps,result,status='页面已核验',crop=None):
    items.append(dict(code=code,role=role,title=title,shot=shot,entry=entry,steps=steps,result=result,status=status,crop=crop))

item('G01','通用','登录与识别工作台','57-logout','网站首页 → 登录',[
 '打开 http://211.154.20.65:20018，输入账号及对应密码，点击“登录并继续”。',
 '学生账号进入面试大厅；管理员进入教学工作空间；企业账号进入企业招聘工作台。',
 '核对右上角姓名及顶部菜单，再开始操作；切换账号前先退出当前登录。'],
 '本次三个账号均登录成功。密码不写入手册；账号或密码错误时，页面会显示错误提示。','三种身份均已实际登录', (590,455,2840,1900))

item('S01','学生','面试大厅与练习概况','03-student-home','学生工作台 → 面试大厅',[
 '查看累计练习次数、最近平均表现及历史最佳，了解自己的练习情况。',
 '点击“立即开始面试”配置岗位练习，或点击“随机问题面试”进入单题快练。',
 '向下滚动查看近期面试记录，点击“查看报告”；记录较多时使用底部分页。'],
 '示例账号为刘海 222308。首页显示的次数与分数是采集时的历史数据，会随练习变化。')
item('S02','学生','配置公司岗位与模拟面试','05-student-job-config','面试大厅 → 立即开始面试',[
 '先选择公司，再选择岗位；右侧查看公司介绍和岗位要求。示例选择浙江创智科技的售前技术支持。',
 '在左侧配置区选择面试官音色，再向下滚动选择新手、标准或压力模式，以及本次递交的简历或盲面。',
 '确认后点击“开始模拟面试”。后续按题作答；完成后查看报告，再按提示开展下一次练习。'],
 '页面提示：所属公司可查看该岗位的面试记录及本次递交简历。本次只核验配置表单，未新建面试；实时作答界面未实测。',
 '配置已核验  未启动新面试',(690,445,2745,1820))
item('S03','学生','随机问题单题快练','19-student-random','面试大厅 → 随机问题面试',[
 '阅读随机抽取的问题，点击“换一题”切换题目；采集时题库共 30 题。',
 '使用“开始语音”作答，或直接在下方文本框输入、补充或修改答案。',
 '点击“结束回答并分析”请求评分、评价与建议；摄像头为可选项，开启后提交回答时采集当前帧。'],
 '当前地址为 HTTP，页面提示音视频需要安全连接。建议由管理员提供有效 HTTPS 地址；本次未开启设备或提交答案。',
 '页面及输入入口已核验  分析未提交',(555,425,2880,1950))
item('S04','学生','浏览学习资料与进度','06-student-learning','顶部导航 → 学习资料',[
 '进入知识充电站，查看课程模块数和总体进度。',
 '选择礼仪、表达、如果你要做服务行业、面试或职场能力课程卡片。',
 '按卡片上的“开始学习”“继续学习”或“已学完，去复习”进入课程。'],
 '采集时显示 5 个课程模块、总体进度 30%。完成状态按当前账号分别记录。')
item('S05','学生','阅读课程与切换章节','07-student-course','学习资料 → 课程卡片 → 文章章节',[
 '左侧查看课程目录，点击 DOC 章节阅读正文，点击 QUIZ 章节进入测验。',
 '阅读正文并查看页面的学习状态；本次示例“常见礼仪”显示已完成学习。',
 '使用页底“上一节”“下一节”连续学习，或通过顶部面包屑返回知识充电站。'],
 '课程文章与测验位于同一目录中。本次阅读的是已有完成记录，没有代替学生提交测验。')
item('S06','学生','完成随堂测验','08-student-quiz','课程目录 → QUIZ 测验章节',[
 '查看题目数量和及格要求。示例礼仪测验共 4 题，满分 100 分，80 分及格。',
 '逐题选择答案，向下滚动完成其余题目。',
 '核对答案后点击页底“提交试卷”，根据页面反馈安排后续学习。'],
 '本次核验题目、单选项和提交入口，未代答或提交；提交后的成绩反馈与进度变化未实测。',
 '题目与提交入口已核验  未交卷')
item('S07','学生','查看五维能力与成长轨迹','09-student-radar','顶部导航 → 能力成长',[
 '查看综合战力、历史最佳及五维能力模型，对比个人与班级平均水平。',
 '点击“成长轨迹”切换近期得分走势；右侧查看五维成长曲线及趋势提示。',
 '向下滚动，可点击“生成诊断报告”请求 AI 职业诊断，并查看智能推荐训练入口。'],
 '五维包括专业技能、逻辑思维、语言表达、抗压能力和礼仪态度。趋势标注为非成绩预测；部分推荐训练链接当前指向本页锚点。',
 '能力图与轨迹切换已核验  诊断未生成')
item('S08','学生','查找练习记录与打开报告','12-student-history-list','顶部导航 → 练习记录',[
 '查看累计模拟、平均分、最高分，以及成长曲线和练习岗位分布。',
 '下滚到详细记录列表，按时间、岗位、面试官、难度及得分识别记录。',
 '点击“查看报告”进入复盘；底部分页可浏览其他记录。部分近期记录提供“隐藏记录”入口。'],
 '采集时搜索框为禁用状态，不作为可用搜索功能介绍。本次未隐藏记录；隐藏操作的后续恢复流程未实测。')
item('S09','学生','阅读面试总评与画面复盘','13-student-report','面试大厅或练习记录 → 查看报告',[
 '先核对岗位、时间和综合得分，阅读面试官总评及五维能力分析。',
 '在“视频画面与仪态复盘”中点击不同时间戳，查看对应画面、关键词与仪态点评。',
 '点击“查看对应回答”定位答复；点击完整画面链接查看原图；需要继续练习时可使用报告中的下一轮入口。'],
 '示例为历史技术员面试报告。画面点评只依据该帧可见姿态；下一轮入口已发现，本次未启动新一轮。')
item('S10','学生','逐句复盘与参考回答','14-student-report-review','面试报告 → 向下滚动到对话深度复盘',[
 '按面试官问题与自己的回答逐条回顾，阅读每条回答下的 AI 评价或优化建议。',
 '展开“查看满分参考回答”对照表达方式；带画面时间戳的回答可跳回仪态复盘区域。',
 '报告下方提供“评估匹配度”，可请求岗位匹配分析，结合建议选择下一次训练重点。'],
 '本次核验已有问题、回答、逐句反馈及相关入口；未触发新的匹配度评估。参考回答展开后的内容未单独核验。',
 '历史复盘已核验  新评估未生成')
item('S11','学生','回看已结束面试对话','53-student-conversation','面试报告 → 查看对话记录',[
 '进入面试回顾页，核对岗位、难度及当前面试状态。',
 '滚动对话区域查看面试官提问和学生回答；有画面记录时，可查看时间、关键词及仪态点评。',
 '点击“查看报告”返回评分页；右侧小贴士提供取景、视线和设备摆放建议。'],
 '本次截图为已结束面试，只提供回顾。不能将该页面当作正在作答的面试室截图。')
item('S12','学生','管理个人简历库','15-student-resumes','顶部导航 → 智能简历中心',[
 '查看简历卡片、名称与更新时间；点击“进入编辑器”打开某一份简历。',
 '点击“维护档案”维护新建简历时可导入的基础资料，或点击“新建简历”创建独立版本。',
 '页面存在重命名对话框；如需重命名，先通过简历卡片的管理入口进入，再核对名称后保存。'],
 '示例账号显示 3/5 份简历。重命名对话框已从页面控件核对，卡片管理入口未展开实测。')
item('S13','学生','新建简历并导入基础档案','54-student-resume-new','智能简历中心 → 新建简历',[
 '在对话框填写便于区分的简历名称，例如对应岗位的求职简历。',
 '按需要保留或取消“一键导入基础档案”；勾选时导入姓名、电话、邮箱等母版信息。',
 '点击“立即创建”提交，或点击“取消”关闭；创建后再进入编辑器补齐经历。'],
 '本次只打开新建对话框，未创建简历。导入的是基础档案，不应假定包含其他简历中的全部经历。',
 '新建表单已核验  未创建',(1180,770,2250,1500))
item('S14','学生','编辑简历与导出 PDF','16-student-resume-editor','智能简历中心 → 进入编辑器',[
 '在左侧切换基本信息、教育背景、实习工作经历、项目经验、校园经历、获奖和技能证书模块。',
 '在中间填写内容，按需隐藏模块或字段；自我评价提供“润色”入口；查看右侧实时预览并保存。',
 '选择简历模板，按需使用“智能一页纸”调整，再点击“导出 PDF”。'],
 '本次打开已有简历，未改写简历、调用润色或导出文件。截图中的真实手机号和邮箱已遮盖。',
 '编辑器及导出入口已核验  未改写或导出')
item('S15','学生','维护个人基础资料','55-student-base-file','顶部导航 → 基本资料 或 智能简历中心 → 维护档案',[
 '填写姓名、求职意向、电话、邮箱、所在城市和自我评价。',
 '核对信息后，在基本资料页点击“保存信息”，或在维护基础档案弹窗点击“保存档案”。',
 '以后新建简历时勾选“一键导入基础档案”；已有简历是否同步更新，应另行核对。'],
 '基础档案作为新建简历的母版。本次未修改字段内容；取证过程中发生一次原值保存，不构成资料更新。',
 '两处入口已核验  字段内容未更改',(1015,475,2390,1850))
item('S16','学生','查看班级风云榜','18-student-leaderboard','顶部导航 → 班级风云榜',[
 '先核对当前班级及自己的排名信息。',
 '切换“综合实力榜”“巅峰时刻榜”“勤奋之星榜”，分别查看不同维度的排行。',
 '结合列表中的面试场次、历史最高分和平均分了解练习情况。'],
 '采集时“我的平均分”显示横线，不能据此写成 0 分。综合榜已打开，另外两种榜单的切换结果未单独截图。')

item('A01','管理员','教学概览与最新面试','23-admin-dashboard','管理员登录 → 教学概览',[
 '查看当前权限范围内已完成面试场次、平均综合得分及学生最高均分。',
 '在最新面试记录中核对学生、班级、岗位、得分和时间，点击“查看”打开报告。',
 '使用学生名册、面试流水、能力画像快捷入口；展开“教学管理”进入其余管理功能。'],
 '采集时显示 101 场已完成面试、平均 62.0 分。统计是当前快照；优秀表现 Top 5 按学生平均分排序。')
item('A02','管理员','筛选学生名册与账号维护','25-admin-students','顶部导航 → 学生名册',[
 '使用系部、班级下拉框筛选，或输入姓名、学号搜索；示例搜索 222308。',
 '查看学生所属班级、练习次数、平均得分及最近活跃时间。',
 '点击“查看详情”进入学生档案；“重置密码”“停用”用于账号维护，操作前核对目标学生。'],
 '本次实际完成学号筛选并打开详情，没有重置密码或停用账号。此页不替代批量导入学生入口。')
item('A03','管理员','查看学生个体学情','26-admin-student-detail','学生名册 → 查看详情',[
 '核对姓名、学号、系部、班级及技能标签，查看平均分和练习次数。',
 '阅读近期成长曲线，向下查看历史面试时间、岗位和得分。',
 '选择某条“查看报告”，依据问题与回答开展具体指导；完成后返回花名册。'],
 '本次使用 222308 的历史记录核验。页面显示“暂无技能标签”不等于学生没有技能，仅表示此处未完善。')
item('A04','管理员','管理面试记录流水','27-admin-interviews','顶部导航 → 面试记录',[
 '查看近 1 小时、24 小时、1 周、1 个月、1 年及全部记录的统计，点击“刷新数据”更新。',
 '按学生、岗位、得分、开始时间、耗时和状态识别记录，点击“查看”进入面试报告。',
 '使用分页浏览；需要排查隐藏记录时点击“查看已隐藏记录”。记录行提供“隐藏”入口。'],
 '本次只查看记录，没有隐藏或恢复数据。页面提供的是时间窗口统计，不能默认其支持自定义起止日期筛选。')
item('A05','管理员','分析群体能力与偏差预警','28-admin-capability','顶部导航 → 能力画像',[
 '用顶部视图选择器确定统计范围，查看学生总数及活跃参与度。',
 '结合五维能力模型、薄弱项分析和面试力分布，了解群体表现。',
 '查看能力偏差预警，定位需要进一步了解的维度，再回到学生档案核对具体回答。'],
 '示例全校视图显示 135 名学生、48 人已完成面试。预警是页面统计结果，本手册未据此作出学生考核或录用决定。')
item('A06','管理员','比较班级表现','29-admin-compare','教学管理 → 班级对比看板',[
 '查看各班级平均总分柱状图，识别参与统计的班级。',
 '下滚查看五维能力热力表，对比各班专业技能、逻辑、表达、抗压、礼仪及总分。',
 '查看“高频薄弱题”聚合区域，将结果作为后续课堂训练选题的参考。'],
 '页面包含未分班或测试班数据，阅读时应注意统计范围。该看板用于班级横向比较。')
item('A07','管理员','检索学生简历','30-admin-resumes','教学管理 → 学生简历预览',[
 '在搜索框输入姓名、学号、简历标题、班级或系部信息。',
 '核对列表中的学生身份、系部班级、简历标题和更新时间。',
 '点击对应行“预览”，进入只读简历页面。'],
 '页面明确标注仅支持查看与打印，不提供编辑、删除等操作。搜索入口已核验，本次未另行验证多条件组合查询。')
item('A08','管理员','预览与打印学生简历','60-admin-resume-preview','学生简历预览 → 对应简历 → 预览',[
 '核对只读预览标题中的学生身份及学号，阅读简历内容。',
 '选择显示模板，按需要使用“智能一页纸”调整预览。',
 '点击“打印 / PDF”打开打印流程，完成纸质打印或另存 PDF。'],
 '本次核验只读页面和打印入口，没有改写学生简历或实际打印。截图中的联系方式已遮盖。',
 '只读预览已核验  未打印')
item('A09','管理员','管理课程分类与内容清单','32-admin-course-category','教学管理 → 课程内容管理',[
 '点击“新建分类”建立学习分类；管理现有内容时先点击左侧分类名称。',
 '右侧查看该分类下的文章和测验，以及对应的内容类型。',
 '点击“添加内容”进入表单；分类旁的叉号和内容行的“删除”为移除入口，操作时核对目标。'],
 '本次打开礼仪分类，确认包含文章与测验。未新增分类或删除内容；删除后的恢复机制未实测。')
item('A10','管理员','新增学习文章或测验','33-admin-course-form','课程内容管理 → 分类 → 添加内容',[
 '输入内容标题，在类型下拉框中选择文章或测验。',
 '根据类型填写内容；页面标注支持 HTML 文本或 JSON 题目，并提供“填入示例模板”。',
 '核对分类、标题、类型及内容后保存；不发布时取消。'],
 '新增表单已打开，未提交。建议先利用示例模板理解格式；具体 JSON 字段应以页面模板为准。',
 '新增表单已核验  未保存',(955,490,2580,1750))
item('A11','管理员','维护系部与班级','35-admin-department','教学管理 → 组织与学生管理',[
 '左侧系部列表点击“新增”建立系部，或选择已有系部进行管理。',
 '右侧核对当前系部，点击“批量创建班级”进入班级创建流程。',
 '查看该系部班级卡片；移除系部或班级前核对目标及其现有学生归属。'],
 '本次选择数字经济系，看到 2222、2223、2534 三个班级。未新增、删除或调整学生归属。')
item('A12','管理员','批量导入学生名单','36-admin-student-import','组织与学生管理 → 下载模板 → 批量导入学生',[
 '先下载系统提供的 Excel 模板，按模板要求填写学生名单。',
 '点击“批量导入学生”，选择填写完成的模板文件，核对拟导入范围。',
 '点击“开始导入”，再回到学生名册核对结果；取消则关闭导入窗口。'],
 '页面提示：班级不存在时，系统会在对应系部下自动创建。本次只查看导入窗口，没有上传或导入名单。',
 '导入表单已核验  未上传',(1190,820,2380,1410))
item('A13','管理员','开通校企合作账号','37-admin-partnerships','教学管理 → 校企合作管理',[
 '选择已有公司，或保留“新增合作公司”并填写新公司名称及介绍。',
 '填写登录账号、联系人和初始密码；页面要求初始密码至少 10 个字符，首次登录需修改。',
 '核对所属公司后点击“开通公司账号”；已有公司可以开通多个联系人账号。'],
 '本次只核验表单，未新建公司账号。页面提示每个企业账号只可访问所属公司的岗位和面试记录。',
 '开通表单已核验  未开通')
item('A14','管理员','维护企业联系人与登录状态','59-admin-partner-account','校企合作管理 → 下滚到公司账号',[
 '核对公司名称、登录账号、联系人、启用状态和岗位数量。',
 '更新联系人时修改对应输入框并点击“更新联系人”。',
 '需要停用时使用“停用账号”；需要密码重置时，由管理员核对账号并自行完成临时密码设置。'],
 '示例为浙江创智科技 zjczkj、联系人宋经理。本次未更新联系人、停用账号或重置密码。',
 '维护入口已核验  未变更')
item('A15','管理员','管理企业资料与岗位库','39-admin-jobs','教学管理 → 企业与岗位管理',[
 '在左侧公司列表选择目标公司，右侧查看该公司的岗位。',
 '点击“新增公司”维护新企业；公司旁的编辑符号进入公司资料修改，叉号为删除入口。',
 '在岗位卡片中点击“编辑”维护岗位，或点击“新增岗位”建立岗位；删除前核对目标岗位。'],
 '本次选择浙江创智科技，核验其 3 个岗位及编辑、删除入口，没有修改或删除企业与岗位。')
item('A16','管理员','新增岗位与维护面试要求','40-admin-job-form','企业与岗位管理 → 公司 → 新增岗位',[
 '确认当前管理公司，填写岗位名称。',
 '在“岗位要求与提示词”中填写职责、技能与考察要求；输入区支持 Markdown。',
 '核对内容后保存，或取消关闭。已有岗位可通过“编辑”进入类似维护流程。'],
 '页面明确说明内容对学生可见，同时作为 AI 面试的背景资料。本次只打开新增表单，未发布岗位。',
 '岗位表单已核验  未保存',(920,470,2530,1790))
item('A17','管理员','配置随机面试问题题库','41-admin-question-bank','教学管理 → 随机问题题库',[
 '查看当前题数和文本框中的题目列表。',
 '每行输入一个独立问题，修改时保留清晰的题目边界。',
 '确认后点击“保存题库配置”；学生端随机问题面试会从该列表抽题。'],
 '采集时题库为 30 题。本次没有修改题目或保存题库。')
item('A18','管理员','配置语音视频功能开关','42-admin-settings','教学管理 → 系统设置 → AI 面试官配置',[
 '按教学安排查看文字对话语音播报 TTS、实时语音交互和视频面试三个开关。',
 '阅读开关说明：实时语音支持连续对话与打断；视频分析在提交回答时使用一张当前帧。',
 '需要变更时统一调整并点击“保存设置”，再使用学生账号核对入口变化。'],
 '采集时三个开关均启用。页面提示关闭实时语音会停止正在进行的会话；本次没有保存配置变更。')
item('A19','管理员','配置存储保留与练习冷却','58-admin-settings-bottom','系统设置 → 下滚到存储保留策略与面试节奏控制',[
 '设置 TTS 音频保留天数和临时文件保留小时数，核对清理说明。',
 '设置会话保留、放弃罚时、完成冷却的分钟数；按需要启用强制查看报告后才能再次面试。',
 '核对后保存。本次读取到的参数为 30 天、24 小时、10 分钟、5 分钟、1 分钟，强制复盘已勾选。'],
 '以输入框当前值为准：页面部分帮助文字中的默认值与当前值不同。本次未保存任何设置变更。')
item('A20','管理员','查看测试账号使用状态','43-admin-test-accounts','右上角个人菜单 → 测试账号与使用状态',[
 '进入测试账号页面，查看每个测试学员的可用或使用中状态。',
 '阅读页面说明，确认账号占用和释放规则；采集时页面显示 10 个测试账号。',
 '仅在测试入口允许且账号可用时选择使用；管理员已登录时截图中的“使用此账号”按钮为禁用状态。'],
 '页面说明状态每 5 秒更新，关闭页面或断网后约 3 分钟释放。这里用于查看状态，本次未切换测试账号。')

item('E01','企业','查看公司招聘概览','44-company-overview','企业账号登录 → 公司概览',[
 '核对公司名称，查看岗位数、面试记录数和参与学生数。',
 '点击“管理岗位”维护岗位，或点击“查看记录”进入本公司面试列表。',
 '在最近面试中点击报告、对话记录或递交简历，分别查看相关证据。'],
 '示例账号 zjczkj 属于浙江创智科技，联系人宋经理。采集时为 3 个岗位、17 条面试记录、8 名参与学生。')
item('E02','企业','浏览岗位与进入关联面试','45-company-positions','顶部导航 → 面试岗位',[
 '查看本公司的岗位名称、职责和要求。',
 '点击“编辑岗位”维护内容；点击“查看面试记录”查看该岗位的面试。',
 '点击“一键推荐学生”查看系统生成的岗位推荐名单，或点击“新增岗位”打开新建表单。'],
 '页面提示岗位要求用于学生选岗和 AI 面试，保存后立即生效。本次没有改动岗位内容。')
item('E03','企业','新增本公司面试岗位','46-company-position-new','面试岗位 → 新增岗位',[
 '填写岗位名称，明确招聘岗位。',
 '填写岗位职责与要求，可包括工作职责、必备技能、适合专业及面试考察重点。',
 '核对内容后点击“保存岗位”；不发布则点击“取消”或“返回岗位”。'],
 '输入支持 Markdown，内容对学生可见。页面提示历史面试保留当时岗位要求；本次只查看表单，未新增岗位。',
 '新增表单已核验  未发布')
item('E04','企业','编辑已有岗位','47-company-position-edit','面试岗位 → 对应岗位 → 编辑岗位',[
 '核对原岗位名称和职责要求，确认正在维护的岗位。',
 '修改需要调整的内容，检查是否仍清楚描述职责、技能与考察重点。',
 '点击“保存岗位”生效，或取消返回；历史面试按页面说明保留当时的要求。'],
 '本次打开网络安全服务工程师编辑页，未改写或保存。企业端页面未见岗位删除入口。',
 '编辑表单已核验  未保存')
item('E05','企业','查看岗位学生推荐及依据','48-company-recommendations','面试岗位 → 一键推荐学生',[
 '先阅读推荐依据，确认当前岗位与入选条件。',
 '查看推荐学生的适配参考分、专业技能分、面试综合分及总结。',
 '点击“查看面试证据”核对原报告；有递交简历时结合简历查看，无简历时页面会提示。'],
 '页面规则：参考分为专业技能×60%＋综合分×40%，参考分≥75且技能≥60；每人取该岗位最新有效完成记录，排除停用、兜底及缺失评分。此为页面规则转述。')
item('E06','企业','按岗位筛选学生面试记录','49-company-interviews','顶部导航 → 学生面试记录',[
 '在“面试岗位”下拉框选择岗位并点击“筛选”，或保留全部岗位。',
 '查看时间窗口统计，按学生、岗位、得分、时间、耗时和状态核对记录；需要时刷新数据。',
 '每条记录可进入“查看报告”“对话记录”；本次有递交简历时显示简历链接，否则显示未递交。'],
 '企业页面说明范围为本公司岗位。未见管理员的隐藏入口或学生名册管理入口；本次没有进行越权访问测试。')
item('E07','企业','阅读面试报告与仪态证据','50-company-report','学生面试记录 → 查看报告',[
 '核对岗位与学生，阅读综合得分、总评及五维能力分析。',
 '点击画面时间戳查看对应截图和仪态点评，通过“查看对应回答”定位原答复。',
 '下滚查看逐句复盘，或使用顶部链接进入对话记录、递交简历和岗位面试列表。'],
 '示例为售前技术支持历史报告。企业页面展示历史证据，本次未发起面试、修改评分或作出录用操作。')
item('E08','企业','查看学生原始对话与画面','51-company-conversation','学生面试记录 → 对话记录',[
 '核对岗位、面试模式和已结束状态。',
 '在对话区域滚动阅读提问与学生回答，有画面时查看时间戳、关键词和仪态点评。',
 '需要完整画面时点击相应链接；点击“查看报告”回到综合复盘页。'],
 '这是历史面试回顾页面，不能在此替学生追加回答。本次只阅读记录。')
item('E09','企业','查看面试时递交的简历','52-company-resume','面试记录 → 递交简历 或 报告 → 查看递交简历',[
 '核对学生姓名、学号、简历名称及“面试时递交于”的时间。',
 '在只读页面浏览内容，按需选择显示模板或使用“智能一页纸”。',
 '点击“打印 / PDF”进入打印流程，完成后可返回面试详情继续查看报告。'],
 '此入口与一条具体面试关联；未递交简历的记录不会提供同样内容。本次未打印，截图中的真实联系方式已遮盖。',
 '递交简历页已核验  未打印')

item('G02','通用','选择页面主题','56-theme','页面右上角 → 主题',[
 '点击“主题”打开选择面板，查看亮色和暗色外观。',
 '亮色主题可选择奶油、鼠尾草、雾蓝、薰衣草或玫瑰色调。',
 '选择需要的外观后关闭面板；页面说明偏好会自动保存。'],
 '本次仅展开主题面板，没有切换主题。截图以学生端为例，管理员和企业顶部同样提供主题入口。',
 '主题选项已核验  未变更',(2620,245,3410,1300))
item('G03','通用','自行修改登录密码','22-change-password','右上角姓名 → 修改密码',[
 '在个人菜单进入“修改密码”。',
 '由账号持有人填写当前密码、新密码及确认新密码，页面要求新密码至少 10 个字符。',
 '持有人核对后自行点击“保存新密码”，按页面反馈完成后续登录。'],
 '本次仅查看空表单，没有输入新密码或提交。三种身份均可通过个人菜单找到密码维护入口。',
 '入口及空表单已核验  未改密',(1240,500,2200,1560))
item('G04','学生及管理员','查看 WikiBook 账号关联状态','21-account-links','右上角姓名 → 账号关联设置',[
 '打开关联页面，核对当前 Interview 账号。',
 '若服务已配置，可按页面要求登录 WikiBook 并确认双方身份。',
 '若显示“账号关联服务尚未配置，请联系管理员”，停止关联并交由平台管理员处理。'],
 '本次实际显示未配置，关联按钮禁用，因此不能完成绑定。企业账号个人菜单中未见该入口。',
 '当前未配置  暂不可完成关联',(390,390,3040,1800))
item('G05','通用','退出并切换账号','20-account-menu','右上角姓名 → 退出登录',[
 '点击右上角姓名，核对菜单显示的账号标识。',
 '点击“退出登录”，确认页面回到登录入口。',
 '需要其他身份时输入对应账号重新登录，再核对目标工作台。'],
 '本次三个账号均通过各自身份实际登录取证，切换前均退出；采集结束已退出最后使用的账号。',
 '登录切换与退出已实际核验',(2420,245,3100,1050))

# Crop UI screenshots to the relevant page region, preserving genuine pixels.
# Redactions are limited to private contact values; page structure is unchanged.
REDACTIONS={
 '16-student-resume-editor':[(520,611,708,640),(752,611,952,640),(1280,428,1480,451)],
 '52-company-resume':[(854,552,1118,580)],
 '60-admin-resume-preview':[(578,555,794,610)],
}
def figure(it):
    im=Image.open(SHOTS/(it['shot']+'.png')).convert('RGB')
    sx,sy=im.width/2048,im.height/1217
    draw=ImageDraw.Draw(im)
    for a,b,c,d in REDACTIONS.get(it['shot'],[]):
        draw.rectangle((int(a*sx),int(b*sy),int(c*sx),int(d*sy)),fill='#D7D7D7')
    crop=it['crop'] or (390,420,3040,1940)
    im=im.crop(crop)
    dest=FIGS/(it['code']+'.png')
    im.save(dest,optimize=True)
    return dest, im.size

doc=Document()
sec=doc.sections[0]
sec.orientation=WD_ORIENT.LANDSCAPE
sec.page_width=Inches(11.693)
sec.page_height=Inches(8.268)
sec.top_margin=Inches(.5)
sec.bottom_margin=Inches(.5)
sec.left_margin=Inches(.65)
sec.right_margin=Inches(.65)
sec.header_distance=Inches(.18)
sec.footer_distance=Inches(.18)

def font(style,size,bold=False):
    style.font.name='Arial Unicode MS'
    style.font.size=Pt(size)
    style.font.bold=bold
    style.font.color.rgb=RGBColor(0,0,0)
    style.element.get_or_add_rPr().rFonts.set(qn('w:eastAsia'),'Arial Unicode MS')
    style.paragraph_format.space_after=Pt(4)
    style.paragraph_format.line_spacing=1.15

font(doc.styles['Normal'],10.5)
font(doc.styles['Title'],29,True)
font(doc.styles['Subtitle'],14)
font(doc.styles['Heading 1'],19,True)
font(doc.styles['Heading 2'],14,True)
font(doc.styles['Caption'],8.5)
for sty in ['Title','Subtitle','Heading 1','Heading 2']:
    doc.styles[sty].paragraph_format.keep_with_next=True
for style in doc.styles:
    for border in list(style.element.iter(qn('w:pBdr'))):
        border.getparent().remove(border)

header=sec.header.paragraphs[0]
header.text='嘉善技师学院 AI 智聘平台     三角色功能流程手册'
header.style='Caption'
footer=sec.footer.paragraphs[0]
footer.alignment=WD_ALIGN_PARAGRAPH.RIGHT
footer.add_run('2026 年 10 月 21 日核验     第 ')
fld=OxmlElement('w:fldSimple'); fld.set(qn('w:instr'),'PAGE'); footer._p.append(fld)
footer.add_run(' 页')
for r in footer.runs: r.font.size=Pt(8)

def para(text,boldlead=None):
    p=doc.add_paragraph()
    if boldlead:
        p.add_run(boldlead).bold=True
    p.add_run(text)
    return p

def bookmark(p,name):
    start=OxmlElement('w:bookmarkStart'); start.set(qn('w:id'),str(100+len(doc.paragraphs))); start.set(qn('w:name'),name)
    end=OxmlElement('w:bookmarkEnd');end.set(qn('w:id'),start.get(qn('w:id')))
    p._p.insert(0,start); p._p.append(end)

def link(p,text,anchor):
    h=OxmlElement('w:hyperlink');h.set(qn('w:anchor'),anchor)
    r=OxmlElement('w:r'); pr=OxmlElement('w:rPr')
    col=OxmlElement('w:color');col.set(qn('w:val'),'000000');pr.append(col)
    r.append(pr);t=OxmlElement('w:t');t.text=text;r.append(t);h.append(r);p._p.append(h)

def table(rows,widths):
    t=doc.add_table(rows=0,cols=len(widths)); t.autofit=False
    for col,w in zip(t.columns,widths): col.width=Inches(w)
    for i,row in enumerate(rows):
        cells=t.add_row().cells
        for c,w,txt in zip(cells,widths,row):
            c.width=Inches(w);c.text=txt
            tcpr=c._tc.get_or_add_tcPr()
            borders=OxmlElement('w:tcBorders')
            for edge in ['top','left','bottom','right']:
                e=OxmlElement('w:'+edge);e.set(qn('w:val'),'single');e.set(qn('w:sz'),'4');e.set(qn('w:color'),'D9D9D9');borders.append(e)
            tcpr.append(borders)
            mar=OxmlElement('w:tcMar')
            for edge in ['top','left','bottom','right']:
                e=OxmlElement('w:'+edge);e.set(qn('w:w'),'95');e.set(qn('w:type'),'dxa');mar.append(e)
            tcpr.append(mar)
            va=OxmlElement('w:vAlign');va.set(qn('w:val'),'center');tcpr.append(va)
            shade=OxmlElement('w:shd');shade.set(qn('w:fill'),'244459' if i==0 else ('F3F6F8' if i%2==0 else 'FFFFFF'));tcpr.append(shade)
            for p in c.paragraphs:
                p.paragraph_format.space_after=Pt(1)
                for r in p.runs:
                    r.font.size=Pt(10.5)
                    r.font.bold=i==0
                    r.font.color.rgb=RGBColor.from_string('FFFFFF' if i==0 else '000000')
        if i==0:
            rep=OxmlElement('w:tblHeader');t.rows[-1]._tr.get_or_add_trPr().append(rep)
    return t

# Front matter is kept compact: purpose, role mapping, workflow and navigation.
doc.add_paragraph('嘉善技师学院 AI 智聘平台',style='Title')
doc.add_paragraph('学生 管理员 企业功能流程手册',style='Subtitle')
para('本手册依据指定网站的三个账号实际登录与页面截图编写，帮助学生完成学习与面试练习、帮助管理员开展教学管理、帮助企业查看岗位与面试材料。每项功能给出入口、操作顺序及核验边界，可配合截图逐项使用。')
para('站点  http://211.154.20.65:20018        核验日期  2026 年 10 月 21 日        版本  1.0')
table([
 ['使用视角','核验账号','页面身份','主要工作台'],
 ['学生','222308','刘海','面试大厅与个人成长练习'],
 ['管理员','lzy','劳振煜','教学工作空间与全校管理'],
 ['企业','zjczkj','浙江创智科技  宋经理','企业招聘工作台'],
],[1.2,1.4,2.8,4.9])
doc.add_paragraph('三种视角的推荐流程',style='Heading 2')
para('学生  基础档案 → 简历 → 学习资料 → 岗位面试配置或单题快练 → 历史报告 → 能力成长')
para('管理员  系部班级与学生 → 课程题库 → 企业与岗位 → 面试流水 → 个体学情及班级能力分析')
para('企业  岗位维护 → 本公司面试记录 → 报告与对话 → 递交简历 → 推荐依据及面试证据')
para('密码不纳入文档。截图仅裁剪界面并遮盖部分联系方式；示例姓名、学号、成绩与画面来自账号可见的历史数据，按内部操作资料使用。')

doc.add_page_break()
doc.add_paragraph('阅读说明与核验范围',style='Heading 1')
para('功能页按学生 S、管理员 A、企业 E、通用 G 编号。阅读时先确认身份，再根据入口路径操作；截图为采集当时页面，后续数据与布局变化以网站为准。')
doc.add_paragraph('如何理解核验状态',style='Heading 2')
table([
 ['标记','本次实际完成的工作','使用时的含义'],
 ['页面已核验','已登录对应账号并打开相关页面或历史数据','说明功能入口和可见界面，不等于全流程测试通过'],
 ['表单已核验 未提交','已打开新增 编辑 导入等操作表单','保存 导入 发布的结果未实测，应按真实业务需要操作'],
 ['当前未配置','页面提示服务未配置或按钮禁用','只说明现状，不把该入口写成已可完成的功能'],
],[1.9,4.4,4.0])
doc.add_paragraph('本次操作边界',style='Heading 2')
para('已核验三种身份登录、菜单导航、学生学号筛选、历史报告与对话、简历只读预览、课程与岗位表单，以及退出登录。没有新增正式面试、提交测验、发布岗位、导入名单、重置密码或保存系统配置变更。基础档案取证中发生一次原值保存，字段内容没有更改。')
para('标准岗位面试未启动新会话，手册用配置页和历史回顾页说明入口及复盘流程；实时语音、实时视频、生成诊断、匹配度计算、参考回答展开和 PDF 输出未做端到端验证。相关页均说明边界。')
doc.add_paragraph('当前站点的使用条件',style='Heading 2')
para('HTTP 地址下，网页提示麦克风与摄像头需要安全连接。正式使用宜由管理员提供带有效证书的 HTTPS 地址；本次没有修改浏览器安全策略或开启设备权限。WikiBook 账号关联服务当前未配置，学生及管理员端的绑定按钮不可用。')
para('截图中的统计是采集快照，不能把横线当成零分。管理员查看的是当前权限范围；企业页面说明仅查看所属公司内容，本次未进行越权访问验证。')

# Two index pages, linked to bookmarked function headings.
index_groups=[('学生与通用登录', [x for x in items if x['code']=='G01' or x['code'].startswith('S')]),
              ('管理员', [x for x in items if x['code'].startswith('A')]),
              ('企业与公共功能', [x for x in items if x['code'].startswith('E') or x['code'] in ['G02','G03','G04','G05']])]
front_count=5
for group,subset in index_groups:
    doc.add_page_break()
    doc.add_paragraph(group+'功能索引',style='Heading 1')
    para('点击功能名称可跳转；也可使用 Word 导航窗格浏览标题。')
    for it in subset:
        p=doc.add_paragraph();p.paragraph_format.space_after=Pt(0)
        p.paragraph_format.line_spacing=Pt(18)
        pg=front_count+items.index(it)+1
        link(p, f"{it['code']}  {it['title']}    {pg}",it['code'])

manifest=[]
for i,it in enumerate(items):
    doc.add_page_break()
    p=doc.add_paragraph(f"{it['code']}  {it['title']}",style='Heading 1');bookmark(p,it['code'])
    pp=para(f"{it['role']}  |  入口：{it['entry']}  |  核验：{it['status']}")
    for r in pp.runs:r.font.size=Pt(9)
    img,sz=figure(it)
    maxw,maxh=10.3,4.25
    w=min(maxw,maxh*sz[0]/sz[1]);h=w*sz[1]/sz[0]
    p=doc.add_paragraph();p.alignment=WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after=Pt(0);p.paragraph_format.line_spacing=1
    run=p.add_run();shape=run.add_picture(str(img),width=Inches(w))
    shape._inline.docPr.set('descr',f"{it['role']}界面 {it['title']} 实站截图")
    p=doc.add_paragraph(f"图 {i+1:02d}  {it['title']}  采集自指定站点" ,style='Caption')
    p.alignment=WD_ALIGN_PARAGRAPH.CENTER;p.paragraph_format.space_after=Pt(5)
    for j,step in enumerate(it['steps'],1):
        p=para(step,boldlead=f'{j}  ')
        p.paragraph_format.space_after=Pt(3)
    p=para(it['result'],boldlead='结果与说明  ')
    p.paragraph_format.space_after=Pt(0)
    for r in p.runs:r.font.size=Pt(9.5)
    manifest.append(dict(code=it['code'],title=it['title'],page=front_count+i+1,source=it['shot']+'.png',figure=img.name,status=it['status']))

doc.core_properties.title='嘉善技师学院 AI 智聘平台三角色功能流程手册'
doc.core_properties.subject='学生 管理员 企业的实际页面与操作流程'
doc.core_properties.author=''
doc.core_properties.keywords='操作手册 功能流程 实站截图'
doc.core_properties.comments=''
for p in doc.paragraphs:
    for border in list(p._p.iter(qn('w:pBdr'))):
        border.getparent().remove(border)
dest=ROOT/'AI智聘平台三角色功能流程手册.docx'
doc.save(dest)
(ROOT/'manual-content.json').write_text(json.dumps(items,ensure_ascii=False,indent=2))
(ROOT/'figure-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
md=['# 嘉善技师学院 AI 智聘平台三角色功能流程手册','', '核验日期：2026 年 10 月 21 日。站点：http://211.154.20.65:20018。',
    '', '本文件为可维护文字源；完整排版与核验范围见同目录 Word 手册。','']
for it in items:
    md += [f"## {it['code']} {it['title']}",'',f"身份：{it['role']}。入口：{it['entry']}。核验：{it['status']}。",'',f"![{it['title']}](figures/{it['code']}.png)",'']
    md += [f'{j}. {s}' for j,s in enumerate(it['steps'],1)]
    md += ['',it['result'],'']
(ROOT/'手册文字源.md').write_text('\n'.join(md))
print(json.dumps({'output':str(dest),'functions':len(items),'planned_pages':front_count+len(items),'images':len(manifest)},ensure_ascii=False))
