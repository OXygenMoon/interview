import json
import logging
from urllib.parse import urlsplit
from openai import OpenAI
from ..config import Config
from .interview_prompts import (
    CHAT_PROMPT, CHAT_PROMPT_VERSION, DETAILS_PROMPT,
    OVERALL_PROMPT, RANDOM_ANSWER_PROMPT, REPORT_PROMPT_VERSION,
    STUDENT_MODES, VISION_PROMPT, VISION_REVIEW_PROMPT,
    get_assessment_prompt, get_interaction_mode, get_round_scope,
)
from .local_asr import ASRUnavailableError, AudioDecodeError, transcribe_local_audio
from .visual_review import normalize_visual_feedback

# 面试文本及视觉请求使用配置的 OpenAI 兼容服务。
client = OpenAI(
    api_key=Config.LLM_API_KEY,
    base_url=Config.LLM_BASE_URL
)


def chat_request_options():
    """仅向 DeepSeek 发送其扩展参数，兼容其他 OpenAI 格式服务。"""
    if urlsplit(Config.LLM_BASE_URL).hostname == 'api.deepseek.com':
        return {'extra_body': {'thinking': {'type': Config.LLM_THINKING}}}
    return {}

import re


class AIServiceError(RuntimeError):
    """AI output is unavailable or invalid and must not become a score."""


REQUIRED_SCORE_DIMENSIONS = ("专业技能", "逻辑思维", "语言表达", "抗压能力", "礼仪态度")
SCORE_WEIGHTS = (40, 25, 20, 10, 5)


def parse_json_safely(text):
    """
    清洗 AI 返回的文本，确保能被 json.loads 解析
    移除 ```json 和 ``` 标记
    """
    if not text: return {}

    # 1. 移除 Markdown 代码块标记
    cleaned_text = re.sub(r'```json\s*', '', text, flags=re.IGNORECASE)
    cleaned_text = re.sub(r'```', '', cleaned_text)

    # 2. 移除首尾空白
    cleaned_text = cleaned_text.strip()

    try:
        return json.loads(cleaned_text)
    except json.JSONDecodeError:
        print(f"❌ JSON 解析失败，原始文本: {text[:100]}...")
        return {}


def _build_interview_messages(history_messages, target_role, difficulty, context_info, visual_context_str, round_num=1):
    """构建面试对话的消息列表（系统提示 + 历史）。供流式/非流式共用。round_num 控制面试官人设。"""
    # Only application-owned instructions enter the system message. Candidate
    # profiles and role names remain explicitly untrusted data.
    mode_prompt = get_interaction_mode(difficulty)
    round_scope = get_round_scope(round_num, difficulty)
    system_prompt = f"{CHAT_PROMPT}\n【本轮范围】{round_scope}\n【互动模式】{mode_prompt}"
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": json.dumps({
            "data_type": "interview_background",
            "target_role": target_role,
            "reference_material": context_info or "",
        }, ensure_ascii=False)},
    ]
    # Visual feedback is for the UI only; it must not steer interviewing.
    for msg in history_messages:
        if getattr(msg, 'generation_status', 'completed') != 'completed':
            continue
        role = "assistant" if msg.sender == "ai" else "user"
        messages.append({"role": role, "content": msg.content})
    return messages


def get_ai_response(history_messages, target_role="Python工程师", difficulty = "标准模式", context_info="", visual_context_str="", round_num=1):
    """非流式调用面试模型（保留用于兼容路径）。"""
    messages = _build_interview_messages(history_messages, target_role, difficulty, context_info, visual_context_str, round_num)
    try:
        print(f"正在请求面试模型: {Config.LLM_MODEL_NAME} ...")
        response = client.chat.completions.create(
            **chat_request_options(),
            model=Config.LLM_MODEL_NAME,
            messages=messages,
            temperature=0.7,
            max_tokens=512,
            top_p=0.9
        )
        return response.choices[0].message.content

    except Exception as e:
        print(f"❌ LLM API Error: {e}")
        # 错误处理：返回中性兜底，避免把 SDK 错误串写入历史并被 TTS 朗读
        return "抱歉，我刚才走神了，能再说一遍吗？"


