import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from aiogram import Bot, Dispatcher
from aiogram.types import Update
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from config import API_TOKEN, WEBHOOK_URL, WEBHOOK_HOST, PROXY_URL
from handlers.admin import router as admin_router
from handlers.client import router as client_router
from handlers.shift import router as shift_router
from utils.database import init_db

logging.basicConfig(level=logging.INFO)

session = AiohttpSession(proxy=PROXY_URL) if PROXY_URL else None
bot = Bot(token=API_TOKEN, session=session, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
if PROXY_URL:
    logging.info("Telegram API requests routed through proxy")
dp = Dispatcher(storage=MemoryStorage())

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from handlers.shift import start_shift_auto
from config import WAITER_CHAT_ID

scheduler = AsyncIOScheduler(timezone="Europe/Moscow")

async def setup_scheduler():
    scheduler.add_job(
        start_shift_auto,
        CronTrigger(hour=11, minute=1),  # или свои время/минуты
        name="start_shift_morning"
    )
    scheduler.start()
    logging.info("Scheduler started")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1) Подключаем Aiogram-роутеры
    dp.include_router(admin_router)
    dp.include_router(client_router)
    dp.include_router(shift_router)
    # 2) Инициализируем БД
    await init_db()
    logging.info("База данных инициализирована")
    await setup_scheduler()
    # 3) Устанавливаем вебхук
    await bot.set_webhook(f"{WEBHOOK_HOST}/webhook/{API_TOKEN}", drop_pending_updates=True)
    logging.info(f"Webhook установлен: {WEBHOOK_URL}")
    try:
        yield
    finally:
        # 5) Останавливаем планировщик и убираем вебхук
        scheduler.shutdown(wait=False)
        logging.info("Scheduler stopped")

        await bot.delete_webhook()
        logging.info("Webhook удалён")
        await bot.session.close()
app = FastAPI(lifespan=lifespan)

@app.post("/webhook/{token}")
async def telegram_webhook(request: Request, token: str):
    update = await request.json()
    logging.info("Telegram update: %s", update)
    return await dp.feed_update(bot, Update(**update))
