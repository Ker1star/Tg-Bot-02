from aiogram import Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from config import ADMIN_ID
from states.forms import AddQuestionForm, EditQuestionForm, TestCreationForm, DeleteQuestionForm, AddMaterialsForm
from models.db_models import SessionLocal, Question, Test, UserProgress, Materials
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.future import select
from sqlalchemy.orm import joinedload
from collections import defaultdict
from handlers.notif import send_notifications_to_all_users
#from handlers.admin import start_edit_question_process, create_test_start, add_question_start, start_edit_question_process
import logging

logger = logging.getLogger(__name__)

router = Router()

def get_admin_panel_keyboard() -> ReplyKeyboardMarkup:
    """
    Формирует клавиатуру панели администратора.
    """
    keyboard = [
        [KeyboardButton(text="Добавить материалы")],
        [KeyboardButton(text="Создать тест"), KeyboardButton(text="Добавить вопрос")],
        [KeyboardButton(text="Редактировать вопрос")],
        [KeyboardButton(text="Отслеживание прогресса")],
        [KeyboardButton(text="Удалить тест"), KeyboardButton(text="Удалить вопрос")],
        [KeyboardButton(text="Назад"), KeyboardButton(text="Отмена")]
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

# Команда для вывода панели администратора
@router.message(Command("admin_panel"))
async def admin_panel_handler(message: types.Message, state: FSMContext):
    if message.from_user.id != int(ADMIN_ID):
        await message.answer("❌ У вас нет доступа к админке.")
        return
    await message.answer("Панель администратора:", reply_markup=get_admin_panel_keyboard())

# Обработчик для кнопки "Создать тест"
@router.message(lambda message: message.text == "Создать тест")
async def handle_create_test_admin(message: types.Message, state: FSMContext):
    await create_test_start(message, state)

# Обработчик для кнопки "Добавить вопрос"
@router.message(lambda message: message.text == "Добавить вопрос")
async def handle_add_question_admin(message: types.Message, state: FSMContext):
    await add_question_start(message, state)

# Обработчик для кнопки "Редактировать вопрос"
@router.message(lambda message: message.text == "Редактировать вопрос")
async def handle_edit_question_admin(message: types.Message, state: FSMContext):
    await start_edit_question_process(message, state)

# Обработчик для кнопки "Отмена" в админке
@router.message(lambda message: message.text == "Отмена")
async def handle_admin_cancel(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Действие отменено.", reply_markup=get_admin_panel_keyboard())

@router.message(lambda message: message.text == "Добавить материалы")
async def handle_add_materials_admin(message: types.Message, state: FSMContext):
    await message.answer("Введите название темы для материалов")
    await state.set_state(AddMaterialsForm.name)

#добавление материалов
@router.message (Command("add_materials"))
async def add_materials(message:types.Message, state: FSMContext):
    await message.answer ("Введите название темы для материалов")
    await state.set_state(AddMaterialsForm.name)
@router.message(AddMaterialsForm.name)
async def process_materilas_name(message:types.Message, state: FSMContext):
    await state.update_data(name=message.text)
    await message.answer("Прикрепите ссылку на материалы")
    await state.set_state(AddMaterialsForm.file)

@router.message(AddMaterialsForm.file)
async def process_materilas_file(message:types.Message, state: FSMContext):
    data=await state.get_data()
    materials_name=data.get("name")
    materials_file=message.text
    try:
        async with SessionLocal() as session:
            new_materials=Materials(name=materials_name, file=materials_file)
            session.add(new_materials)
            await session.commit()
            logger.info(f"Добавлены материалы '{new_materials.name}' с ID {new_materials.id}")
        await message.answer(f"✅ Материалы <b>{materials_name}</b> успешно добавлены!")
        await send_notifications_to_all_users(f"📚 Новый материал: {new_materials.name} добавлен! Подробнее в разделе материалов.")
    except SQLAlchemyError as e:
        logger.error("Ошибка при добавлении материалов: %s", e)
        await message.answer("❌ Ошибка при добавлении материалов!")
    
    await state.clear()

# Создание нового теста
@router.message(Command("create_test"))
async def create_test_start(message: types.Message, state: FSMContext):
    if message.from_user.id != int(ADMIN_ID):
        await message.answer("❌ У вас нет доступа к этой команде.")
        return
    await state.clear()
    await message.answer("<b>Создание нового теста</b>\nВведите название теста:")
    await state.set_state(TestCreationForm.name)

@router.message(TestCreationForm.name)
async def process_test_name(message: types.Message, state: FSMContext):
    await state.update_data(test_name=message.text)
    await message.answer("Введите описание теста:")
    await state.set_state(TestCreationForm.description)

@router.message(TestCreationForm.description)
async def process_test_description(message: types.Message, state: FSMContext):
    data = await state.get_data()
    test_name = data.get("test_name")
    test_description = message.text
    try:
        async with SessionLocal() as session:
            new_test = Test(name=test_name, description=test_description)
            session.add(new_test)
            await session.commit()
            logger.info(f"Создан тест '{new_test.name}' с ID {new_test.id}")
        await message.answer(f"✅ Тест <b>{test_name}</b> успешно создан!")
    except SQLAlchemyError as e:
        logger.error("Ошибка при создании теста: %s", e)
        await message.answer("❌ Ошибка при создании теста!")
    await state.clear()

# Добавление нового вопроса
@router.message(Command("add_question"))
async def add_question_start(message: types.Message, state: FSMContext):
    if message.from_user.id != int(ADMIN_ID):
        await message.answer("❌ У вас нет доступа к этой команде.")
        return
    await state.clear()
    try:
        async with SessionLocal() as session:
            tests = await session.execute(select(Test))
            tests = tests.scalars().all()
        if not tests:
            await message.answer("Нет доступных тестов. Сначала создайте тест командой /create_test.")
            return
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=test.name, callback_data=f"select_test_{test.id}")]
                for test in tests
            ]
        )
        await message.answer("Выберите тест для добавления вопроса:", reply_markup=keyboard)
        await state.set_state(AddQuestionForm.select_test)
    except SQLAlchemyError as e:
        logger.error("Ошибка при получении тестов: %s", e)
        await message.answer("❌ Ошибка при получении тестов!")

