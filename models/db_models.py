# models/db_models.py
from sqlalchemy import create_engine, Column, Integer, BigInteger, String, DateTime, ForeignKey, Boolean, Text
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
from datetime import datetime
from config import DATABASE_URL

# Инициализация движка и сессии
engine = create_engine(DATABASE_URL, pool_pre_ping=True,     # Проверяет соединение перед использованием
    pool_recycle=3600)       # Опционально: раз в час сбрасывать соединения, чтобы избежать разрыва "зависших" соединений)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

# Базовый класс для моделей
Base = declarative_base()

# Модель пользователя
class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True, index=True)
    telegram_id = Column(BigInteger, unique=True, index=True, nullable=False)
    first_name = Column(String(255))
    last_name = Column(String(255))
    registration_date = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)  # Мягкое удаление

    # Связь: у пользователя может быть много ответов
    answers = relationship("Answer", back_populates="user", cascade="all, delete-orphan")

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
    correct_answer = Column(String(1), nullable=False)  # Ожидается один символ: "A", "B", "C" или "D"
    option_a = Column(String(255), nullable=False)
    option_b = Column(String(255), nullable=False)
    option_c = Column(String(255), nullable=False)
    option_d = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True)

    # Отношение к тесту, которому принадлежит вопрос
    test = relationship("Test", back_populates="questions")
    # Связь: у вопроса может быть много ответов
    answers = relationship("Answer", back_populates="question", cascade="all, delete-orphan")

# Модель ответа
class Answer(Base):
    __tablename__ = 'answers'
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    question_id = Column(Integer, ForeignKey('questions.id'), nullable=False)
    selected_answer = Column(String(1), nullable=False)
    is_correct = Column(Boolean, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)

    # Связи для удобного доступа к данным пользователя и вопроса
    user = relationship("User", back_populates="answers")
    question = relationship("Question", back_populates="answers")
class UserProgress(Base):
    __tablename__ = 'user_progress'
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    test_id = Column(Integer, ForeignKey('tests.id'), nullable=False)
    current_question = Column(Integer, default=0)
    score = Column(Integer, default=0)
    started_at = Column(DateTime, default=datetime.utcnow)
    finished_at = Column(DateTime)

    # Отношения (опционально)
    user = relationship("User")
    test = relationship("Test")
