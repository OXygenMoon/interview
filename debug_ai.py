import json
from app import create_app
from app.models import ChatMessage
from app.services.ai_agent import _get_details_feedback

app = create_app()


def manual_debug(session_id):
    with app.app_context():
        print(f"🔧 正在调试 Session {session_id}...")

        # 1. 提取该场面试的学生回答
        messages = ChatMessage.query.filter_by(session_id=session_id).order_by(ChatMessage.timestamp).all()
        user_contents = [msg.content for msg in messages if msg.sender == 'user']

        if not user_contents:
            print("❌ 错误：该场面试没有学生回答，无法测试！")
            return

        print(f"📄 提取到 {len(user_contents)} 条学生回答：")
        for i, content in enumerate(user_contents):
            print(f"   [{i + 1}] {content[:20]}...")

        # 2. 直接调用 AI 服务 (模拟后台逻辑)
        print("\n🤖 正在请求 AI (DeepSeek)... 请等待约 5-10 秒...")

        # 这里的岗位写死或者查库，仅做测试
        try:
            ai_result = _get_details_feedback(user_contents, "Python工程师")
        except Exception as e:
            print(f"\n❌ AI 调用直接报错: {e}")
            return

        # 3. 打印 AI 的原始返回结果
        print("\n======== AI 返回的原始数据 ========")
        print(json.dumps(ai_result, indent=2, ensure_ascii=False))
        print("===================================")

        # 4. 模拟匹配逻辑
        print(f"\n📊 匹配测试 (应匹配 {len(user_contents)} 条):")
        matched_count = 0
        if isinstance(ai_result, list):
            for db_content, review in zip(user_contents, ai_result):
                print(f"   ✅ 匹配成功 -> 建议: {review.get('suggestion', '')[:20]}...")
                matched_count += 1

            if matched_count < len(user_contents):
                print(f"⚠️ 警告: AI 只返回了 {len(ai_result)} 条，少于输入的 {len(user_contents)} 条！")
        else:
            print(f"❌ 错误: AI 返回的不是列表 (List)，而是 {type(ai_result)}")


if __name__ == "__main__":
    # 这里填你刚才查到的 Session ID，也就是 3
    manual_debug(3)