@router.callback_query(lambda c: c.data and c.data.startswith("select_test_"))
async def process_test_selection(callback: types.CallbackQuery, state: FSMContext):
    test_id = int(callback.data.split("_")[-1])
    await state.update_data(test_id=test_id)
    await callback.message.answer("Введите текст вопроса:")
    await state.set_state(AddQuestionForm.question_text)

@router.message(AddQuestionForm.question_text)
async def process_question_text(message: types.Message, state: FSMContext):
    await state.update_data(question_text=message.text)
    await message.answer("Введите вариант ответа A:")
    await state.set_state(AddQuestionForm.option_a)

@router.message(AddQuestionForm.option_a)
async def process_option_a(message: types.Message, state: FSMContext):
    await state.update_data(option_a=message.text)
    await message.answer("Введите вариант ответа B:")
    await state.set_state(AddQuestionForm.option_b)

@router.message(AddQuestionForm.option_b)
async def process_option_b(message: types.Message, state: FSMContext):
    await state.update_data(option_b=message.text)
    await message.answer("Введите вариант ответа C:")
    await state.set_state(AddQuestionForm.option_c)

@router.message(AddQuestionForm.option_c)
async def process_option_c(message: types.Message, state: FSMContext):
    await state.update_data(option_c=message.text)
    await message.answer("Введите вариант ответа D:")
    await state.set_state(AddQuestionForm.option_d)

@router.message(AddQuestionForm.option_d)
async def process_option_d(message: types.Message, state: FSMContext):
    await state.update_data(option_d=message.text)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="A", callback_data="correct_A"),
         InlineKeyboardButton(text="B", callback_data="correct_B")],
        [InlineKeyboardButton(text="C", callback_data="correct_C"),
         InlineKeyboardButton(text="D", callback_data="correct_D")]
    ])
    await message.answer("Выберите правильный ответ:", reply_markup=keyboard)
    await state.set_state(AddQuestionForm.correct_answer)

