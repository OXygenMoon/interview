import os


class Config:
    APP_ENV = os.environ.get('APP_ENV', os.environ.get('FLASK_ENV', 'production')).lower()
    SECRET_KEY = os.environ.get('SECRET_KEY')
    CSRF_ENABLED = os.environ.get('CSRF_ENABLED', 'true').lower() == 'true'
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        'DATABASE_URL',
        'sqlite:///app.db',
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    MAX_CONTENT_LENGTH = int(os.environ.get('MAX_CONTENT_LENGTH', 8 * 1024 * 1024))
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    SESSION_COOKIE_SECURE = os.environ.get(
        'SESSION_COOKIE_SECURE',
        'true' if APP_ENV == 'production' else 'false',
    ).lower() == 'true'
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = 'Lax'
    REMEMBER_COOKIE_SECURE = SESSION_COOKIE_SECURE

    # Cross-platform account association (disabled until all three are configured).
    ACCOUNT_LINK_INTERVIEW_URL = os.environ.get('ACCOUNT_LINK_INTERVIEW_URL', '')
    ACCOUNT_LINK_WIKIBOOK_URL = os.environ.get('ACCOUNT_LINK_WIKIBOOK_URL', '')
    ACCOUNT_LINK_SECRET = os.environ.get('ACCOUNT_LINK_SECRET', '')
    # Timezone of legacy naive business timestamps (datetime.now writes).
    INTERVIEW_RECORD_TIMEZONE = os.environ.get('INTERVIEW_RECORD_TIMEZONE', 'Asia/Shanghai')
    SESSION_COOKIE_NAME = os.environ.get('SESSION_COOKIE_NAME', 'interview_session' if ACCOUNT_LINK_SECRET else 'session')
    REMEMBER_COOKIE_NAME = os.environ.get('REMEMBER_COOKIE_NAME', 'interview_remember' if ACCOUNT_LINK_SECRET else 'remember_token')

    # === Durable report queue ===
    REDIS_URL = os.environ.get('REDIS_URL', 'redis://127.0.0.1:6379/0')
    REPORT_QUEUE_MODE = os.environ.get(
        'REPORT_QUEUE_MODE',
        'rq' if APP_ENV == 'production' else 'auto',
    ).lower()
    REPORT_QUEUE_NAME = os.environ.get(
        'REPORT_QUEUE_NAME',
        'interview_reports',
    )
    REPORT_JOB_TIMEOUT_SECONDS = int(os.environ.get(
        'REPORT_JOB_TIMEOUT_SECONDS',
        '600',
    ))
    REPORT_JOB_RESULT_TTL_SECONDS = int(os.environ.get(
        'REPORT_JOB_RESULT_TTL_SECONDS',
        '86400',
    ))
    REPORT_JOB_FAILURE_TTL_SECONDS = int(os.environ.get(
        'REPORT_JOB_FAILURE_TTL_SECONDS',
        '604800',
    ))
    REPORT_RETRY_INTERVALS = os.environ.get(
        'REPORT_RETRY_INTERVALS',
        '30,120',
    )

    # === DeepSeek 面试对话、报告及视觉分析 ===
    # 密钥只通过服务端环境变量配置，本地 .env 不提交到 Git。
    LLM_API_KEY = os.environ.get('LLM_API_KEY')
    LLM_BASE_URL = os.environ.get('LLM_BASE_URL', 'https://api.deepseek.com')
    # DeepSeek-V4.1-Flash 的官方 API 模型标识。
    LLM_MODEL_NAME = os.environ.get('LLM_MODEL_NAME', 'deepseek-flash')
    LLM_REPORT = os.environ.get('LLM_REPORT', LLM_MODEL_NAME)
    VLM_MODEL_NAME = os.environ.get('VLM_MODEL_NAME', LLM_MODEL_NAME)
    # 短回复使用非思考模式，避免思考占用 token 上限并延迟首字。
    LLM_THINKING = os.environ.get('LLM_THINKING', 'disabled')

    # SenseVoice 在部署机器上离线识别，不使用云端 ASR 凭证。
    ASR_MODEL_DIR = os.environ.get(
        'ASR_MODEL_DIR',
        os.path.join(os.path.dirname(os.path.dirname(__file__)), '.local', 'asr', 'sensevoice'),
    )
    ASR_LANGUAGE = os.environ.get('ASR_LANGUAGE', 'auto')
    ASR_NUM_THREADS = int(os.environ.get('ASR_NUM_THREADS', '2'))

    # === 火山引擎 TTS 配置 (豆包同款) ===
    # 密钥从环境变量读取
    VOLC_APPID = os.environ.get('VOLC_APPID')
    VOLC_ACCESS_TOKEN = os.environ.get('VOLC_ACCESS_TOKEN')

    # Cluster ID 通常是 'volcano_tts'，如果控制台显示不一样请修改
    VOLC_CLUSTER_ID = "volcano_tts"

    # 音色选择 (常用音色推荐)：
    # BV700_streaming: 灿灿 (知性女声，最常用，类似豆包)
    # BV701_streaming: 阳光 (活力男声)
    # BV001_streaming: 姐姐 (温柔女声)
    # BV002_streaming: 故事 (深情男声)
    VOLC_AVAILABLE_VOICES = {
        '大壹老师': "zh_male_dayi_saturn_bigtts",
        '晓甜老师': 'zh_female_mizai_saturn_bigtts',
        'VV老师': 'zh_female_vv_uranus_bigtts'
    }

    VOLC_DEFAULT_VOICE = "zh_male_dayi_saturn_bigtts"
