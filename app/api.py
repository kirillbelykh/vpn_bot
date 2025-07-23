from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pony.orm import db_session
from database import User
from utils import check_active_subscription, decrypt_telegram_id
import logging
from dotenv import load_dotenv

load_dotenv()
# Создаём отдельный логгер для FastAPI
logger = logging.getLogger("fastapi_server")
logger.setLevel(logging.INFO)
# Создаём обработчик для записи в файл
file_handler = logging.FileHandler("api.log", encoding="utf-8")
formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
file_handler.setFormatter(formatter)
# Добавляем обработчик в логгер
logger.addHandler(file_handler)
# Отключаем дублирование в root logger
logger.propagate = False

app = FastAPI()

# Настраиваем CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],  
    allow_headers=["*"],  
)

PREFIX = "%13%03%03%3F"  # Префикс для маскировки

@app.get("/conf/{encrypted_id}")
@db_session
def get_connection_data(encrypted_id: str):
    """Обрабатывает GET-запрос для получения данных подключения."""
    try:
        telegram_id = decrypt_telegram_id(encrypted_id)
    except ValueError:
        logger.error(f"Ошибка декодирования encrypted_id: {encrypted_id}")
        raise HTTPException(status_code=400, detail="Некорректный encrypted_id")

    user = User.get(telegram_id=telegram_id)

    if not user:
        logger.error(f"Пользователь с telegram_id={telegram_id} не найден")
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    # Проверяем подписку
    if not check_active_subscription(telegram_id) and not user.started:
        logger.warning(f"Пользователь {telegram_id} пытается подключиться без активной подписки")
        raise HTTPException(status_code=403, detail="Подписка не активна или пробный ключ истек")

    # Формируем данные для подключения
    connection_data = {
        "server": user.host,
        "server_port": int(user.server_port),
        "password": user.password,
        "method": user.method,
        "prefix": PREFIX
    }

    return JSONResponse(content=connection_data, status_code=200)
