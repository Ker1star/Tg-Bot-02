from aiogram import Router, types, Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton, File
from config import ADMIN_ID, API_TOKEN, STATIC_ROOT, STATIC_URL
from states.forms import AddQuestionForm, EditQuestionForm, TestCreationForm, DeleteQuestionForm, AddMaterialsForm, AddExamForm, QuestionStreamForm, BulkAddQuestionsForm
from models.db_models import SessionLocal, Question, Test, UserProgress, Materials, Exam, QuestionImage, Category, Transaction
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.future import select
from sqlalchemy.orm import joinedload
from collections import defaultdict
from handlers.notif import send_notifications_to_all_users
import logging, os, datetime, uuid
from zoneinfo import ZoneInfo
from sqlalchemy import delete
from handlers.utils import admin_only
from states.forms import AddProductForm, AddBalanceForm
from models.db_models import Product, Wallet, User

admin_ids = os.getenv('ADMIN_ID')

admin_ids_list = [int(admin_id.strip()) for admin_id in admin_ids.split(',')]

logger = logging.getLogger(__name__)

router = Router()

def get_admin_panel_keyboard() -> ReplyKeyboardMarkup:
    """
    Формирует клавиатуру панели администратора.
    """
    keyboard = [
        [KeyboardButton(text="Добавить материалы"), KeyboardButton(text="Удалить материалы")],
        [KeyboardButton(text="Создать тест"), KeyboardButton(text="Добавить вопрос")],
        [KeyboardButton(text="Редактировать вопрос"), KeyboardButton(text="Отслеживание прогресса")],
        [KeyboardButton(text="Удалить тест"), KeyboardButton(text="Удалить вопрос"), KeyboardButton(text="Сброс прогресса")],
        [KeyboardButton(text="Добавить товар"), KeyboardButton(text="Начислить баллы")],
        [KeyboardButton(text="Назад"), KeyboardButton(text="Отмена")]
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

# — — Добавить товар — —
@router.message(lambda msg: msg.text == "Добавить товар")
@admin_only
async def cmd_add_product(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("🛒 Введите название товара:")
    await state.set_state(AddProductForm.name)

@router.message(AddProductForm.name)
async def product_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text)
    await message.answer("Введите описание товара:")
    await state.set_state(AddProductForm.desc)

@router.message(AddProductForm.desc)
async def product_desc(message: types.Message, state: FSMContext):
    await state.update_data(desc=message.text)
    await message.answer("Введите цену товара (целое число в баллах):")
    await state.set_state(AddProductForm.price)

@router.message(AddProductForm.price)
async def product_price(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        return await message.answer("Нужно число. Пожалуйста, введите цену цифрами:")
    await state.update_data(price=int(message.text))

    # Загружаем все активные категории из БД
    async with SessionLocal() as session:
        result = await session.execute(select(Category))
        categories = result.scalars().all()

    if not categories:
        return await message.answer("❌ Нет ни одной категории. Сначала создайте категории в БД.")

    # Формируем inline-клавиатуру с кнопками категорий
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=cat.name, callback_data=f"choose_cat_{cat.id}")]
            for cat in categories
        ]
    )
    await message.answer("🗂 Выберите категорию:", reply_markup=keyboard)
    await state.set_state(AddProductForm.category)


@router.callback_query(lambda c: c.data and c.data.startswith("choose_cat_"))
async def choose_category(callback: types.CallbackQuery, state: FSMContext):
    # Получаем ID категории из callback_data
    cat_id = int(callback.data.split("_")[-1])
    # Опционально: достаем название, чтобы подтвердить выбор
    async with SessionLocal() as session:
        category = await session.get(Category, cat_id)

    if not category:
        await callback.answer("❌ Категория не найдена.", show_alert=True)
        return

    # Сохраняем выбор в state
    await state.update_data(category_id=cat_id)
    # Подтверждаем выбор и запрашиваем следующий шаг
    await callback.message.edit_text(f"✅ Категория выбрана: «{category.name}»")
    await callback.message.answer("📸 Прикрепите фотографию товара:")
    await state.set_state(AddProductForm.image_url)
    await callback.answer()

