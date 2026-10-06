"""Seed deterministic data into the isolated E2E database."""

import json
from datetime import datetime, timedelta

from app import create_app, db
from app.models import (
    ChatMessage,
    Company,
    Department,
    InterviewSession,
    LearningCategory,
    LearningMaterial,
    Position,
    SchoolClass,
    User,
)


PASSWORDS = {
    'student': 'StudentPass123!',
    'interview_student': 'InterviewPass123!',
    'mobile_interview_student': 'MobileInterviewPass123!',
    'teacher': 'TeacherPass123!',
    'admin': 'AdminPass123!',
}


def make_user(username, role, truename):
    user = User(
        username=username,
        role=role,
        truename=truename,
        department='智能制造系',
        class_name='软件一班',
        active=True,
        must_change_password=False,
    )
    user.set_password(PASSWORDS[username])
    return user


def main():
    app = create_app()
    app.config.update(TESTING=True)
    with app.app_context():
        if User.query.filter_by(username='student').first():
            return

        department = Department(name='智能制造系')
        department.classes.append(SchoolClass(name='软件一班'))

        company = Company(
            name='未来科技',
            description='专注可靠的软件与智能制造解决方案。',
        )
        position = Position(
            name='后端开发工程师',
            description='负责 Python 服务、数据库设计与稳定性建设。',
        )
        company.positions.append(position)

        category = LearningCategory(
            name='面试基础训练',
            icon='🧭',
            sort_order=1,
        )
        category.materials.extend([
            LearningMaterial(
                title='面试准备清单',
                material_type='article',
                content='<p>准备项目案例，并用清晰结构表达。</p>',
                sort_order=1,
            ),
            LearningMaterial(
                title='基础知识测验',
                material_type='quiz',
                content=json.dumps([
                    {
                        'id': 1,
                        'title': 'HTTP 中表示成功的状态码是？',
                        'options': [
                            {'key': 'A', 'val': '200'},
                            {'key': 'B', 'val': '500'},
                        ],
                        'answer': 'A',
                    },
                    {
                        'id': 2,
                        'title': '数据库事务的一致性缩写属于？',
                        'options': [
                            {'key': 'A', 'val': 'CRUD'},
                            {'key': 'B', 'val': 'ACID'},
                        ],
                        'answer': 'B',
                    },
                ], ensure_ascii=False),
                sort_order=2,
            ),
        ])

        student = make_user('student', 'student', '端到端学生')
        interview_student = make_user(
            'interview_student',
            'student',
            '面试流程学生',
        )
        teacher = make_user('teacher', 'teacher', '端到端教师')
        admin = make_user('admin', 'admin', '端到端管理员')
        mobile_student = make_user('mobile_interview_student', 'student', '手机交互学生')
        student.student_id = 'E2E-STUDENT-001'
        interview_student.student_id = 'E2E-STUDENT-002'

        db.session.add_all([
            department,
            company,
            category,
            student,
            interview_student,
            teacher,
            admin,
            mobile_student,
        ])
        db.session.flush()

        started = datetime.now() - timedelta(hours=3)
        completed = InterviewSession(
            user_id=student.id,
            position_id=position.id,
            target_role='后端开发工程师',
            difficulty='标准模式',
            voice_type='zh_male_dayi_saturn_bigtts',
            status='completed',
            total_score=86,
            radar_data={
                '专业技能': 88,
                '逻辑思维': 84,
                '表达能力': 86,
            },
            summary_comment='基础扎实，回答结构清楚，能够结合项目说明取舍。',
            start_time=started,
            end_time=started + timedelta(minutes=25),
            last_activity=started + timedelta(minutes=25),
            reviewed=True,
            report_queue_status='finished',
        )
        db.session.add(completed)
        db.session.flush()
        db.session.add_all([
            ChatMessage(
                session_id=completed.id,
                sender='ai',
                content='请介绍一次服务稳定性改进。',
            ),
            ChatMessage(
                session_id=completed.id,
                sender='user',
                content='我通过指标、告警和压测闭环改进稳定性。',
                is_good_response=True,
                suggestion='可以补充量化结果。',
            ),
        ])
        db.session.commit()


if __name__ == '__main__':
    main()
