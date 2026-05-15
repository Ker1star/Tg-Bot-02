from config import WAITER_CHAT_ID, ADMIN_ID
from models.db_models import ShiftTaskTemplate, ShiftTaskInstance
from datetime import date, timedelta, datetime
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from models.db_models import SessionLocal 
from models.db_models import User
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
import logging
from aiogram.exceptions import TelegramBadRequest

logger = logging.getLogger(__name__)

router = Router()

async def start_shift_auto():
    today = date.today()
    weekday = today.weekday()

    async with SessionLocal() as session:
        # создаём сегодняшние инстансы, если нет
        tmpl_result = await session.execute(
            select(ShiftTaskTemplate)
            .filter(
                ShiftTaskTemplate.weekday == weekday,
                ShiftTaskTemplate.is_active == True
            )
        )
        templates = tmpl_result.scalars().all()

        inst_today = await session.execute(
            select(ShiftTaskInstance).filter(ShiftTaskInstance.due_date == today)
        )
        existing_today = inst_today.scalars().all()
        existing_ids = {i.template_id for i in existing_today}

        created = 0
        for t in templates:
            if t.id not in existing_ids:
                session.add(
                    ShiftTaskInstance(
                        template_id=t.id,
                        due_date=today,
                        completed=False,
                    )
                )
                created += 1

        await session.commit()

        # берём все открытые задачи (как в /start_shift)
        result = await session.execute(
            select(
                ShiftTaskInstance.id,
                ShiftTaskInstance.due_date,
                ShiftTaskTemplate.title,
                ShiftTaskTemplate.description,
            )
            .join(ShiftTaskTemplate)
            .filter(ShiftTaskInstance.completed == False)
        )
        open_tasks = result.all()

    logger.info("Shift auto: created=%s, open_tasks=%s", created, len(open_tasks))

    from api.bot import bot

    await bot.send_message(WAITER_CHAT_ID, "🔔 Начало смены!")

    if not open_tasks:
        await bot.send_message(WAITER_CHAT_ID, "На эту смену нет незакрытых задач. 🎉")
        return

    for inst_id, due_date, title, description in open_tasks:
        text = (
            f"📝 Задача: <b>{title}</b>\n"
            f"С даты: {due_date.strftime('%d.%m.%Y')}"
        )
        if description:
            text += f"\n\n{description}"

        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="✅ Выполнено",
                        callback_data=f"shift_done_{inst_id}",
                    )
                ]
            ]
        )
        await bot.send_message(WAITER_CHAT_ID, text, reply_markup=kb)


MAX_TASK_AGE_DAYS = 7
async def cleanup_old_tasks():
    cutoff = date.today() - timedelta(days=MAX_TASK_AGE_DAYS)
    async with SessionLocal() as session:
        # Удаляем ИНСТАНСЫ, старше 7 дней, даже если они не выполнены
        result = await session.execute(
            select(ShiftTaskInstance).filter(ShiftTaskInstance.due_date < cutoff)
        )
        stale = result.scalars().all()
        for inst in stale:
            await session.delete(inst)
        await session.commit()

@router.message(Command("start_shift"))
async def start_shift(message: types.Message, state: FSMContext):
    await cleanup_old_tasks()

    if message.chat.id != WAITER_CHAT_ID:
        await message.answer("Эта команда доступна только в чате официантов. 🚫")
        return

    today = date.today()

    async with SessionLocal() as session:
        # 1) создаём инстансы задач на сегодня, если их ещё нет
        result = await session.execute(
            select(ShiftTaskTemplate).filter(
                ShiftTaskTemplate.weekday == today.weekday(),
                ShiftTaskTemplate.is_active == True,
            )
        )
        todays_templates = result.scalars().all()

        result = await session.execute(
            select(ShiftTaskInstance)
            .filter(ShiftTaskInstance.due_date == today)
        )
        today_instances = result.scalars().all()
        existing_by_tmpl = {inst.template_id for inst in today_instances}

        for t in todays_templates:
            if t.id not in existing_by_tmpl:
                session.add(
                    ShiftTaskInstance(
                        template_id=t.id,
                        due_date=today,
                        completed=False,
                    )
                )

        await session.commit()

        # 2) получаем все незавершённые задачи (включая хвост прошлых дней)
        result = await session.execute(
            select(
                ShiftTaskInstance.id,
                ShiftTaskInstance.due_date,
                ShiftTaskTemplate.title,
                ShiftTaskTemplate.description,
            )
            .join(ShiftTaskTemplate)
            .filter(ShiftTaskInstance.completed == False)
        )
        open_tasks = result.all()

    if not open_tasks:
        await message.answer("На эту смену нет незакрытых задач. 🎉")
        return

    # 3) уже после закрытия сессии просто шлём сообщения
    for inst_id, due_date, title, description in open_tasks:
        text = (
            f"📝 Задача: <b>{title}</b>\n"
            f"С даты: {due_date.strftime('%d.%m.%Y')}"
        )
        if description:
            text += f"\n\n{description}"

        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="✅ Выполнено",
                        callback_data=f"shift_done_{inst_id}",
                    )
                ]
            ]
        )
        await message.answer(text, reply_markup=kb)

@router.callback_query(lambda c: c.data and c.data.startswith("shift_done_"))
async def shift_task_done(callback: types.CallbackQuery, state: FSMContext):
    inst_id = int(callback.data.split("_")[-1])

    async with SessionLocal() as session:
        inst = await session.get(ShiftTaskInstance, inst_id)

        if not inst:
            return await callback.answer("Задача не найдена.", show_alert=True)

        if inst.completed:
            try:
                await callback.message.edit_reply_markup(reply_markup=None)
            except Exception:
                pass
            return await callback.answer("Уже выполнена.")

        # помечаем выполненной
        inst.completed = True
        inst.completed_at = datetime.utcnow()

        res = await session.execute(
            select(User).filter(User.telegram_id == callback.from_user.id)
        )
        user = res.scalar_one_or_none()
        if user:
            inst.completed_by_user_id = user.id

        await session.commit()
        logger.info(
            "Shift task done: inst_id=%s user_telegram_id=%s",
            inst_id,
            callback.from_user.id,
        )

    # сессия уже закрыта, тут только UI
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    await callback.answer("Готово 👍")

from aiogram.filters import Command
@router.message(Command("chat_id"))
async def debug_chat_id(message: types.Message):
    await message.answer(f"chat_id = {message.chat.id}")