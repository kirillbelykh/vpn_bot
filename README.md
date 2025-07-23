# 🤖 Telegram VPN Бот

## 📌 Описание / Description

### 🇷🇺 Русский
- Генерирует уникальные ключи доступа через Outline API
- Управляет подписками и их сроками
- Обрабатывает оплаты через ЮKassa
- Хранит все данные в базе PostgreSQL
- Имеет реферальную программу
- Встроенный планировщик проверяет окончание подписок и отключает их
- Умеет отправлять инструкции по подключению
- Полностью автоматизирован и прост в использовании

### 🇬🇧 English
- Generates unique access keys using Outline API
- Tracks subscriptions and expiration dates
- Handles payments via YooKassa
- Stores data in PostgreSQL
- Includes a referral program
- Has a built-in scheduler to manage expired subscriptions
- Sends automatic VPN setup instructions
- Fully automated and easy to use

## 🛠️ Стек технологий / Tech Stack
- Python 3
- FastAPI
- aiogram3 (Telegram bot framework)
- PostgreSQL
- Pony ORM
- Outline API
- YooKassa 
- APScheduler (планировщик задач)
- Linux VPS + nginx

## ⚙️ Требования для запуска / Setup Requirements
🇷🇺 Русский
- Установите Outline Manager
Поддерживаются Windows, macOS и Linux.
- Создайте сервер в Outline Manager
В процессе создания будет сгенерирована команда установки сервера.
Скопируйте её и вставьте в терминал на вашем VPS.
- Создайте Telegram-бота через @BotFather
	•	Отправьте команду /start
	•	Затем /newbot
	•	Введите название и юзернейм (например: MyVpnBot)
	•	Скопируйте токен, который выдаст BotFather — он нужен для .env
- Зарегистрируйтесь в YooKassa
Получите идентификатор магазина (Shop ID) и секретный ключ.
- Заполните файл .env на основе .env.example
- Установите зависимости и запустите бота:
  ```bash
  pip install -r requirements.txt
  python3 bot.py
  ```

🇬🇧 English
- Install Outline Manager
Available for Windows, macOS, and Linux.
- Create a server via Outline Manager
It will generate an installation command.
Copy it and run it in the terminal on your VPS.
- Create a Telegram bot using @BotFather
	•	Send /start
	•	Then /newbot
	•	Enter a name and username (e.g. MyVpnBot)
	•	Copy the token — you’ll need it for the .env file
- Register on YooKassa
Get your Shop ID and Secret Key.
- Fill in the .env file using .env.example as a reference
- Install dependencies and run the bot:
   ```bash
  pip install -r requirements.txt
  python3 bot.py
   ```
