from yookassa import Configuration, Payment
import uuid
from dotenv import load_dotenv
import os
from logger import logger
import asyncio


load_dotenv()

Configuration.account_id = os.getenv("TEST_SHOP_ID")  # Идентификатор магазина
Configuration.secret_key = os.getenv("TEST_SECRET_KEY")  # Секретный ключ

async def create_payment(amount, description, user_id):
    """Создаем платеж через Юкассу"""
    try:
        
        idempotence_key = str(uuid.uuid4())
      
        logger.info(f"Создаем платеж для {user_id}")
        payment = await asyncio.to_thread(Payment.create, {
            "amount": {
                "value": f"{amount:.2f}",  # Сумма с двумя знаками после запятой
                "currency": "RUB"
            },
            "confirmation": {
                "type": "redirect",
                "return_url": f"https://t.me/ishowspeedvpnbot?start={user_id}"
            },
            "capture": True,
            "description": description,
            "metadata": {
                "user_id": str(user_id)  # Добавляем ID пользователя
            }
        }, idempotence_key)
        
        logger.info("Возвращаю данные платежа...")
        return payment.confirmation.confirmation_url, payment.id  # URL для оплаты и ID платежа
    except Exception as e:
        logger.error(f"Ошибка при создании платежа: {e}")
        return None, None


logged_payments = {}

async def get_payment_status(payment_id):
    """Возвращаем статус платежа"""
    try:
        if payment_id not in logged_payments:
            logger.info(f"Проверяю статус платежа")
            logged_payments[payment_id] = True  # Отмечаем, что лог уже был выведен

        payment = await asyncio.to_thread(Payment.find_one, payment_id)
        
        if payment:
            if payment.status == 'succeeded':
                logger.info(f"Платеж успешно завершен.")
                return payment.status  # Return status ('pending', 'succeeded', 'canceled')
            return payment.status
            
        else:
            logger.warning(f"Платеж с ID {payment_id} не найден.")
            return None

    except Exception as e:
        logger.error(f"Ошибка при проверке статуса для платежа ID {payment_id}: {e}")
        return None
