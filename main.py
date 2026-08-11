import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from api.bot import bot, dp
from handlers.admin import router as admin_router
from handlers.client import router as client_router
from handlers.shift import router as shift_router, start_shift_auto
from handlers.schedule import router as schedule_router
from utils.database import init_db


async def main():
    dp.include_router(admin_router)
    dp.include_router(client_router)
    dp.include_router(shift_router)
    dp.include_router(schedule_router)

    await init_db()
    logging.info("База данных инициализирована")

    scheduler = AsyncIOScheduler(timezone="Europe/Moscow")
    scheduler.add_job(
        start_shift_auto,
        CronTrigger(hour=8, minute=30),
        name="start_shift_morning",
        misfire_grace_time=3600,
    )
    scheduler.start()
    logging.info("Scheduler started")

    await bot.delete_webhook(drop_pending_updates=True)
    logging.info("Webhook очищен, стартую polling")

    try:
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown(wait=False)
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
