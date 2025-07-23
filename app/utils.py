from pony.orm import db_session, commit
from database import User 
from datetime import datetime
from Crypto.Cipher import AES
import base64
import os
from dotenv import load_dotenv
from logger import logger

load_dotenv()

# Декодируем SECRET_KEY из .env
SECRET_KEY = base64.b64decode(os.getenv("SECRET_KEY"))
if len(SECRET_KEY) not in [16, 24, 32]:
    raise ValueError("Неверная длина SECRET_KEY! Должно быть 16, 24 или 32 байта.")

@db_session
def check_active_subscription(telegram_id: int) -> bool:
    """Проверка наличия активной подписки"""
    user = User.get(telegram_id=telegram_id)
    if user and user.subscription_end and user.subscription_end > datetime.now():
        return True
    return False

def pad(text: str) -> bytes:
    """Дополняем текст до кратного 16 размера (AES требует фиксированную длину блока)."""
    return text.encode() + b" " * (16 - len(text) % 16)

def encrypt_telegram_id(telegram_id: int) -> str:
    """Шифрует telegram_id и возвращает Base64 строку."""
    cipher = AES.new(SECRET_KEY, AES.MODE_ECB)
    encrypted = cipher.encrypt(pad(str(telegram_id)))
    return base64.urlsafe_b64encode(encrypted).decode()

def decrypt_telegram_id(encrypted_id: str) -> int:
    """Дешифрует Base64 строку обратно в telegram_id."""
    try:
        cipher = AES.new(SECRET_KEY, AES.MODE_ECB)
        decrypted = cipher.decrypt(base64.urlsafe_b64decode(encrypted_id)).strip()
        return int(decrypted.decode())
    except Exception as e:
        raise ValueError(f"Ошибка расшифровки ID: {e}")
    
async def update_user_data(user_id, ss_data, dynamic_key):
    """Обновляет данные пользователя в базе данных."""
    with db_session:
        user = User.get(telegram_id=user_id)
        if user:
            user.host = ss_data["server"]
            user.server_port = ss_data["server_port"]
            user.method = ss_data["method"]
            user.password = ss_data["password"]
            user.key_id = ss_data["key_id"]
            user.access_key = ss_data["access_key"]
            user.dynamic_key = dynamic_key
            commit()
        else:
            logger.error(f"Не найден пользователь {user_id} для обновления данных!")