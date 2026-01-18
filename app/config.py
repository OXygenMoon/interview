import os


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-key-very-secret'
    SQLALCHEMY_DATABASE_URI = 'sqlite:///app.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # === 硅基流动 (SiliconFlow) 配置 ===
    # 1. 填入你在官网申请的 Key
    LLM_API_KEY = "sk-oyiwowqyddmemzkgjgkyajwkpkbrestyrxmhzipwveifoipx"

    # 2. 硅基流动的 Base URL (固定写法)
    LLM_BASE_URL = "https://api.siliconflow.cn/v1"

    # 3. 模型名称 (注意：硅基流动的模型名是带厂商前缀的)
    # 推荐使用 'deepseek-ai/DeepSeek-V3' (智能、强)
    # 或者 'Qwen/Qwen2.5-72B-Instruct' (阿里通义千问，也很强)
    LLM_MODEL_NAME = "Qwen/Qwen2.5-72B-Instruct"
    LLM_REPORT = "deepseek-ai/DeepSeek-V3"

    # === 火山引擎 TTS 配置 (豆包同款) ===
    # 请填入您在火山引擎控制台获取的信息
    VOLC_APPID = "7407227094"  # 您的 AppID
    VOLC_ACCESS_TOKEN = "Y1EtUCSI2GL0x612i-_uO-tGF_8mqOrn"  # 您的 Access Token

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


