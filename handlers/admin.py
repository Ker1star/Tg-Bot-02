from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from config import ADMIN_ID
from states.forms import AddQuestionForm, EditQuestionForm, TestCreationForm
from models.db_models import SessionLocal, Question, Test
from sqlalchemy.exc import SQLAlchemyError
import logging
logger = logging.getLogger(__name__)

router = Router()

def get_admin_panel_keyboard() -> ReplyKeyboardMarkup:
    """
    Формирует клавиатуру панели администратора.
    """
    keyboard = [
        [KeyboardButton(text="Создать тест"), KeyboardButton(text="Добавить вопрос")],
        [KeyboardButton(text="Редактировать вопрос")],
        [KeyboardButton(text="Отмена")]
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
    from handlers.admin import create_test_start  # импорт функции создания теста
    await create_test_start(message, state)

# Обработчик для кнопки "Добавить вопрос"
@router.message(lambda message: message.text == "Добавить вопрос")
async def handle_add_question_admin(message: types.Message, state: FSMContext):
    from handlers.admin import add_question_start  # импорт функции добавления вопроса
    await add_question_start(message, state)

# Обработчик для кнопки "Редактировать вопрос"
@router.message(lambda message: message.text == "Редактировать вопрос")
async def handle_edit_question_admin(message: types.Message, state: FSMContext):
    from handlers.admin import edit_question_start  # импорт функции редактирования вопроса
    await edit_question_start(message, state)

# Обработчик для кнопки "Отмена" в админке
@router.message(lambda message: message.text == "Отмена")
async def handle_admin_cancel(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Действие отменено.", reply_markup=get_admin_panel_keyboard())

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
        with SessionLocal() as session:
            new_test = Test(name=test_name, description=test_description)
            session.add(new_test)
            session.commit()
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
        with SessionLocal() as session:
            tests = session.query(Test).all()
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
        with SessionLocal() as session:
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
            session.commit()
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

# Редактирование вопроса
@router.message(Command("edit_question"))
async def edit_question_start(message: types.Message, state: FSMContext):
    if message.from_user.id != int(ADMIN_ID):
        await message.answer("❌ У вас нет доступа к этой команде.")
        return
    await state.clear()
    await message.answer("Введите ID вопроса для редактирования:")
    await state.set_state(EditQuestionForm.question_id)

@router.message(EditQuestionForm.question_id)
async def process_edit_question_id(message: types.Message, state: FSMContext):
    try:
        q_id = int(message.text)
    except ValueError:
        await message.answer("ID должен быть числом. Попробуйте еще раз:")
        return
    session = SessionLocal()
    question = session.query(Question).filter(Question.id == q_id).first()
    session.close()
    if not question:
        await message.answer("Вопрос с таким ID не найден. Введите корректный ID:")
        return
    await state.update_data(
        question_id=q_id,
        old_question_text=question.question_text,
        old_option_a=question.option_a,
        old_option_b=question.option_b,
        old_option_c=question.option_c,
        old_option_d=question.option_d,
        old_correct_answer=question.correct_answer
    )
    await message.answer(
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
    new_text = data.get("old_question_text") if message.text.lower() == "/skip" else message.text
    await state.update_data(new_question_text=new_text)
    await message.answer(f"Введите новый вариант ответа A или /skip чтобы оставить \"{data.get('old_option_a')}\":")
    await state.set_state(EditQuestionForm.option_a)

@router.message(EditQuestionForm.option_a)
async def process_edit_option_a(message: types.Message, state: FSMContext):
    data = await state.get_data()
    new_option_a = data.get("old_option_a") if message.text.lower() == "/skip" else message.text
    await state.update_data(new_option_a=new_option_a)
    await message.answer(f"Введите новый вариант ответа B или /skip чтобы оставить \"{data.get('old_option_b')}\":")
    await state.set_state(EditQuestionForm.option_b)

@router.message(EditQuestionForm.option_b)
async def process_edit_option_b(message: types.Message, state: FSMContext):
    data = await state.get_data()
    new_option_b = data.get("old_option_b") if message.text.lower() == "/skip" else message.text
    await state.update_data(new_option_b=new_option_b)
    await message.answer(f"Введите новый вариант ответа C или /skip чтобы оставить \"{data.get('old_option_c')}\":")
    await state.set_state(EditQuestionForm.option_c)

@router.message(EditQuestionForm.option_c)
async def process_edit_option_c(message: types.Message, state: FSMContext):
    data = await state.get_data()
    new_option_c = data.get("old_option_c") if message.text.lower() == "/skip" else message.text
    await state.update_data(new_option_c=new_option_c)
    await message.answer(f"Введите новый вариант ответа D или /skip чтобы оставить \"{data.get('old_option_d')}\":")
    await state.set_state(EditQuestionForm.option_d)

@router.message(EditQuestionForm.option_d)
async def process_edit_option_d(message: types.Message, state: FSMContext):
    data = await state.get_data()
    new_option_d = data.get("old_option_d") if message.text.lower() == "/skip" else message.text
    await state.update_data(new_option_d=new_option_d)
    await message.answer(
        f"Введите новый правильный ответ (A, B, C или D) или /skip чтобы оставить \"{data.get('old_correct_answer')}\":"
    )
    await state.set_state(EditQuestionForm.correct_answer)

@router.message(EditQuestionForm.correct_answer)
async def process_edit_correct_answer(message: types.Message, state: FSMContext):
    data = await state.get_data()
    if message.text.lower() == "/skip":
        new_correct = data.get("old_correct_answer")
    else:
        if message.text.upper() not in ["A", "B", "C", "D"]:
            await message.answer("Некорректный вариант. Введите A, B, C или D, или /skip для пропуска:")
            return
        new_correct = message.text.upper()
    await state.update_data(new_correct_answer=new_correct)
    session = SessionLocal()
    q_id = data.get("question_id")
    question = session.query(Question).filter(Question.id == q_id).first()
    if question:
        question.question_text = data.get("new_question_text")
        question.option_a = data.get("new_option_a")
        question.option_b = data.get("new_option_b")
        question.option_c = data.get("new_option_c")
        question.option_d = data.get("new_option_d")
        question.correct_answer = data.get("new_correct_answer")
        session.commit()
        await message.answer("✅ Вопрос успешно обновлен!", parse_mode="HTML")
    else:
        await message.answer("❌ Ошибка: вопрос не найден.")
    session.close()
    await state.clear()
