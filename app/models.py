from . import db
from datetime import datetime
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash


class User(UserMixin, db.Model):
    """用户表"""
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(128))

    truename = db.Column(db.String(50))
    student_id = db.Column(db.String(20), unique=True)
    role = db.Column(db.String(20), default='student')
    department = db.Column(db.String(50))
    class_name = db.Column(db.String(50))

    resume_text = db.Column(db.Text)

    # === 新增：简历技能标签 ===
    resume_tags = db.Column(db.String(255))  # 用逗号分隔的字符串存储

    created_at = db.Column(db.DateTime, default=datetime.now)

    # === 权限辅助方法 ===
    @property
    def is_admin(self):
        return self.role == 'admin'

    @property
    def is_dept_head(self):
        return self.role in ['dept_head', 'admin']

    @property
    def is_teacher(self):
        return self.role in ['teacher', 'dept_head', 'admin']

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class InterviewSession(db.Model):
    """面试场次表"""
    __tablename__ = 'interview_sessions'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))

    # 为了方便统计查询，建立反向关系
    user = db.relationship('User', backref='sessions')

    target_role = db.Column(db.String(50))
    difficulty = db.Column(db.String(20))
    voice_type = db.Column(db.String(50), default='BV001_streaming')

    status = db.Column(db.String(20), default='ongoing')
    total_score = db.Column(db.Integer)
    radar_data = db.Column(db.JSON)
    summary_comment = db.Column(db.Text)
    start_time = db.Column(db.DateTime, default=datetime.now)
    end_time = db.Column(db.DateTime)


class ChatMessage(db.Model):
    """对话详情表"""
    __tablename__ = 'chat_messages'
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey('interview_sessions.id'))

    sender = db.Column(db.String(10))
    content = db.Column(db.Text)
    audio_url = db.Column(db.String(200))

    is_good_response = db.Column(db.Boolean, default=False)
    suggestion = db.Column(db.Text)

    timestamp = db.Column(db.DateTime, default=datetime.now)
    reference_answer = db.Column(db.Text)  # 满分参考答案


class Department(db.Model):
    """系部表"""
    __tablename__ = 'departments'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    # 关联班级
    classes = db.relationship('SchoolClass', backref='department', cascade='all, delete-orphan')


class SchoolClass(db.Model):
    """班级表"""
    __tablename__ = 'school_classes'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    department_id = db.Column(db.Integer, db.ForeignKey('departments.id'))

    # 联合唯一索引：同一个系部下班级名不能重复
    __table_args__ = (db.UniqueConstraint('department_id', 'name', name='_dept_class_uc'),)


class LearningCategory(db.Model):
    """学习分类（如：面试礼仪、技术基础）"""
    __tablename__ = 'learning_categories'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    icon = db.Column(db.String(20), default='📚')  # Emoji 图标
    sort_order = db.Column(db.Integer, default=0)

    # 关联内容
    materials = db.relationship('LearningMaterial', backref='category', cascade='all, delete-orphan',
                                order_by='LearningMaterial.sort_order')


class LearningMaterial(db.Model):
    """学习具体内容（一节课）"""
    __tablename__ = 'learning_materials'
    id = db.Column(db.Integer, primary_key=True)
    category_id = db.Column(db.Integer, db.ForeignKey('learning_categories.id'))
    title = db.Column(db.String(100), nullable=False)

    # 类型: 'article' (文章) 或 'quiz' (测验)
    material_type = db.Column(db.String(20), default='article')

    # 内容:
    # 如果是 article: 存储 HTML/Markdown 文本
    # 如果是 quiz: 存储 JSON 字符串 [{"question":"...", "options":["..."], "answer":"..."}]
    content = db.Column(db.Text)

    sort_order = db.Column(db.Integer, default=0)


class UserLearningProgress(db.Model):
    """学生学习进度"""
    __tablename__ = 'user_learning_progress'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    material_id = db.Column(db.Integer, db.ForeignKey('learning_materials.id'))

    status = db.Column(db.String(20), default='completed')  # 目前只存完成状态
    score = db.Column(db.Integer, default=0)  # 测验得分 (0-100)
    completed_at = db.Column(db.DateTime, default=datetime.now)

    # 联合唯一索引：防止重复记录
    __table_args__ = (db.UniqueConstraint('user_id', 'material_id', name='_user_material_uc'),)