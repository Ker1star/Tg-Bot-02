from functools import wraps
from models.db_models import SessionLocal
from sqlalchemy.ext.asyncio import AsyncSession
from functools import wraps
from aiogram import types
from config import ADMIN_ID

def admin_only(handler):
    @wraps(handler)
    async def wrapper(message: types.Message, *args, **kwargs):
        if message.from_user.id not in ADMIN_ID:
            return await message.answer("❌ У вас нет доступа к этой команде.")
        return await handler(message, *args, **kwargs)
    return wrapper

def with_session(func):
    @wraps(func)
    async def wrapper(*args, session: AsyncSession = None, **kwargs):
        async with SessionLocal() as session:
            try:
                return await func(*args, session=session, **kwargs)
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.commit()
    return wrapper

async def prompt(message, text: str, keyboard=None, parse_mode=None):
    """
    Унифицированная отправка текста с опциональной клавиатурой и parse_mode.
    """
    await message.answer(text, reply_markup=keyboard, parse_mode=parse_mode)