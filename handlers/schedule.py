"""
График смен: сбор доступности, построение расписания, замены.

Рабочие допущения (проверить с администратором на живых данных, схема
их переживёт без изменений, если что-то из этого не так):
  - обычная смена: 12:00 - 22:00, по пятницам и субботам до 23:00
    (совпадает с реальным режимом работы ресторана на сайте marta11.ru);
  - "вечер" для проверки минимального веса начинается в 18:00;
  - "выходные" для правила минимального веса — суббота и воскресенье;
  - вопросы 2 и 3 опроса доступности — оба про самое раннее время выхода
    (в 13:00 и в 18:00 соответственно), а не про время ухода.
"""

import logging
import re
from datetime import date, datetime, time, timedelta

from aiogram import Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest
from sqlalchemy import update
from sqlalchemy.future import select

from config import ADMIN_ID, WAITER_CHAT_ID
from handlers.utils import admin_only
from handlers.notif import send_admin_notification
from states.forms import AvailabilitySurveyForm
from models.db_models import (
    SessionLocal,
    User,
    SchedulePeriod,
    AvailabilityResponse,
    AvailabilityConstraint,
    ShiftAssignment,
    ReplacementBroadcastMessage,
)

logger = logging.getLogger(__name__)
router = Router()

# --- Допущения по времени работы (см. докстринг файла) ---------------------
SHIFT_START = time(12, 0)
SHIFT_END_LATE = time(23, 0)   # пятница, суббота
SHIFT_END_NORMAL = time(22, 0)
EVENING_START = time(18, 0)
MIN_WEIGHT_ANYTIME = 1.0
MIN_EVENING_WEIGHT_WEEKDAY = 1.5
MIN_EVENING_WEIGHT_WEEKEND = 2.5
URGENT_REPLACEMENT_BONUS = 50  # ₽/час, если замена нужна меньше чем за сутки


def _shift_end_for(d: date) -> time:
    return SHIFT_END_LATE if d.weekday() in (4, 5) else SHIFT_END_NORMAL  # Пт=4, Сб=5


def _is_weekend_for_staffing(d: date) -> bool:
    return d.weekday() in (5, 6)  # Сб, Вс


def _next_monday() -> date:
    today = date.today()
    return today + timedelta(days=(7 - today.weekday()) % 7 or 7)


def _parse_day_numbers(text: str, period: SchedulePeriod) -> list[date]:
    """'3, 7, 14' -> список реальных дат внутри периода. Кидает ValueError с
    понятным текстом, если число вне периода."""
    numbers = [chunk.strip() for chunk in re.split(r"[,\s]+", text.strip()) if chunk.strip()]
    result = []
    for raw in numbers:
        if not raw.isdigit():
            raise ValueError(f"Не понял «{raw}» — пишите просто числа месяца через запятую.")
        day_num = int(raw)
        candidates = [
            period.start_date + timedelta(days=i)
            for i in range((period.end_date - period.start_date).days + 1)
            if (period.start_date + timedelta(days=i)).day == day_num
        ]
        if not candidates:
            raise ValueError(f"Дата «{day_num}» не входит в период {period.start_date:%d.%m}–{period.end_date:%d.%m}.")
        result.extend(candidates)
    return result


def _skip_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="➡️ Далее (таких дат нет)", callback_data="avail_skip")]])


# --- Кто вообще считается персоналом для графика -----------------------------
# По умолчанию is_active=True ставится всем, кто хоть раз нажал /start, и
# нигде в боте не сбрасывается — то есть само по себе это поле не значит
# «работает сейчас». Три команды ниже дают админу реальный рычаг: увидеть
# список и вручную отметить, кто в пуле кандидатов на смены, а кто нет.
# Администраторы (ADMIN_ID) в пул смен не попадают в любом случае.

@router.message(Command("staff_list"))
@admin_only
async def staff_list_cmd(message: types.Message, state: FSMContext):
    async with SessionLocal() as session:
        result = await session.execute(select(User).order_by(User.first_name))
        users = result.scalars().all()

    if not users:
        await message.answer("Пока никто не регистрировался в боте.")
        return

    lines = ["👥 <b>Все, кто регистрировался в боте:</b>\n"]
    for u in users:
        role = "👑 админ" if u.telegram_id in ADMIN_ID else ("✅ в пуле смен" if u.is_active else "⛔ не в пуле")
        lines.append(f"• {u.first_name} {u.last_name or ''} — id {u.telegram_id} — {role} — вес {u.weight}")
    await message.answer("\n".join(lines), parse_mode="HTML")