def stream_ai_response(history_messages, target_role="Python工程师", difficulty="标准模式", context_info="", visual_context_str="", round_num=1):
    """流式调用：逐 token yield 内容片段。出错抛异常，由调用方捕获并兜底。"""
    messages = _build_interview_messages(history_messages, target_role, difficulty, context_info, visual_context_str, round_num)
    print(f"正在流式请求面试模型: {Config.LLM_MODEL_NAME} ...")
    response = client.chat.completions.create(
        **chat_request_options(),
        model=Config.LLM_MODEL_NAME,
        messages=messages,
        temperature=0.7,
        max_tokens=512,
        top_p=0.9,
        stream=True,
    )
    for chunk in response:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta
        content = getattr(delta, "content", None)
        if content:
            yield content


def evaluate_random_answer(question, answer):
    """
    单题问答评估：返回 score / evaluation / suggestion
    """
    system_prompt = RANDOM_ANSWER_PROMPT
    user_prompt = json.dumps({"question": question, "answer": answer}, ensure_ascii=False)

    try:
        response = client.chat.completions.create(
            **chat_request_options(),
            model=Config.LLM_REPORT,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.1,
            response_format={"type": "json_object"}
        )

        parsed = parse_json_safely(response.choices[0].message.content)
        if not isinstance(parsed, dict) or 'score' not in parsed:
            raise ValueError('missing score')
        score = int(parsed['score'])
        score = max(0, min(100, score))
        evaluation = str(parsed.get('evaluation') or '').strip()
        suggestion = str(parsed.get('suggestion') or '').strip()
        if not evaluation or not suggestion:
            raise ValueError('missing evaluation or suggestion')

        return {
            "score": score,
            "evaluation": evaluation,
            "suggestion": suggestion,
        }
    except Exception as e:
        print(f"❌ 单题评估失败: {e}")
        raise AIServiceError('单题评估服务暂时不可用') from e


def generate_interview_report(history_messages, target_role, round_num=1,
                              difficulty="标准模式", position_context=None):
    """
    面试结束时调用：采用【双通道分析】策略
    """
    print("🚀 开始生成面试报告 (含参考答案)...")

    transcript = []
    qa_pairs = []
    qa_message_ids = []

    # === 核心逻辑：组装 Q & A 对 ===
    # 我们需要找到每一条 User 消息，并找到它“紧邻的前一条” AI 消息作为问题

    temp_question = "（面试官开场白/未记录的问题）"  # 默认值

    for msg in history_messages:
        if getattr(msg, 'generation_status', 'completed') != 'completed':
            continue
        transcript.append({
            "message_id": getattr(msg, 'id', None),
            "sender": msg.sender,
            "content": msg.content or "",
        })

        if msg.sender == 'ai':
            temp_question = msg.content  # 记录当前问题

        elif msg.sender == 'user':
            # A one-character answer can be meaningful; length is not quality.
            if (msg.content or '').strip():
                qa_pairs.append({
                    "question": temp_question,
                    "answer": msg.content
                })
                qa_message_ids.append(getattr(msg, 'id', None))

    if not qa_pairs:
        # The legacy UI requires numbers. These zeros are evidence placeholders,
        # not a judgment about abilities; a nullable report needs a UI migration.
        return {
            'overall': {
                'scores': dict.fromkeys(REQUIRED_SCORE_DIMENSIONS, 0),
                'evaluated_dimensions': [],
                'total_score': 0,
                'comment': '本次没有候选人作答证据，尚不能形成整体能力评价。'
                           '五维均未评估；0 为未展示证据占位，不代表实际能力为零。'
                           '建议完成岗位相关问题后重新评估。',
            },
            'details_list': [],
            'evaluation_source': 'rule',
        }

    # Structured sender fields prevent quoted role labels from becoming roles.
    # No visual observations are sent to either scoring or coaching.
    full_text = json.dumps(transcript, ensure_ascii=False)
    round_count = len(qa_pairs)  # Legacy metadata, not proof of completeness.
    overall_data = _get_overall_score(
        full_text, target_role, round_count, round_num, difficulty, position_context,
    )
    details_list = _get_details_feedback(qa_pairs, target_role, round_num, difficulty)
    identified_details = []
    for message_id, detail in zip(qa_message_ids, details_list):
        if isinstance(detail, dict):
            detail = dict(detail)
            detail['message_id'] = message_id
        identified_details.append(detail)

    return {
        "overall": overall_data,
        "details_list": identified_details
    }

