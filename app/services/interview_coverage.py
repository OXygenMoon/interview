"""Plan five interview topics during conversation; never gate a user's finish request."""

import re

from .interview_prompts import STUDENT_MODES


DIMENSIONS = ('专业技能', '逻辑思维', '语言表达', '抗压能力', '礼仪态度')


def required_questions(difficulty, round_num=1):
    difficulty = difficulty or '标准模式'
    student = difficulty in STUDENT_MODES
    skills = {
        1: '这个岗位平时主要做什么？请说出一项你了解的工作。',
        2: '请说出这个岗位会用到的一项工具或技能，以及它的用途。',
        3: '如果接到一项岗位相关但还不会的任务，你会怎样学习并完成它？',
    }
    questions = {
        '专业技能': skills.get(round_num, skills[1]),
        '逻辑思维': '如果要完成一项岗位相关的小任务，你会先做什么、再做什么？',
        '抗压能力': ('假设实训任务快到提交时间了，但你还有一部分没完成，你会怎么办？'
                     if student else '假设工作快到交付时间了，但需求临时改变，你会如何应对？'),
        '语言表达': '请用一两句话，向不了解这个岗位的人说明它的一项工作内容。',
        '礼仪态度': ('假设同学给你的资料有一处不清楚，你会怎样礼貌地向他确认？请直接说出你会说的话。'
                     if student else '假设同事给你的资料有一处不清楚，你会怎样礼貌地向他确认？请直接说出你会说的话。'),
    }
    if difficulty == '新手模式':
        hints = {
            '专业技能': '可以从课堂或实训中接触过的内容说起。',
            '逻辑思维': '说出两个简单步骤就可以。',
            '抗压能力': '可以想想怎样安排剩余任务，或怎样向老师求助。',
            '语言表达': '用自己的话简单说明就可以。',
            '礼仪态度': '可以从“你好，我想确认一下”开始。',
        }
        questions = {d: q + hints[d] for d, q in questions.items()}
    return questions


def _normalized(text):
    # ASR and the interviewer may change punctuation without changing the question.
    return re.sub(r'[\W_]+', '', text or '')


def _question_dimension(content, questions):
    normalized = _normalized(content)
    # Match the question itself, without requiring optional coaching wording.
    for dimension, question in questions.items():
        if _normalized(question.split('？')[0]) in normalized:
            return dimension

    # Coverage is advisory for planning, not a condition for ending. Accept
    # familiar paraphrases from both text and voice interviews. Inspect asking
    # sentences so a reflection on the last answer cannot reset the topic.
    sentences = re.split(r'(?<=[。！？!?])', content)
    asking = ''.join(s for s in sentences if re.search(
        r'[？?]|怎么|怎样|如何|什么|为什么|请.*(?:说|讲|介绍|说明)|说说|讲讲|用.*(?:介绍|说明|描述)|向.*(?:介绍|说明)', s))
    patterns = (
        ('礼仪态度', r'礼貌|怎样.*(?:开口|确认|沟通)|怎么.*(?:开口|确认|沟通)|你会.*(?:说的话|怎么说)'),
        ('抗压能力', r'来不及|截止|快到.*(?:时间|交付|提交)|时间.*(?:紧|不够|不足)|需求.*(?:改变|变化)|任务.*(?:冲突|变化)|遇到.*(?:困难|突发)|压力.*(?:应对|处理)'),
        ('语言表达', r'用.*(?:一句|两句|一两句|几句|自己的话).*(?:介绍|说明|描述)|向.*(?:不了解|不熟悉).*(?:介绍|说明)'),
        ('逻辑思维', r'先.*再|步骤|顺序|流程|怎样安排|怎么安排|如何安排'),
        ('专业技能', r'岗位.*(?:做什么|职责|工作|技能|工具)|主要.*(?:做什么|工作|职责)|工具.*用途|技能.*用途|怎样.*(?:学习|完成).*任务|(?:项目|实训|操作|产品|业务).*(?:介绍|说明|怎么|怎样|如何)|(?:介绍|说说|讲讲).*(?:项目|技能|经历|工作)'),
    )
    for dimension, pattern in patterns:
        if re.search(pattern, asking):
            return dimension
    return None


def _is_nonanswer(content):
    text = _normalized(content)
    clarification = re.fullmatch(
        r'(?:请|能不能|可以|能|麻烦|帮我)*(?:再说一遍|重复一下|解释一下)(?:题意|问题|这道题|这个问题)?'
        r'|(?:这个问题|这道题|题目|问题)(?:是)?什么意思', text)
    return (bool(clarification) or text.isdigit() or text in {
        '谢谢', '再见', '结束', '结束面试', '面试结束', '我要结束面试',
        '我想结束面试', '请结束面试', '不想继续了', '我不知道该怎么说',
        '请解释题意', '什么意思', '没听清', '请再说一遍', '好', '好的',
        '继续', '请继续', '这题问过了', '这个问题已经回答过了',
    })


