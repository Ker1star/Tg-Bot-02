from aiogram import Router, types, F
from aiogram.filters import Command
from models.db_models import SessionLocal, User, Question, Test, UserProgress, Materials
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.future import select
import datetime, os, random, asyncio, time
import html, logging
from sqlalchemy.ext.asyncio import AsyncSession
from config import ADMIN_ID
from handlers.admin import admin_panel_handler
from handlers.notif import send_admin_notification, send_notification
from collections import defaultdict
from sqlalchemy.orm import joinedload
from zoneinfo import ZoneInfo
router = Router()
logger = logging.getLogger(__name__)

admin_ids = os.getenv('ADMIN_ID')
admin_ids_list = [int(admin_id.strip()) for admin_id in admin_ids.split(',')]

def get_main_menu_keyboard() -> ReplyKeyboardMarkup:
    """
    Формирует клавиатуру с описательными кнопками.
    """
    keyboard = [
        [KeyboardButton(text="📚 Учебные материалы")],
        [KeyboardButton(text="📝 Пройти тест"), KeyboardButton(text="❓ Помощь")],
        [KeyboardButton(text="❌ Отмена"), KeyboardButton(text="🛒 Магазин")]
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

from aiogram.types import WebAppInfo

@router.message(lambda msg: msg.text == "🛒 Магазин")
async def show_store_button(message: types.Message):
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(
                text="Открыть магазин",
                web_app=WebAppInfo(url="https://e3a4-151-236-4-174.ngrok-free.app")
            )
        ]]
    )
    await message.answer("Добро пожаловать в магазин!", reply_markup=keyboard)


@router.message(lambda message: message.text == "📚 Учебные материалы")
async def handle_materials_earn(message: types.Message, state: FSMContext):
    await materials_handler(message, state)



@router.message(lambda message: message.text == "📝 Пройти тест")
async def handle_pass_test(message: types.Message, state: FSMContext):
    await start_test(message, state)

@router.message(lambda message: message.text == "❓ Помощь")
async def handle_help(message: types.Message, state: FSMContext):
    help_text = (
        "🤖 <b>Добро пожаловать в раздел помощи!</b>\n\n"
        "Вот несколько советов по работе с ботом:\n\n"
        "📝 <b>Пройти тест</b>\n"
        "Нажмите кнопку <b>📝 Пройти тест</b> для начала тестирования. Выберите интересующий тест и следуйте инструкциям.\n\n"
        "📊 <b>Мой прогресс</b>\n"
        "Нажмите кнопку 📊 <b>Мой прогресс</b> для получения результатов пройденных Вами тестов.\n\n"
        "<b>📚 Учебные материалы</b>\n"
        "Кнопка <b>📚 Учебные материалы</b> открывает список материалов для изучения. Выберите нужный раздел для просмотра.\n\n"
        "❌ <b>Отмена</b>\n"
        "Если вы хотите прервать текущее действие, нажмите кнопку <b>❌ Отмена</b>.\n\n"
        "Если у вас возникли вопросы или проблемы, обратитесь к администратору."
    )
  
    await message.answer(help_text, parse_mode="HTML", reply_markup=get_main_menu_keyboard())


