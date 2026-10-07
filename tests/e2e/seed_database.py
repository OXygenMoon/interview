"""Seed deterministic data into the isolated E2E database."""

import json
import base64
from datetime import datetime, timedelta

from app import create_app, db
from app.services.test_accounts import seed_test_accounts
from app.services.submitted_resume import snapshot_resume
from app.models import (
    ChatMessage,
    Company,
    Department,
    InterviewSession,
    LearningCategory,
    LearningMaterial,
    Position,
    Resume,
    SchoolClass,
    User,
)


PASSWORDS = {
    'student': 'StudentPass123!',
    'interview_student': 'InterviewPass123!',
    'mobile_interview_student': 'MobileInterviewPass123!',
    'realtime_student': 'RealtimePass123!',
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
        seed_test_accounts()
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
        realtime_student = make_user('realtime_student', 'student', '实时语音测试学生')
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
            realtime_student,
        ])
        db.session.flush()

        submitted = Resume(user_id=student.id, title='递交简历排版测试', template_id='campus', content={
            'basic': {'name': '端到端学生', 'phone': '13800000000', 'email': 'student@example.test',
                      'job_target': '后端开发工程师', 'self_evaluation': '熟悉 Python，参与服务稳定性项目。'},
            'education': [{'school': '嘉善技师学院', 'major': '软件工程', 'date': '2024—2026'}],
            'projects': [{'name': '服务稳定性项目', 'role': '开发', 'description': '完成指标、告警和压测闭环。'}],
            'skills': ['Python', 'SQL'], 'layout': {'density': 1},
        })
        db.session.add(submitted)
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
            resume_snapshot='端到端学生的递交简历：熟悉 Python，参与服务稳定性项目。',
            use_resume=True, resume_id=submitted.id, resume_document_snapshot=snapshot_resume(submitted),
        )
        db.session.add(completed)
        db.session.flush()
        db.session.add_all([
            ChatMessage(
                session_id=completed.id,
                sender='ai',
                content='请介绍一次服务稳定性改进。',
                timestamp=started + timedelta(seconds=60),
            ),
            ChatMessage(
                session_id=completed.id,
                sender='user',
                content='我通过指标、告警和压测闭环改进稳定性。',
                is_good_response=True,
                suggestion='可以补充量化结果。',
                reference_answer='示例思路：说明改进前后的故障率和具体行动。',
                timestamp=started + timedelta(seconds=90),
                visual_captured_at=started + timedelta(seconds=90),
                visual_image=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aQ1sAAAAASUVORK5CYII='),
                visual_context=json.dumps({
                    'tags': ['头肩居中', '镜头偏低'],
                    'comment': '本帧头肩居中。建议将镜头抬至眼睛同高，保持自然姿态。',
                }, ensure_ascii=False),
            ),
        ])
        visual_report = InterviewSession(
            user_id=admin.id,
            target_role='仪态翻页测试',
            difficulty='标准模式',
            status='completed',
            total_score=70,
            radar_data={'表达能力': 70},
            summary_comment='用于验证不同时间戳的画面切换。',
            start_time=started,
            end_time=started + timedelta(minutes=15),
            reviewed=True,
            report_queue_status='finished',
        )
        db.session.add(visual_report)
        db.session.flush()
        for index in range(9):
            captured = started + timedelta(seconds=90 + index * 30)
            db.session.add(ChatMessage(
                session_id=visual_report.id,
                sender='user',
                content=f'第 {index + 1} 次仪态练习回答。',
                timestamp=captured,
                visual_captured_at=captured if index != 8 else None,
                visual_image=(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aQ1sAAAAASUVORK5CYII=')
                              if index != 8 else None),
                visual_context=json.dumps({
                    'tags': [f'画面标签 {index + 1}'],
                    'comment': f'第 {index + 1} 帧仪态点评：保持头肩自然，调整镜头高度。',
                }, ensure_ascii=False),
            ))
        db.session.commit()


if __name__ == '__main__':
    main()
