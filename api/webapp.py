from fastapi import APIRouter, Depends
from models.db_models import SessionLocal, Product, Wallet
from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi.responses import JSONResponse
from aiogram import Bot
from config import API_TOKEN
from models.db_models import User
from fastapi import HTTPException
from models.db_models import Wallet, Product, Transaction, User, Category
from handlers.notif import send_admin_notification
from sqlalchemy.orm import selectinload

router = APIRouter()
bot_api = Bot(token=API_TOKEN)

from typing import AsyncGenerator

async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session

@router.get("/products")
async def list_products(session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(Product)
        .options(selectinload(Product.category))
        .filter(Product.is_active == True))
    items = result.scalars().all()
    return [{"id": p.id, "name": p.name, "desc": p.description, "price": p.price, "img": p.image_url, "category": p.category.name if p.category else None}
            for p in items]

@router.get("/balance/{telegram_id}")
async def get_balance(telegram_id: int, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(Wallet).filter(Wallet.user_id == telegram_id))
    wallet = result.scalar_one_or_none()
    return {"balance": wallet.balance if wallet else 0}

@router.post("/purchase")
async def make_purchase(data: dict, session: AsyncSession = Depends(get_session)):
    tid = data["telegram_id"]
    pid = data["product_id"]
    # Загружаем пользователя, кошелёк и товар
    user = (await session.execute(select(User).filter(User.telegram_id == tid))).scalar_one_or_none()
    if not user:
        raise HTTPException(404, "User not found")
    wallet = (await session.execute(select(Wallet).filter(Wallet.user_id == user.id))).scalar_one_or_none()
    product = (await session.execute(select(Product).filter(Product.id == pid, Product.is_active==True))).scalar_one_or_none()
    if not product:
        raise HTTPException(404, "Product not found")
    if not wallet or wallet.balance < product.price:
        return JSONResponse({"success": False, "error": "Недостаточно средств"})
    # Списываем
    wallet.balance -= product.price
    # Сохраняем транзакцию
    tx = Transaction(
        user_id=user.id,
        amount=-product.price,
        type="debit",
        reason="покупка товара",
    )
    session.add(tx)
    await session.commit()
    # Уведомляем админов
    await send_admin_notification(f"🛒 Покупка: {user.first_name} {user.last_name} — {product.name} за {product.price} баллов")
    return {"success": True, "new_balance": wallet.balance}

@router.get("/user/{telegram_id}")
async def get_user_profile(telegram_id: int, session: AsyncSession = Depends(get_session)):
    # Получаем пользователя из БД
    result = await session.execute(select(User).filter(User.telegram_id == telegram_id))
    db_user = result.scalar_one_or_none()
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")

    wallet_res = await session.execute(
        select(Wallet).filter(Wallet.user_id == db_user.id)
    )
    wallet = wallet_res.scalar_one_or_none()
    balance = wallet.balance if wallet else 0
    # Получаем аватарку через Bot API
    photo_url = None
    try:
        photos = await bot_api.get_user_profile_photos(telegram_id, limit=1)
        if photos.total_count and photos.photos:
            largest = photos.photos[0][-1]
            file_obj = await bot_api.get_file(largest.file_id)
            photo_url = f"https://api.telegram.org/file/bot{API_TOKEN}/{file_obj.file_path}"
    except Exception:
        pass

    return {
        "first_name": db_user.first_name or "",
        "last_name": db_user.last_name or "",
        "balance": balance,
        "photo_url": photo_url
    }
@router.get("/transactions/{telegram_id}")
async def get_history(telegram_id: int, session: AsyncSession = Depends(get_session)):
    user = (await session.execute(select(User).filter(User.telegram_id == telegram_id))).scalar_one_or_none()
    if not user:
        raise HTTPException(404, "User not found")
    txs = (await session.execute(
        select(Transaction).filter(Transaction.user_id == user.id).order_by(Transaction.timestamp.desc())
    )).scalars().all()
    return [
      {"amount": t.amount, "type": t.type, "reason": t.reason, "when": t.timestamp.isoformat()}
      for t in txs
    ]
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.future import select
from models.db_models import Wallet, Product, Transaction, User
from handlers.notif import send_admin_notification

@router.post("/purchase_cart")
async def purchase_cart(data: dict, session: AsyncSession = Depends(get_session)):
    tid = data.get("telegram_id")
    items = data.get("items", [])
    # 1) Найти пользователя и кошелёк
    user = (await session.execute(select(User).filter(User.telegram_id == tid))).scalar_one_or_none()
    if not user:
        raise HTTPException(404, "User not found")
    wallet = (await session.execute(select(Wallet).filter(Wallet.user_id == user.id))).scalar_one_or_none()
    if not wallet:
        return JSONResponse({"success": False, "error": "Кошелёк не найден"})

    # 2) Подгрузить товары
    prod_ids = [it["product_id"] for it in items]
    prods = {p.id: p for p in (await session.execute(
        select(Product).filter(Product.id.in_(prod_ids), Product.is_active == True)
    )).scalars().all()}

    # 3) Вычислить сумму
    total = 0
    for it in items:
        p = prods.get(it["product_id"])
        if not p:
            return JSONResponse({"success": False, "error": f"Товар {it['product_id']} не найден"})
        total += p.price * it["quantity"]

    if wallet.balance < total:
        return JSONResponse({"success": False, "error": "Недостаточно средств"})

    # 4) Списать баланс и сохранить транзакции
    wallet.balance -= total
    for it in items:
        p = prods[it["product_id"]]
        tx = Transaction(
            user_id=user.id,
            amount=-(p.price * it["quantity"]),
            type="debit",
            reason=f"Корзина: {p.name} x{it['quantity']}"
        )
        session.add(tx)

    await session.commit()

    # 5) Уведомить админов
    desc = ", ".join(f"{p.name} x{it['quantity']}" for it in items for p in [prods[it["product_id"]]])
    await send_admin_notification(
        f"🛒 Корзина от {user.first_name} {user.last_name}: {desc}. Сумма {total} баллов"
    )

    return {"success": True, "new_balance": wallet.balance}
