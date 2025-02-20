import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from aiogram import Bot, Dispatcher
from aiogram.types import Update
from config import API_TOKEN, WEBHOOK_PATH, WEBHOOK_URL, WEBHOOK_HOST
from handlers import admin, client
from utils.database import init_db
from fastapi.middleware.cors import CORSMiddleware


logging.basicConfig(level=logging.INFO)



bot = Bot(token=API_TOKEN)
dp = Dispatcher()

dp.include_router(admin.router)
dp.include_router(client.router)

init_db()

@asynccontextmanager
async def lifespan(app: FastAPI):
    #await bot.delete_webhook()  # очистить старый вебхук
    await bot.set_webhook(f"{WEBHOOK_HOST}/webhook/{API_TOKEN}", allowed_updates=dp.resolve_used_update_types(),
                          drop_pending_updates=True)
    logging.info(f"Webhook установлен: {WEBHOOK_URL}")
    yield
    await bot.delete_webhook() #удалить после завершения работы
    await bot.session.close()  # закрытие сессии после завершения работы приложения

app = FastAPI(lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"])

@app.get("/")
async def read_root():
    return {"message": "Hello, World!"}


logger = logging.getLogger(__name__)

@app.post("/webhook/{token}")  # токен из URL, а не query-параметра
async def telegram_webhook(request: Request, token: str):
    if token != API_TOKEN:
        logger.warning("Invalid token")
        return {"ok": False}
    try:
        update = await request.json()
        update_obj = Update(**update)  # Преобразуем словарь в объект Update
        await dp.feed_update(bot, update_obj)  # Передаем объект update в feed_update
        return {"ok": True}
    except Exception as e:
        logger.error(f"Error processing webhook: {e}")
        return {"ok": False, "error": str(e)}

#if __name__ == '__main__':
   # import uvicorn
    #uvicorn.run("api.bot:app", host="0.0.0.0", port=8000, log_level="info")
