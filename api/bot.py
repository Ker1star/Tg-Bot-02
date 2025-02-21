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
dp["_startup_log"] = True  # Логирует зарегистрированные обработчики
dp.include_router(admin.router)
dp.include_router(client.router)


init_db()

@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        
        await bot.set_webhook(f"{WEBHOOK_HOST}/webhook/{API_TOKEN}", drop_pending_updates=True)
        logging.info(f"Webhook установлен: {WEBHOOK_URL}")
        yield
    except Exception as e:
        logging.error(f"Ошибка в lifespan: {e}")
    finally:
        await bot.delete_webhook()  # Удаляем вебхук, когда приложение завершает работу
app = FastAPI(lifespan=lifespan)

@app.post("/webhook/{token}")  # токен из URL, а не query-параметра
async def telegram_webhook(request: Request, token: str):
    try:
        update = await request.json()
        logging.info(f"Получено обновление: {update}")
        update_obj = Update(**update)  # Преобразуем словарь в объект Update
        loop = asyncio.get_event_loop()
        await loop.create_task(dp.feed_update(bot, update_obj))
        return {"ok": True}
    except Exception as e:
        logging.error(f"Ошибка при обработке обновления: {e}")
        return {"ok": False, "error": str(e)}

#if __name__ == '__main__':
   # import uvicorn
    #uvicorn.run("api.bot:app", host="0.0.0.0", port=8000, log_level="info")