@router.message(AddProductForm.image_url)
async def product_image(message: types.Message, state: FSMContext):
    if not message.photo:
        return await message.answer("❗ Пожалуйста, отправьте фотографию товара.")
    photo = message.photo[-1]
    ext = ".jpg"
    filename = f"{uuid.uuid4().hex}{ext}"
    upload_dir = os.path.join(STATIC_ROOT, "uploads", "products")
    os.makedirs(upload_dir, exist_ok=True)
    file_path = os.path.join(upload_dir, filename)
    tg_file = await message.bot.get_file(photo.file_id)

    await message.bot.download_file(tg_file.file_path, destination=file_path)

    public_url = f"{STATIC_URL}/uploads/products/{filename}"

    # 5. Сохранить товар в БД
    data = await state.get_data()
    try:
        async with SessionLocal() as session:
            async with session.begin():
                new = Product(
                    name=data["name"],
                    description=data["desc"],
                    price=data["price"],
                    image_url=public_url,
                    category_id=data["category_id"]
                )
                session.add(new)

        await message.answer(f"✅ Товар «{data['name']}» добавлен в магазин.")
    except Exception as e:
        logger.error(f"Ошибка при добавлении товара: {e}", exc_info=True)
        await message.answer("❌ Ошибка при сохранении товара!")
    finally:
        await state.clear()

from models.db_models import Wallet, Transaction, User
from sqlalchemy.future import select

# — — Начислить баллы — —
@router.message(lambda msg: msg.text == "Начислить баллы")
@admin_only
async def cmd_add_balance(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("💰 Введите Telegram ID пользователя:")
    await state.set_state(AddBalanceForm.telegram_id)

@router.message(AddBalanceForm.telegram_id)
async def bal_user_id(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        return await message.answer("ID — число. Повторите ввод:")
    await state.update_data(telegram_id=int(message.text))
    await message.answer("Введите количество баллов для зачисления/списания (целое число, можно отрицательное):")
    await state.set_state(AddBalanceForm.amount)

@router.message(AddBalanceForm.amount)
async def bal_amount(message: types.Message, state: FSMContext):
    text = message.text.strip()
    if not (text.lstrip('-').isdigit()):
        return await message.answer("Нужно целое число (можно с минусом). Повторите ввод:")
    amount = int(text)
    await state.update_data(amount=amount)
    await message.answer("Введите причину начисления/списания:")
    await state.set_state(AddBalanceForm.reason)

@router.message(AddBalanceForm.reason)
async def bal_reason(message: types.Message, state: FSMContext):
    data = await state.get_data()
    reason = message.text.strip()
    if not reason:
        return await message.answer("Причина не может быть пустой. Повторите ввод:")
    telegram_id = data['telegram_id']
    amount = data['amount']

    async with SessionLocal() as session:
        # Находим или создаём пользователя
        result = await session.execute(select(User).filter(User.telegram_id == telegram_id))
        user = result.scalar_one_or_none()
        if not user:
            return await message.answer(f"❌ Пользователь с ID {telegram_id} не найден.")
        # Находим или создаём кошелёк
        wallet_res = await session.execute(select(Wallet).filter(Wallet.user_id == user.id))
        wallet = wallet_res.scalar_one_or_none()
        if not wallet:
            wallet = Wallet(user_id=user.id, balance=0)
            session.add(wallet)
        # Изменяем баланс
        wallet.balance += amount
        # Сохраняем транзакцию
        tx = Transaction(
            user_id=user.id,
            amount=amount,
            type="credit" if amount > 0 else "debit",
            reason=reason
        )
        session.add(tx)
        await session.commit()

    await message.answer(
        f"✅ Пользователю {telegram_id} {'зачислено' if amount>0 else 'списано'} {abs(amount)} баллов.\n"
        f"Причина: «{reason}».\n"
        f"Новый баланс: {wallet.balance}"
    )
    await state.clear()


# Команда для вывода панели администратора
@router.message(Command("admin_panel"))
@admin_only
async def admin_panel_handler(message: types.Message, state: FSMContext):
    await message.answer("Панель администратора:", reply_markup=get_admin_panel_keyboard())

# Обработчик для кнопки "Создать тест"
@router.message(lambda message: message.text == "Создать тест")
@admin_only
async def handle_create_test_admin(message: types.Message, state: FSMContext):
    await create_test_start(message, state)

# Обработчик для кнопки "Редактировать вопрос"
@router.message(lambda message: message.text == "Редактировать вопрос")
@admin_only
async def handle_edit_question_admin(message: types.Message, state: FSMContext):
    await start_edit_question_process(message, state)

# Обработчик для кнопки "Отмена" в админке
@router.message(lambda message: message.text == "Отмена")
@admin_only
async def handle_admin_cancel(message: types.Message, state: FSMContext):
    await state.clear()
    await message.answer("Действие отменено.", reply_markup=get_admin_panel_keyboard())

# Обработчик для кнопки "Назад" в админке
@router.message(lambda message: message.text == "Назад")
@admin_only
async def handle_admin_back(message: types.Message, state: FSMContext):
    from handlers.client import start_handler
    await start_handler(message, state)

@router.message(lambda message: message.text == "Добавить материалы")
@admin_only
async def handle_add_materials_admin(message: types.Message, state: FSMContext):
    await message.answer("Введите название темы для материалов")
    await state.set_state(AddMaterialsForm.name)

@router.message(lambda message: message.text == "Сброс прогресса")
@admin_only
async def reset_progress_all_handler(message: types.Message, state: FSMContext):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Да, сбросить", callback_data="reset_all_yes")],
        [InlineKeyboardButton(text="Нет, отменить", callback_data="reset_all_no")]
    ])
    await message.answer("Вы уверены, что хотите сбросить прогресс для всех пользователей?", reply_markup=keyboard)

