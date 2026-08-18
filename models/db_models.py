from sqlalchemy import create_engine, Column, Integer, BigInteger, String, DateTime, ForeignKey, Boolean, Text, Date, Time, Float
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
from datetime import datetime
from config import DATABASE_URL

# Асинхронный движок для базы данных
engine = create_async_engine(DATABASE_URL, echo=True, pool_pre_ping=True)

# Асинхронная сессия
SessionLocal = sessionmaker(
    bind=engine, class_=AsyncSession, expire_on_commit=False
)


# Перезапуск сессии и подключений
async def restart_session():
    # Закрытие текущих соединений
    await engine.dispose()
    engine = create_async_engine(DATABASE_URL, echo=True, pool_pre_ping=True)
    SessionLocal = sessionmaker(
    bind=engine, class_=AsyncSession, expire_on_commit=False)
    return SessionLocal

Base = declarative_base()
# Модель пользователя
class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True, index=True)
    telegram_id = Column(BigInteger, unique=True, index=True, nullable=False)
    first_name = Column(String(255))
    last_name = Column(String(255))
    registration_date = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)

    # Составляющие веса сотрудника для графика (см. handlers/schedule.py).
    # exam_score: 0.15 стажёр, 0.25 после сдачи меню, 0.5 после сдачи всех
    # экзаменов/практической проверки — выставляется администратором вручную.
    exam_score = Column(Float, nullable=False, default=0.15, server_default="0.15")
    # admin_score: оценка администратора, 0..0.5, обновляется ежемесячно.
    admin_score = Column(Float, nullable=False, default=0.0, server_default="0")
    hire_date = Column(Date, nullable=True)

    answers = relationship("Answer", back_populates="user", cascade="all, delete-orphan")
    Userprogress = relationship("UserProgress", back_populates="user", cascade="all, delete-orphan")

    @property
    def tenure_bonus(self) -> float:
        """+0.10 веса за каждые полные полгода стажа с hire_date."""
        if not self.hire_date:
            return 0.0
        today = datetime.utcnow().date()
        months = (today.year - self.hire_date.year) * 12 + (today.month - self.hire_date.month)
        return (months // 6) * 0.10

    @property
    def weight(self) -> float:
        """Итоговый вес = экзамен/практика + оценка администратора + стаж.
        Не хранится в базе, чтобы не протухал по мере роста стажа — считается на лету."""
        return round((self.exam_score or 0.0) + (self.admin_score or 0.0) + self.tenure_bonus, 2)

class ShiftTaskTemplate(Base):
    __tablename__ = "shift_task_templates"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(255), nullable=False)      # короткий текст задачи
    description = Column(Text)                       # подробнее, если нужно
    weekday = Column(Integer, nullable=False)        # 0=понедельник ... 6=воскресенье
    is_active = Column(Boolean, default=True)
    instances = relationship(
        "ShiftTaskInstance",
        back_populates="template",
        cascade="all, delete-orphan",
    )

class ShiftTaskInstance(Base):
    __tablename__ = "shift_task_instances"

    id = Column(Integer, primary_key=True, index=True)
    template_id = Column(Integer, ForeignKey("shift_task_templates.id"), nullable=False)
    due_date = Column(Date, nullable=False)          # дата смены
    completed = Column(Boolean, default=False)
    completed_at = Column(DateTime)
    completed_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    template = relationship("ShiftTaskTemplate")
    completed_by_user = relationship("User")

# Модель теста
class Test(Base):
    __tablename__ = 'tests'
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    is_active = Column(Boolean, default=True)

    # Связь: у теста может быть много вопросов
    questions = relationship("Question", back_populates="test", cascade="all, delete-orphan")


# Модель вопроса
class Question(Base):
    __tablename__ = 'questions'
    id = Column(Integer, primary_key=True, index=True)
    test_id = Column(Integer, ForeignKey('tests.id'), nullable=False)
    question_text = Column(Text, nullable=False)
    correct_answer = Column(String(1), nullable=False)
    option_a = Column(String(255), nullable=False)
    option_b = Column(String(255), nullable=False)
    option_c = Column(String(255), nullable=False)
    option_d = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True)

    test = relationship("Test", back_populates="questions")
    answers = relationship("Answer", back_populates="question", cascade="all, delete-orphan")
    images = relationship("QuestionImage", backref="question", cascade="all, delete-orphan")

