from aiogram import Router, types, F
from aiogram.filters import Command
from models.db_models import SessionLocal, User, Question, Test, UserProgress, Materials, Answer
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton, CallbackQuery
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
from aiogram.exceptions import TelegramBadRequest
router = Router()
logger = logging.getLogger(__name__)

admin_ids = os.getenv('ADMIN_ID')
admin_ids_list = [int(admin_id.strip()) for admin_id in admin_ids.split(',')]

def get_main_menu_keyboard() -> ReplyKeyboardMarkup:
    keyboard = [
        [KeyboardButton(text="📚 Учебные материалы")],
        [KeyboardButton(text="📝 Пройти тест"), KeyboardButton(text="❓ Помощь")],
        [KeyboardButton(text="❌ Отмена")]
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)


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
        [KeyboardButton(text="📚 Учебные материалы"), KeyboardButton(text="📊 Мой прогресс")],
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

# Для throttle на “Далее”
user_next_question_time = defaultdict(lambda: 0)
THROTTLE_PERIOD = 2.0  # сек

# -----------------------------------------------------------------------------
# Обработчик выбора ответа
# -----------------------------------------------------------------------------
@router.callback_query(lambda c: c.data.startswith("answer_"))
async def answer_question_callback(callback: CallbackQuery, state: FSMContext):
    # 1) моментальный ack
    try:
        await callback.answer()
    except TelegramBadRequest as e:
        logger.warning(f"answer_question: callback.answer failed: {e}")

    # 2) получаем текущее состояние
    data = await state.get_data()
    current_q_idx = int(callback.data.split("_")[1])
    answered = set(data.get("answered_questions", []))

    # 3) блокировка повторов
    if data.get("processing_answer", False):
        return
    if current_q_idx in answered:
        try:
            await callback.answer("Вы уже ответили на этот вопрос.", show_alert=True)
        except TelegramBadRequest:
            pass
        return

    # 4) ставим флаг «в процессе» и отмечаем вопрос отвеченным
    await state.update_data(processing_answer=True)
    answered.add(current_q_idx)
    await state.update_data(answered_questions=list(answered))

    # 5) сохраняем локально текущий score
    current_score = data.get("score", 0)

    try:
        # 6) снимаем клавиатуру
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except TelegramBadRequest as e:
            logger.warning(f"answer_question: remove keyboard failed: {e}")

        # 7) сохраняем ответ в БД
        selected_letter = callback.data.split("_")[2]
        question = data["questions"][current_q_idx]
        is_correct = (selected_letter == question["correct"])
        async with SessionLocal() as session:
            user = (await session.execute(
                select(User).filter(User.telegram_id == callback.from_user.id)
            )).scalar_one()
            answer = Answer(
                user_id=user.id,
                question_id=question["id"],
                selected_answer=selected_letter,
                is_correct=is_correct
            )
            session.add(answer)
            await session.commit()

        # 8) **инкрементируем score**
        if is_correct:
            current_score += 1
            await state.update_data(score=current_score)

        # 9) удаляем вопрос и варианты
        chat_id = callback.message.chat.id
        for key in ("question_msg_id", "options_msg_id"):
            msg_id = data.get(key)
            if msg_id:
                try:
                    await callback.message.bot.delete_message(chat_id, msg_id)
                except Exception as e:
                    logger.error(f"Ошибка удаления msg {msg_id}: {e}")

        # 10) строим фидбек и кнопку «Далее»
        letters = ['A','B','C','D']
        lines = []
        for letter, opt in zip(letters, question["options"]):
            mark = "✅" if letter == question["correct"] else ("❌" if letter == selected_letter else "▫️")
            lines.append(f"{mark} <b>{letter}:</b> {html.escape(opt)}")
        ui_text = (
            f"<b>Вопрос {current_q_idx+1}:</b> {html.escape(question['text'])}\n\n"
            + "\n".join(lines)
        )
        next_kb = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="➡️ Далее", callback_data="next_question")]]
        )
        try:
            await callback.message.edit_text(ui_text, parse_mode="HTML", reply_markup=next_kb)
        except TelegramBadRequest as e:
            if "not modified" not in str(e):
                logger.error(f"answer_question: edit_text failed: {e}")

    finally:
        # 11) снимаем флаг блокировки
        await state.update_data(processing_answer=False)
# -----------------------------------------------------------------------------
# Обработчик кнопки “Далее”
# -----------------------------------------------------------------------------
@router.callback_query(lambda c: c.data == "next_question")
async def next_question_callback(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    now = time.monotonic()

    # Throttle
    if now - user_next_question_time[user_id] < THROTTLE_PERIOD:
        try:
            await callback.answer("Пожалуйста, подождите...", show_alert=True)
        except TelegramBadRequest:
            pass
        return
    user_next_question_time[user_id] = now

    # ack сразу
    try:
        await callback.answer()
    except TelegramBadRequest as e:
        logger.warning(f"next_question: callback.answer failed: {e}")

    # снимаем клавиатуру
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except TelegramBadRequest as e:
        logger.warning(f"next_question: remove keyboard failed: {e}")

    # защита от параллельного запуска
    data = await state.get_data()
    if data.get("processing_next"):
        return
    await state.update_data(processing_next=True)

    # удаляем feedback-сообщение целиком
    try:
        await callback.message.delete()
    except TelegramBadRequest as e:
        logger.warning(f"next_question: delete feedback failed: {e}")

    # отправляем следующий вопрос
    await state.update_data(current_index=data.get("current_index", 0) + 1)
    await send_current_question(callback.message, state)

    # сбрасываем флаг
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