def _get_overall_score(full_text, target_role, round_count=0, round_num=1,
                       difficulty="标准模式", position_context=None):
    """Evaluate recorded evidence with the compatible numeric report contract."""
    print("📊 正在进行整体打分...")
    # Retained until report/UI support a distinct insufficient-evidence state.
    cap = 60 if round_count < 3 else 100
    system_prompt = get_assessment_prompt(OVERALL_PROMPT, difficulty, round_num)
    user_prompt = json.dumps({
        "target_role": target_role,
        "round_scope": get_round_scope(round_num, difficulty),
        "difficulty": difficulty,
        "position_context": position_context or {},
        "message_count": round_count,
        "legacy_total_cap": cap,
        "transcript": full_text,
    }, ensure_ascii=False)

    try:
        response = client.chat.completions.create(
            **chat_request_options(),
            model=Config.LLM_REPORT,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.1,
            response_format={"type": "json_object"}
        )
        result = parse_json_safely(response.choices[0].message.content)
        if not isinstance(result, dict):
            raise ValueError('overall result is not an object')
        scores = result.get('scores')
        if not isinstance(scores, dict):
            raise ValueError('missing scores')
        clean_scores = {}
        for dimension in REQUIRED_SCORE_DIMENSIONS:
            value = int(scores[dimension])
            if not 0 <= value <= 100:
                raise ValueError(f'invalid score for {dimension}')
            clean_scores[dimension] = value
        total_score = int(result['total_score'])
        if not 0 <= total_score <= 100:
            raise ValueError('invalid total score')
        comment = str(result.get('comment') or '').strip()
        if not comment:
            raise ValueError('missing report comment')
        evaluated_dimensions = result.get('evaluated_dimensions')
        if (not isinstance(evaluated_dimensions, list)
                or any(not isinstance(d, str) or d not in REQUIRED_SCORE_DIMENSIONS
                       for d in evaluated_dimensions)
                or len(set(evaluated_dimensions)) != len(evaluated_dimensions)):
            raise ValueError('invalid evaluated dimensions')
        if any(clean_scores[d] != 0 for d in REQUIRED_SCORE_DIMENSIONS
               if d not in evaluated_dimensions):
            raise ValueError('unassessed dimension has a score')
        if difficulty in STUDENT_MODES:
            if '专业技能' not in evaluated_dimensions:
                cap = 0
            elif clean_scores['专业技能'] < 60:
                cap = min(cap, 59)
        weighted_points = 0
        weight_sum = 0
        for dimension, weight in zip(REQUIRED_SCORE_DIMENSIONS, SCORE_WEIGHTS):
            if dimension in evaluated_dimensions:
                weighted_points += clean_scores[dimension] * weight
                weight_sum += weight
        weighted_score = ((weighted_points + weight_sum // 2) // weight_sum
                          if weight_sum else 0)
        result = {
            'scores': clean_scores,
            'evaluated_dimensions': evaluated_dimensions,
            # Recompute for every mode so placeholder zeros or an inconsistent
            # model total cannot penalize dimensions that were never assessed.
            'total_score': min(weighted_score, cap),
            'comment': comment,
        }
        unassessed = [d for d in REQUIRED_SCORE_DIMENSIONS if d not in evaluated_dimensions]
        scope_note = (f'本分数为{difficulty}下已考察范围的入门练习得分。'
                      if difficulty in STUDENT_MODES else '本分数为本轮已考察范围的表现得分。')
        if unassessed:
            scope_note += '、'.join(unassessed) + '未评估，0为占位，不参与总分。'
        result['comment'] = scope_note + comment
        return result
    except Exception as e:
        print(f"❌ 整体打分失败: {e}")
        raise AIServiceError('整体报告评分失败') from e


def _get_details_feedback(user_answers, target_role, round_num=1, difficulty="标准模式"):
    """
    内部函数：请求 AI 对用户回答列表进行逐一按顺序点评
    user_answers: 按顺序排列的 question / answer 对象列表
    """
    if not user_answers:
        return []  # 返回空列表

    print(f"📝 正在分析 {len(user_answers)} 组问答数据 (生成点评+范例)...")

    system_prompt = get_assessment_prompt(DETAILS_PROMPT, difficulty, round_num)
    user_prompt = json.dumps({
        "target_role": target_role,
        "round_scope": get_round_scope(round_num, difficulty),
        "difficulty": difficulty,
        "qa_pairs": user_answers,
    }, ensure_ascii=False)

    try:
        response = client.chat.completions.create(
            **chat_request_options(),
            model=Config.LLM_REPORT,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.1,
            response_format={"type": "json_object"}
        )

        # 使用安全解析器
        result = parse_json_safely(response.choices[0].message.content)

        reviews = result.get('reviews', [])
        if not isinstance(reviews, list) or len(reviews) != len(user_answers):
            raise ValueError('review count does not match answer count')
        clean_reviews = []
        for review in reviews:
            if not isinstance(review, dict):
                raise ValueError('review is not an object')
            suggestion = str(review.get('suggestion') or '').strip()
            reference = str(review.get('reference') or '').strip()
            is_good = review.get('is_good')
            if not suggestion or not reference or not isinstance(is_good, bool):
                raise ValueError('review fields are incomplete')
            clean_reviews.append({
                'suggestion': suggestion,
                'reference': reference,
                'is_good': is_good,
            })
        return clean_reviews

    except Exception as e:
        print(f"❌ 逐句点评失败: {e}")
        raise AIServiceError('逐题点评失败') from e
def transcribe_audio(audio_file_path):
    """在部署机器上识别录音，转写文字由调用方交给 DeepSeek。"""
    try:
        return transcribe_local_audio(audio_file_path)
    except AudioDecodeError:
        logging.getLogger(__name__).exception('录音解码失败')
        raise
    except ASRUnavailableError as e:
        logging.getLogger(__name__).exception('本地语音识别组件不可用')
        raise AIServiceError('语音识别服务尚未就绪，请联系管理员检查本地模型和录音解码组件') from e
    except Exception as e:
        logging.getLogger(__name__).exception('本地语音识别失败')
        raise AIServiceError('语音识别暂时不可用，请稍后重试或输入文字') from e


def analyze_resume_tags(resume_text):
    """
    功能：从简历中提取 5-8 个核心技能关键词
    """
    if not resume_text: return ""

    system_prompt = """
    你是一个专业的简历分析师。请阅读用户的简历内容，提取出 5 到 8 个最核心的“硬技能”或“软技能”关键词。
    要求：
    1. 只返回关键词，用英文逗号分隔。
    2. 不要包含任何其他废话或前缀。
    3. 例如返回：Python, 数据分析, 沟通能力, 英语六级, MySQL
    """

    try:
        response = client.chat.completions.create(
            **chat_request_options(),
            model=Config.LLM_MODEL_NAME,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": resume_text[:2000]}  # 防止太长
            ],
            temperature=0.3  # 低创造性，更精准
        )
        return response.choices[0].message.content.replace('，', ',').strip()
    except Exception as e:
        print(f"标签提取失败: {e}")
        return ""


