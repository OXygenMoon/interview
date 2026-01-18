import base64
import json
import uuid
import requests
import os
import time
from ..config import Config


def text_to_speech(text, output_dir, specific_voice=None):
    """
    基于官方 API 文档实现的火山引擎 TTS
    """
    try:
        # 1. 准备目录和文件名
        os.makedirs(output_dir, exist_ok=True)
        filename = f"tts_{uuid.uuid4().hex}.mp3"
        file_path = os.path.join(output_dir, filename)

        print(f"正在调用火山引擎: {text[:15]}...")
        start_time = time.time()

        # 2. 准备参数
        # 接口地址 (官方文档标准地址)
        host = "openspeech.bytedance.com"
        api_url = f"https://{host}/api/v1/tts"

        # 鉴权 Header (注意：官方示例只用了 Authorization)
        header = {"Authorization": f"Bearer;{Config.VOLC_ACCESS_TOKEN}"}

        # final_voice = specific_voice if specific_voice else Config.VOLC_VOICE_TYPE
        final_voice = specific_voice if specific_voice else Config.VOLC_DEFAULT_VOICE

        # 3. 构造请求体 (完全照搬官方示例结构)
        request_json = {
            "app": {
                "appid": Config.VOLC_APPID,
                "token": "access_token",  # 官方要求固定填这个字符串
                "cluster": Config.VOLC_CLUSTER_ID  # 确保是 'volcano_tts'
            },
            "user": {
                "uid": "user_001"
            },
            "audio": {
                "voice_type": final_voice,
                "encoding": "mp3",
                "speed_ratio": 1.0,
                "volume_ratio": 1.0,
                "pitch_ratio": 1.0,
            },
            "request": {
                "reqid": str(uuid.uuid4()),
                "text": text,
                "text_type": "plain",
                "operation": "query",  # query 表示同步返回音频
                "with_frontend": 1,
                "frontend_type": "unitTson"
            }
        }

        # 4. 发送请求
        resp = requests.post(api_url, json=request_json, headers=header)

        # 5. 处理响应
        resp_data = resp.json()

        if "data" in resp_data:
            data = resp_data["data"]
            # 解码并写入文件
            with open(file_path, "wb") as file_to_save:
                file_to_save.write(base64.b64decode(data))

            print(f"✅ 语音生成成功! 耗时: {time.time() - start_time:.2f}s")
            return filename
        else:
            # 打印错误信息
            print(f"❌ 火山引擎报错: {resp_data}")
            # 如果报错 3001，一定是服务没开通或 Cluster ID 填错了
            return None

    except Exception as e:
        print(f"❌ TTS 系统异常: {e}")
        return None