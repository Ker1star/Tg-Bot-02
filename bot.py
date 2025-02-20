# bot.py
import asyncio
import logging
from aiogram import Bot, Dispatcher, Router
from config import API_TOKEN
from handlers import admin, client
from utils.database import init_db

logging.basicConfig(level=logging.INFO)

bot = Bot(token=API_TOKEN)
dp = Dispatcher()
router = Router()

# Подключаем роутеры (хэндлеры)
dp.include_router(admin.router)
dp.include_router(client.router)

async def main():
    # Инициализируем базу данных (создаем таблицы, если их еще нет)
    init_db()
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())