@router.message(Command("staff_off"))
@admin_only
async def staff_off_cmd(message: types.Message, state: FSMContext):
    await _toggle_staff(message, active=False)


@router.message(Command("staff_on"))
@admin_only
async def staff_on_cmd(message: types.Message, state: FSMContext):
    await _toggle_staff(message, active=True)


async def _toggle_staff(message: types.Message, active: bool):
    parts = message.text.split()
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer(f"Использование: {parts[0]} <telegram_id> — id смотрите в /staff_list")
        return
    telegram_id = int(parts[1])
    async with SessionLocal() as session:
        user = (await session.execute(select(User).filter(User.telegram_id == telegram_id))).scalar_one_or_none()
        if not user:
            await message.answer("Такого пользователя нет.")
            return
        user.is_active = active
        await session.commit()
    await message.answer(f"✅ {user.first_name} теперь {'в пуле смен' if active else 'исключён(а) из пула смен'}.")


# --- Запуск нового периода и рассылка опроса --------------------------------

@router.message(Command("new_period"))
@admin_only
async def new_period_cmd(message: types.Message, state: FSMContext):
    await _do_new_period(message)


async def _do_new_period(reply_to: types.Message):
    start = _next_monday()
    end = start + timedelta(days=13)

    async with SessionLocal() as session:
        period = SchedulePeriod(start_date=start, end_date=end, status="collecting")
        session.add(period)
        await session.commit()
        await session.refresh(period)

        result = await session.execute(select(User).filter(User.is_active == True, User.telegram_id.notin_(ADMIN_ID)))
        users = result.scalars().all()

    from api.bot import bot

    sent = 0
    for user in users:
        kb = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="📋 Пройти опрос доступности", callback_data=f"avail_start_{period.id}")]]
        )
        try:
            await bot.send_message(
                user.telegram_id,
                f"📅 Собираем доступность на период {start:%d.%m}–{end:%d.%m}.\n"
                f"Нажмите кнопку и ответьте на 4 коротких вопроса.",
                reply_markup=kb,
            )
            sent += 1
        except Exception as e:
            logger.warning("Не удалось отправить опрос user_id=%s: %s", user.id, e)

    await reply_to.answer(f"✅ Период #{period.id} ({start:%d.%m}–{end:%d.%m}) создан, опрос разослан {sent} сотрудникам.")


# --- FSM опроса доступности --------------------------------------------------

@router.callback_query(lambda c: c.data and c.data.startswith("avail_start_"))
async def avail_start(callback: types.CallbackQuery, state: FSMContext):
    period_id = int(callback.data.split("_")[-1])
    async with SessionLocal() as session:
        period = await session.get(SchedulePeriod, period_id)
    if not period or period.status != "collecting":
        await callback.answer("Опрос по этому периоду уже закрыт.", show_alert=True)
        return

    await state.set_state(AvailabilitySurveyForm.day_off_dates)
    await state.update_data(period_id=period_id, day_off=[], late_13=[], late_18=[])
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except TelegramBadRequest:
        pass
    await callback.message.answer(
        f"1) В какие числа вы целый день не сможете работать ({period.start_date:%d.%m}–{period.end_date:%d.%m})?\n"
        f"Перечислите через запятую (например: 3, 7, 14) или нажмите «Далее».",
        reply_markup=_skip_keyboard(),
    )
    await callback.answer()


async def _load_period(state: FSMContext) -> SchedulePeriod:
    data = await state.get_data()
    async with SessionLocal() as session:
        return await session.get(SchedulePeriod, data["period_id"])


