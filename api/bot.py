import asyncio
import logging
import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from aiogram import Bot, Dispatcher
from aiogram.types import Update
from config import API_TOKEN, WEBHOOK_PATH, WEBHOOK_URL, WEBHOOK_HOST
from handlers.admin import router as admin_router
from handlers.client import router as client_router
from utils.database import init_db
from fastapi.middleware.cors import CORSMiddleware


logging.basicConfig(level=logging.INFO)



bot = Bot(token=API_TOKEN)
dp = Dispatcher()
dp["_startup_log"] = True  # Логирует зарегистрированные обработчики


init_db()

@asynccontextmanager
async def lifespan(app: FastAPI):
        dp.include_router(admin_router)
        dp.include_router(client_router)
        await bot.set_webhook(f"{WEBHOOK_HOST}/webhook/{API_TOKEN}", drop_pending_updates=True)
        logging.info(f"Webhook установлен: {WEBHOOK_URL}")
        yield
        logging.info("Shutting down bot...")
        await bot.delete_webhook()  # Удаляем вебхук только после завершения работы приложения
        logging.info("Webhook deleted")

app = FastAPI(lifespan=lifespan)

@app.post("/webhook/{token}")  # токен из URL, а не query-параметра
async def telegram_webhook(request: Request, token: str):
    try:
        update = await request.json()
        logging.info(f"Получено обновление: {update}")
        update_obj = Update(**update)  # Преобразуем словарь в объект Update
        loop = asyncio.get_event_loop()

        logging.info("Цикл событий активен.")

        await loop.create_task(dp.feed_update(bot, update_obj))
        logging.info("Вроде норм.")
        return {"ok": True}
    except Exception as e:
        logging.error(f"Ошибка при обработке обновления: {e}")
        return {"ok": False, "error": str(e)}

