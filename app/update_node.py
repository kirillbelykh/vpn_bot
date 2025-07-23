import asyncio
import aiohttp
from logger import logger
from pony.orm import db_session, commit
from database import User

# Настройки серверов
OLD_SERVER = ''
OLD_API = ''

NEW_SERVER = ''
NEW_API = ''

# Ограничение количества одновременных запросов
SEMAPHORE_LIMIT = 10  # Количество одновременных запросов к API
semaphore = asyncio.Semaphore(SEMAPHORE_LIMIT)


@db_session
def get_users_to_update():
    """Генератор пользователей, подключенных к старому серверу (по одному за раз)."""
    for user in User.select().filter(lambda u: u.host == OLD_SERVER):
        yield user


async def delete_old_vpn_key(user):
    """Удаляет старый VPN-ключ пользователя на старом сервере."""
    headers = {"Content-Type": "application/json"}
    async with semaphore, aiohttp.ClientSession() as session:
        try:
            async with session.delete(f"{OLD_API}{user.key_id}", headers=headers, ssl=False) as response:
                if response.status == 204:
                    logger.info(f"✅ Ключ для пользователя {user.telegram_id} удален.")
                else:
                    logger.error(f"❌ Не удалось удалить ключ {user.key_id} (пользователь {user.telegram_id}). Статус: {response.status}")
        except Exception as e:
            logger.error(f"❌ Ошибка удаления ключа для пользователя {user.telegram_id}: {e}")


async def request_access_key(user_id: int) -> dict:
    """Отправляет POST-запрос на новый сервер Outline и возвращает данные подключения."""
    headers = {"Content-Type": "application/json"}
    payload = {"name": str(user_id)}  # Telegram ID в качестве имени ключа

    async with semaphore, aiohttp.ClientSession() as session:
        try:
            async with session.post(NEW_API, headers=headers, json=payload, ssl=False) as response:
                response.raise_for_status()  # Проверяем HTTP-статус ответа

                data = await response.json()  # Декодируем JSON-ответ
                if not data or "accessUrl" not in data:
                    logger.error(f"❌ Некорректный ответ сервера Outline для пользователя {user_id}")
                    return None

                return {
                    "access_key": data["accessUrl"],
                    "key_id": data["id"],
                    "server_port": data["port"],
                    "method": data["method"],
                    "password": data["password"]
                }

        except aiohttp.ClientResponseError as e:
            logger.error(f"❌ Ошибка HTTP {e.status}: {e.message} для пользователя {user_id}")
        except aiohttp.ClientError as e:
            logger.error(f"❌ Ошибка при запросе к серверу Outline: {e}")
        except Exception as e:
            logger.error(f"❌ Неизвестная ошибка при генерации ключа: {e}")

    return None  # Если что-то пошло не так, возвращаем None


@db_session
def update_user_data(user, ss_data: dict):
    """Обновляет данные пользователя в БД с новым VPN-ключом."""
    try:
        user.host = NEW_SERVER
        user.server_port = ss_data["server_port"]
        user.password = ss_data["password"]
        user.method = ss_data["method"]
        user.key_id = ss_data["key_id"]
        user.access_key = ss_data["access_key"]
        commit()
        logger.info(f"✅ Данные пользователя {user.telegram_id} обновлены на новый сервер.")
    except Exception as e:
        logger.error(f"❌ Ошибка обновления пользователя {user.telegram_id}: {e}")


async def migrate_users_to_new_server():
    """Основная функция для удаления старых ключей и генерации новых."""
    users = get_users_to_update()  # Используем генератор напрямую
    processed_users = 0  # Счетчик обработанных пользователей

    async for user in users:
        # Удаляем старый ключ
        await delete_old_vpn_key(user)

        # Генерируем новый ключ
        new_key_data = await request_access_key(user.telegram_id)
        if new_key_data:
            update_user_data(user, new_key_data)
            processed_users += 1
        else:
            logger.error(f"❌ Не удалось сгенерировать новый ключ для {user.telegram_id}")

    logger.info(f"✅ Перенос завершен. Обработано {processed_users} пользователей.")


if __name__ == "__main__":
    asyncio.run(migrate_users_to_new_server())