@router.callback_query(lambda c: c.data == "avail_skip")
async def avail_skip(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except TelegramBadRequest:
        pass
    await _advance_survey(callback.message, state)


@router.message(AvailabilitySurveyForm.day_off_dates)
async def avail_day_off(message: types.Message, state: FSMContext):
    await _collect_dates(message, state, "day_off")


@router.message(AvailabilitySurveyForm.late_from_13)
async def avail_late_13(message: types.Message, state: FSMContext):
    await _collect_dates(message, state, "late_13")


@router.message(AvailabilitySurveyForm.late_from_18)
async def avail_late_18(message: types.Message, state: FSMContext):
    await _collect_dates(message, state, "late_18")


async def _collect_dates(message: types.Message, state: FSMContext, field: str):
    period = await _load_period(state)
    try:
        dates = _parse_day_numbers(message.text, period)
    except ValueError as e:
        await message.answer(f"❌ {e}\nПопробуйте ещё раз или нажмите «Далее».", reply_markup=_skip_keyboard())
        return
    data = await state.get_data()
    data[field] = [d.isoformat() for d in dates]
    await state.update_data(**data)
    await _advance_survey(message, state)


async def _advance_survey(message: types.Message, state: FSMContext):
    current = await state.get_state()
    period = await _load_period(state)

    if current == AvailabilitySurveyForm.day_off_dates.state:
        await state.set_state(AvailabilitySurveyForm.late_from_13)
        await message.answer(
            "2) В какие числа вы можете выйти на смену только с 13:00?\n"
            "Перечислите через запятую или нажмите «Далее».",
            reply_markup=_skip_keyboard(),
        )
    elif current == AvailabilitySurveyForm.late_from_13.state:
        await state.set_state(AvailabilitySurveyForm.late_from_18)
        await message.answer(
            "3) В какие числа вы можете выйти на смену только с 18:00?\n"
            "Перечислите через запятую или нажмите «Далее».",
            reply_markup=_skip_keyboard(),
        )
    elif current == AvailabilitySurveyForm.late_from_18.state:
        await state.set_state(AvailabilitySurveyForm.wishes)
        await message.answer(
            "4) Если есть другие пожелания по графику — напишите. Если нет — «Далее».",
            reply_markup=_skip_keyboard(),
        )
    elif current == AvailabilitySurveyForm.wishes.state:
        await _finish_survey(message, state, wishes=None)


@router.message(AvailabilitySurveyForm.wishes)
async def avail_wishes(message: types.Message, state: FSMContext):
    await _finish_survey(message, state, wishes=message.text)


async def _finish_survey(message: types.Message, state: FSMContext, wishes: str | None):
    data = await state.get_data()
    async with SessionLocal() as session:
        user = (await session.execute(select(User).filter(User.telegram_id == message.chat.id))).scalar_one_or_none()
        if not user:
            await message.answer("❌ Вы не зарегистрированы, нажмите /start и попробуйте снова.")
            await state.clear()
            return

        response = AvailabilityResponse(period_id=data["period_id"], user_id=user.id, comment=wishes)
        session.add(response)
        await session.flush()

        for iso in data.get("day_off", []):
            session.add(AvailabilityConstraint(response_id=response.id, date=date.fromisoformat(iso), constraint_type="day_off"))
        for iso in data.get("late_13", []):
            session.add(AvailabilityConstraint(response_id=response.id, date=date.fromisoformat(iso), constraint_type="earliest_start", time_value=time(13, 0)))
        for iso in data.get("late_18", []):
            session.add(AvailabilityConstraint(response_id=response.id, date=date.fromisoformat(iso), constraint_type="earliest_start", time_value=time(18, 0)))

        await session.commit()

    await state.clear()
    await message.answer("✅ Спасибо, ответы записаны!")


# --- Построение графика ------------------------------------------------------

async def _availability_map(session, period_id: int):
    """user_id -> {'day_off': {date,...}, 'earliest': {date: time}}"""
    result = await session.execute(
        select(AvailabilityResponse.user_id, AvailabilityConstraint)
        .join(AvailabilityConstraint, AvailabilityConstraint.response_id == AvailabilityResponse.id)
        .filter(AvailabilityResponse.period_id == period_id)
    )
    out: dict[int, dict] = {}
    for user_id, constraint in result.all():
        bucket = out.setdefault(user_id, {"day_off": set(), "earliest": {}})
        if constraint.constraint_type == "day_off":
            bucket["day_off"].add(constraint.date)
        elif constraint.constraint_type == "earliest_start":
            # если пришло несколько ограничений на одну дату — берём самое позднее (строже)
            prev = bucket["earliest"].get(constraint.date)
            if prev is None or constraint.time_value > prev:
                bucket["earliest"][constraint.date] = constraint.time_value
    return out


def _hours(start: time, end: time) -> float:
    return (datetime.combine(date.min, end) - datetime.combine(date.min, start)).seconds / 3600


async def _resolve_period_id(message: types.Message, status_wanted: str, from_text: bool = True) -> int | None:
    """Если id периода не указан явно — берём последний период в нужном статусе."""
    if from_text and message.text:
        parts = message.text.split()
        if len(parts) >= 2 and parts[1].isdigit():
            return int(parts[1])

    async with SessionLocal() as session:
        result = await session.execute(
            select(SchedulePeriod).filter(SchedulePeriod.status == status_wanted).order_by(SchedulePeriod.id.desc())
        )
        period = result.scalars().first()
    if not period:
        await message.answer(f"Не нашёл период в статусе «{status_wanted}» — возможно, нужный шаг уже пройден.")
        return None
    return period.id


@router.message(Command("generate_schedule"))
@admin_only
async def generate_schedule_cmd(message: types.Message, state: FSMContext):
    period_id = await _resolve_period_id(message, "collecting")
    if period_id is None:
        return
    await _do_generate_schedule(message, period_id)


async def _do_generate_schedule(reply_to: types.Message, period_id: int):
    message = reply_to

    async with SessionLocal() as session:
        period = await session.get(SchedulePeriod, period_id)
        if not period:
            await message.answer("Период не найден.")
            return

        result = await session.execute(select(User).filter(User.is_active == True, User.telegram_id.notin_(ADMIN_ID)))
        waiters = result.scalars().all()
        availability = await _availability_map(session, period_id)

        # чистим старые черновые назначения на этот период (перегенерация)
        old = (await session.execute(select(ShiftAssignment).filter(ShiftAssignment.period_id == period_id))).scalars().all()
        for a in old:
            await session.delete(a)
        await session.flush()

        accumulated_hours = {w.id: 0.0 for w in waiters}
        flagged_days = []

        num_days = (period.end_date - period.start_date).days + 1
        for i in range(num_days):
            day = period.start_date + timedelta(days=i)
            shift_end = _shift_end_for(day)
            min_evening = MIN_EVENING_WEIGHT_WEEKEND if _is_weekend_for_staffing(day) else MIN_EVENING_WEIGHT_WEEKDAY

            candidates = []
            for w in waiters:
                info = availability.get(w.id, {"day_off": set(), "earliest": {}})
                if day in info["day_off"]:
                    continue
                start = max(SHIFT_START, info["earliest"].get(day, SHIFT_START))
                if start >= shift_end:
                    continue  # физически не успевает
                candidates.append((w, start))

            candidates.sort(key=lambda pair: (-pair[0].weight, accumulated_hours[pair[0].id]))

            chosen = []
            has_core = False
            evening_weight = 0.0
            for w, start in candidates:
                covers_evening = start <= EVENING_START
                if has_core and (evening_weight >= min_evening or not covers_evening):
                    # минимум уже закрыт, а этот кандидат вечер и так не покрывает —
                    # добираем только если ещё не хватает вечернего веса
                    if evening_weight >= min_evening:
                        break
                chosen.append((w, start, shift_end))
                if w.weight >= MIN_WEIGHT_ANYTIME:
                    has_core = True
                if covers_evening:
                    evening_weight += w.weight
                if has_core and evening_weight >= min_evening:
                    break

            ok = has_core and evening_weight >= min_evening
            if not ok:
                flagged_days.append(day)

            for w, start, end in chosen:
                session.add(ShiftAssignment(
                    period_id=period_id, user_id=w.id, date=day,
                    start_time=start, end_time=end,
                    status="planned",
                    is_flagged=not ok,
                    flag_reason=None if ok else "Не набирается минимальный вес на смену/вечер — проверьте вручную.",
                ))
                accumulated_hours[w.id] += _hours(start, end)

        period.status = "generating"
        await session.commit()

    report = f"✅ Черновик графика для периода #{period_id} готов.\n"
    if flagged_days:
        report += "🔴 Дни с нехваткой людей/веса: " + ", ".join(d.strftime("%d.%m") for d in flagged_days) + "\n"
    else:
        report += "Все дни закрыты по минимальным условиям.\n"
    report += "Проверьте и опубликуйте: /publish_schedule " + str(period_id)
    await message.answer(report)


@router.message(Command("publish_schedule"))
@admin_only
async def publish_schedule_cmd(message: types.Message, state: FSMContext):
    period_id = await _resolve_period_id(message, "generating")
    if period_id is None:
        return
    await _do_publish_schedule(message, period_id)


async def _do_publish_schedule(reply_to: types.Message, period_id: int):
    message = reply_to

    from api.bot import bot

    async with SessionLocal() as session:
        period = await session.get(SchedulePeriod, period_id)
        if not period:
            await message.answer("Период не найден.")
            return

        result = await session.execute(
            select(ShiftAssignment, User)
            .join(User, User.id == ShiftAssignment.user_id)
            .filter(ShiftAssignment.period_id == period_id)
            .order_by(ShiftAssignment.date)
        )
        rows = result.all()
        period.status = "published"
        await session.commit()

    by_user: dict[int, list] = {}
    for assignment, user in rows:
        by_user.setdefault(user.telegram_id, []).append(assignment)

    for telegram_id, assignments in by_user.items():
        lines = [f"📅 Ваш график на {period.start_date:%d.%m}–{period.end_date:%d.%m}:"]
        for a in sorted(assignments, key=lambda x: x.date):
            mark = " 🔴" if a.is_flagged else ""
            lines.append(f"• {a.date:%d.%m} ({a.date.strftime('%a')}) {a.start_time:%H:%M}–{a.end_time:%H:%M}{mark}")
        try:
            await bot.send_message(telegram_id, "\n".join(lines))
        except Exception as e:
            logger.warning("Не удалось отправить график telegram_id=%s: %s", telegram_id, e)

    await message.answer(f"✅ График периода #{period_id} разослан {len(by_user)} сотрудникам.")


# --- Замена -------------------------------------------------------------

@router.message(Command("need_replacement"))
@router.message(lambda m: m.text == "🔄 Нужна замена")
async def need_replacement_cmd(message: types.Message, state: FSMContext):
    """Показывает кнопками ближайшие смены самого сотрудника, чтобы не нужно
    было помнить/вводить числовой id смены."""
    async with SessionLocal() as session:
        user = (await session.execute(select(User).filter(User.telegram_id == message.chat.id))).scalar_one_or_none()
        if not user:
            await message.answer("Вы не зарегистрированы, нажмите /start.")
            return
        result = await session.execute(
            select(ShiftAssignment)
            .filter(ShiftAssignment.user_id == user.id, ShiftAssignment.status == "planned", ShiftAssignment.date >= date.today())
            .order_by(ShiftAssignment.date)
        )
        assignments = result.scalars().all()

    if not assignments:
        await message.answer("У вас нет предстоящих запланированных смен.")
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"{a.date:%d.%m} ({a.date.strftime('%a')}) {a.start_time:%H:%M}–{a.end_time:%H:%M}",
            callback_data=f"need_repl_{a.id}",
        )]
        for a in assignments
    ])
    await message.answer("На какую смену нужна замена?", reply_markup=kb)