class QuestionImage(Base):
    __tablename__ = 'question_images'
    id = Column(Integer, primary_key=True, index=True)
    question_id = Column(Integer, ForeignKey('questions.id'), nullable=False)
    image = Column(String(1024), nullable=False)

# Модель ответа
class Answer(Base):
    __tablename__ = 'answers'
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    question_id = Column(Integer, ForeignKey('questions.id'), nullable=False)
    selected_answer = Column(String(1), nullable=False)
    is_correct = Column(Boolean, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="answers")
    question = relationship("Question", back_populates="answers")

# Модель прогресса пользователя в тесте
class UserProgress(Base):
    __tablename__ = 'user_progress'
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    test_id = Column(Integer, ForeignKey('tests.id'), nullable=False)
    current_question = Column(Integer, default=0)
    score = Column(Integer, default=0)
    started_at = Column(DateTime, default=datetime.utcnow)
    finished_at = Column(DateTime)

    user = relationship("User")
    test = relationship("Test")

class Materials(Base):
    __tablename__ = '_materials_'
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    file = Column(String(1024), nullable=False)
    is_active = Column(Boolean, default=True)

class Exam(Base):
    __tablename__ = 'exams'
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    file = Column(String(1024), nullable=False)
    is_active = Column(Boolean, default=True)


# --- Графики смен -----------------------------------------------------------

class SchedulePeriod(Base):
    """Двухнедельный период, на который собираем доступность и строим график."""
    __tablename__ = 'schedule_periods'
    id = Column(Integer, primary_key=True, index=True)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    # collecting -> опрос доступности идёт; generating -> строим график;
    # published -> график разослан
    status = Column(String(20), nullable=False, default='collecting', server_default='collecting')
    created_at = Column(DateTime, default=datetime.utcnow)

    responses = relationship("AvailabilityResponse", back_populates="period", cascade="all, delete-orphan")
    assignments = relationship("ShiftAssignment", back_populates="period", cascade="all, delete-orphan")


class AvailabilityResponse(Base):
    """Ответ одного сотрудника на опрос доступности за период (мини-досье)."""
    __tablename__ = 'availability_responses'
    id = Column(Integer, primary_key=True, index=True)
    period_id = Column(Integer, ForeignKey('schedule_periods.id'), nullable=False)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    comment = Column(Text, nullable=True)  # свободные пожелания, вопрос 4
    submitted_at = Column(DateTime, default=datetime.utcnow)

    period = relationship("SchedulePeriod", back_populates="responses")
    user = relationship("User")
    constraints = relationship("AvailabilityConstraint", back_populates="response", cascade="all, delete-orphan")


class AvailabilityConstraint(Base):
    """Одно ограничение на конкретную дату: выходной / раннее или позднее время.

    ВАЖНО: вопросы 2 и 3 из майндмэпы в переданном виде звучат одинаково
    ("с X часов") — не до конца понятно, вопрос 3 про "не раньше 18" или
    "не позже 18" (уйти пораньше). Схема ниже держит earliest_start и
    latest_end раздельно, чтобы не переделывать её, когда смысл уточнится.
    """
    __tablename__ = 'availability_constraints'
    id = Column(Integer, primary_key=True, index=True)
    response_id = Column(Integer, ForeignKey('availability_responses.id'), nullable=False)
    date = Column(Date, nullable=False)
    # day_off | earliest_start | latest_end
    constraint_type = Column(String(20), nullable=False)
    time_value = Column(Time, nullable=True)  # null для day_off

    response = relationship("AvailabilityResponse", back_populates="constraints")