def anonymize_resume_pii(resume_text):
    """
    功能：隐私脱敏，将姓名、手机号、邮箱替换为 ***
    """
    if not resume_text: return ""

    system_prompt = """
    请对下面的简历文本进行“隐私脱敏”处理。
    任务：
    1. 将所有的【真实姓名】替换为 "**"
    2. 将所有的【手机号】替换为 "138****0000"
    3. 将所有的【邮箱地址】替换为 "***@mail.com"
    4. 身份证号如果存在，替换为 "******************"
    5. 保持简历的其他内容、格式、换行完全不变！不要试图总结或重写简历，只做替换。
    """

    try:
        response = client.chat.completions.create(
            **chat_request_options(),
            model=Config.LLM_MODEL_NAME,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": resume_text}
            ],
            temperature=0.1  # 极低创造性，严格遵循指令
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"脱敏失败: {e}")
        return resume_text  # 失败则返回原位


def analyze_image(image_base64, detailed=False):
    """
    功能：调用配置的视觉模型分析图片
    image_base64: Base64 编码的图片字符串 (带前缀 data:image/jpeg;base64,...)
    """
    if not image_base64:
        return ""

    print("🖼️ 正在进行视觉分析...")

    system_prompt = VISION_REVIEW_PROMPT if detailed else VISION_PROMPT

    try:
        response = client.chat.completions.create(
            **chat_request_options(),
            model=Config.VLM_MODEL_NAME,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": system_prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": image_base64
                            }
                        }
                    ]
                }
            ],
            temperature=0.1,
            max_tokens=350 if detailed else 100
        )
        result = response.choices[0].message.content
        # 尝试清理可能存在的 markdown 标记
        cleaned_result = result.replace('```json', '').replace('```', '').strip()
        if detailed:
            review = json.loads(cleaned_result)
            if not isinstance(review, dict) or not isinstance(review.get('tags'), list) or not isinstance(review.get('comment'), str) or not review['comment'].strip():
                raise ValueError('invalid visual review')
            cleaned_result = json.dumps(normalize_visual_feedback(review), ensure_ascii=False)
        print(f"👁️ 视觉分析结果: {cleaned_result}")
        return cleaned_result

    except Exception as e:
        print(f"❌ 视觉分析失败: {e}")
        return ""
