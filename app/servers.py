import json
from logger import logger
import aiofiles

HOSTS_FILE = "hosts.json"

async def load_servers_from_file(file_path):
    """Асинхронно загружает серверы из файла."""
    try:
        async with aiofiles.open(file_path, "r", encoding="utf-8") as file:
            contents = await file.read()
            data = json.loads(contents)
            if not isinstance(data, list):
                logger.error("Ошибка: данные в файле не являются списком.")
                return []
            return data
    except Exception as e:
        logger.error(f"Ошибка загрузки файла {file_path}: {e}")
        return []

async def save_servers_to_file(file_path, servers):
    """Асинхронно сохраняет серверы в файл."""
    try:
        async with aiofiles.open(file_path, "w", encoding="utf-8") as f:
            await f.write(json.dumps(servers, indent=4))
    except Exception as e:
        logger.error(f"Ошибка при сохранении серверов в файл {file_path}: {e}")

def get_available_server(servers):
    """Возвращает доступный сервер"""
    for server in servers:
        if server['current_devices'] < server['max_devices']:
            return server
    return None

async def has_free_slots(servers):
    return any(server["current_devices"] < server["max_devices"] for server in servers)


async def add_device_to_host(host, change):
    """Обновляет текущее количество подключенных устройств на сервере асинхронно."""
    try:
        async with aiofiles.open(HOSTS_FILE, "r", encoding="utf-8") as file:
            contents = await file.read()
            hosts = json.loads(contents)

        for server in hosts:
            if server["host"] == host:
                server["current_devices"] = max(0, server["current_devices"] + change)
                break
        else:
            return False  # Сервер не найден

        async with aiofiles.open(HOSTS_FILE, "w", encoding="utf-8") as file:
            await file.write(json.dumps(hosts, indent=4, ensure_ascii=False))

        return True

    except Exception as e:
        logger.error(f"🚨 Ошибка обновления current_devices для {host}: {e}")
        return False
    
    
async def update_current_devices_in_hosts(server_usage):
    """Обновляет кол-во устройств на сервере"""
    try:
        async with aiofiles.open("hosts.json", mode="r") as file:
            content = await file.read()
            hosts = json.loads(content)

        # Обновляем количество подключенных пользователей для конкретного сервера
        for server in hosts:
            host_name = server["host"]
            if host_name in server_usage:
                server["current_devices"] = server_usage[host_name]

        # Записываем обновленные данные в hosts.json
        async with aiofiles.open("hosts.json", mode="w") as file:
            await file.write(json.dumps(hosts, indent=4, ensure_ascii=False))

        for host, count in server_usage.items():
            logger.info(f"✅ Изменено кол-во устройств на {host}: {count}")

    except Exception as e:
        logger.error(f"❌ Ошибка при обновлении hosts.json: {e}")