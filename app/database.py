from pony.orm import Database, Required, Optional, Set, PrimaryKey, db_session, select
from datetime import datetime
import os
from dotenv import load_dotenv

load_dotenv()

DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")

db = Database()

class User(db.Entity):
    telegram_id = PrimaryKey(int, size=64)  
    username = Optional(str, unique=True)   
    started = Required(bool, default=False)
    referral_code = Optional(str, unique=True)
    referral_bonus_active = Required(bool, default=False)
    referred_by = Optional("User", reverse="referrals")
    referrals = Set("User", reverse="referred_by")
    subscription_end = Optional(datetime)
    trial_used = Required(bool, default=False)
    trial_end_date = Optional(datetime)
    host = Optional(str, nullable=True)
    server_port = Optional(str, nullable=True)
    password = Optional(str, nullable=True)
    method = Optional(str, nullable=True)
    access_key = Optional(str, nullable=True)
    dynamic_key = Optional(str, nullable=True)
    key_id = Optional(int, nullable=True)
    last_payment_id = Optional(str, nullable=True)
    created_at = Required(datetime, default=datetime.now)  
    subscriptions = Set('Subscription')
    payments = Set('Payment')  

class Subscription(db.Entity):
    user = Required(User, reverse='subscriptions')
    start_date = Required(datetime)
    end_date = Required(datetime)
    amount = Required(float, default=0.0)  
    status = Required(str, default="Active")

class Payment(db.Entity):
    id = PrimaryKey(str)
    user = Required(User, reverse='payments')
    amount = Required(float)
    payment_date = Required(datetime, default=datetime.now)
    status = Required(str)


db.bind(
    provider="postgres",
    user=DB_USER,
    password=DB_PASSWORD,
    host=DB_HOST,
    database=DB_NAME,
    port=DB_PORT
)

db.generate_mapping(create_tables=True)

@db_session
def get_all_data():
    users = select(u for u in User if u.subscriptions.exists(lambda s: s.status == "Active"))[:]

    if not users:
        return "Нет активных пользователей."

    response = "🔹 *Список активных пользователей:*\n\n"

    for user in users:
        response += f"👤 *{user.username}* (ID: {user.telegram_id})\n"
        response += f"🔑 VPN-ключ: `{user.access_key or 'нет'}`\n"
        response += f"📅 Подписка до: {user.subscription_end.strftime('%Y-%m-%d') if user.subscription_end else 'Нет'}\n"
        response += f"🔑 ID ключа: `{user.key_id or 'нет'}`\n"

        subscriptions = [s for s in user.subscriptions if s.status == "Active"]
        for sub in subscriptions:
            response += f"  ├ 🏷 {sub.amount}₽ | {sub.start_date.strftime('%d.%m.%Y')} → {sub.end_date.strftime('%d.%m.%Y')}\n"

        payments = user.payments.order_by(Payment.payment_date)
        if payments:
            response += "  💳 *Платежи:*\n"
            for payment in payments:
                response += f"  ├ 💰 {payment.amount}₽ | {payment.payment_date.strftime('%d.%m.%Y')} | {payment.status}\n"

        response += "\n"
    if len(response) > 1024:
        return "Ответ слишком длинный, попробуй /database user"
    else:
        return response.strip()

@db_session
def get_user_data(username):
    user = User.get(username=username)

    if not user:
        return f"❌ Пользователь *{username}* не найден."

    response = f"👤 *{user.username}* (ID: {user.telegram_id})\n"
    response += f"🔑 VPN-ключ: `{user.access_key or 'нет'}`\n"
    response += f"📅 Дата окончания подписки: {user.subscription_end.strftime('%Y-%m-%d') if user.subscription_end else 'Нет'}\n"
    response += f"🔑 ID ключа: `{user.key_id or 'нет'}`\n"

    subscriptions = user.subscriptions.order_by(Subscription.start_date)
    if subscriptions:
        response += "🏷 *Подписки:*\n"
        for sub in subscriptions:
            response += f"  ├ {sub.amount}₽ | {sub.start_date.strftime('%d.%m.%Y')} → {sub.end_date.strftime('%d.%m.%Y')} | {sub.status}\n"

    payments = user.payments.order_by(Payment.payment_date)
    if payments:
        response += "💳 *Платежи:*\n"
        for payment in payments:
            response += f"  ├ 💰 {payment.amount}₽ | {payment.payment_date.strftime('%d.%m.%Y')} | {payment.status}\n"

    return response.strip()


@db_session
def clear_user_data(telegram_id=802171486):
    user = User.get(telegram_id=telegram_id)
    if user:
        Subscription.select(lambda s: s.user == user).delete(bulk=True)
        Payment.select(lambda p: p.user == user).delete(bulk=True)
        user.delete()
        print(f"✅ Данные пользователя {telegram_id} полностью удалены.")
        return f"✅ Данные пользователя {telegram_id} полностью удалены."
    else:
        print(f"⚠️ Пользователь {telegram_id} не найден.")