@router.message(lambda message: message.text == "❌ Отмена")
async def handle_cancel(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Действие отменено.", reply_markup=get_main_menu_keyboard())

@router.message(lambda message: message.text == "🔧 Админ панель")
async def admin_panel(message: types.Message, state: FSMContext):
    await admin_panel_handler(message, state)

@router.message(Command("start"))
async def start_handler(message: types.Message, state: FSMContext):
    logging.info(f"Команда /start от {message.from_user.username}")

    keyboard = [
        [KeyboardButton(text="📚 Учебные материалы")], [KeyboardButton(text="📊 Мой прогресс"), KeyboardButton(text="🛒 Магазин")],
        [KeyboardButton(text="📝 Пройти тест"), KeyboardButton(text="❓ Помощь")],
        [KeyboardButton(text="❌ Отмена")],
    ]
    
    if message.from_user.id in admin_ids_list:  
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
            message_for_admin = f"Пользователь {message.from_user.first_name} зарегестрирован в системе.\n" 

            await session.commit()
            await message.answer(f"🎉 Вы успешно зарегистрированы, <b>{message.from_user.first_name}</b>!\nВыберите команду из меню ниже:", 
                                 reply_markup=ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True))
            await send_notification( 511147194, message_for_admin)
            
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
            # Получаем все активные тесты
            tests_result = await session.execute(select(Test).filter(Test.is_active == True))
            tests = tests_result.scalars().all()
            if not tests:
                await message.answer("❌ Нет доступных тестов.")
                return
            # Получаем данные пользователя
            result = await session.execute(select(User).filter(User.telegram_id == message.from_user.id))
            user = result.scalar_one_or_none()
            passed_test_ids = set()
            if user:
                progress_result = await session.execute(select(UserProgress).filter(UserProgress.user_id == user.id))
                progress_list = progress_result.scalars().all()
                for progress in progress_list:
                    # Если пользователь прошёл тест (процент > 85%)
                    if progress.current_question > 0 and (progress.score / progress.current_question) > 0.85:
                        passed_test_ids.add(progress.test_id)
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text=f"{'✅ ' if test.id in passed_test_ids else ''}{test.name}", callback_data=f"start_test_{test.id}")]
                    for test in tests
                ]
            )
        await message.answer("Выберите тест для прохождения:", reply_markup=keyboard)
    except SQLAlchemyError as e:
        await message.answer("❌ Ошибка при получении списка тестов.")


@router.callback_query(lambda c: c.data and c.data.startswith("start_test_"))
async def start_test_callback(callback: types.CallbackQuery, state: FSMContext):
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception as e:
        logger.error(f"Ошибка при удалении клавиатуры: {e}")

    # Проверяем флаг, чтобы не обрабатывать повторно
    data = await state.get_data()
    if data.get("processing_test", False):
        await callback.answer("Пожалуйста, подождите...", show_alert=True)
        return

    await state.update_data(processing_test=True)
    await state.update_data(user_telegram_id=callback.from_user.id)
    test_id = int(callback.data.split("_")[-1])
    user_telegram_id = callback.from_user.id
    # Проверяем, сдавал ли пользователь этот тест ранее
    async with SessionLocal() as session:
         result = await session.execute(select(User).filter(User.telegram_id == user_telegram_id))
         user = result.scalar_one_or_none()
         if user:
             result = await session.execute(select(UserProgress).filter(
                     UserProgress.user_id == user.id,
                     UserProgress.test_id == test_id
             ))
             progress_list = result.scalars().all()
             for progress in progress_list:
                 if progress.current_question > 0 and (progress.score / progress.current_question) > 0.85:
                     await callback.message.answer("✅ Тест уже пройден!")
                     await state.update_data(processing_test=False) 
                     await callback.answer() 
                     return

    try:
        async with SessionLocal() as session:
            result = await session.execute(
            select(Question)
            .options(joinedload(Question.images))
            .filter(Question.test_id == test_id, Question.is_active == True)
            )
            result = result.unique()  # устранение дублирующих записей
            questions = result.scalars().all()
        if not questions:
            await callback.message.answer("В этом тесте пока нет вопросов.")
            return
         # Перемешиваем вопросы случайным образом
        random.shuffle(questions)
        questions_data = [{
            "id": q.id,
            "text": q.question_text,
            "options": [q.option_a, q.option_b, q.option_c, q.option_d], 
            "correct": q.correct_answer,
            "images": [img.image for img in q.images]
        } for q in questions]
        await state.update_data(test_id=test_id, questions=questions_data, current_index=0, score=0, started_at=datetime.datetime.utcnow())
        await send_current_question(callback.message, state)
    except SQLAlchemyError as e:
        logger.error(f"Ошибка при запуске теста: {e}")
        await callback.message.answer("❌ Ошибка при запуске теста.")

