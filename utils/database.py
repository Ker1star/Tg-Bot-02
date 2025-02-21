from models.db_models import engine, Base

async def init_db():
    async with engine.begin() as conn:
        # Создаём все таблицы, если они еще не созданы
        await conn.run_sync(Base.metadata.create_all)