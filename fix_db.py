from app import create_app, db
from app.models import ChatMessage, InterviewSession
import json

# 这里填您日志里生成的那个完整的 JSON 内容 (我已帮您填入刚才日志里的内容)
# 如果您想修复其他场次，请让 AI 重新生成，或者手动填入
MOCK_AI_RESPONSE = {
    "details": [
        {
            "suggestion": "自我介绍过于简单，建议补充技术背景或相关经验。",
            "is_good": False
        },
        {
            "suggestion": "项目动机明确，体现了解决问题的能力，但过度依赖AI工具需警惕技术深度不足。",
            "is_good": True
        },
        {
            "suggestion": "技术栈描述清晰，但未提及反爬处理和数据清洗等关键细节。",
            "is_good": False
        }
    ]
}

app = create_app()


def quick_fix(session_id):
    with app.app_context():
        print(f"🔧 正在强制修复 Session {session_id}...")

        # 1. 获取数据库里的学生回答
        all_msgs = ChatMessage.query.filter_by(session_id=session_id).order_by(ChatMessage.timestamp).all()
        user_msgs = [m for m in all_msgs if m.sender == 'user']

        print(f"数据库里有 {len(user_msgs)} 条学生回答。")

        # 2. 读取模拟的 AI 数据 (注意 key 是 details)
        reviews_list = MOCK_AI_RESPONSE.get('details', [])

        print(f"准备写入 {len(reviews_list)} 条点评...")

        # 3. 写入
        count = 0
        for db_msg, review in zip(user_msgs, reviews_list):
            db_msg.suggestion = review.get('suggestion')
            db_msg.is_good_response = review.get('is_good')
            count += 1
            print(f"   ✅ ID {db_msg.id} <- {review.get('suggestion')[:10]}...")

        db.session.commit()
        print(f"🎉 修复完成！请刷新页面查看。")


if __name__ == "__main__":
    # 请确认 Session ID (根据您刚才的日志，应该是最近一次，可能是 3 或 4)
    # 您可以在数据库或页面 URL 里看 id
    quick_fix(3)