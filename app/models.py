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

    # 新增：个人基础信息（用于一键导入简历）
    # 结构: {name, phone, email, location, job_target, self_evaluation, ...}
    profile_info = db.Column(db.JSON)

    created_at = db.Column(db.DateTime, default=datetime.now)
    active = db.Column(db.Boolean, default=True, nullable=False)
    must_change_password = db.Column(db.Boolean, default=False, nullable=False)
    deactivated_at = db.Column(db.DateTime)

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

    @property
    def is_active(self):
        return bool(self.active)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Resume(db.Model):
    """简历表"""
    __tablename__ = 'resumes'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    title = db.Column(db.String(100), default='我的简历')
    template_id = db.Column(db.String(50), default='modern')
    content = db.Column(db.JSON)  # 存储简历的结构化数据
    created_at = db.Column(db.DateTime, default=datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    user = db.relationship('User', backref='resumes')


class InterviewSession(db.Model):
    """面试场次表"""
    __tablename__ = 'interview_sessions'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))

    # 为了方便统计查询，建立反向关系
    user = db.relationship('User', foreign_keys=[user_id], backref='sessions')

    # 关联岗位 ID (允许为空，兼容旧数据)
    position_id = db.Column(db.Integer, db.ForeignKey('positions.id'), nullable=True)
    resume_id = db.Column(db.Integer, db.ForeignKey('resumes.id'), nullable=True)
    resume_snapshot = db.Column(db.Text)
    position_snapshot = db.Column(db.JSON)
    prior_round_summary = db.Column(db.JSON)
    llm_model = db.Column(db.String(100))
    prompt_version = db.Column(db.String(50))

    target_role = db.Column(db.String(50))
    difficulty = db.Column(db.String(20))
    voice_type = db.Column(db.String(50), default='zh_male_dayi_saturn_bigtts')
    use_resume = db.Column(db.Boolean, default=False)

    status = db.Column(db.String(20), default='ongoing')
    total_score = db.Column(db.Integer)
    radar_data = db.Column(db.JSON)
    summary_comment = db.Column(db.Text)
    evaluation_source = db.Column(db.String(30))
    report_model = db.Column(db.String(100))
    report_prompt_version = db.Column(db.String(50))
    report_error = db.Column(db.Text)
    start_time = db.Column(db.DateTime, default=datetime.now)
    end_time = db.Column(db.DateTime)

    # Phase 0：刷新保留 / 冷却系统 / 复盘门槛
    last_activity = db.Column(db.DateTime, default=datetime.now)  # 最近一次互动（用于 10min TTL）
    reviewed = db.Column(db.Boolean, default=False)  # 学生是否已查看本次报告（复盘门槛）
    abandoned = db.Column(db.Boolean, default=False)  # 是否中途放弃（触发放弃罚时）

    # Phase 4：面试进阶链（初面→复面→终面）
    round = db.Column(db.Integer, default=1)  # 当前轮次 1/2/3
    parent_session_id = db.Column(db.Integer, nullable=True, unique=True)  # 每轮最多只能有一个下一轮
    deleted_at = db.Column(db.DateTime)
    deleted_by_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    deletion_reason = db.Column(db.String(255))
    status_before_delete = db.Column(db.String(20))
    deleted_by = db.relationship('User', foreign_keys=[deleted_by_id])


class ChatMessage(db.Model):
    """对话详情表"""
    __tablename__ = 'chat_messages'
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey('interview_sessions.id'))

    sender = db.Column(db.String(10))
    content = db.Column(db.Text)
    audio_url = db.Column(db.String(200))
    audio_urls = db.Column(db.JSON(none_as_null=True))  # 流式 TTS 的多片段 URL 列表

    is_good_response = db.Column(db.Boolean, default=False)
    suggestion = db.Column(db.Text)

    timestamp = db.Column(db.DateTime, default=datetime.now)
    reference_answer = db.Column(db.Text)  # 满分参考答案

    # 新增：视觉分析上下文 (存储 JSON 或 文本标签)
    visual_context = db.Column(db.Text)
    generation_status = db.Column(db.String(30), default='completed', nullable=False)
    model_name = db.Column(db.String(100))
    error_message = db.Column(db.Text)


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


class Company(db.Model):
    """公司表（一级分类）"""
    __tablename__ = 'companies'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)  # Markdown 格式的公司介绍/提示词
    created_at = db.Column(db.DateTime, default=datetime.now)

    # 关联岗位
    positions = db.relationship('Position', backref='company', cascade='all, delete-orphan')


class Position(db.Model):
    """岗位表（二级分类）"""
    __tablename__ = 'positions'
    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey('companies.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)  # Markdown 格式的岗位介绍/提示词
    created_at = db.Column(db.DateTime, default=datetime.now)

    # 关联面试场次
    sessions = db.relationship('InterviewSession', backref='position', lazy='dynamic')


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


class LearningAttempt(db.Model):
    """Every quiz submission, including failed attempts."""
    __tablename__ = 'learning_attempts'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    material_id = db.Column(db.Integer, db.ForeignKey('learning_materials.id'), nullable=False)
    score = db.Column(db.Integer, nullable=False)
    passed = db.Column(db.Boolean, nullable=False, default=False)
    answers = db.Column(db.JSON)
    attempted_at = db.Column(db.DateTime, default=datetime.now, nullable=False)


class RandomPracticeAttempt(db.Model):
    """Durable result for a one-question random practice."""
    __tablename__ = 'random_practice_attempts'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    question = db.Column(db.Text, nullable=False)
    answer = db.Column(db.Text, nullable=False)
    score = db.Column(db.Integer)
    evaluation = db.Column(db.Text)
    suggestion = db.Column(db.Text)
    visual_feedback = db.Column(db.Text)
    status = db.Column(db.String(30), nullable=False, default='completed')
    error_message = db.Column(db.Text)
    model_name = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.now, nullable=False)


class SystemConfig(db.Model):
    """系统全局配置表"""
    __tablename__ = 'system_configs'
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(50), unique=True, nullable=False)  # 配置键，如 'enable_tts'
    value = db.Column(db.String(255))  # 配置值
    description = db.Column(db.String(255))  # 描述
    updated_at = db.Column(db.DateTime, default=datetime.now, onupdate=datetime.now)

    @staticmethod
    def get(key, default=None):
        config = SystemConfig.query.filter_by(key=key).first()
        return config.value if config else default

    @staticmethod
    def set(key, value, description=None):
        config = SystemConfig.query.filter_by(key=key).first()
        if config:
            config.value = str(value)
            if description:
                config.description = description
        else:
            config = SystemConfig(key=key, value=str(value), description=description)
            db.session.add(config)
        db.session.commit()