async def send_current_question(message: types.Message, state: FSMContext):
    data = await state.get_data()
    index = data.get("current_index", 0)
    questions = data.get("questions", [])
    if index >= len(questions):
        # Если флаг "finished" уже установлен, выходим из функции
        if data.get("finished", False):
            return
        await state.update_data(finished=True)
        score = data.get("score", 0)
        total = len(questions)
        # Вычисляем процент правильных ответов
        if total > 0:
            percentage = (score / total) * 100
        else:
            percentage = 0  # Если нет вопросов, то процент равен 0

        test_id = data.get("test_id")
        # Получаем название теста по test_id
        async with SessionLocal() as session:
            test = await session.execute(select(Test).filter(Test.id == test_id))
            test = test.scalar_one_or_none()
            test_name = test.name if test else "Неизвестный тест"

        # Получаем данные пользователя по telegram_id
        async with SessionLocal() as session:
            result = await session.execute(select(User).filter(User.telegram_id == data.get("user_telegram_id")))
            user_obj = result.scalar_one_or_none()
            if user_obj:
                user_name = user_obj.first_name + (f" {user_obj.last_name}" if user_obj.last_name else "")
            else:
                user_name = "Неизвестный пользователь"

        # Оценка результата
        result = "успешно сдан✅ " if percentage > 85 else "не сдан❌"
        message_for_admin = f"Пользователь {user_name} завершил тест '{test_name}'. Результат: {score}/{total} ({percentage:.2f}%). Тест {result}."

        
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
        if result == "успешно сдан✅ ":
            await message.answer(f"🎉 Тест завершён! Ваш результат: <b>{score}</b> из <b>{total}</b> ({percentage:.2f}%). Тест {result}.", parse_mode="HTML")
        else:
            await message.answer(f"❌ Тест завершён! Ваш результат: <b>{score}</b> из <b>{total}</b> ({percentage:.2f}%). Тест {result}. Еще раз просмотрите материалы и попробуйте снова.", parse_mode="HTML")
        await send_admin_notification(message_for_admin)

        await state.clear()
        return
    question = questions[index]
    letters = ['A', 'B', 'C', 'D']

    
    if question.get("images") and len(question["images"]) > 0:
        images = question["images"]
        if len(images) == 1:
            # Отправляем одно изображение с подписью (текст вопроса)
            question_msg = await message.answer_photo(
                photo=images[0],
                caption=f"<b>Вопрос {index + 1}:</b> {html.escape(question['text'])}",
                parse_mode="HTML"
            )
        else:
            # Если изображений несколько – отправляем медиагруппу, подпись добавляем к первому фото
            media = [types.InputMediaPhoto(media=img) for img in images]
            media[0].caption = f"<b>Вопрос {index + 1}:</b> {html.escape(question['text'])}"
            media[0].parse_mode = "HTML"
            await message.answer_media_group(media)
    else:
        # Если изображений нет, просто отправляем текст вопроса
        question_msg = await message.answer(f"<b>Вопрос {index + 1}:</b> {html.escape(question['text'])}", parse_mode="HTML")

    # Отправляем варианты ответов
    options_message = "\n".join([f"<b>{letter}:</b> <i>{option}</i>" for letter, option in zip(letters, question["options"])])
    options_msg = await message.answer(f"<b>Ответы на вопрос {index + 1}:</b>\n{options_message}", parse_mode="HTML")

    # Формируем клавиатуру с вариантами ответов
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=letter, callback_data=f"answer_{index}_{letter}")]
            for letter in letters
        ]
    )
    keyboard_msg = await message.answer("Выберите вариант ответа:", reply_markup=keyboard)
    await state.update_data(
        question_msg_id=question_msg.message_id,
        options_msg_id=options_msg.message_id,
        keyboard_msg_id=keyboard_msg.message_id
        )

@router.callback_query(lambda c: c.data and c.data.startswith("answer_"))
async def answer_question_callback(callback: types.CallbackQuery, state: FSMContext):
    data_parts = callback.data.split("_")
    index = int(data_parts[1])
    selected_letter = data_parts[2]

    data = await state.get_data()
    question = data["questions"][index]
    correct = question["correct"]
    score = data["score"]

    # Обновляем счёт, если нужно
    if selected_letter == correct:
        score += 1
    await state.update_data(score=score)

    # Удаляем старые сообщения с вопросом и вариантами
    chat_id = callback.message.chat.id
    for key in ("question_msg_id", "options_msg_id"):
        msg_id = data.get(key)
        if msg_id:
            try:
                await callback.message.bot.delete_message(chat_id, msg_id)
            except Exception as e:
                logger.error(f"Ошибка удаления сообщения {msg_id}: {e}")

    # Строим новый «красивый» текст
    letters = ['A', 'B', 'C', 'D']
    lines = []
    for letter, opt in zip(letters, question["options"]):
        if letter == correct:
            mark = "✅"              # правильный вариант
        elif letter == selected_letter:
            mark = "❌"              # куда нажал пользователь
        else:
            mark = "▫️"              # остальные
        lines.append(f"{mark} <b>{letter}:</b> {html.escape(opt)}")

    ui_text = (
        f"<b>Вопрос {index+1}:</b> {html.escape(question['text'])}\n\n"
        + "\n".join(lines)
    )

    # Кнопка «Далее»
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➡️ Далее", callback_data="next_question")]
        ]
    )

    # Редактируем исходное сообщение кнопки, вставляя наш UI
    await callback.message.edit_text(ui_text, parse_mode="HTML", reply_markup=keyboard)

