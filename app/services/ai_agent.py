import json
from openai import OpenAI
from ..config import Config

# 初始化客户端 (连接到硅基流动)
client = OpenAI(
    api_key=Config.LLM_API_KEY,
    base_url=Config.LLM_BASE_URL
)

import re


class AIServiceError(RuntimeError):
    """AI output is unavailable or invalid and must not become a score."""


REPORT_PROMPT_VERSION = 'interview-report-v2'
CHAT_PROMPT_VERSION = 'interview-chat-v2'
REQUIRED_SCORE_DIMENSIONS = ("专业技能", "逻辑思维", "语言表达", "抗压能力", "礼仪态度")


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
    difficulty_prompts = {
        "新手模式": (
            "你是一位非常友善、循循善诱的面试官。你的目标是帮助新手建立自信。"
            "特点：1. 语气温和鼓励。2. 如果求职者回答不上来，请主动给出提示或引导。3. 即使回答简单，也要给予肯定。"
        ),
        "标准模式": (
            "你是一位专业的企业面试官。请保持职业、中立的态度。"
            "特点：1. 考察专业能力和软技能。2. 流程规范。3. 有追问但不过分刁难。"
        ),
        "压力模式": (
            "你是一位严厉、挑剔、喜欢质疑的资深面试官。你的目标是测试求职者的抗压能力和临场反应。"
            "特点：1. 语气冷淡甚至带有质疑（如'你确定吗？'、'这听起来很普通'）。2. 频繁打断（模拟），对细节通过不断追问来挖掘漏洞。3. 不要给任何提示。"
        )
    }
    mode_prompt = difficulty_prompts.get(difficulty, difficulty_prompts["标准模式"])

    # 进阶链：按轮次切换面试官人设
    round_personas = {
        1: "本轮为【初面】（HR 面）：你是企业的人力资源面试官，重点考察自我介绍、求职动机、沟通表达能力、职业素养与企业文化契合度。语气亲和、轻松。",
        2: "本轮为【复面】（技术面）：你是企业的技术面试官，针对【{role}】岗位深入考察专业技能、项目经验、技术深度与问题解决能力。可以出具体的技术问题、追问实现细节。",
        3: "本轮为【终面】（高管/CTO 面）：你是企业的高管，考察综合素质、战略思维、抗压能力、职业规划与价值观。语气沉稳、有压迫感，会问宏观与开放性问题。",
    }
    round_persona = round_personas.get(round_num, round_personas[1]).format(role=target_role)

    system_prompt = f"""
    你现在是一位专业的面试官，正在面试【{target_role}】岗位。
    {round_persona}
    {mode_prompt}

    {f"【背景资料】\n{context_info}\n" if context_info else ""}

    {f"【视觉观察】\n当前求职者的视觉状态：{visual_context_str}\n请根据此状态适当调整你的语气（如发现紧张则安抚，发现自信则加强挑战）。" if visual_context_str else ""}

    你的行为准则：
    请根据求职者的上一句回答进行回复（提问下一个问题或追问）。
    回答要求：
    1. 简短精炼，口语化，不要长篇大论。
    2. 每次只问一个问题。
    3. 如果求职者提到“谢谢”、“结束”或“再见”，请礼貌回复并说“面试结束”。

    请用口语化的风格交流，不要像个机器人。
    """

    messages = [{"role": "system", "content": system_prompt}]
    for msg in history_messages:
        if getattr(msg, 'generation_status', 'completed') != 'completed':
            continue
        role = "assistant" if msg.sender == "ai" else "user"
        messages.append({"role": role, "content": msg.content})
    return messages


def get_ai_response(history_messages, target_role="Python工程师", difficulty = "标准模式", context_info="", visual_context_str="", round_num=1):
    """非流式调用硅基流动大模型（保留用于兼容路径）。"""
    messages = _build_interview_messages(history_messages, target_role, difficulty, context_info, visual_context_str, round_num)
    try:
        print(f"正在请求硅基流动模型: {Config.LLM_MODEL_NAME} ...")
        response = client.chat.completions.create(
            model=Config.LLM_MODEL_NAME,
            messages=messages,
            temperature=0.7,
            max_tokens=512,
            top_p=0.9
        )
        return response.choices[0].message.content

    except Exception as e:
        print(f"❌ SiliconFlow API Error: {e}")
        # 错误处理：返回中性兜底，避免把 SDK 错误串写入历史并被 TTS 朗读
        return "抱歉，我刚才走神了，能再说一遍吗？"