@router.message(Command("my_schedule"))
@router.message(lambda m: m.text == "📅 Мой график")
async def my_schedule_cmd(message: types.Message, state: FSMContext):
    async with SessionLocal() as session:
        user = (await session.execute(select(User).filter(User.telegram_id == message.chat.id))).scalar_one_or_none()
        if not user:
            await message.answer("Вы не зарегистрированы, нажмите /start.")
            return
        result = await session.execute(
            select(ShiftAssignment)
            .filter(ShiftAssignment.user_id == user.id, ShiftAssignment.date >= date.today())
            .order_by(ShiftAssignment.date)
        )
        assignments = result.scalars().all()

    if not assignments:
        await message.answer("У вас пока нет смен в графике.")
        return

    status_mark = {
        "planned": "",
        "needs_replacement": " 🔄 ищем замену",
        "replaced": " ✅ заменён(а)",
        "confirmed": "",
    }
    lines = ["📅 <b>Ваши ближайшие смены:</b>\n"]
    for a in assignments:
        lines.append(
            f"• {a.date:%d.%m} ({a.date.strftime('%a')}) "
            f"{a.start_time:%H:%M}–{a.end_time:%H:%M}{status_mark.get(a.status, '')}"
        )
    await message.answer("\n".join(lines), parse_mode="HTML")


