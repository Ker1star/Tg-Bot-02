"""
Открытие/закрытие точки: чек-лист с фото-эталонами.

Пока только одна точка (El Gusto) — структура готова под несколько
(поле location у каждой модели), вторую добавим отдельным сидом, когда
будет своя майндмэпа.

Ход для сотрудника: кнопка в меню -> выбор "Открытие"/"Закрытие" -> бот
идёт по пунктам подряд. Для фото-пунктов с эталоном сначала показывает
образец, потом ждёт фото от сотрудника с тем же ракурсом. Пункты с
переменным числом ответов (чеки, часы сотрудников) собираются по одному
до нажатия "Готово". По завершении — весь отчёт (текст + фото) уходит
админам на проверку.

Эталонные фото никто, кроме админа, не задаёт — команда ниже.
"""

import logging

from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest
from sqlalchemy.future import select

from config import ADMIN_ID
from handlers.utils import admin_only
from models.db_models import (
    SessionLocal,
    User,
    ChecklistItemTemplate,
    ChecklistSubmission,
    ChecklistAnswer,
)

logger = logging.getLogger(__name__)
router = Router()

DEFAULT_LOCATION = 'el_gusto'
LOCATION_LABELS = {'el_gusto': 'El Gusto'}
SHIFT_LABELS = {'open': 'Открытие', 'close': 'Закрытие'}

MULTI_TYPES = {'multi_photo', 'multi_text'}
PHOTO_TYPES = {'photo', 'multi_photo'}


class ChecklistFlow(StatesGroup):
    running = State()


class ReferenceSetup(StatesGroup):
    waiting_photo = State()


# --- Сид фиксированной структуры чек-листа -----------------------------------
# Состав и порядок пунктов — часть кода, не БД: так его видно в диффах и
# нельзя случайно сломать через бота. Меняется reference_file_id — он и
# правда живёт в базе, задаётся админской командой ниже.

_OPEN_ITEMS = [
    ('brakerazh_pivo', 'Бракераж: пиво', 'photo', True, None),
    ('brakerazh_vino', 'Бракераж: вино', 'photo', True, None),
    ('brakerazh_frukty', 'Бракераж: фрукты', 'photo', True, None),
    ('brakerazh_drugoe', 'Бракераж: другое', 'photo', True, None),
    ('markirovki', 'Маркировки', 'photo', True, None),
    ('staff_mirror', 'Сотрудники', 'photo', False,
     'Сфотографируйтесь в зеркало, руки вперёд — должно быть видно, что украшений нет.'),
    ('bar_outside', 'Бар снаружи', 'photo', True, None),
    ('bar_inside', 'Бар изнутри', 'photo', True, None),
    ('coffee_machine', 'Кофемашина заряжена', 'photo', True, None),
    ('ac_remotes', 'Пульты от кондиционеров', 'photo', True, None),
    ('visual_pizzeria', 'Визуал: пиццерия', 'photo', True, None),
    ('visual_hall', 'Визуал: зал', 'photo', True, None),
    ('visual_table17', 'Визуал: стол №17', 'photo', True, None),
    ('visual_tables_wardrobe', 'Визуал: столы 1-2 + гардероб', 'photo', True, None),
    ('visual_guest_toilet', 'Визуал: гостевой туалет', 'photo', True, None),
    ('visual_dessert_case', 'Визуал: десертная витрина', 'photo', True, None),
]

_CLOSE_ITEMS = [
    ('zamyvka', 'Замывка', 'photo', True,
     'Пришлите фото с тем же ракурсом, что и эталон — должно быть чисто.'),
    ('kassa_checks', 'Касса: чеки', 'multi_photo', False,
     'Пришлите фото всех нужных чеков по одному. Когда закончите — «Готово».'),
    ('tech_issues', 'Технические неисправности на точке', 'text', False,
     'Есть ли технические неисправности? Опишите, либо нажмите «Нет».'),
    ('writeoffs', 'Списанные сегодня товары', 'text', False,
     'Перечислите списанные сегодня товары, либо нажмите «Нет».'),
    ('revenue_today', 'Выручка за сегодня', 'text', False, 'Укажите выручку за сегодня, ₽.'),
    ('cash_in_register', 'Наличные в кассе', 'text', False, 'Укажите сумму наличных в кассе, ₽.'),
    ('checks_count', 'Количество чеков', 'text', False, 'Укажите количество чеков за смену.'),
    ('staff_hours', 'Часы каждого сотрудника', 'multi_text', False,
     'Пришлите по одному сообщению на каждого сотрудника в формате «Имя Число часов». '
     'Когда закончите — «Готово».'),
]