# Глобальный словарь блокировок для каждого пользователя
user_locks = {}

# Глобальный словарь для хранения времени последнего нажатия "Далее" для каждого пользователя
user_next_question_time = defaultdict(lambda: 0)
THROTTLE_PERIOD = 2.0  # время в секундах, в течение которого повторный tap будет игнорироваться

@router.callback_query(lambda c: c.data == "next_question")
async def next_question_callback(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    now = time.monotonic()
    if now - user_next_question_time[user_id] < THROTTLE_PERIOD:
         # Если прошло недостаточно времени с предыдущего нажатия – уведомляем пользователя и не обрабатываем запрос
         await callback.answer("Пожалуйста, подождите...", show_alert=True)
         return
    # Обновляем время последнего нажатия
    user_next_question_time[user_id] = now

     # Удаляем предыдущий блок с обратной связью целиком
    try:
        await callback.message.delete()
    except Exception as e:
        logger.error(f"Не удалось удалить сообщение с обратной связью: {e}")

    data = await state.get_data()
    if not data:
         await callback.answer("Тест уже завершён!", show_alert=True)
         return

    # Можно дополнительно использовать флаг в состоянии (если требуется)
    if data.get("processing_next", False):
         await callback.answer("Пожалуйста, подождите...", show_alert=True)
         return

    await state.update_data(processing_next=True)
    current_index = data.get("current_index", 0) + 1
    await state.update_data(current_index=current_index)
    await send_current_question(callback.message, state)
    await state.update_data(processing_next=False)

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

@router.message(lambda message: message.text == "📊 Мой прогресс")
async def handle_progress(message: types.Message, state: FSMContext):
    try:
        async with SessionLocal() as session:
            # Получаем пользователя по telegram_id
            result = await session.execute(select(User).filter(User.telegram_id == message.from_user.id))
            user = result.scalar_one_or_none()
            if not user:
                await message.answer("Похоже, вы не зарегистрированы. Используйте команду /start для регистрации.")
                return

            # Получаем записи прогресса пользователя, сортируя по дате завершения (сначала последние)
            result = await session.execute(
            select(UserProgress)
            .options(joinedload(UserProgress.test))
            .filter(UserProgress.user_id == user.id)
            .order_by(UserProgress.finished_at.desc())
            )
            progress_list = result.scalars().all()

        if not progress_list:
            await message.answer("У вас пока нет записей прогресса.")
            return

        # Формируем сообщение с отчётом
        msg = "📊 <b>Ваш прогресс:</b>\n\n"
        for progress in progress_list:
            # Если связь с тестом настроена (relationship) – можно получить имя теста
            test_name = progress.test.name if progress.test else "Неизвестный тест"
            finished_date = progress.finished_at.strftime("%d.%m.%Y %H:%M") 
            if progress.finished_at:
                # Преобразуем время завершения из UTC в московскую зону (Europe/Moscow)
                finished_date_moscow = progress.finished_at.replace(tzinfo=datetime.timezone.utc).astimezone(ZoneInfo("Europe/Moscow"))
                finished_date = finished_date_moscow.strftime("%d.%m.%Y %H:%M")
            else:
                finished_date = "N/A"
            if progress.current_question:
                percent = (progress.score / progress.current_question) * 100
            else:
                percent = 0
            msg += (
                f"• <b>{test_name}</b>\n"
                f"  Результат: {progress.score}/{progress.current_question} ({percent:.2f}%)\n"
                f"  Завершён: {finished_date}\n\n"
            )
        await message.answer(msg, parse_mode="HTML")
    except SQLAlchemyError as e:
        logger.error(f"Ошибка при получении прогресса: {e}")
        await message.answer("❌ Ошибка при получении вашего прогресса.")    