# --- Меню графиков для администратора ---------------------------------------

def _schedule_admin_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🆕 Новый период + разослать опрос", callback_data="sched_new_period")],
        [InlineKeyboardButton(text="⚙️ Построить график", callback_data="sched_generate")],
        [InlineKeyboardButton(text="📤 Опубликовать график", callback_data="sched_publish")],
        [InlineKeyboardButton(text="👥 Сотрудники и веса", callback_data="sched_staff")],
        [InlineKeyboardButton(text="🔄 Кто ищет замену", callback_data="sched_pending")],
    ])


@router.message(lambda m: m.text == "Графики смен")
@admin_only
async def schedule_admin_menu(message: types.Message, state: FSMContext):
    await message.answer("📅 Графики смен — выберите действие:", reply_markup=_schedule_admin_menu())


@router.callback_query(lambda c: c.data == "sched_new_period")
async def sched_new_period_cb(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_ID:
        await callback.answer("Нет доступа.", show_alert=True)
        return
    await callback.answer("Создаю период и рассылаю опрос…")
    await _do_new_period(callback.message)


@router.callback_query(lambda c: c.data == "sched_generate")
async def sched_generate_cb(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_ID:
        await callback.answer("Нет доступа.", show_alert=True)
        return
    await callback.answer("Строю график…")
    period_id = await _resolve_period_id(callback.message, "collecting", from_text=False)
    if period_id is None:
        return
    await _do_generate_schedule(callback.message, period_id)


@router.callback_query(lambda c: c.data == "sched_publish")
async def sched_publish_cb(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_ID:
        await callback.answer("Нет доступа.", show_alert=True)
        return
    await callback.answer("Публикую…")
    period_id = await _resolve_period_id(callback.message, "generating", from_text=False)
    if period_id is None:
        return
    await _do_publish_schedule(callback.message, period_id)


@router.callback_query(lambda c: c.data == "sched_staff")
async def sched_staff_cb(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_ID:
        await callback.answer("Нет доступа.", show_alert=True)
        return
    await callback.answer()
    await _render_staff_list(callback.message)


_MONTHS_SHORT = ["янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]


def _staff_keyboard(staff) -> InlineKeyboardMarkup:
    rows = []
    for u, last_seen in staff:
        if last_seen:
            seen = f"{_MONTHS_SHORT[last_seen.month - 1]} {last_seen.year}"
        else:
            seen = "не заходил(а)"
        rows.append([InlineKeyboardButton(
            text=f"{'✅' if u.is_active else '⛔'} {u.first_name} · {seen}",
            callback_data=f"staff_toggle_{u.id}",
        )])
    rows.append([InlineKeyboardButton(text="⛔ Выключить всех (начать с нуля)", callback_data="staff_all_off")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _load_staff(session):
    """Сотрудники + дата последней активности.

    Активность считаем по таблице answers: сброс прогресса чистит только
    user_progress, а ответы остаются — поэтому это единственный след,
    переживающий сброс, и по нему видно, кто реально ещё заходит.
    Сортировка: сначала недавно активные, чтобы действующий штат был сверху.
    """
    from models.db_models import Answer
    from sqlalchemy import func

    result = await session.execute(
        select(User, func.max(Answer.timestamp))
        .outerjoin(Answer, Answer.user_id == User.id)
        .group_by(User.id)
    )
    rows = [(u, ts) for u, ts in result.all() if u.telegram_id not in ADMIN_ID]
    rows.sort(key=lambda pair: (pair[1] is None, -(pair[1].timestamp() if pair[1] else 0)))
    return rows


async def _render_staff_list(message: types.Message):
    async with SessionLocal() as session:
        staff = await _load_staff(session)

    if not staff:
        await message.answer("Пока никто не регистрировался в боте.")
        return

    active = sum(1 for u, _ in staff if u.is_active)
    await message.answer(
        f"👥 <b>Сотрудники</b> — в графике {active} из {len(staff)}.\n"
        "Рядом с именем — когда человек последний раз что-то делал в боте "
        "(по ответам на тесты, эта отметка переживает сброс прогресса).\n"
        "Нажмите на человека, чтобы включить/исключить его из графика.",
        reply_markup=_staff_keyboard(staff),
        parse_mode="HTML",
    )


@router.callback_query(lambda c: c.data == "staff_all_off")
async def staff_all_off_cb(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_ID:
        await callback.answer("Нет доступа.", show_alert=True)
        return

    async with SessionLocal() as session:
        await session.execute(
            update(User).where(User.telegram_id.notin_(ADMIN_ID)).values(is_active=False)
        )
        await session.commit()
        staff = await _load_staff(session)

    try:
        await callback.message.edit_reply_markup(reply_markup=_staff_keyboard(staff))
    except TelegramBadRequest:
        pass
    await callback.answer("Все выключены — теперь включите тех, кто работает.")


@router.callback_query(lambda c: c.data and c.data.startswith("staff_toggle_"))
async def staff_toggle_cb(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_ID:
        await callback.answer("Нет доступа.", show_alert=True)
        return
    user_id = int(callback.data.split("_")[-1])

    async with SessionLocal() as session:
        user = await session.get(User, user_id)
        if not user:
            await callback.answer("Пользователь не найден.", show_alert=True)
            return
        user.is_active = not user.is_active
        await session.commit()
        new_state = user.is_active
        name = user.first_name

        staff = await _load_staff(session)

    try:
        await callback.message.edit_reply_markup(reply_markup=_staff_keyboard(staff))
    except TelegramBadRequest:
        pass
    await callback.answer(f"{name}: {'в графике' if new_state else 'исключён(а)'}")


@router.callback_query(lambda c: c.data == "sched_pending")
async def sched_pending_cb(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_ID:
        await callback.answer("Нет доступа.", show_alert=True)
        return
    await callback.answer()

    async with SessionLocal() as session:
        result = await session.execute(
            select(ShiftAssignment, User)
            .join(User, User.id == ShiftAssignment.user_id)
            .filter(ShiftAssignment.status == "needs_replacement")
            .order_by(ShiftAssignment.date)
        )
        rows = result.all()

    if not rows:
        await callback.message.answer("Сейчас никто не ищет замену.")
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"📣 {a.date:%d.%m} {a.start_time:%H:%M} (вместо {u.first_name}) — расширить",
            callback_data=f"sched_expand_{a.id}",
        )]
        for a, u in rows
    ])
    await callback.message.answer(
        "🔄 Ищут замену. Кнопка расширяет рассылку на всех, включая стажёров:",
        reply_markup=kb,
    )


@router.callback_query(lambda c: c.data and c.data.startswith("sched_expand_"))
async def sched_expand_cb(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id not in ADMIN_ID:
        await callback.answer("Нет доступа.", show_alert=True)
        return
    assignment_id = int(callback.data.split("_")[-1])
    await callback.answer("Рассылаю всем…")
    await _broadcast_replacement(assignment_id, expand=True)
    await callback.message.answer("✅ Рассылка расширена на всех сотрудников.")


@router.callback_query(lambda c: c.data and c.data.startswith("need_repl_"))
async def need_replacement_pick(callback: types.CallbackQuery, state: FSMContext):
    assignment_id = int(callback.data.split("_")[-1])

    async with SessionLocal() as session:
        assignment = await session.get(ShiftAssignment, assignment_id)
        user = (await session.execute(select(User).filter(User.telegram_id == callback.from_user.id))).scalar_one_or_none()
        if not assignment or not user or assignment.user_id != user.id:
            await callback.answer("Смена не найдена среди ваших.", show_alert=True)
            return
        if assignment.status != "planned":
            await callback.answer("Эта смена уже не в статусе «запланирована».", show_alert=True)
            return

        assignment.status = "needs_replacement"
        await session.commit()

    try:
        await callback.message.edit_text(f"🔄 Ищу замену на {assignment.date:%d.%m} {assignment.start_time:%H:%M}–{assignment.end_time:%H:%M}, сообщу как только кто-то откликнется.")
    except TelegramBadRequest:
        pass
    await callback.answer()
    await _broadcast_replacement(assignment_id, expand=False)


@router.message(Command("pending_replacements"))
@admin_only
async def pending_replacements_cmd(message: types.Message, state: FSMContext):
    async with SessionLocal() as session:
        result = await session.execute(
            select(ShiftAssignment, User)
            .join(User, User.id == ShiftAssignment.user_id)
            .filter(ShiftAssignment.status == "needs_replacement")
            .order_by(ShiftAssignment.date)
        )
        rows = result.all()

    if not rows:
        await message.answer("Сейчас никто не ищет замену.")
        return

    lines = ["🔄 <b>Ищут замену:</b>"]
    for a, u in rows:
        lines.append(f"• id {a.id} — {a.date:%d.%m} {a.start_time:%H:%M}–{a.end_time:%H:%M}, вместо {u.first_name}")
    lines.append("\nРасширить рассылку: /expand_replacement <id>")
    await message.answer("\n".join(lines), parse_mode="HTML")


@router.message(Command("expand_replacement"))
@admin_only
async def expand_replacement_cmd(message: types.Message, state: FSMContext):
    parts = message.text.split()
    if len(parts) < 2 or not parts[1].isdigit():
        await message.answer("Использование: /expand_replacement <id смены> — id смотрите в /pending_replacements. Расширяет рассылку на всех, включая стажёров.")
        return
    await _broadcast_replacement(int(parts[1]), expand=True)
    await message.answer("Рассылка расширена на всех сотрудников.")


async def _broadcast_replacement(assignment_id: int, expand: bool):
    from api.bot import bot

    async with SessionLocal() as session:
        assignment = await session.get(ShiftAssignment, assignment_id)
        if not assignment or assignment.status != "needs_replacement":
            return
        original = await session.get(User, assignment.user_id)

        result = await session.execute(select(User).filter(User.is_active == True, User.telegram_id.notin_(ADMIN_ID)))
        all_users = result.scalars().all()

        busy_that_day = set(
            (await session.execute(
                select(ShiftAssignment.user_id).filter(
                    ShiftAssignment.period_id == assignment.period_id,
                    ShiftAssignment.date == assignment.date,
                    ShiftAssignment.status.in_(("planned", "confirmed", "replaced")),
                )
            )).scalars().all()
        )

        candidates = [
            u for u in all_users
            if u.id != assignment.user_id and u.id not in busy_that_day
            and (expand or u.weight >= MIN_WEIGHT_ANYTIME)
        ]

        hours_until = (datetime.combine(assignment.date, assignment.start_time) - datetime.utcnow()).total_seconds() / 3600
        is_urgent = hours_until < 24
        bonus_text = f"\n💰 Срочная замена: +{URGENT_REPLACEMENT_BONUS} ₽/час к ставке." if is_urgent else ""

        text = (
            f"🆘 Нужна замена на смену {assignment.date:%d.%m} "
            f"{assignment.start_time:%H:%M}–{assignment.end_time:%H:%M}"
            f" (вместо {original.first_name if original else '—'})."
            f"{bonus_text}\n\nКто первый нажмёт — тот и выходит."
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✅ Я выйду", callback_data=f"claim_repl_{assignment.id}")]])

        for u in candidates:
            try:
                sent = await bot.send_message(u.telegram_id, text, reply_markup=kb)
                session.add(ReplacementBroadcastMessage(assignment_id=assignment.id, user_id=u.id, chat_id=sent.chat.id, message_id=sent.message_id))
            except Exception as e:
                logger.warning("Не удалось отправить предложение замены user_id=%s: %s", u.id, e)

        await session.commit()


@router.callback_query(lambda c: c.data and c.data.startswith("claim_repl_"))
async def claim_replacement(callback: types.CallbackQuery, state: FSMContext):
    assignment_id = int(callback.data.split("_")[-1])

    async with SessionLocal() as session:
        candidate = (await session.execute(select(User).filter(User.telegram_id == callback.from_user.id))).scalar_one_or_none()
        if not candidate:
            await callback.answer("Вы не зарегистрированы.", show_alert=True)
            return

        # атомарный захват: обновляем, только если статус ещё "нужна замена" —
        # это и решает гонку при одновременном нажатии несколькими людьми.
        result = await session.execute(
            update(ShiftAssignment)
            .where(ShiftAssignment.id == assignment_id, ShiftAssignment.status == "needs_replacement")
            .values(status="replaced", replaced_by_user_id=candidate.id)
        )
        await session.commit()
        won = result.rowcount == 1

        if not won:
            await callback.answer("Замена уже найдена, кто-то успел раньше 🙁", show_alert=True)
            return

        assignment = await session.get(ShiftAssignment, assignment_id)
        broadcasts = (await session.execute(
            select(ReplacementBroadcastMessage).filter(ReplacementBroadcastMessage.assignment_id == assignment_id)
        )).scalars().all()

    from api.bot import bot

    for b in broadcasts:
        try:
            if b.user_id == candidate.id:
                await bot.edit_message_text("✅ Вы вышли на эту замену.", chat_id=b.chat_id, message_id=b.message_id)
            else:
                await bot.edit_message_text("Замена уже найдена, спасибо за отклик 🙏", chat_id=b.chat_id, message_id=b.message_id)
        except Exception as e:
            logger.warning("Не удалось обновить сообщение о замене: %s", e)

    await callback.answer("Готово, вы вышли на смену ✅")
    await send_admin_notification(
        f"Замена на {assignment.date:%d.%m} {assignment.start_time:%H:%M}–{assignment.end_time:%H:%M} найдена: "
        f"{candidate.first_name}."
    )