async def ensure_checklist_seeded():
    """Идемпотентно создаёт недостающие пункты чек-листа. Ничего не удаляет
    и не переупорядочивает существующие — только добавляет новые step_key."""
    async with SessionLocal() as session:
        existing = (await session.execute(
            select(ChecklistItemTemplate.location, ChecklistItemTemplate.shift_type, ChecklistItemTemplate.step_key)
        )).all()
        existing_keys = {(loc, st, key) for loc, st, key in existing}

        def _add(shift_type, items):
            for order_index, (step_key, title, item_type, needs_reference, prompt_text) in enumerate(items):
                if (DEFAULT_LOCATION, shift_type, step_key) in existing_keys:
                    continue
                session.add(ChecklistItemTemplate(
                    location=DEFAULT_LOCATION,
                    shift_type=shift_type,
                    step_key=step_key,
                    order_index=order_index,
                    title=title,
                    prompt_text=prompt_text,
                    item_type=item_type,
                    needs_reference=needs_reference,
                ))

        _add('open', _OPEN_ITEMS)
        _add('close', _CLOSE_ITEMS)
        await session.commit()


# --- Меню сотрудника ----------------------------------------------------------

@router.message(Command("checklist"))
@router.message(lambda m: m.text == '🧾 Открытие/закрытие')
async def checklist_menu(message: types.Message, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='🔓 Открытие', callback_data='cl_start_open')],
        [InlineKeyboardButton(text='🔒 Закрытие', callback_data='cl_start_close')],
    ])
    await message.answer(f'📍 {LOCATION_LABELS[DEFAULT_LOCATION]}\nЧто делаем?', reply_markup=kb)


@router.callback_query(lambda c: c.data in ('cl_start_open', 'cl_start_close'))
async def checklist_start(callback: types.CallbackQuery, state: FSMContext):
    shift_type = 'open' if callback.data == 'cl_start_open' else 'close'

    async with SessionLocal() as session:
        user = (await session.execute(select(User).filter(User.telegram_id == callback.from_user.id))).scalar_one_or_none()
        if not user:
            await callback.answer('Вы не зарегистрированы, нажмите /start.', show_alert=True)
            return

        items = (await session.execute(
            select(ChecklistItemTemplate)
            .filter(ChecklistItemTemplate.location == DEFAULT_LOCATION, ChecklistItemTemplate.shift_type == shift_type)
            .order_by(ChecklistItemTemplate.order_index)
        )).scalars().all()
        if not items:
            await callback.answer('Чек-лист ещё не настроен.', show_alert=True)
            return

        submission = ChecklistSubmission(location=DEFAULT_LOCATION, shift_type=shift_type, user_id=user.id)
        session.add(submission)
        await session.commit()

        items_data = [{
            'id': i.id, 'key': i.step_key, 'title': i.title, 'prompt_text': i.prompt_text,
            'item_type': i.item_type, 'reference_file_id': i.reference_file_id,
        } for i in items]

    await state.set_state(ChecklistFlow.running)
    await state.update_data(submission_id=submission.id, shift_type=shift_type, items=items_data, index=0, multi_count=0)

    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except TelegramBadRequest:
        pass
    await callback.answer()
    await _send_current_item(callback.message, state)


def _done_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='✅ Готово', callback_data='cl_done_multi')]])


def _skip_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text='Нет', callback_data='cl_skip_text')]])


