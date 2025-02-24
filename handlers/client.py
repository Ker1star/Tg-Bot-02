from aiogram import Router, types, F
from aiogram.filters import Command
from models.db_models import SessionLocal, User, Question, Test, UserProgress, Materials
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.future import select
import datetime
import html, logging
from sqlalchemy.ext.asyncio import AsyncSession
from config import ADMIN_ID
from handlers.admin import admin_panel_handler 
router = Router()
logger = logging.getLogger(__name__)

def get_main_menu_keyboard() -> ReplyKeyboardMarkup:
    """
    Формирует клавиатуру с описательными кнопками.
    """
    keyboard = [
        [KeyboardButton(text="📚 Учебные материалы")],
        [KeyboardButton(text="📝 Пройти тест"), KeyboardButton(text="❓ Помощь")],
        [KeyboardButton(text="❌ Отмена")],
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

@router.message(lambda message: message.text == "📚 Учебные материалы")
async def handle_materials_earn(message: types.Message, state: FSMContext):
    await materials_handler(message, state)


# Обработчик для кнопки "Пройти тест"
@router.message(lambda message: message.text == "📝 Пройти тест")
async def handle_pass_test(message: types.Message, state: FSMContext):
    # Вызов уже существующего обработчика теста
    await start_test(message, state)

# Обработчик для кнопки "Помощь"
@router.message(lambda message: message.text == "❓ Помощь")
async def handle_help(message: types.Message, state: FSMContext):
    # Здесь можно вывести справочную информацию по работе бота
    await message.answer("🔹 Информация по работе бота:\n- '📝 Пройти тест' — начать тестирование.\n- '❌ Отмена' — отменить текущее действие.")

# Обработчик для кнопки "Отмена"
@router.message(lambda message: message.text == "❌ Отмена")
async def handle_cancel(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Действие отменено.", reply_markup=get_main_menu_keyboard())

@router.message(lambda message: message.text == "🔧 Админ панель")
async def admin_panel(message: types.Message, state: FSMContext):
    # Вызов уже существующего обработчика админки
    await admin_panel_handler(message, state)

@router.message(Command("start"))
async def start_handler(message: types.Message, state: FSMContext):
    logging.info(f"Команда /start от {message.from_user.username}")
    # Проверка на ID администратора
    is_admin = message.from_user.id == int(ADMIN_ID)

    # Формируем клавиатуру в зависимости от того, является ли пользователь администратором
    keyboard = [
        [KeyboardButton(text="📚 Учебные материалы")],
        [KeyboardButton(text="📝 Пройти тест"), KeyboardButton(text="❓ Помощь")],
        [KeyboardButton(text="❌ Отмена")]
    ]
    
    # Добавляем кнопку для админов
    if is_admin:
        keyboard.insert(0, [KeyboardButton(text="🔧 Админ панель")])

    async with SessionLocal() as session:
        user = await session.execute(select(User).filter(User.telegram_id == message.from_user.id))
        user = user.scalar_one_or_none()
        
        if not user:
            new_user = User(
                telegram_id=message.from_user.id,
                first_name=message.from_user.first_name,
                last_name=message.from_user.last_name or ""
            )
            session.add(new_user)
            await session.commit()
            await message.answer(f"🎉 Вы успешно зарегистрированы, <b>{message.from_user.first_name}</b>!\nВыберите команду из меню ниже:", 
                                 reply_markup=ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True))
        else:
            await message.answer(f"👋 Добро пожаловать, <b>{message.from_user.first_name}</b>!\nВыберите команду из меню ниже:", 
                                 reply_markup=ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True))

@router.message(Command("materials"))
async def materials_handler(message: types.Message, state: FSMContext):
    try:
        async with SessionLocal() as session:
            result = await session.execute(select(Materials).filter(Materials.is_active == True))
            materials = result.scalars().all()
            
            if not materials:
                await message.answer("❌ Нет доступных материалов.")
                return

            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text=material.name, callback_data=f"materials{material.id}")]
                                 for material in materials]
            )
            await message.answer("Выберите материал для просмотра:", reply_markup=keyboard)

    except SQLAlchemyError as e:
        logger.error(f"Ошибка при получении материалов: {e}")
        await message.answer("❌ Ошибка при получении списка материалов.")

@router.callback_query(lambda c: c.data and c.data.startswith("materials"))
async def materials_handler_callback(callback: types.CallbackQuery, state: FSMContext):
    try:
        material_id = int(callback.data.split("materials")[-1])
        async with SessionLocal() as session:
            material = await session.execute(select(Materials).filter(Materials.id == material_id))
            material = material.scalar_one_or_none()
            if not material:
                await callback.message.answer("❌ Материал не найден.")
                return
            await callback.message.answer(f"<b>{material.name}</b>\n\n{material.file}", parse_mode="HTML")
    except SQLAlchemyError as e:
        logger.error(f"Ошибка при получении материала: {e}")
    await callback.answer("Материал отправлен.")


