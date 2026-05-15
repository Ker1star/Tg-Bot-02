import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from config import API_TOKEN, PROXY_URL

logging.basicConfig(level=logging.INFO)

session = AiohttpSession(proxy=PROXY_URL) if PROXY_URL else None
bot = Bot(token=API_TOKEN, session=session, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher(storage=MemoryStorage())

if PROXY_URL:
    logging.info("Telegram API requests routed through proxy")