@router.callback_query(lambda c: c.data and c.data.startswith("correct_"))
async def process_correct_answer(callback: types.CallbackQuery, state: FSMContext):
    correct = callback.data.split("_")[1]
    await state.update_data(correct_answer=correct)
    data = await state.get_data()
    try:
        async with SessionLocal() as session:
            new_question = Question(
                test_id=data['test_id'],
                question_text=data['question_text'],
                option_a=data['option_a'],
                option_b=data['option_b'],
                option_c=data['option_c'],
                option_d=data['option_d'],
                correct_answer=data['correct_answer']
            )
            session.add(new_question)
            await session.commit()
            logger.info(f"Админ {callback.from_user.id} добавил вопрос {new_question.id} в тест {data['test_id']}")
        response = (
            f"<b>Вопрос:</b> {data['question_text']}\n"
            f"<b>A:</b> {data['option_a']}\n"
            f"<b>B:</b> {data['option_b']}\n"
            f"<b>C:</b> {data['option_c']}\n"
            f"<b>D:</b> {data['option_d']}\n"
            f"<b>Правильный ответ:</b> {data['correct_answer']}"
        )
        await callback.message.edit_text("Новый вопрос добавлен:\n\n" + response, parse_mode="HTML")
    except SQLAlchemyError as e:
        logger.error("Ошибка при добавлении вопроса: %s", e)
        await callback.message.answer("❌ Ошибка при сохранении вопроса!")
    await state.clear()

@router.message(Command("edit_question"))
async def start_edit_question_process(message: types.Message, state: FSMContext):
    if message.from_user.id != int(ADMIN_ID):
        await message.answer("❌ У вас нет доступа к этой команде.")
        return

    await state.clear()
    
    # Получаем список тестов
    async with SessionLocal() as session:
        tests = await session.execute(select(Test))
        tests = tests.scalars().all()

    if not tests:
        await message.answer("Нет доступных тестов. Сначала создайте тест.")
        return

    # Предлагаем выбрать тест
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=test.name, callback_data=f"edit_test_{test.id}")]
            for test in tests
        ]
    )
    await message.answer("Выберите тест для редактирования вопросов:", reply_markup=keyboard)
    await state.set_state(EditQuestionForm.select_test_for_edit)

@router.callback_query(lambda c: c.data and c.data.startswith("edit_test_"))
async def select_test_for_edit(callback: types.CallbackQuery, state: FSMContext):
    test_id = int(callback.data.split("_")[-1])
    await state.update_data(test_id=test_id)
    
    # Получаем вопросы, связанные с выбранным тестом
    async with SessionLocal() as session:
        result = await session.execute(select(Question).filter(Question.test_id == test_id))
        questions = result.scalars().all()

    if not questions:
        await callback.message.answer("В этом тесте нет вопросов.")
        await state.clear()
        return

    # Предлагаем выбрать вопрос для редактирования
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"Вопрос {q.id}: {q.question_text[:30]}...", callback_data=f"edit_question_{q.id}")]
            for q in questions
        ]
    )
    await callback.message.answer("Выберите вопрос для редактирования:", reply_markup=keyboard)
    await state.set_state(EditQuestionForm.select_question_to_edit)