@router.message(Command("test"))
async def start_test(message: types.Message, state: FSMContext):
    try:
        async with SessionLocal() as session:
            tests = await session.execute(select(Test).filter(Test.is_active == True))
            tests = tests.scalars().all()
        if not tests:
            await message.answer("❌ Нет доступных тестов.")
            return
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=test.name, callback_data=f"start_test_{test.id}")]
                for test in tests
            ]
        )
        await message.answer("Выберите тест для прохождения:", reply_markup=keyboard)
    except SQLAlchemyError as e:
        await message.answer("❌ Ошибка при получении списка тестов.")


@router.callback_query(lambda c: c.data and c.data.startswith("start_test_"))
async def start_test_callback(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(user_telegram_id=callback.from_user.id)
    test_id = int(callback.data.split("_")[-1])
    try:
        async with SessionLocal() as session:
            questions = await session.execute(select(Question).filter(Question.test_id == test_id, Question.is_active == True))
            questions = questions.scalars().all()
        if not questions:
            await callback.message.answer("В этом тесте пока нет вопросов.")
            return
        # Формирование списка вопросов с вариантами ответов (используем буквы A, B, C, D)
        questions_data = [{
            "id": q.id,
            "text": q.question_text,
            "options": [q.option_a, q.option_b, q.option_c, q.option_d],
            "correct": q.correct_answer
        } for q in questions]
        await state.update_data(test_id=test_id, questions=questions_data, current_index=0, score=0, started_at=datetime.datetime.utcnow())
        await send_current_question(callback.message, state)
    except SQLAlchemyError as e:
        await callback.message.answer("❌ Ошибка при запуске теста.")

async def send_current_question(message: types.Message, state: FSMContext):
    data = await state.get_data()
    index = data.get("current_index", 0)
    questions = data.get("questions", [])
    if index >= len(questions):
        score = data.get("score", 0)
        total = len(questions)
        try:
            async with SessionLocal() as session:
                async with session.begin():
                    await save_user_progress(
                        session,
                        telegram_id = data.get("user_telegram_id"),
                        test_id=data.get("test_id"),
                        score=score,
                        started_at=data.get("started_at"),
                        total=len(data.get("questions", []))
                    )
        except Exception as e:
            logging.error(f"Ошибка сохранения прогресса: {e}")
        await message.answer(f"🎉 Тест завершён! Ваш результат: <b>{score}</b> из <b>{total}</b>", parse_mode="HTML")
        await state.clear()
        return
    question = questions[index]
    letters = ['A', 'B', 'C', 'D']
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"{letter}. {option}", callback_data=f"answer_{index}_{letter}")]
            for letter, option in zip(letters, question["options"])
        ]
    )
    escaped_text = html.escape(question["text"])
    await message.answer(f"<b>Вопрос {index + 1}:</b> {escaped_text}", reply_markup=keyboard, parse_mode="HTML")

@router.callback_query(lambda c: c.data and c.data.startswith("answer_"))
async def answer_question_callback(callback: types.CallbackQuery, state: FSMContext):
    data_parts = callback.data.split("_")
    if len(data_parts) < 3:
        return
    index = int(data_parts[1])
    selected_letter = data_parts[2]
    data = await state.get_data()
    questions = data.get("questions", [])
    if index >= len(questions):
        return
    question = questions[index]
    correct = question["correct"]
    score = data.get("score", 0)
    if selected_letter == correct:
        score += 1
        feedback = f"✅ <b>Верно!</b>"
    else:
        feedback = f"❌ <b>Неверно!</b> Правильный ответ: <b>{correct}</b>"
    await state.update_data(score=score)
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Далее", callback_data="next_question")]
        ]
    )
    await callback.message.edit_text(feedback, reply_markup=keyboard, parse_mode="HTML")

@router.callback_query(lambda c: c.data == "next_question")
async def next_question_callback(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    current_index = data.get("current_index", 0) + 1
    await state.update_data(current_index=current_index)
    await send_current_question(callback.message, state)
@router.message()
async def handle_unexpected(message: types.Message):
    await message.answer("Неизвестная команда. Используйте кнопки меню.")

async def save_user_progress(session: AsyncSession, telegram_id: int, test_id: int, score: int, started_at: datetime.datetime, total: int):
    result = await session.execute(select(User).filter(User.telegram_id == telegram_id))
    user = result.scalar_one_or_none()
    if not user:
        logging.error(f"Пользователь с telegram_id {telegram_id} не найден.")
        return

    progress = UserProgress(
        user_id=user.id,
        test_id=test_id,
        current_question=total,  # либо можно назвать поле completed_questions
        score=score,
        started_at=started_at,
        finished_at=datetime.datetime.utcnow()
    )
    session.add(progress)    