@router.callback_query(lambda c: c.data == "reset_all_yes")
async def confirm_reset_all(callback: types.CallbackQuery, state: FSMContext):
    try:
        async with SessionLocal() as session:
            # Удаляем все записи прогресса
            await session.execute(delete(UserProgress))
            await session.commit()
        await callback.message.edit_text("Прогресс для всех пользователей успешно сброшен.")
    except SQLAlchemyError as e:
        logger.error(f"Ошибка при сбросе прогресса для всех: {e}")
        await callback.message.answer("❌ Ошибка при сбросе прогресса.")
    await callback.answer()

@router.callback_query(lambda c: c.data == "reset_all_no")
async def cancel_reset_all(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Сброс прогресса отменён.")
    await callback.answer()


#добавление материалов
@router.message (Command("add_materials"))
@admin_only
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
        #await send_notifications_to_all_users(f"📚 Новый материал: {new_materials.name} добавлен! Подробнее в разделе материалов.")
    except SQLAlchemyError as e:
        logger.error("Ошибка при добавлении материалов: %s", e)
        await message.answer("❌ Ошибка при добавлении материалов!")
    
    await state.clear()

# Добавляем экзамен
@router.message(lambda message: message.text == "Добавить экзамен")
@admin_only
async def handle_add_exam(message: types.Message, state: FSMContext):
    await message.answer("Введите название экзамена:")
    await state.set_state(AddExamForm.name)

@router.message(AddExamForm.name)
async def process_exam_name(message: types.Message, state: FSMContext):
    await state.update_data(name=message.text)
    await message.answer("Прикрепите ссылку на экзамен")
    await state.set_state(AddExamForm.file)

@router.message(AddExamForm.file)
async def process_exam_file(message: types.Message, state: FSMContext):
    data = await state.get_data()
    exam_name = data.get("name")
    exam_file = message.text
    try:
        async with SessionLocal() as session:
            new_exam = Exam(name=exam_name, file=exam_file)
            session.add(new_exam)
            await session.commit()
            logger.info(f"Добавлен экзамен '{new_exam.name}' с ID {new_exam.id}")
        await message.answer(f"✅ Экзамен <b>{exam_name}</b> успешно добавлен!")
    except SQLAlchemyError as e:
        logger.error("Ошибка при добавлении экзамена: %s", e)
        await message.answer("❌ Ошибка при добавлении экзамена!")
    await state.clear()

# Создание нового теста
@router.message(Command("create_test"))
@admin_only
async def create_test_start(message: types.Message, state: FSMContext):
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
        # Предлагаем сразу добавить вопросы или оставить тест пустым
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Добавить вопросы поочередно", callback_data=f"add_questions_now_{new_test.id}")],
            [InlineKeyboardButton(text="Оставить тест пустым", callback_data=f"skip_questions_{new_test.id}")],
            [InlineKeyboardButton(text="Добавить сразу сплошным текстом", callback_data=f"bulk_add_{new_test.id}")],
        ])
        await message.answer(f"✅ Тест <b>{test_name}</b> успешно создан!\nХотите добавить вопросы?", parse_mode="HTML", reply_markup=keyboard)
    except SQLAlchemyError as e:
        logger.error("Ошибка при создании теста: %s", e)
        await message.answer("❌ Ошибка при создании теста!")
    await state.clear()