@router.callback_query(lambda c: c.data and c.data.startswith("edit_question_"))
async def select_question_for_edit(callback: types.CallbackQuery, state: FSMContext):
    question_id = int(callback.data.split("_")[-1])
    await state.update_data(question_id=question_id)  # Ключевая строка!

    # Получаем данные вопроса
    async with SessionLocal() as session:
        question = await session.get(Question, question_id)

    if not question:
        await callback.message.answer("Вопрос не найден!")
        await state.clear()
        return

    # Сохраняем старые данные для редактирования
    await state.update_data(
        old_question_text=question.question_text,
        old_option_a=question.option_a,
        old_option_b=question.option_b,
        old_option_c=question.option_c,
        old_option_d=question.option_d,
        old_correct_answer=question.correct_answer
    )

    # Отправляем администратору текущие данные вопроса для редактирования
    await callback.message.answer(
        f"<b>Текущий вопрос:</b>\n"
        f"{question.question_text}\n"
        f"<b>A:</b> {question.option_a}\n"
        f"<b>B:</b> {question.option_b}\n"
        f"<b>C:</b> {question.option_c}\n"
        f"<b>D:</b> {question.option_d}\n"
        f"<b>Правильный ответ:</b> {question.correct_answer}\n\n"
        "Введите новый текст вопроса или /skip чтобы оставить без изменений:",
        parse_mode="HTML"
    )
    await state.set_state(EditQuestionForm.question_text)

@router.message(EditQuestionForm.question_text)
async def process_edit_question_text(message: types.Message, state: FSMContext):
    data = await state.get_data()
    new_text = message.text.strip()

    # Если текст пустой, оставляем старый
    if new_text == "/skip":
        new_text = data['old_question_text']

    # Обновляем состояние
    await state.update_data(question_text=new_text)

    # Запрашиваем вариант A
    await message.answer("Введите новый вариант ответа A:")
    await state.set_state(EditQuestionForm.option_a)


@router.message(EditQuestionForm.option_a)
async def process_edit_option_a(message: types.Message, state: FSMContext):
    await state.update_data(option_a=message.text)
    await message.answer("Введите новый вариант ответа B:")
    await state.set_state(EditQuestionForm.option_b)

@router.message(EditQuestionForm.option_b)
async def process_edit_option_b(message: types.Message, state: FSMContext):
    await state.update_data(option_b=message.text)
    await message.answer("Введите новый вариант ответа C:")
    await state.set_state(EditQuestionForm.option_c)

@router.message(EditQuestionForm.option_c)
async def process_edit_option_c(message: types.Message, state: FSMContext):
    await state.update_data(option_c=message.text)
    await message.answer("Введите новый вариант ответа D:")
    await state.set_state(EditQuestionForm.option_d)

@router.message(EditQuestionForm.option_d)
async def process_edit_option_d(message: types.Message, state: FSMContext):
    await state.update_data(option_d=message.text)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="A", callback_data="edit_correct_A"),  # Уникальный префикс correct_edit_
     InlineKeyboardButton(text="B", callback_data="edit_correct_B")],
    [InlineKeyboardButton(text="C", callback_data="edit_correct_C"),
     InlineKeyboardButton(text="D", callback_data="edit_correct_D")]
])
    await message.answer("Выберите правильный ответ:", reply_markup=keyboard)
    await state.set_state(EditQuestionForm.correct_answer)