class ShiftAssignment(Base):
    """Один сотрудник на одной смене в рамках периода — единица графика."""
    __tablename__ = 'shift_assignments'
    id = Column(Integer, primary_key=True, index=True)
    period_id = Column(Integer, ForeignKey('schedule_periods.id'), nullable=False)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    date = Column(Date, nullable=False)
    start_time = Column(Time, nullable=False)
    end_time = Column(Time, nullable=False)
    # planned -> обычная смена; needs_replacement -> ищем замену;
    # replaced -> замена найдена; confirmed -> подтверждено администратором
    status = Column(String(20), nullable=False, default='planned', server_default='planned')
    replaced_by_user_id = Column(Integer, ForeignKey('users.id'), nullable=True)
    # для «красных ячеек» — смена не до конца соответствует условиям
    is_flagged = Column(Boolean, nullable=False, default=False, server_default='false')
    flag_reason = Column(Text, nullable=True)

    period = relationship("SchedulePeriod", back_populates="assignments")
    user = relationship("User", foreign_keys=[user_id])
    replaced_by = relationship("User", foreign_keys=[replaced_by_user_id])
    broadcasts = relationship("ReplacementBroadcastMessage", back_populates="assignment", cascade="all, delete-orphan")


class ReplacementBroadcastMessage(Base):
    """Сообщение с предложением о замене, отправленное конкретному сотруднику.

    Нужна отдельная запись на каждого получателя, чтобы после того как
    кто-то нажал «я выйду», можно было отредактировать/убрать кнопку у всех
    остальных, кому ушла та же рассылка.
    """
    __tablename__ = 'replacement_broadcast_messages'
    id = Column(Integer, primary_key=True, index=True)
    assignment_id = Column(Integer, ForeignKey('shift_assignments.id'), nullable=False)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    chat_id = Column(BigInteger, nullable=False)
    message_id = Column(Integer, nullable=False)
    sent_at = Column(DateTime, default=datetime.utcnow)

    assignment = relationship("ShiftAssignment", back_populates="broadcasts")
    user = relationship("User")


# --- Открытие/закрытие точки ------------------------------------------------

class ChecklistItemTemplate(Base):
    """Один пункт чек-листа открытия/закрытия. Порядок и состав фиксированы
    кодом (см. handlers/checklist_seed.py) — редактируется только
    reference_file_id, и то через админскую команду."""
    __tablename__ = 'checklist_item_templates'
    id = Column(Integer, primary_key=True, index=True)
    location = Column(String(32), nullable=False, index=True)  # 'el_gusto' | 'marta' (второй пока не используется)
    shift_type = Column(String(10), nullable=False)  # 'open' | 'close'
    step_key = Column(String(64), nullable=False)  # стабильный ключ пункта, не меняется между релизами
    order_index = Column(Integer, nullable=False)
    title = Column(String(255), nullable=False)
    prompt_text = Column(Text, nullable=True)  # доп. подсказка сотруднику (например про руки/украшения)
    # 'photo' | 'multi_photo' | 'text' | 'multi_text'
    item_type = Column(String(16), nullable=False)
    needs_reference = Column(Boolean, nullable=False, default=False)
    reference_file_id = Column(String(255), nullable=True)  # telegram file_id, задаётся админом один раз


class ChecklistSubmission(Base):
    __tablename__ = 'checklist_submissions'
    id = Column(Integer, primary_key=True, index=True)
    location = Column(String(32), nullable=False)
    shift_type = Column(String(10), nullable=False)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    status = Column(String(16), nullable=False, default='in_progress')  # in_progress | completed
    started_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

    user = relationship("User")
    answers = relationship("ChecklistAnswer", back_populates="submission", cascade="all, delete-orphan")


class ChecklistAnswer(Base):
    """Ответ на один пункт. Для multi_photo/multi_text пунктов — несколько
    строк на один item_id (по одной на каждое присланное фото/сообщение)."""
    __tablename__ = 'checklist_answers'
    id = Column(Integer, primary_key=True, index=True)
    submission_id = Column(Integer, ForeignKey('checklist_submissions.id'), nullable=False)
    item_id = Column(Integer, ForeignKey('checklist_item_templates.id'), nullable=False)
    text_value = Column(Text, nullable=True)
    photo_file_id = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    submission = relationship("ChecklistSubmission", back_populates="answers")
    item = relationship("ChecklistItemTemplate")


# Инициализация базы данных
async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