@router.callback_query(lambda c: c.data and c.data.startswith("bulk_add_"))
async def bulk_add_start(callback: types.CallbackQuery, state: FSMContext):
    test_id = int(callback.data.split("_")[-1])
    await state.update_data(test_id=test_id)
    await callback.message.answer(
        "Пришлите список вопросов одним блоком текста. Формат:\n\n"
        "1) Текст вопроса\n"
        "A) Вариант A\n"
        "B) Вариант B\n"
        "C) Вариант C\n"
        "D) Вариант D\n"
        "Правильный: B\n\n"
        "Используйте пустую строку между вопросами."
    )
    await state.set_state(BulkAddQuestionsForm.text)
    await callback.answer()
@router.message(BulkAddQuestionsForm.text)
async def process_bulk_text(message: types.Message, state: FSMContext):
    data = await state.get_data()
    test_id = data["test_id"]
    text = message.text.strip()

    import re
    # Регекс, который находит блоки вопросов, разделённые двумя переводами строки
    blocks = re.split(r'\n{2,}', text)
    questions = []
    for blk in blocks:
        m = re.search(
            r'^\s*\d+\)\s*(?P<q>.+?)\s*^A\)\s*(?P<a>.+?)\s*^B\)\s*(?P<b>.+?)'
            r'\s*^C\)\s*(?P<c>.+?)\s*^D\)\s*(?P<d>.+?)\s*^Правильный:\s*(?P<correct>[ABCD])',
            blk, flags=re.MULTILINE | re.DOTALL
        )
        if not m:
            await message.answer(f"Не удалось распознать блок:\n\n{blk}\n\n— проверьте формат.")
            return
        questions.append(m.groupdict())

    # Сохраняем все в БД
    try:
        async with SessionLocal() as session:
            for q in questions:
                new_q = Question(
                    test_id=test_id,
                    question_text=q['q'].strip(),
                    option_a=q['a'].strip(),
                    option_b=q['b'].strip(),
                    option_c=q['c'].strip(),
                    option_d=q['d'].strip(),
                    correct_answer=q['correct']
                )
                session.add(new_q)
            await session.commit()
        await message.answer(f"✅ Загружено {len(questions)} вопросов.")
    except Exception as e:
        logger.error(f"Ошибка bulk add: {e}")
        await message.answer("❌ Ошибка при сохранении вопросов.")
    finally:
        await state.clear()

@router.callback_query(lambda c: c.data and c.data.startswith("add_questions_now_"))
async def add_questions_now(callback: types.CallbackQuery, state: FSMContext):
    test_id = int(callback.data.split("_")[-1])
    # Сохраняем test_id в состоянии для дальнейшего добавления вопросов
    await state.update_data(test_id=test_id)
    await callback.message.answer("Введите текст вопроса:")
    # Переходим к новому состоянию для добавления вопросов (поток ввода)
    await state.set_state(QuestionStreamForm.question_text)
    await callback.answer()

@router.message(QuestionStreamForm.question_text)
async def process_stream_question_text(message: types.Message, state: FSMContext):
    await state.update_data(question_text=message.text)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Да", callback_data="upload_images_yes"),
         InlineKeyboardButton(text="Нет", callback_data="upload_images_no")]
    ])
    await message.answer("Хотите загрузить изображения для вопроса?", reply_markup=keyboard)
    # Состояние остается тем же – ждем callback