@router.callback_query(lambda c: c.data.startswith("edit_correct_"))
async def process_edit_correct_answer(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    
    if "question_id" not in data:
        await callback.answer("❌ Ошибка: ID вопроса не найден.")
        await state.clear()
        return
    
    correct_answer = callback.data.split("_")[-1]
    
    try:
        async with SessionLocal() as session:
            # Получаем существующий вопрос
            question = await session.get(Question, data["question_id"])
            if not question:
                await callback.answer("⚠️ Вопрос не найден!")
                return
            
            # Обновляем поля
            question.question_text = data.get("question_text", "")
            question.option_a = data.get("option_a", "")
            question.option_b = data.get("option_b", "")
            question.option_c = data.get("option_c", "")
            question.option_d = data.get("option_d", "")
            question.correct_answer = correct_answer
            
            session.merge(question)
            await session.commit()  # Важно: НЕ вызываем session.add()
            
            response = (
                f"✅ Вопрос #{question.id} обновлён!\n"
                f"Текст: {question.question_text}\n"
                f"A: {question.option_a}\nB: {question.option_b}\n"
                f"C: {question.option_c}\nD: {question.option_d}\n"
                f"Правильный ответ: {correct_answer}"
            )
            await callback.message.edit_text(response)
    
    except SQLAlchemyError as e:
        logger.error(f"Ошибка: {e}")
        await callback.answer("❌ Ошибка сохранения!")
    finally:
        await state.clear()

@router.message(lambda message: message.text == "Отслеживание прогресса")
async def handle_view_progress(message: types.Message, state: FSMContext):
    if message.from_user.id != int(ADMIN_ID):
        await message.answer("❌ У вас нет доступа к этой команде.")
        return
    try:
        async with SessionLocal() as session:
            result = await session.execute(
                select(UserProgress)
                .options(joinedload(UserProgress.user), joinedload(UserProgress.test))
                .order_by(UserProgress.finished_at.desc())
            )
            progress_entries = result.scalars().all()
        if not progress_entries:
            await message.answer("Нет записей прогресса пользователей.")
            return
        # Группировка прогресса по пользователю
        user_progress = defaultdict(list)
        for progress in progress_entries:
            user_progress[progress.user.telegram_id].append(progress)

        # Формирование ответа
        text = "<b>Прогресс пользователей:</b>\n"
        for telegram_id, progresses in user_progress.items():
            # Получаем информацию о пользователе (первый прогресс)
            user = progresses[0].user
            user_info = f"{user.first_name} {user.last_name} (ID: {user.telegram_id})"
            
            text += f"\n<b>{user_info}:</b>\n"
            
            # Добавляем информацию по каждому прогрессу пользователя
            for progress in progresses:
                test_info = progress.test.name if progress.test else "Неизвестный тест"
                finished_at = progress.finished_at.strftime("%Y-%m-%d %H:%M") if progress.finished_at else "N/A"
                text += (f"  - Тест: {test_info} | Баллы: {progress.score} | Завершен: {finished_at}\n")

        await message.answer(text, parse_mode="HTML")

    except SQLAlchemyError as e:
        logger.error("Ошибка при получении прогресса: %s", e)
        await message.answer("❌ Ошибка при получении прогресса!")

@router.message(lambda message: message.text == "Удалить тест")
async def handle_delete_test(message: types.Message, state: FSMContext):
    if message.from_user.id != int(ADMIN_ID):
        await message.answer("❌ У вас нет доступа к этой команде.")
        return
    try:
        async with SessionLocal() as session:
            result = await session.execute(select(Test).filter(Test.is_active == True))
            tests = result.scalars().all()
        if not tests:
            await message.answer("Нет активных тестов для удаления.")
            return
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=test.name, callback_data=f"delete_test_{test.id}")]
                for test in tests
            ]
        )
        await message.answer("Выберите тест для удаления (мягкое удаление):", reply_markup=keyboard)
    except SQLAlchemyError as e:
        logger.error("Ошибка при получении тестов для удаления: %s", e)
        await message.answer("❌ Ошибка при получении тестов!")

@router.callback_query(lambda c: c.data and c.data.startswith("delete_test_"))
async def handle_delete_test(callback: types.CallbackQuery, state: FSMContext):
    test_id = int(callback.data.split("_")[-1])
    try:
        async with SessionLocal() as session:
            result = await session.execute(select(Test).filter(Test.id == test_id))
            test = result.scalar_one_or_none()
            if not test:
                await callback.message.answer("Тест не найден.")
                return
            test.is_active = False  # Мягкое удаление
            await session.commit()
        await callback.message.edit_text(
            f"✅ Тест <b>{test.name}</b> успешно удален (отмечен как неактивный).",
            parse_mode="HTML"
        )
    except SQLAlchemyError as e:
        logger.error("Ошибка при удалении теста: %s", e)
        await callback.message.answer("❌ Ошибка при удалении теста!")