async def _send_current_item(message: types.Message, state: FSMContext):
    data = await state.get_data()
    items = data['items']
    index = data['index']

    if index >= len(items):
        await _finish_submission(message, state)
        return

    item = items[index]
    await state.update_data(multi_count=0)
    n = f'{index + 1}/{len(items)}'

    if item['item_type'] == 'photo':
        if item['reference_file_id']:
            await message.answer_photo(
                item['reference_file_id'],
                caption=f'{n}. Эталон: «{item["title"]}»\n\nПришлите своё фото с таким же ракурсом.',
            )
        else:
            text = f'{n}. {item["title"]}'
            if item['prompt_text']:
                text += f'\n{item["prompt_text"]}'
            await message.answer(text)

    elif item['item_type'] == 'multi_photo':
        text = f'{n}. {item["title"]}\n{item["prompt_text"] or ""}'
        await message.answer(text, reply_markup=_done_keyboard())

    elif item['item_type'] == 'text':
        text = f'{n}. {item["title"]}'
        if item['prompt_text']:
            text += f'\n{item["prompt_text"]}'
        await message.answer(text, reply_markup=_skip_keyboard())

    elif item['item_type'] == 'multi_text':
        text = f'{n}. {item["title"]}\n{item["prompt_text"] or ""}'
        await message.answer(text, reply_markup=_done_keyboard())


async def _save_answer(state: FSMContext, *, text_value: str = None, photo_file_id: str = None):
    data = await state.get_data()
    async with SessionLocal() as session:
        session.add(ChecklistAnswer(
            submission_id=data['submission_id'],
            item_id=data['items'][data['index']]['id'],
            text_value=text_value,
            photo_file_id=photo_file_id,
        ))
        await session.commit()


async def _advance(message: types.Message, state: FSMContext):
    data = await state.get_data()
    await state.update_data(index=data['index'] + 1)
    await _send_current_item(message, state)


@router.message(ChecklistFlow.running, F.photo)
async def checklist_receive_photo(message: types.Message, state: FSMContext):
    data = await state.get_data()
    item = data['items'][data['index']]
    if item['item_type'] not in PHOTO_TYPES:
        await message.answer('Сейчас не нужно фото — прочитайте вопрос выше.')
        return

    file_id = message.photo[-1].file_id
    await _save_answer(state, photo_file_id=file_id)

    if item['item_type'] == 'photo':
        await _advance(message, state)
    else:  # multi_photo
        count = data.get('multi_count', 0) + 1
        await state.update_data(multi_count=count)
        await message.answer(f'✅ Принято ({count}). Ещё, или «Готово».')


@router.message(ChecklistFlow.running, F.text)
async def checklist_receive_text(message: types.Message, state: FSMContext):
    data = await state.get_data()
    item = data['items'][data['index']]
    if item['item_type'] not in ('text', 'multi_text'):
        await message.answer('Сейчас нужно фото, а не текст.')
        return

    await _save_answer(state, text_value=message.text.strip())

    if item['item_type'] == 'text':
        await _advance(message, state)
    else:  # multi_text
        count = data.get('multi_count', 0) + 1
        await state.update_data(multi_count=count)
        await message.answer(f'✅ Принято ({count}). Ещё, или «Готово».')


@router.callback_query(ChecklistFlow.running, lambda c: c.data == 'cl_skip_text')
async def checklist_skip_text(callback: types.CallbackQuery, state: FSMContext):
    await _save_answer(state, text_value=None)
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except TelegramBadRequest:
        pass
    await callback.answer()
    await _advance(callback.message, state)


@router.callback_query(ChecklistFlow.running, lambda c: c.data == 'cl_done_multi')
async def checklist_done_multi(callback: types.CallbackQuery, state: FSMContext):
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except TelegramBadRequest:
        pass
    await callback.answer()
    await _advance(callback.message, state)