# Обработчик решения о загрузке изображений
@router.callback_query(lambda c: c.data in ["upload_images_yes", "upload_images_no"])
async def process_upload_images_decision(callback: types.CallbackQuery, state: FSMContext):
    decision = callback.data
    if decision == "upload_images_yes":
        # Инициализируем список изображений
        await state.update_data(images=[])
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Готово", callback_data="images_upload_done")]
        ])
        await callback.message.answer("Прикрепите одно или несколько изображений для вопроса.\nПосле завершения нажмите кнопку 'Готово'.", reply_markup=keyboard)
        await state.set_state(QuestionStreamForm.images)
    else:
        await callback.message.answer("Изображения не будут загружаться. Введите вариант ответа A:")
        await state.set_state(QuestionStreamForm.option_a)
    await callback.answer()

# Обработчик загрузки изображений
@router.message(QuestionStreamForm.images)
async def process_stream_question_images(message: types.Message, state: FSMContext):
    data = await state.get_data()
    images = data.get("images", [])
    if message.photo:
        # Берем последний (самый большой) вариант изображения
        file_id = message.photo[-1].file_id
        images.append(file_id)
        await state.update_data(images=images)
        await message.answer("Изображение добавлено. Можно добавить ещё, либо нажмите кнопку 'Готово'.")
    else:
        await message.answer("Пожалуйста, прикрепите изображение или нажмите 'Готово'.")

# Обработчик завершения загрузки изображений через клавиатуру
@router.callback_query(lambda c: c.data == "images_upload_done")
async def images_upload_done(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Загрузка изображений завершена. Введите вариант ответа A:")
    await state.set_state(QuestionStreamForm.option_a)
    await callback.answer()

@router.message(QuestionStreamForm.option_a)
async def process_stream_option_a(message: types.Message, state: FSMContext):
    await state.update_data(option_a=message.text)
    await message.answer("Введите вариант ответа B:")
    await state.set_state(QuestionStreamForm.option_b)

@router.message(QuestionStreamForm.option_b)
async def process_stream_option_b(message: types.Message, state: FSMContext):
    await state.update_data(option_b=message.text)
    await message.answer("Введите вариант ответа C:")
    await state.set_state(QuestionStreamForm.option_c)

@router.message(QuestionStreamForm.option_c)
async def process_stream_option_c(message: types.Message, state: FSMContext):
    await state.update_data(option_c=message.text)
    await message.answer("Введите вариант ответа D:")
    await state.set_state(QuestionStreamForm.option_d)

@router.message(QuestionStreamForm.option_d)
async def process_stream_option_d(message: types.Message, state: FSMContext):
    await state.update_data(option_d=message.text)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="A", callback_data="stream_correct_A"),
         InlineKeyboardButton(text="B", callback_data="stream_correct_B")],
        [InlineKeyboardButton(text="C", callback_data="stream_correct_C"),
         InlineKeyboardButton(text="D", callback_data="stream_correct_D")]
    ])
    await message.answer("Выберите правильный ответ:", reply_markup=keyboard)
    await state.set_state(QuestionStreamForm.correct_answer)

