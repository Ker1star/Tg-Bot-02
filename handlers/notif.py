import asyncio
import random
from models.db_models import User, SessionLocal
import logging
from config import ADMIN_ID
from aiogram.enums import ParseMode
from sqlalchemy.future import select
import re

logger = logging.getLogger(__name__)

# Функция для получения всех пользователей из базы данных
async def get_all_users():
    async with SessionLocal() as session:
        result = await session.execute(select(User))
        users = result.scalars().all()
    return users

# Функция для экранирования символов в сообщении (для Markdown V2)
def escape_markdown_v2(text: str) -> str:
    # Экранируем все символы, которые требуют экранирования в Markdown V2
    return re.sub(r'([_.\*[\]()~`>#+\-=|{}.!])', r'\\\1', text)

# Функция для отправки уведомления конкретному пользователю
async def send_notification(telegram_id: int, message: str):
    from api.bot import bot
    try:
        safe_message = escape_markdown_v2(message)
        await bot.send_message(telegram_id, safe_message, parse_mode=ParseMode.MARKDOWN_V2)
    except Exception as e:
        logger.error(f"Не удалось отправить сообщение пользователю {telegram_id}: {e}")

# Функция для рассылки уведомлений всем пользователям с задержкой
async def send_notifications_to_all_users(message: str):
    users = await get_all_users()
    tasks = []

    # Для каждой отправки сообщения добавляем паузу
    for user in users:
        task = send_notification_with_delay(user.telegram_id, message)
        tasks.append(task)

    await asyncio.gather(*tasks)

# Функция для отправки уведомлений с задержкой (от 1 до 5 секунд)
async def send_notification_with_delay(telegram_id: int, message: str):
    try:
        # Задержка между отправками сообщений (рандомный интервал от 1 до 5 секунд)
        delay = random.uniform(1, 5)
        await asyncio.sleep(delay)
        
        # Отправка уведомления пользователю
        await send_notification(telegram_id, message)
        
    except Exception as e:
        logger.error(f"Не удалось отправить сообщение пользователю {telegram_id}: {e}")
async def send_admin_notification(message: str):
    # Отправка уведомлений всем администраторам
    for admin_id in ADMIN_ID:
        await send_notification(admin_id, message)