def stream_ai_response(history_messages, target_role="Python工程师", difficulty="标准模式", context_info="", visual_context_str="", round_num=1):
    """流式调用：逐 token yield 内容片段。出错抛异常，由调用方捕获并兜底。"""
    messages = _build_interview_messages(history_messages, target_role, difficulty, context_info, visual_context_str, round_num)
    print(f"正在流式请求硅基流动模型: {Config.LLM_MODEL_NAME} ...")
    response = client.chat.completions.create(
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
    system_prompt = """
    你是一位严格但专业的面试官。
    你将收到一道面试题与候选人的回答，请按以下 JSON 格式返回：
    {
      "score": 0-100的整数,
      "evaluation": "120字以内，指出回答优劣与关键问题",
      "suggestion": "120字以内，给出可执行的改进建议"
    }
    要求：
    1. 评价必须针对题目与回答本身，不要空话。
    2. 分数要能反映逻辑性、完整性、岗位匹配度与表达清晰度。
    3. 仅返回 JSON，不要输出其他文本。
    """

    user_prompt = f"面试题：{question}\n候选人回答：{answer}"

    try:
        response = client.chat.completions.create(
            model=Config.LLM_REPORT,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.4,
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


def generate_interview_report(history_messages, target_role):
    """
    面试结束时调用：采用【双通道分析】策略
    """
    print("🚀 开始生成面试报告 (含参考答案)...")

    full_text = ""
    qa_pairs = []
    visual_logs = []  # 收集视觉日志

    # === 核心逻辑：组装 Q & A 对 ===
    # 我们需要找到每一条 User 消息，并找到它“紧邻的前一条” AI 消息作为问题

    temp_question = "（面试官开场白/未记录的问题）"  # 默认值

    for msg in history_messages:
        if getattr(msg, 'generation_status', 'completed') != 'completed':
            continue
        role = "面试官" if msg.sender == "ai" else "求职者"
        full_text += f"{role}: {msg.content}\n"

        # 收集视觉信息 (仅 User 发送的)
        if msg.sender == 'user' and msg.visual_context:
             visual_logs.append(f"时刻{msg.timestamp.strftime('%H:%M:%S')}: {msg.visual_context}")

        if msg.sender == 'ai':
            temp_question = msg.content  # 记录当前问题

        elif msg.sender == 'user':
            # 只有当回答长度足够时才分析
            if len(msg.content) > 1:
                qa_pairs.append({
                    "question": temp_question,
                    "answer": msg.content
                })

    # 将视觉日志合并到 full_text 中供整体评分使用
    if visual_logs:
        full_text += "\n\n【视觉/体态观察记录】\n" + "\n".join(visual_logs)

    # 任务 1: 宏观评分（传入实际作答轮数，用于完成度因子）
    round_count = len(qa_pairs)
    overall_data = _get_overall_score(full_text, target_role, round_count)

    # 任务 2: 逐句点评 + 范例生成 (传入 QA 对)
    details_list = _get_details_feedback(qa_pairs, target_role)

    return {
        "overall": overall_data,
        "details_list": details_list
    }

def _get_overall_score(full_text, target_role, round_count=0):
    """内部函数：请求 AI 进行整体打分（含完成度因子）"""
    print("📊 正在进行整体打分...")

    # 完成度上限：依据求职者实际作答轮数
    if round_count < 3:
        cap = 60
        completeness = "不完整（草草结束或中途退出）"
    elif round_count <= 5:
        cap = 100
        completeness = "正常"
    else:
        cap = 100
        completeness = "完整（经历开场→主体→收尾）"

    system_prompt = f"""
    你是一位资深的【{target_role}】面试官。
    请根据面试记录，对求职者进行整体评估。

    【完成度参考】本次面试求职者实际作答约 {round_count} 轮，判定为：{completeness}。
    评分必须体现完成度：
    - 作答不足 3 轮或中途退出：总分上限 60。
    - 3-5 轮：正常评分。
    - 超过 5 轮且经历自我介绍→主体→收尾的完整流程：可给 80 以上。

    请严格返回 JSON 格式：
    {{
        "scores": {{ "专业技能": 0-100, "逻辑思维": 0-100, "语言表达": 0-100, "抗压能力": 0-100, "礼仪态度": 0-100 }},
        "total_score": 0-100 (整数),
        "comment": "300字以内的整体总结评语，包含优点和改进建议。"
    }}
    """

    try:
        response = client.chat.completions.create(
            model=Config.LLM_MODEL_NAME,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": full_text}
            ],
            temperature=0.7,
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
        result = {
            'scores': clean_scores,
            'total_score': min(total_score, cap),
            'comment': comment,
        }
        return result
    except Exception as e:
        print(f"❌ 整体打分失败: {e}")
        raise AIServiceError('整体报告评分失败') from e


def _get_details_feedback(user_answers, target_role):
    """
    内部函数：请求 AI 对用户回答列表进行逐一按顺序点评
    user_answers: 纯文本列表 ['回答1', '回答2', ...]
    """
    if not user_answers:
        return []  # 返回空列表

    print(f"📝 正在分析 {len(user_answers)} 组问答数据 (生成点评+范例)...")

    # 构造清晰的 JSON 数组结构
    answers_json = json.dumps(user_answers, ensure_ascii=False)

    system_prompt = f"""
        你是一位资深的面试教练。你将收到一个列表，包含【面试官问题】和【求职者回答】。

        请针对每一组问答，返回一个 JSON 对象，必须包含以下三个字段：

        1. "suggestion": (字符串) 简短犀利的点评（指出不足或肯定亮点）。
        2. "is_good": (布尔值) 回答是否合格。
        3. "reference": (字符串) 【满分回答范例】。
           - 假设你是一位经验丰富的候选人，针对该问题，给出一个符合 STAR 法则、逻辑清晰、体现专业度的回答。
           - 必须结合【{target_role}】的岗位特点。
           - 范例长度控制在 100-200 字之间，口语化，不要太书面。

        【重要】返回格式必须是 JSON 数组，且长度与输入数组完全一致！
        格式示例：
        {{
            "reviews": [
                {{
                    "suggestion": "...",
                    "is_good": false,
                    "reference": "如果是我的话，我会这样回答：首先..."
                }}
            ]
        }}
        """

    user_prompt = f"求职者回答列表：\n{answers_json}"

    try:
        response = client.chat.completions.create(
            model=Config.LLM_REPORT,  # 这里调用的是不一样的 deepseek
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.7,
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
    """
    将音频文件转换为文字 (ASR)
    使用硅基流动的 SenseVoice 模型
    """
    try:
        print(f"正在进行语音识别: {audio_file_path} ...")

        # 打开本地保存的临时音频文件
        with open(audio_file_path, "rb") as audio_file:
            # 调用 OpenAI 格式的 audio 接口
            transcription = client.audio.transcriptions.create(
                model="FunAudioLLM/SenseVoiceSmall",  # 硅基流动推荐的免费ASR模型
                file=audio_file
            )

        print(f"识别结果: {transcription.text}")
        return transcription.text

    except Exception as e:
        print(f"❌ 语音识别失败: {e}")
        return ""  # 识别失败返回空字符串


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


def analyze_image(image_base64):
    """
    功能：调用 VLM (如 Qwen-VL) 分析图片
    image_base64: Base64 编码的图片字符串 (带前缀 data:image/jpeg;base64,...)
    """
    if not image_base64:
        return ""

    print("🖼️ 正在进行视觉分析...")

    # System Prompt for Vision
    # 注意：视觉模型通常直接理解 user message 中的图片
    system_prompt = """
    你是一位行为心理学家和面试官。请分析这张面试者的视频截图。
    请判断他的状态，并给出简短的评价标签（3-4个）。

    关注维度：
    1. 眼神（如：眼神飘忽、眼神坚定、直视镜头）
    2. 表情（如：表情自然、神情紧张、面带微笑）
    3. 体态（如：坐姿端正、摇头晃脑、身体僵硬）

    输出要求：
    请直接返回一个 JSON 数组，包含 3-4 个具体的短语。
    例如：["眼神飘忽", "神情紧张", "坐姿端正"]
    不要包含 Markdown 标记，直接返回数组。
    """

    try:
        response = client.chat.completions.create(
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
            temperature=0.5,
            max_tokens=100
        )
        result = response.choices[0].message.content
        # 尝试清理可能存在的 markdown 标记
        cleaned_result = result.replace('```json', '').replace('```', '').strip()
        print(f"👁️ 视觉分析结果: {cleaned_result}")
        return cleaned_result

    except Exception as e:
        print(f"❌ 视觉分析失败: {e}")
        return ""