@router.callback_query(lambda c: c.data and c.data.startswith("stream_correct_"))
async def process_stream_correct_answer(callback: types.CallbackQuery, state: FSMContext):
    correct = callback.data.split("_")[-1]
    await state.update_data(correct_answer=correct)
    data = await state.get_data()
    test_id = data.get("test_id")
    try:
        async with SessionLocal() as session:
            new_question = Question(
                test_id=test_id,
                question_text=data['question_text'],
                option_a=data['option_a'],
                option_b=data['option_b'],
                option_c=data['option_c'],
                option_d=data['option_d'],
                correct_answer=correct
            )
            session.add(new_question)
            await session.flush()  # Получаем new_question.id

            for img in data.get("images", []):
                new_image = QuestionImage(question_id=new_question.id, image=img)
                session.add(new_image)
            await session.commit()
            logger.info(f"Добавлен вопрос {new_question.id} в тест {test_id} (поток вопросов)")
        response = (
            f"<b>Вопрос:</b> {data['question_text']}\n"
            f"<b>A:</b> {data['option_a']}\n"
            f"<b>B:</b> {data['option_b']}\n"
            f"<b>C:</b> {data['option_c']}\n"
            f"<b>D:</b> {data['option_d']}\n"
            f"<b>Правильный ответ:</b> {correct}"
        )
        await callback.message.edit_text("Новый вопрос добавлен:\n\n" + response, parse_mode="HTML")
    except SQLAlchemyError as e:
        logger.error("Ошибка при добавлении вопроса: %s", e)
        await callback.message.answer("❌ Ошибка при сохранении вопроса!")
        await state.clear()
        return

    # После добавления вопроса предлагаем добавить еще или закончить процесс
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Добавить ещё", callback_data="stream_add_another")],
        [InlineKeyboardButton(text="Завершить", callback_data="stream_finish")]
    ])
    await callback.message.answer("Вопрос добавлен. Хотите добавить ещё один?", reply_markup=keyboard)
    # Сохраняем test_id перед очисткой остальных данных
    current_data = await state.get_data()
    test_id = current_data.get("test_id")
    await state.set_data({"test_id": test_id})

@router.callback_query(lambda c: c.data == "stream_add_another")
async def stream_add_another(callback: types.CallbackQuery, state: FSMContext):
    # Переходим к вводу нового вопроса, оставляя test_id в состоянии
    data = await state.get_data()
    if "test_id" not in data:
        await callback.message.answer("Ошибка: тест не найден в состоянии.")
        await state.clear()
        return
    await callback.message.answer("Введите текст нового вопроса:")
    await state.set_state(QuestionStreamForm.question_text)
    await callback.answer()

@router.callback_query(lambda c: c.data == "stream_finish")
async def stream_finish(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Добавление вопросов завершено. Возвращаемся в админ-панель.")
    await state.clear()
    await callback.answer()

@router.callback_query(lambda c: c.data and c.data.startswith("skip_questions_"))
async def skip_questions(callback: types.CallbackQuery, state: FSMContext):
    await callback.message.answer("Тест оставлен пустым. Вы можете добавить вопросы позже через соответствующую команду.")
    await state.clear()
    await callback.answer()

# Добавление нового вопроса
@router.message(lambda msg: msg.text == "Добавить вопрос")
@admin_only
async def handle_add_question_admin(message: types.Message, state: FSMContext):
    await state.clear()
    async with SessionLocal() as session:
        result = await session.execute(select(Test).filter(Test.is_active == True))
        tests = result.scalars().all()
    if not tests:
        await message.answer("❌ Нет ни одного теста. Сначала создайте тест.")
        return
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=test.name, callback_data=f"select_add_method_{test.id}")]
            for test in tests
        ]
    )
    await message.answer("Выберите тест для добавления вопросов:", reply_markup=keyboard)

@router.callback_query(lambda c: c.data and c.data.startswith("select_add_method_"))
async def select_add_method(callback: types.CallbackQuery, state: FSMContext):
    test_id = int(callback.data.split("_")[-1])
    await state.update_data(test_id=test_id)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Добавить вопросы поочередно", callback_data=f"add_questions_now_{test_id}")],
        [InlineKeyboardButton(text="Добавить вопросы сплошным текстом", callback_data=f"bulk_add_{test_id}")]
    ])
    await callback.message.answer("Выберите способ добавления вопросов:", reply_markup=keyboard)
    await callback.answer()
