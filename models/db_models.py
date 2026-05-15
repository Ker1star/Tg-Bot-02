from sqlalchemy import create_engine, Column, Integer, BigInteger, String, DateTime, ForeignKey, Boolean, Text, Date, Time
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

    answers = relationship("Answer", back_populates="user", cascade="all, delete-orphan")
    Userprogress = relationship("UserProgress", back_populates="user", cascade="all, delete-orphan")

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
    
# Инициализация базы данных
async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

