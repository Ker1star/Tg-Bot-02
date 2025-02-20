# bot.py
import asyncio
import logging
from aiogram import Bot, Dispatcher
from config import API_TOKEN, WEBHOOK_PATH, WEBHOOK_URL
from handlers import admin, client
from utils.database import init_db

from fastapi import FastAPI, Request
from aiogram.types import Update

logging.basicConfig(level=logging.INFO)

# Инициализация бота и диспетчера
bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# Регистрируем роутеры с обработчиками (админ и клиент)
dp.include_router(admin.router)
dp.include_router(client.router)

# Инициализируем базу данных
init_db()

# Функции запуска и остановки вебхука
async def on_startup():
    await bot.set_webhook(WEBHOOK_URL)
    logging.info(f"Webhook установлен: {WEBHOOK_URL}")

async def on_shutdown():
    await bot.delete_webhook()
    logging.info("Webhook удалён")

# Создаём FastAPI-приложение
app = FastAPI()

# Основной endpoint для вебхука. Обратите внимание, что URL совпадает с WEBHOOK_PATH
@app.post(WEBHOOK_PATH)
async def telegram_webhook(request: Request):
    data = await request.json()
    update = Update(**data)
    asyncio.create_task(dp.feed_update(update))
    return {"ok": True}

# Регистрация событий запуска и остановки
@app.on_event("startup")
async def startup_event():
    await on_startup()

@app.on_event("shutdown")
async def shutdown_event():
    await on_shutdown()

# Локальный запуск для отладки
if __name__ == '__main__':
    import uvicorn
    uvicorn.run("bot:app", host="0.0.0.0", port=8000, log_level="info")