@router.message(Command("edit_question"))
@admin_only
async def start_edit_question_process(message: types.Message, state: FSMContext):
    await state.clear()
    
    # Получаем список тестов
    async with SessionLocal() as session:
        tests = await session.execute(select(Test).filter(Test.is_active == True))
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
        result = await session.execute(select(Question).filter(Question.test_id == test_id, Question.is_active == True))
        questions = result.scalars().all()

    if not questions:
        await callback.message.answer("В этом тесте нет вопросов.")
        await state.clear()
        return

    # Формируем сообщение со списком вопросов (с полным текстом)
    message_text = "Выберите вопрос для редактирования:\n\n"
    for idx, q in enumerate(questions, start=1):
        message_text += f"{idx}. {q.question_text}\n\n"

    # Формируем список кнопок с номерами вопросов
    buttons = [InlineKeyboardButton(text=str(idx), callback_data=f"edit_question_{q.id}")
            for idx, q in enumerate(questions, start=1)]

    # Группируем кнопки по 4 штуки в строке (можно изменить число для нужной компактности)
    rows = [buttons[i:i+4] for i in range(0, len(buttons), 4)]
    keyboard = InlineKeyboardMarkup(inline_keyboard=rows)

    # Отправляем сообщение со списком вопросов
    await callback.message.answer(message_text, parse_mode="HTML")
    # Отправляем компактную клавиатуру для выбора
    await callback.message.answer("Нажмите на номер вопроса для редактирования:", reply_markup=keyboard)
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
@admin_only
async def handle_view_progress(message: types.Message, state: FSMContext):
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
                finished_date = progress.finished_at.strftime("%Y-%m-%d %H:%M")
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
                text += (f"  - Тест: {test_info} | Результат: {progress.score}/{progress.current_question} ({percent:.2f}%)\n Завершен: {finished_date}\n")

        await message.answer(text, parse_mode="HTML")

    except SQLAlchemyError as e:
        logger.error("Ошибка при получении прогресса: %s", e)
        await message.answer("❌ Ошибка при получении прогресса!")

@router.message(lambda message: message.text == "Удалить тест")
@admin_only
async def handle_delete_test(message: types.Message, state: FSMContext):
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

@router.message(lambda message: message.text == "Удалить материалы")
@admin_only
async def handle_delete_materials(message: types.Message, state: FSMContext):
    try:
        async with SessionLocal() as session:
            result = await session.execute(select(Materials).filter(Materials.is_active == True))
            materials = result.scalars().all()
        if not materials:
            await message.answer("Нет материалов для удаления.")
            return
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=material.name, callback_data=f"delete_materials_{material.id}")]
                for material in materials
            ]
        )
        await message.answer("Выберите материал для удаления:", reply_markup=keyboard)
    except SQLAlchemyError as e:
        logger.error("Ошибка при получении материалов для удаления: %s", e)
        await message.answer("❌ Ошибка при получении материалов!")

@router.callback_query(lambda c: c.data and c.data.startswith("delete_materials_"))
async def handle_delete_materials(callback: types.CallbackQuery, state: FSMContext):
    materials_id = int(callback.data.split("_")[-1])
    try:
        async with SessionLocal() as session:
            result = await session.execute(select(Materials).filter(Materials.id == materials_id))
            materials = result.scalar_one_or_none()
            if not materials:
                await callback.message.answer("Материал не найден.")
                return
            materials.is_active = False
            await session.commit()
        await callback.message.edit_text(
            f"✅ Материал <b>{materials.name}</b> успешно удален.",
            parse_mode="HTML"
        )
    except SQLAlchemyError as e:
        logger.error("Ошибка при удалении материалов: %s", e)
        await callback.message.answer("❌ Ошибка при удалении материалов!")

@router.message(lambda message: message.text == "Удалить вопрос")
@admin_only
async def handle_delete_question(message: types.Message, state: FSMContext):
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

    # Формируем сообщение со списком вопросов (с полным текстом)
    message_text = "Выберите вопрос для удаления:\n\n"
    for idx, q in enumerate(questions, start=1):
        message_text += f"{idx}. {q.question_text}\n\n"

    # Формируем список кнопок с номерами вопросов
    buttons = [InlineKeyboardButton(text=str(idx), callback_data=f"question_deleted_{q.id}")
            for idx, q in enumerate(questions, start=1)]

    # Группируем кнопки по 4 штуки в строке (можно изменить число для нужной компактности)
    rows = [buttons[i:i+4] for i in range(0, len(buttons), 4)]
    keyboard = InlineKeyboardMarkup(inline_keyboard=rows)

    # Отправляем сообщение со списком вопросов
    await callback.message.answer(message_text, parse_mode="HTML")
    await callback.message.answer("Нажмите на номер вопроса для удаления:", reply_markup=keyboard)
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