@router.message(lambda message: message.text == "Удалить вопрос")
async def handle_delete_question(message: types.Message, state: FSMContext):
    if message.from_user.id != int(ADMIN_ID):
        await message.answer("❌ У вас нет доступа к этой команде.")
        return

    await state.clear()
    
    # Получаем список тестов
    async with SessionLocal() as session:
        tests = await session.execute(select(Test).filter(Test.is_active == True))  # Фильтрация по is_active
        tests = tests.scalars().all()

    if not tests:
        await message.answer("Нет доступных тестов. Сначала создайте тест.")
        return

    # Предлагаем выбрать тест для удаления вопросов
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=test.name, callback_data=f"test_deleted_{test.id}")]
            for test in tests
        ]
    )
    await message.answer("Выберите тест для удаления вопросов:", reply_markup=keyboard)
    await state.set_state(DeleteQuestionForm.select_test_for_delete)


@router.callback_query(lambda c: c.data and c.data.startswith("test_deleted_"))
async def select_test_for_delete(callback: types.CallbackQuery, state: FSMContext):
    test_id = int(callback.data.split("_")[-1])
    await state.update_data(test_id=test_id)
    
    # Получаем только активные вопросы, связанные с выбранным тестом
    async with SessionLocal() as session:
        result = await session.execute(select(Question).filter(Question.test_id == test_id, Question.is_active == True))  # Фильтрация по is_active
        questions = result.scalars().all()

    if not questions:
        await callback.message.answer("В этом тесте нет вопросов.")
        await state.clear()
        return

    # Предлагаем выбрать вопрос для удаления
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"Вопрос {q.id}: {q.question_text[:30]}...", callback_data=f"question_deleted_{q.id}")]
            for q in questions
        ]
    )
    await callback.message.answer("Выберите вопрос для удаления:", reply_markup=keyboard)
    await state.set_state(DeleteQuestionForm.question_id)


@router.callback_query(lambda c: c.data and c.data.startswith("question_deleted_"))
async def select_question_for_delete(callback: types.CallbackQuery, state: FSMContext):
    question_id = int(callback.data.split("_")[-1])
    await state.update_data(question_id=question_id)

    # Получаем данные вопроса
    async with SessionLocal() as session:
        question = await session.get(Question, question_id)

    if not question:
        await callback.message.answer("Вопрос не найден!")
        await state.clear()
        return

    # Формируем клавиатуру с кнопками "Да" и "Нет"
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Да", callback_data="confirm_delete_yes"),
         InlineKeyboardButton(text="Нет", callback_data="confirm_delete_no")]
    ])

    # Отправляем данные вопроса и запрашиваем подтверждение удаления
    await callback.message.answer(
        f"<b>Текущий вопрос:</b>\n"
        f"{question.question_text}\n"
        f"<b>A:</b> {question.option_a}\n"
        f"<b>B:</b> {question.option_b}\n"
        f"<b>C:</b> {question.option_c}\n"
        f"<b>D:</b> {question.option_d}\n"
        f"<b>Правильный ответ:</b> {question.correct_answer}\n\n"
        "Точно хотите удалить вопрос?",
        reply_markup=keyboard,
        parse_mode="HTML"
    )
    # Можно оставить состояние, чтобы потом использовать question_id для подтверждения


@router.callback_query(lambda c: c.data in ["confirm_delete_yes", "confirm_delete_no"])
async def confirm_delete_question(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if "question_id" not in data:
        await callback.answer("❌ Ошибка: ID вопроса не найден.")
        await state.clear()
        return

    question_id = data["question_id"]

    if callback.data == "confirm_delete_yes":
        # Мягкое удаление: устанавливаем флаг is_active в False
        async with SessionLocal() as session:
            question = await session.get(Question, question_id)
            if question:
                question.is_active = False
                await session.commit()
                await callback.message.edit_text("✅ Вопрос успешно удален (мягкое удаление).")
            else:
                await callback.message.edit_text("Вопрос не найден.")
    else:  # callback.data == "confirm_delete_no"
        await callback.message.edit_text("Удаление отменено.")

    await state.clear()
@router.message(lambda message: message.text == "Отмена")
async def handle_admin_cancel(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Действие отменено.", reply_markup=get_admin_panel_keyboard())