def dimension_answers(history, difficulty, round_num=1):
    questions = required_questions(difficulty, round_num)
    evidence = {}
    pending = None
    for message in history:
        if getattr(message, 'generation_status', 'completed') != 'completed':
            continue
        content = (message.content or '').strip()
        if message.sender == 'ai':
            dimension = _question_dimension(content, questions)
            if dimension:
                pending = (dimension, content)
            elif re.search(r'没.*(?:理解|听清)|意思|是指|是说|这道题|这个问题|再说|具体一点|换个说法', content):
                # A clarification stays with the original question. Losing
                # this association caused the repeated finish-time questions.
                continue
            elif '？' in content or '?' in content:
                pending = None
        elif message.sender == 'user' and pending and content:
            if _is_nonanswer(content):
                continue
            dimension, question = pending
            evidence[dimension] = {'question': question, 'answer': content}
            pending = None
    return evidence


def closing_response(history, difficulty, round_num=1):
    completed = [m for m in history if getattr(m, 'generation_status', 'completed') == 'completed']
    last_user = next((m.content or '' for m in reversed(completed) if m.sender == 'user'), '')
    end_request = re.fullmatch(
        r'(?:(?:好的|好|谢谢老师|谢谢面试官|谢谢|请|我想|我要|我希望|我现在要|现在|就|先|那|那么))*'
        r'(?:结束|停止)(?:这场|本场|本次|整个|整场)?面试(?:吧|了|谢谢)*'
        r'|(?:我)?(?:不想继续|无法继续)(?:面试)?(?:了)?', _normalized(last_user))
    if end_request:
        return '好的，面试结束。你可以点击“结束面试”，根据已有回答生成报告。'
    if missing_dimensions(completed, difficulty, round_num):
        return None
    if re.search(r'继续练习|再问|想继续|再来|继续面试', last_user):
        return None
    return '本轮计划的问题已经回答完了，谢谢你的分享。你可以点击“结束面试”查看报告。'


def planned_response(history, difficulty, round_num=1):
    closing = closing_response(history, difficulty, round_num)
    if closing:
        return closing
    completed = [m for m in history if getattr(m, 'generation_status', 'completed') == 'completed']
    if (not completed or completed[-1].sender != 'user'
            or not any(m.sender == 'ai' for m in completed)
            or _is_nonanswer(completed[-1].content or '')):
        # Keep model support for a clarification instead of treating it as an
        # answer. The pending topic remains attached to its original question.
        return None
    missing = missing_dimensions(completed, difficulty, round_num)
    if not missing:
        return None  # The candidate explicitly requested extra practice.
    question = required_questions(difficulty, round_num)[missing[0]]
    return ('谢谢你的回答。' if dimension_answers(completed, difficulty, round_num) else '') + question


def missing_dimensions(history, difficulty, round_num=1):
    evidence = dimension_answers(history, difficulty, round_num)
    return [d for d in required_questions(difficulty, round_num) if d not in evidence]


def coverage_instructions(history, difficulty, round_num=1):
    questions = required_questions(difficulty, round_num)
    missing = missing_dimensions(history, difficulty, round_num)
    plan = '\n'.join(f'{dimension}：{question}' for dimension, question in questions.items())
    state = ('下一道计划题：' + questions[missing[0]] if missing
             else '五维计划题均已作答。现在只做简短收尾，提示点击“结束面试”查看报告，不再自动加题。')
    return (
        '\n【提前规划的五维问题与收尾】\n'
        '每一轮、每一种难度都必须考察专业技能、逻辑思维、语言表达、抗压能力、礼仪态度。'
        '开始前按以下顺序规划五个主题，在正常对话中分别提问并等待作答，不能只问专业或自我介绍。'
        '以下是预先准备的问题，可以结合岗位自然表达，不输出维度标签。'
        '一次只问一道，按下列顺序优先补齐；不要先连续深挖专业知识。'
        '答错或明确不会仍算已考察，允许按当前模式辅导。澄清或结束语不算作答。'
        '抗压题是一个真实的小困难情境，不要求严厉语气；礼仪题要求实际沟通用语。'
        '不能用自述抗压强、一句谢谢、上一轮表现代替必答题。'
        '同一主题已作答就进入下一主题；澄清和追问属于原题，不能因此丢失原题作答。'
        '已有实质作答时直接使用下一道计划题，不再增加同主题细节题；只有请求澄清时解释原题。'
        '不用逐字匹配问句判断完成；已用不同说法问答过的主题不要重问。'
        '正常完成五个主题后立即提示结束，不主动追加练习题或再问一轮。'
        '用户明确要求结束时立即结束，不补问、不要求先答完、不阻止生成报告。'
        '本清单仅用于正常提问安排；历史问句识别可能遗漏，必须结合完整对话核对，'
        '不能因为清单缺项重问已答题，不能在结束按钮提交后插入任何问题。\n'
        + plan + '\n提问安排参考（请结合完整对话核对）：' + ('、'.join(missing) or '已完成') + '\n' + state
    )
