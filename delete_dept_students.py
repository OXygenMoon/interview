
import sys
import os
from app import create_app, db
from app.models import User, InterviewSession, ChatMessage, UserLearningProgress

app = create_app()

def delete_students_by_dept(dept_name):
    with app.app_context():
        # 1. 查找该系部下的所有学生
        students = User.query.filter_by(department=dept_name, role='student').all()
        
        if not students:
            print(f"没有找到系部为 '{dept_name}' 的学生。")
            return

        print(f"找到 {len(students)} 名学生属于 '{dept_name}'，准备删除...")
        
        count = 0
        for student in students:
            try:
                # 2. 删除学生的所有面试记录
                sessions = InterviewSession.query.filter_by(user_id=student.id).all()
                for session in sessions:
                    # 删除聊天记录
                    ChatMessage.query.filter_by(session_id=session.id).delete()
                    # 删除 Session
                    db.session.delete(session)
                
                # 3. 删除学习进度
                UserLearningProgress.query.filter_by(user_id=student.id).delete()

                # 4. 删除学生账号
                db.session.delete(student)
                count += 1
                print(f"已删除学生: {student.truename} ({student.student_id})")
            except Exception as e:
                print(f"删除学生 {student.truename} 失败: {e}")
                db.session.rollback() # 回滚当前事务，防止后续删除受影响
                # 重新开始一个新的事务用于下一个循环
                
        try:
            db.session.commit()
            print(f"操作完成，共成功删除 {count} 名学生及其关联数据。")
        except Exception as e:
            print(f"提交事务失败: {e}")
            db.session.rollback()

if __name__ == "__main__":
    delete_students_by_dept("数字经艺系")
