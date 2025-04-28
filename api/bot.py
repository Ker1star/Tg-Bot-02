import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse
from config import STATIC_ROOT

from aiogram import Bot, Dispatcher
from aiogram.types import Update
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from config import API_TOKEN, WEBHOOK_URL, WEBHOOK_HOST
from handlers.admin import router as admin_router
from handlers.client import router as client_router
from api.webapp import router as webapp_router
from utils.database import init_db

logging.basicConfig(level=logging.INFO)

bot = Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1) Подключаем Aiogram-роутеры
    dp.include_router(admin_router)
    dp.include_router(client_router)
    # 2) Инициализируем БД
    await init_db()
    logging.info("База данных инициализирована")
    # 3) Устанавливаем вебхук
    await bot.set_webhook(f"{WEBHOOK_HOST}/webhook/{API_TOKEN}", drop_pending_updates=True)
    logging.info(f"Webhook установлен: {WEBHOOK_URL}")
    yield
    # 4) Удаляем вебхук при завершении
    await bot.delete_webhook()
    logging.info("Webhook удалён")

app = FastAPI(lifespan=lifespan)

# A) Telegram webhook endpoint
@app.post("/webhook/{token}")
async def telegram_webhook(request: Request, token: str):
    update = await request.json()
    # логируем, чтобы убедиться в поступлении
    logging.info("Telegram update: %s", update)
    return await dp.feed_update(bot, Update(**update))

# B) Ваш Web App API — НУЖНО ДО статики
app.include_router(webapp_router, prefix="/webapp")

# C) Отдаём index.html на корне и alias /index.html
@app.get("/", response_class=HTMLResponse)
async def serve_index():
    return FileResponse("webapp/index.html")

@app.get("/index.html", response_class=HTMLResponse)
async def serve_index_alias():
    return FileResponse("webapp/index.html")


# E) Монтируем всю остальную статику под /static
app.mount("/static", StaticFiles(directory=STATIC_ROOT), name="static")
