"""Server-owned questions and completion checks for all five interview dimensions."""

import re


DIMENSIONS = ('专业技能', '逻辑思维', '语言表达', '抗压能力', '礼仪态度')


def required_questions(difficulty, round_num=1):
    difficulty = difficulty or '标准模式'
    student = difficulty in ('新手模式', '标准模式')
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


def dimension_answers(history, difficulty, round_num=1):
    questions = required_questions(difficulty, round_num)
    evidence = {}
    pending = None
    for message in history:
        if getattr(message, 'generation_status', 'completed') != 'completed':
            continue
        content = (message.content or '').strip()
        if message.sender == 'ai':
            normalized = _normalized(content)
            # One turn must ask only one question. Match only assistant text,
            # never a candidate's claim that a dimension has been covered.
            matches = [d for d, q in questions.items()
                       if _normalized(q) in normalized]
            pending = (matches[0], content) if len(matches) == 1 else None
        elif message.sender == 'user' and pending and content:
            if _normalized(content) in {
                '谢谢', '再见', '结束', '结束面试', '面试结束', '我要结束面试',
                '我想结束面试', '请结束面试', '不想继续了', '我不知道该怎么说',
                '请解释题意', '什么意思', '没听清', '请再说一遍',
            }:
                continue
            dimension, question = pending
            evidence[dimension] = {'question': question, 'answer': content}
            pending = None
    return evidence


def missing_dimensions(history, difficulty, round_num=1):
    evidence = dimension_answers(history, difficulty, round_num)
    return [d for d in required_questions(difficulty, round_num) if d not in evidence]


def coverage_instructions(history, difficulty, round_num=1):
    questions = required_questions(difficulty, round_num)
    missing = missing_dimensions(history, difficulty, round_num)
    plan = '\n'.join(f'{dimension}：{question}' for dimension, question in questions.items())
    state = ('下一道必答题：' + questions[missing[0]] if missing
             else '五维必答题均已作答，可以按需补充练习；不重复必答题。')
    return (
        '\n【五维必答题与完成检查】\n'
        '每一轮、每一种难度都必须考察专业技能、逻辑思维、语言表达、抗压能力、礼仪态度。'
        '以下五道必答题必须分别出现并等待作答，不能只问专业或自我介绍。'
        '必答问句原样保留，可以在前后加一句自然的回应或提示，不输出维度标签。'
        '一次只问一道，按下列顺序优先补齐；不要先连续深挖专业知识。'
        '答错或明确不会仍算已考察，允许按当前模式辅导。澄清或结束语不算作答。'
        '抗压题是一个真实的小困难情境，不要求严厉语气；礼仪题要求实际沟通用语。'
        '不能用自述抗压强、一句谢谢、上一轮表现代替必答题。'
        '五维未齐时不主动收尾、不声称完成；希望结束时说明还需补充的问题，'
        '用户无法继续时尊重其停止意愿，不能谎称已经完成五维评估。\n'
        + plan + '\n尚需作答的维度：' + ('、'.join(missing) or '无') + '\n' + state
    )
