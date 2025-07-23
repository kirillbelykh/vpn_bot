from logger import logger
import aiohttp
from pony.orm import db_session, commit, count 
from database import User
from servers import load_servers_from_file, save_servers_to_file, get_available_server, add_device_to_host
from datetime import datetime, timedelta
from utils import encrypt_telegram_id, update_user_data

HOSTS_FILE = "hosts.json"
CONN_NAME = "AirVPN"
DOMAIN = "e-airvpn.ru"


async def activate_trial(user_id) -> str:
    """Генерирует пробный ключ доступа"""
    logger.info(f"Запрос на активацию пробного доступа для пользователя с ID {user_id}")

    with db_session:
        user = User.get(telegram_id=user_id)

        if not user:
            logger.warning(f"Пользователь с ID {user_id} не найден в системе.")
            return "Вы не зарегистрированы в системе."

        # Проверяем, есть ли активная подписка
        if user.subscription_end and user.subscription_end > datetime.now():
            return "Вы уже приобрели полноценную подписку. Пробный ключ недоступен."

        # Проверяем, использовал ли пользователь пробный ключ
        if user.trial_used:
            return "Вы уже использовали пробный ключ. Оформите подписку для дальнейшего доступа."

        # Генерируем VPN-ключ
        dynamic_key = await generate_vpn_key(user_id)
        if not dynamic_key:
            return "Ошибка при выдаче пробного ключа.\nПожалуйста, обратитесь в поддержку @airvpnsupport."

        # Первым 10 пользователям даём 7 дней, остальным 24 часа
        end_date = datetime.now() + timedelta(days=3)

        # Обновляем данные пользователя
        user.trial_end_date = end_date
        user.trial_used = True

        commit()
        return dynamic_key
    
async def generate_dynamic_key(telegram_id: int) -> str:
    """Генерирует динамический ключ доступа для пользователя с шифрованным telegram_id."""
    try:
        # Шифруем telegram_id
        encrypted_id = encrypt_telegram_id(telegram_id)
        # Формируем динамический ключ
        dynamic_key = f"ssconf://{DOMAIN}/conf/{encrypted_id}#{CONN_NAME}"
        return dynamic_key

    except Exception as e:
        logger.error(f"Ошибка при генерации динамического ключа: {e}")
        return None


async def request_access_key(api_url, headers, payload) -> dict:
    """Отправляет POST-запрос на сервер Outline и возвращает данные подключения."""
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(api_url, headers=headers, json=payload, ssl=False) as response:
                response.raise_for_status() 

                data = await response.json() 
                if data:
                    logger.info("Есть ответ сервера")

                access_key = data.get("accessUrl")
                key_id = data.get("id")
                server_port = data.get("port")
                method = data.get("method")
                password = data.get("password")

                if not access_key or not key_id:
                    return None

                return {
                    "access_key": access_key,
                    "key_id": key_id,
                    "server_port": server_port,
                    "method": method,
                    "password": password
                }

        except aiohttp.ClientResponseError as e:
            logger.error(f"Ошибка HTTP {e.status}: {e.message}")
        except aiohttp.ClientError as e:
            logger.error(f"Ошибка при отправке запроса: {e}")
        except Exception as e:
            logger.error(f"Неизвестная ошибка: {e}")

    return None  # Если что-то пошло не так, возвращаем None

async def generate_vpn_key(user_id):
    """Возвращает динамический ключ через бота"""
    try:
        logger.info(f"Начало генерации VPN-ключа для пользователя {user_id}")

        # Получение сервера и локации
        servers = await load_servers_from_file('hosts.json')
        server = get_available_server(servers)
        if not server:
            logger.warning(f"Не удалось найти доступный сервер для пользователя {user_id}")
            return None

        api_url = f"{server['api_url']}/access-keys"
        headers = {"Content-Type": "application/json"}
        payload = {"name": str(user_id)}

        access_data = await request_access_key(api_url, headers, payload)

        if not access_data:
            logger.error(f"Ошибка: сервер {server['host']} не вернул данные доступа для {user_id}")
            return None

        # Преобразуем данные в нужные типы
        ss_data = {
            "server": str(server.get("host", "UNKNOWN_SERVER")),
            "server_port": str(access_data.get("server_port", "")),
            "password": str(access_data.get("password", "")),
            "method": str(access_data.get("method", "")),
            "key_id": int(access_data.get("key_id", 0)),
            "access_key": str(access_data.get("access_key", ""))
        }

        if not all(ss_data.values()):
            logger.error(f"Ошибка: получены неполные данные подключения для {user_id}: {ss_data}")
            return None

        # Генерация динамического ключа
        dynamic_key = await generate_dynamic_key(user_id)

        # Обновление данных пользователя в БД
        await update_user_data(user_id, ss_data, dynamic_key)
        
        await add_device_to_host(server["host"], +1)  # 🟢 Увеличиваем подключенных пользователей
        return dynamic_key

    except aiohttp.ClientError as e:
        logger.error(f"Ошибка сети при запросе к Outline VPN для {user_id}: {e}")
        return None
    except Exception as e:
        logger.error(f"Непредвиденная ошибка при генерации ключа для {user_id}: {e}", exc_info=True)
        return None


async def delete_vpn_key(key_id):
    """Удаляем ключ доступа"""
    try:
        logger.info(f"Ищу сервер для удаления ключа с ID {key_id}...")

        with db_session:
            user = User.get(key_id=key_id)
            if not user:
                logger.error(f"Пользователь {user.telegram_id} не найден в базе данных.")
                return False

            vpn_key_id = user.key_id
            if not vpn_key_id:
                logger.error(f"У пользователя {user.telegram_id} нет связанного VPN-ключа.")
                return False

            host = user.host  
            if not host:
                logger.error(f"Для пользователя {user.telegram_id} не найден сервер для удаления ключа.")
                return False

        servers = await load_servers_from_file('hosts.json')
        if not servers:
            logger.info("Нет доступных серверов для удаления ключа.")
            return False

        server = next((s for s in servers if s['host'] == host), None)
        if not server:
            logger.error(f"Не удалось найти сервер с IP {host} в списке серверов.")
            return False

        api_url = f"{server['api_url']}/access-keys/{vpn_key_id}"
        headers = {"Content-Type": "application/json"}

        async with aiohttp.ClientSession() as session:
            try:
                logger.info(f"Отправка DELETE запроса на сервер Outline для удаления ключа {vpn_key_id} пользователя {user.telegram_id}...")
                async with session.delete(api_url, headers=headers, ssl=False) as response:
                    if response.status == 204:  
                        logger.info(f"Ключ {vpn_key_id} пользователя {user.telegram_id} успешно удален.")
                        
                        server['current_devices'] -= 1
                        await save_servers_to_file('hosts.json', servers)

                        with db_session:
                            # Получаем пользователя
                            user = User.get(key_id=key_id)
                            if user:
                                # Удаляем данные VPN-ключа, но не трогаем подписку
                                user.access_key = None
                                user.key_id = None
                                user.host = None
                                user.server_port = None
                                user.password = None
                                user.method = None

                                commit()

                        return True
                    else:
                        logger.error(f"Ошибка удаления ключа: {response.status} {await response.text()}")
            except aiohttp.ClientError as e:
                logger.error(f"Ошибка при отправке DELETE запроса: {e}")

    except Exception as e:
        logger.error(f"Общая ошибка: {e}")

    return False