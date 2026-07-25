"""Canonical random-practice question bank validation."""

import json
import re

from .. import db
from ..models import SystemConfig


DEFAULT_RANDOM_INTERVIEW_QUESTIONS = [
    "请你做一个 1 分钟的自我介绍，并突出与岗位相关的优势。",
    "请分享一个你遇到困难并最终解决的问题，重点说说你的思考过程。",
    "如果你和同事在方案上意见不一致，你会如何推进沟通并达成结果？",
    "请举例说明你如何在压力下保证任务质量和交付时间。",
    "你为什么想加入我们公司？你最看重的是什么？",
]


def sanitize_questions(values):
    """Remove blanks, tiny fragments and duplicates while preserving order."""
    cleaned = []
    seen = set()
    for value in values or []:
        question = re.sub(r'\s+', ' ', str(value or '')).strip()
        key = question.casefold()
        if len(question) < 8 or key in seen:
            continue
        seen.add(key)
        cleaned.append(question)
    return cleaned


def get_random_interview_questions():
    raw_value = SystemConfig.get('random_interview_questions', '[]')
    try:
        parsed = json.loads(raw_value) if raw_value else []
    except (TypeError, json.JSONDecodeError):
        parsed = []
    questions = sanitize_questions(parsed if isinstance(parsed, list) else [])
    return questions if len(questions) >= 3 else list(DEFAULT_RANDOM_INTERVIEW_QUESTIONS)


def repair_question_bank():
    """Persist a clean bank so broken historical config cannot reappear."""
    questions = get_random_interview_questions()
    serialized = json.dumps(questions, ensure_ascii=False)
    config = SystemConfig.query.filter_by(key='random_interview_questions').first()
    if config and config.value == serialized:
        return False
    if config:
        config.value = serialized
        config.description = '随机问题面试题库（JSON数组）'
    else:
        db.session.add(SystemConfig(
            key='random_interview_questions',
            value=serialized,
            description='随机问题面试题库（JSON数组）',
        ))
    db.session.commit()
    return True