async def _finish_submission(message: types.Message, state: FSMContext):
    data = await state.get_data()
    submission_id = data['submission_id']

    from datetime import datetime

    async with SessionLocal() as session:
        submission = await session.get(ChecklistSubmission, submission_id)
        submission.status = 'completed'
        submission.completed_at = datetime.utcnow()
        worker = await session.get(User, submission.user_id)

        items = (await session.execute(
            select(ChecklistItemTemplate)
            .filter(ChecklistItemTemplate.location == submission.location, ChecklistItemTemplate.shift_type == submission.shift_type)
            .order_by(ChecklistItemTemplate.order_index)
        )).scalars().all()
        answers = (await session.execute(
            select(ChecklistAnswer).filter(ChecklistAnswer.submission_id == submission_id)
        )).scalars().all()
        await session.commit()

        answers_by_item = {}
        for a in answers:
            answers_by_item.setdefault(a.item_id, []).append(a)

        shift_label = SHIFT_LABELS.get(submission.shift_type, submission.shift_type)
        loc_label = LOCATION_LABELS.get(submission.location, submission.location)
        when = submission.completed_at.strftime('%d.%m.%Y %H:%M')
        who = f'{worker.first_name} {worker.last_name or ""}'.strip()

        lines = [f'📋 <b>{shift_label} — {loc_label}</b>', f'{when} · {who}', '']
        photo_jobs = []  # (caption, file_id)

        for item in items:
            item_answers = answers_by_item.get(item.id, [])
            if item.item_type in PHOTO_TYPES:
                for a in item_answers:
                    if a.photo_file_id:
                        photo_jobs.append((item.title, a.photo_file_id))
                if not item_answers:
                    lines.append(f'• {item.title}: — нет фото —')
            else:
                values = [a.text_value for a in item_answers if a.text_value] or ['—']
                lines.append(f'• <b>{item.title}:</b> {"; ".join(values)}')

    from api.bot import bot

    report_text = '\n'.join(lines)
    for admin_id in ADMIN_ID:
        try:
            await bot.send_message(admin_id, report_text, parse_mode='HTML')
            for caption, file_id in photo_jobs:
                await bot.send_photo(admin_id, file_id, caption=caption)
        except Exception as e:
            logger.warning('Не удалось отправить отчёт чек-листа admin_id=%s: %s', admin_id, e)

    await state.clear()
    await message.answer(f'✅ Чек-лист «{shift_label} — {loc_label}» отправлен на проверку. Спасибо!')


# --- Админ: настройка эталонных фото -----------------------------------------

@router.message(Command("set_references"))
@router.message(lambda m: m.text == '🖼 Эталоны чек-листа')
@admin_only
async def reference_menu(message: types.Message, state: FSMContext):
    await _render_reference_list(message)


async def _render_reference_list(message: types.Message):
    async with SessionLocal() as session:
        items = (await session.execute(
            select(ChecklistItemTemplate)
            .filter(ChecklistItemTemplate.location == DEFAULT_LOCATION, ChecklistItemTemplate.needs_reference == True)
            .order_by(ChecklistItemTemplate.shift_type, ChecklistItemTemplate.order_index)
        )).scalars().all()

    if not items:
        await message.answer('Пунктов с эталоном нет.')
        return

    rows = [
        [InlineKeyboardButton(
            text=f'{"✅" if i.reference_file_id else "⛔"} {SHIFT_LABELS.get(i.shift_type, i.shift_type)}: {i.title}',
            callback_data=f'clref_{i.id}',
        )]
        for i in items
    ]
    await message.answer(
        '🖼 <b>Эталонные фото.</b> ✅ — задано, ⛔ — нет.\nНажмите на пункт, чтобы загрузить/заменить фото.',
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        parse_mode='HTML',
    )


@router.callback_query(lambda c: c.data and c.data.startswith('clref_'))
async def reference_pick(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_ID:
        await callback.answer('Нет доступа.', show_alert=True)
        return
    item_id = int(callback.data.split('_')[-1])
    await state.set_state(ReferenceSetup.waiting_photo)
    await state.update_data(item_id=item_id)
    await callback.answer()
    await callback.message.answer('Пришлите новое эталонное фото для этого пункта.')


@router.message(ReferenceSetup.waiting_photo, F.photo)
async def reference_receive_photo(message: types.Message, state: FSMContext):
    data = await state.get_data()
    file_id = message.photo[-1].file_id
    async with SessionLocal() as session:
        item = await session.get(ChecklistItemTemplate, data['item_id'])
        item.reference_file_id = file_id
        title = item.title
        await session.commit()

    await state.clear()
    await message.answer(f'✅ Эталон для «{title}» сохранён.')
    await _render_reference_list(message)


@router.message(ReferenceSetup.waiting_photo)
async def reference_receive_wrong_type(message: types.Message, state: FSMContext):
    await message.answer('Нужно именно фото. Пришлите картинку.')
