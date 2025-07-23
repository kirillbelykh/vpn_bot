import asyncio
import os
import signal
from logger import logger
import locale
from payments import create_payment, get_payment_status
from datetime import datetime, timedelta
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F, Router
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton, CallbackQuery, Message
from aiogram.types.input_file import FSInputFile
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from pony.orm import db_session, commit, count
from database import User, Subscription, Payment, get_all_data, get_user_data, clear_user_data
from keygen import generate_vpn_key, delete_vpn_key, activate_trial
from info import welcome_text, info_about_vpn, instruction
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from servers import load_servers_from_file, has_free_slots, update_current_devices_in_hosts
from collections import defaultdict

scheduler = AsyncIOScheduler()

locale.setlocale(locale.LC_TIME, 'ru_RU.UTF-8')

load_dotenv()
TOKEN = os.getenv('TOKEN')

# Making bot
bot = Bot(token=TOKEN)
dp = Dispatcher()
# Router
router = Router()
dp.include_router(router)

# Start menu
@router.message(Command("menu"))
async def show_main_menu(message: Message):
    main_menu = await main_menu_keyboard()
    await message.answer(welcome_text, reply_markup=main_menu)

# Start menu
async def main_menu_keyboard():
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="💳 Оплата", callback_data="payment"),
        InlineKeyboardButton(text="📜 Инструкция", callback_data="guide")
    )
    builder.row(
        InlineKeyboardButton(text="🎁 Реферал", callback_data="referral"),
        InlineKeyboardButton(text="ℹ️ Информация", callback_data="info")
    )
    builder.row(
        InlineKeyboardButton(text="🔧 Поддержка", callback_data="support")
    )
    builder.row(
        InlineKeyboardButton(text="🔗Скачать Outline", callback_data="outline"),
    )
    return builder.adjust(2, 2, 2).as_markup()

async def reply_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="🔑 Мой ключ"), 
                KeyboardButton(text="📊 Статус подписки"), 
                KeyboardButton(text="Пробный ключ")
            ]
        ],
        resize_keyboard=True  # Делает клавиатуру адаптивной по размеру
    )
@router.message(F.text == "Пробный ключ")
@db_session
async def process_trial_key(message: Message):
    user_id = message.from_user.id
    user = User.get(telegram_id=user_id)
    
    # Если пользователя нет в базе данных
    if not user:
        await bot.send_message(user_id, "Для начала нажмите команду /start")
        return
    
    # Если у пользователя активная подписка
    if user.subscription_end and user.subscription_end > datetime.now():
        await bot.send_message(user_id, "Вы уже активировали подписку, VPN работает.")
        return

    if user.subscription_end and user.subscription_end <= datetime.now():
        await bot.send_message(user_id, "Вы уже приобретали подписку. Пробный ключ недоступен")
        return
    # Если пользователь уже использовал пробный ключ
    if user.trial_used:
        await bot.send_message(user_id, "Вы уже использовали пробный ключ. Оформите подписку для дальнейшего доступа.")
        return
    
    # Если пользователь еще не использовал пробный ключ и подписка не активна
    result = await activate_trial(user_id)
    
    if result:
        await bot.send_message(user_id, "Пробный доступ активирован на 3 дня!\nТапните, чтобы скопировать Ваш VPN-ключ:")
        await message.answer(f"`{result}`", parse_mode="MarkdownV2")
    else:
        logger.error("Ошибка активации пробного ключа.")
        await bot.send_message(user_id, "Произошла ошибка при активации пробного ключа.")

# Back button
@router.callback_query(F.data == "back_to_main")
async def back_to_main_menu(callback: CallbackQuery):
    main_menu = await main_menu_keyboard()
    await callback.message.edit_text(welcome_text, reply_markup=main_menu)

# Start command 
@router.message(Command("start"))
@db_session
async def welcome_message(message: Message):
    logger.info(f"Бот работает... {message.chat.username}")
    # Get ref code
    ref_code = message.text.split()[-1] if len(message.text.split()) > 1 else None
    username = message.from_user.username
    user = await create_user_if_not_exists(message.chat.id, username, ref_code)

    # Append ref code
    if ref_code:
        inviter = User.get(referral_code=ref_code)
        if inviter:
            user.referred_by = str(inviter.telegram_id)  # Сохраняем пригласившего
    commit()
    main_menu = await main_menu_keyboard()
    # Welcome text + buttons
    reply_kb = await reply_keyboard()
    await message.answer(welcome_text, reply_markup=main_menu)
    await message.answer("Выберите действие ⬆️⬆️⬆️", reply_markup=reply_kb)

# Packet choice
async def payment_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="1 месяц - 149₽", callback_data="1_month")],
        [InlineKeyboardButton(text="3 месяца - 399₽", callback_data="3_months")],
        [InlineKeyboardButton(text="6 месяцев - 799₽", callback_data="6_months")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main")]
    ])

# Handling payment button
@router.callback_query(F.data == "payment")
async def show_payment_menu(callback: CallbackQuery):
    pay_menu = await payment_menu()
    await callback.message.edit_text("💰 Выберите тарифный план:", reply_markup=pay_menu)

@router.callback_query(F.data.in_(["1_month", "3_months", "6_months"]))
async def handle_subscription(callback: CallbackQuery):
    """Обрабатывает нажатие на кнопку подписки и передаёт управление в `process_subscription`."""
    await callback.answer()
    await process_subscription(callback)

async def process_subscription(callback: CallbackQuery):
    """Запускает процесс подписки и создаёт платёжную ссылку."""
    user_id = callback.from_user.id
    await callback.message.edit_reply_markup(reply_markup=None)

    # Выбираем цену и дни по колбэку
    subscription_options = {
        "1_month": (149, 30),
        "3_months": (399, 90),
        "6_months": (799, 182),
    }
    amount, days = subscription_options.get(callback.data, (None, None))
    
    if not amount or not days:
        await callback.message.answer("Ошибка при выборе подписки.")
        return

    with db_session:
        user = User.get(telegram_id=user_id)
        if not user or not user.started:
            await callback.message.answer("Вы должны сначала нажать /start, чтобы начать использовать бота.")
            return

    # Проверяем наличие мест на сервере
    servers = await load_servers_from_file('hosts.json')
    if not await has_free_slots(servers):
        await callback.message.answer("❌ Нет свободных мест на серверах. Напишите в поддержку.")
        return

    # Генерируем платёжную ссылку
    payment_url, payment_id = await generate_payment_link(user_id, amount, days)
    if not payment_url or not payment_id:
        await callback.message.answer("Ошибка при создании платежа. Попробуйте снова.")
        return

    # Отправляем платёжное сообщение
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Перейти к оплате 💳", url=payment_url)],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="payment")]
    ])
    payment_message = await callback.message.edit_text("Пожалуйста, перейдите по ссылке для оплаты:", reply_markup=markup)

    # Проверяем статус оплаты
    await check_payment_status(user_id, payment_id, days, amount, payment_message.message_id)
    
async def generate_payment_link(user_id: int, amount: int, days: int):
    """Создаёт платёжную ссылку и возвращает URL и ID платежа."""
    try:
        payment_url, payment_id = await create_payment(amount, f"Подписка на {days} дней", user_id)
        if payment_url and payment_id:
            logger.info(f"✅ Платёжная ссылка создана: {payment_url}")
            return payment_url, payment_id
        else:
            logger.error("❌ Ошибка при генерации платежа!")
            return None, None
    except Exception as e:
        logger.error(f"🚨 Ошибка при создании платежа: {e}")
        return None, None

async def check_payment_status(user_id, payment_id, days, amount, payment_message, timeout=600, check_interval=10):
    start_time = datetime.now()
    while True:
        try:
            status = await get_payment_status(payment_id)
            if status == "succeeded":
                with db_session:
                    user = User.get(telegram_id=user_id)
                    if user:
                        logger.info("Заносим данные в БД...")
                        await bot.delete_message(user_id, payment_message)
                        # Получаем текущую активную подписку
                        active_subscription = Subscription.get(user=user, status="Active")

                        # Если подписка активна, продлеваем её
                        if active_subscription and active_subscription.end_date > datetime.now():
                            logger.info("Подписка активна, продлеваем её...")
                            active_subscription.end_date += timedelta(days=days)
                            user.subscription_end = active_subscription.end_date
                            is_new_subscription = False
                        elif active_subscription and active_subscription.end_date <= datetime.now():
                            logger.info("Продлеваем завершенную подписку")
                            active_subscription.end_date += timedelta(days=days)
                            user.subscription_end = active_subscription.end_date
                            is_new_subscription = False
                        else:
                            # Если подписки нет или она закончилась, создаём новую
                            logger.info("Создаю новую подписку")
                            now = datetime.now()
                            user.subscription_end = now + timedelta(days=days)  # Корректная дата окончания
                            logger.info(f"Дата окончания подписки: {user.subscription_end}")
                            active_subscription = Subscription(
                                user=user,
                                start_date=now,
                                end_date=user.subscription_end,
                                amount=amount,
                                status="Active",
                            )
                            is_new_subscription = True

                        # Записываем платеж
                        payment = Payment(
                            id=payment_id,
                            user=user,
                            amount=amount,
                            payment_date=datetime.now(),
                            status=status
                        )

                        if payment.id:
                            user.last_payment_id = str(payment.id)
                            logger.info("Платеж был занесен в БД")
                            
                        commit()

                        formatted_date = user.subscription_end.strftime("%d %B %Y")

                        # Генерация нового ключа, если это новая подписка или ключ был удалён
                        if is_new_subscription:
                            logger.info("Генерируем новый VPN-ключ...")
                            if user.trial_end_date and user.trial_end_date > datetime.now():
                                    user.trial_end_date = datetime.now()
                                    logger.info(f"Удаляем пробный ключ {user.key_id}")
                                    await delete_vpn_key(user.key_id)
                                    
                            result = await generate_vpn_key(user_id)

                            if result:
                                user.trial_used = True
                                logger.info("Сгенерировал новый ключ")
                                dynamic_key = result
                                # Отправляем сообщение с ключом в формате кода
                                await bot.send_message(user_id, "✅ Оплата подтверждена! Тапните, чтобы скопировать Ваш VPN-ключ:")
                                await bot.send_message(user_id, text=f"`{dynamic_key}`", parse_mode="MarkdownV2")
                            else:
                                logger.error("Ошибка: generate_vpn_key() вернул None!")
                                await bot.send_message(user_id, "⚠️ Ошибка генерации VPN-ключа. Напишите в поддержку @vpnstalker.")
                        elif not user.access_key:
                            logger.info("Генерирую ключ после продления закончившейся подписки")
                            result = await generate_vpn_key(user_id)
                            if result:
                                dynamic_key = result
                                await bot.send_message(user_id, "✅ Оплата подтверждена! Ваш VPN-ключ активен!")
                        else:
                            await bot.send_message(user_id, f"📅 Ваша подписка продлена! Теперь она активна до {formatted_date}\nПереходите в Outline и подключайтесь!")

                        break
            
            elapsed_time = (datetime.now() - start_time).total_seconds()
            if elapsed_time > timeout:
                await bot.send_message(user_id, "⏳ Время на оплату истекло. Попробуйте снова.")

            await asyncio.sleep(check_interval)
            
        except Exception as e:
            logger.error(f"Ошибка при проверке статуса платежа {payment_id}: {e}")
            await bot.send_message(user_id, "⚠️ Произошла ошибка при проверке платежа. Попробуйте позже.")
            break

async def check_subscriptions():
    try:
        server_usage = defaultdict(int)  # Храним число активных пользователей на каждом сервере

        with db_session:
            for user in User.select():  # Используем генератор, не загружаем всех в память
                logger.info(f"🔍 Проверяю подписку пользователя {user.telegram_id}...")

                # 1️⃣ Проверяем пробную подписку
                if user.trial_used and user.trial_end_date and not user.subscription_end:
                    trial_hours_left = (user.trial_end_date - datetime.now()).total_seconds() / 3600  

                    if trial_hours_left <= 0:
                        logger.info("Пробная подписка использована и закончилась")

                        if user.key_id:
                            delete_key = await delete_vpn_key(user.key_id)

                            with db_session:
                                u = User.get(telegram_id=user.telegram_id)
                                if u:
                                    u.key_id = None  # Очищаем VPN-ключ
                                    commit()

                            if delete_key:
                                logger.info(f"✅ Пробный ключ пользователя {user.telegram_id} был удален.")
                                await bot.send_message(
                                    user.telegram_id,
                                    "⏳ Пробный ключ деактивирован.\nОформите подписку, чтобы продолжить пользоваться VPN."
                                )
                            else:
                                logger.warning(f"⚠ Ошибка удаления пробного ключа пользователя {user.telegram_id}.")

                # 2️⃣ Проверяем обычную подписку
                if user.subscription_end and user.key_id:
                    sub_hours_left = (user.subscription_end - datetime.now()).total_seconds() / 3600  

                    if sub_hours_left <= 0:
                        delete_key = await delete_vpn_key(user.key_id)

                        with db_session:
                            u = User.get(telegram_id=user.telegram_id)
                            if u:
                                u.key_id = None  # Очищаем VPN-ключ
                                commit()

                        if delete_key:
                            logger.info(f"✅ Подписка пользователя {user.telegram_id} истекла, ключ удалён.")
                            await bot.send_message(
                                user.telegram_id,
                                "❌ Срок вашей подписки истёк.\nПродлите её, чтобы снова пользоваться VPN."
                            )
                        else:
                            logger.warning(f"⚠ Ошибка удаления ключа пользователя {user.telegram_id}.")

                    elif 0 < sub_hours_left <= 72:
                        await bot.send_message(
                            user.telegram_id,
                            f"⚠ Ваша подписка истекает через {int(sub_hours_left // 24)} дня "
                            f"({user.subscription_end.strftime('%d %B %Y')}).\nОплатите заранее, и дни прибавятся к остатку!"
                        )

                # 3️⃣ Учитываем активные подключения
                if user.host:
                    server_usage[user.host] += 1

        logger.info("✅ Проверка подписок завершена")

    except Exception as e:
        logger.error(f"🚨 Ошибка проверки подписок: {e}")

    await update_current_devices_in_hosts(server_usage)  # Обновляем активные устройства

async def send_notification():
    try:
        with db_session:
            # Фильтрация на уровне базы данных
            users = User.select(lambda u: not u.trial_used and not u.subscription_end)
            
            for user in users:
                await bot.send_message(
                    user.telegram_id, 
                    "Еще не попробовали? Нажмите кнопку **Пробный ключ** и испытайте\nскорость нашего VPN за 24 часа!", 
                    parse_mode="MarkdownV2"
                )
                
    except Exception as e:
        logger.error(f"Произошла ошибка оповещений новых юзеров: {e}")
        
def get_next_20():
    now = datetime.now()
    today_20 = now.replace(hour=20, minute=0, second=0, microsecond=0)
    return today_20 if now <= today_20 else today_20 + timedelta(days=1)
        

# Scheduler
def start_scheduler():
    scheduler.add_job(check_subscriptions, IntervalTrigger(hours=3), replace_existing=True)
    scheduler.add_job(send_notification, IntervalTrigger(days=2, start_date=get_next_20()), id="send_notification_job", replace_existing=True)
    logger.info("✅ Планировщик задач запущен.")

def stop_scheduler():
    scheduler.shutdown()
    logger.info("❌ Планировщик остановлен.")

async def create_user_if_not_exists(telegram_id, username, ref_code=None):
    user = User.get(telegram_id=telegram_id)
    if not user:
        logger.info(f"Создаю нового пользователя {username}")
        inviter = User.get(referral_code=ref_code) if ref_code else None

        if ref_code and not inviter:
            logger.warning(f"Не удалось найти инвайтера с реферальным кодом {ref_code}.")

        # Create user
        new_user = User(
            telegram_id=telegram_id,
            username=username,
            started=True,
            referral_code=f"ref{telegram_id}",
            referred_by=inviter if isinstance(inviter, User) else None,
            created_at=datetime.now()
        )

        return new_user

    logger.info(f"Пользователь {username} уже существует.")
    return user


@router.message(F.text == "🔑 Мой ключ")
async def show_my_keys(message: Message):
    user_id = message.from_user.id
    with db_session:
        user = User.get(telegram_id=user_id)
        if user:
            # Проверяем, что subscription_end и trial_end_date не равны None
            if user.dynamic_key:
                if user.subscription_end and user.subscription_end > datetime.now():
                    key = user.dynamic_key
                    # Отправляем ключ как код
                    await message.answer("Тапните, чтобы скопировать")
                    await message.answer(f"`{key}`", parse_mode="MarkdownV2")
                elif user.trial_end_date and user.trial_end_date > datetime.now():
                    key = user.dynamic_key
                    # Отправляем ключ как код
                    await message.answer("Тапните, чтобы скопировать")
                    await message.answer(f"`{key}`", parse_mode="MarkdownV2")
                else:
                    await message.answer("У вас нет активных ключей или подписка истекла.")
            else:
                await message.answer("У вас нет VPN-ключа. Для подключения оформите подписку или пробный ключ")
        else:
            await message.answer("Пользователь не найден.")

@router.callback_query(F.data == "support")
async def support_menu(callback: CallbackQuery):
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main"))

    await callback.message.edit_text("📞 Мы всегда на связи: @airvpnsupport", reply_markup=builder.as_markup())


# Check invite programm
async def process_successful_payment(user_id: int):
    user = User.get(telegram_id=user_id)
    if user and user.referred_by:
        inviter = user.referred_by  # Это уже объект User
        if inviter and not inviter.referral_bonus_active:
            logger.info(f"Есть инвайтер! {inviter.username}")

            if inviter.subscription_end and inviter.subscription_end > datetime.now():
                logger.info("У инвайтера есть активная подписка!")

                last_subscription = Subscription.get(user=inviter, end_date=inviter.subscription_end)
                if last_subscription:
                    last_subscription.end_date += timedelta(days=30)
                    inviter.subscription_end = last_subscription.end_date
                else:
                    logger.warning("Не удалось найти активную подписку для инвайтера.")

                inviter.referral_bonus_active = True
                commit()

                logger.info(f"Пользователь {inviter.telegram_id} получил 1 месяц бесплатно!")
                await bot.send_message(inviter.telegram_id, "🎉 Вам начислен бонус: +1 месяц к вашей подписке!")

            else:
                logger.info(f"Инвайтер {inviter.telegram_id} не имеет активной подписки, бонус не начислен.")
                await bot.send_message(inviter.telegram_id, "❌ Ваш бонус не был начислен, так как у вас нет активной подписки.")


@router.callback_query(F.data == "info")
async def info(callback: CallbackQuery):
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main"))
    await callback.message.edit_text(info_about_vpn, reply_markup=builder.as_markup())

@router.callback_query(F.data == "referral")
@db_session
async def refferal_link(callback: CallbackQuery):
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_main"))
    user = User.get(telegram_id=callback.message.chat.id)
    if user:
        ref_link = f"https://t.me/@vpn_airbot?start={user.referral_code}"
        await callback.message.edit_text(f"Ваша реферральная ссылка: {ref_link}\nПосле оплаты приглашенного вы получите +1 месяц бесплатно", reply_markup=builder.as_markup())
    else:
        await callback.message.edit_text("Для начала нажмите команду /start")



@router.callback_query(F.data == "outline")
async def send_device_options(callback: CallbackQuery):
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="iOS", url="https://apps.apple.com/app/outline-app/id1356177741"),
        InlineKeyboardButton(text="Android", url="https://play.google.com/store/apps/details?id=org.outline.android.client")
    )
    builder.row(
        InlineKeyboardButton(text="PC (Windows)", url="https://getoutline.org/#download"),  # Ссылка для Windows
        InlineKeyboardButton(text="MacOS", url="https://getoutline.org/#download")  # Ссылка для MacOS
    )
    builder.row(
        InlineKeyboardButton(text="Назад", callback_data="back_to_main")  # Кнопка "Назад"
    )
    await callback.message.edit_text(
        "Выберите ваше устройство для скачивания приложения Outline:",
        reply_markup=builder.as_markup()
    )


# List of images
GUIDE_IMAGES = [
    './images/aaa.jpg',
    './images/abc.jpg',
    './images/bbb.jpg',
    './images/outline.jpg',
    './images/usekey.jpg',
]

# State of views
class ScreenshotState(StatesGroup):
    viewing = State()

@router.callback_query(F.data == "guide")
async def send_guide(callback: CallbackQuery):
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="📸 Подробнее", callback_data="send_screenshots"))
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="back_to_main"))
    builder.row(InlineKeyboardButton(text="🔗 Скачать Outline", callback_data="outline"))

    await callback.message.edit_text(instruction, reply_markup=builder.as_markup())


@router.callback_query(F.data == "send_screenshots")
async def start_screenshots(callback: CallbackQuery, state: FSMContext):
    if not GUIDE_IMAGES:
        await callback.message.answer("⚠ Скриншоты отсутствуют.")
        return

    await state.set_state(ScreenshotState.viewing)
    await state.update_data(index=0)
    
    await send_image(callback.message, 0, state)


async def send_image(message: Message, index: int, state: FSMContext):
    data = await state.get_data()

    if 0 <= index < len(GUIDE_IMAGES):
        image_path = GUIDE_IMAGES[index]

        if os.path.exists(image_path):
            media_file = FSInputFile(image_path)
            keyboard = await generate_pagination_keyboard(index)

            if "message_id" in data:
                await message.bot.edit_message_media(
                    media=types.InputMediaPhoto(media=media_file),
                    chat_id=message.chat.id,
                    message_id=data["message_id"],
                    reply_markup=keyboard
                )
            else:
                sent_message = await message.answer_photo(media_file, reply_markup=keyboard)
                await state.update_data(message_id=sent_message.message_id)
        else:
            await message.answer(f"❌ Изображение не найдено: {image_path}")

async def generate_pagination_keyboard(index: int) -> InlineKeyboardMarkup:
    buttons = []

    if index > 0:
        buttons.append(InlineKeyboardButton(text="⬅ Назад", callback_data=f"screenshot_{index-1}"))

    if index < len(GUIDE_IMAGES) - 1:
        buttons.append(InlineKeyboardButton(text="Далее ➡", callback_data=f"screenshot_{index+1}"))
    else:
        buttons.append(InlineKeyboardButton(text="✅ Готово", callback_data="done"))

    return InlineKeyboardMarkup(inline_keyboard=[buttons])

# Back and forward buttons
@router.callback_query(F.data.startswith("screenshot_"))
async def navigate_screenshots(callback: CallbackQuery, state: FSMContext):
    index = int(callback.data.split("_")[1])
    await send_image(callback.message, index, state)
    await state.update_data(index=index)


@router.callback_query(F.data == "done")
async def close_screenshots(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()

    if "message_id" in data:
        try:
            await callback.message.delete()
        except Exception as e:
            logger.error(f"Ошибка при удалении сообщений: {e}")

    await state.clear()

    await callback.answer("📌 Просмотр завершен!")


@router.message(F.text == "📊 Статус подписки")
@db_session
async def handle_status(message: Message):
    user = User.get(telegram_id=message.chat.id)

    if not user:
        await message.answer("❌ Вы не зарегистрированы в системе.")
        return

    # Дата начала подписки (берем первую подписку пользователя)
    first_subscription = user.subscriptions.order_by(lambda s: s.start_date).first()

    # Дата окончания подписки
    subscription_end = user.subscription_end

    # Количество приглашенных пользователей
    invited_count = count(u for u in User if u.referred_by == user)  # ✅ Теперь count импортирован


    if subscription_end and subscription_end > datetime.now():
        status = "🟩 Активна"
        sub_end_text = subscription_end.strftime("%d %B %Y")
        sub_start_text = first_subscription.start_date.strftime("%d %B %Y") if first_subscription else "Неизвестно"
        
        text = (
            f"📊 <b>Статус подписки</b>\n\n"
            f"🟢 Статус: {status}\n"
            f"📅 Начало подписки: {sub_start_text}\n"
            f"📅 Окончание подписки: {sub_end_text}\n"
            f"👥 Приглашено пользователей: {invited_count}\n"
        )
        await message.answer(text, parse_mode="HTML")

    else:
        await message.answer("❌ У вас нет активной подписки.")



AUTHORIZED_USER_ID = int(os.getenv("AUTHORIZED_USER_ID"))
@router.message(Command('database'))
async def handle_get_data(message: Message):
    if message.chat.id == AUTHORIZED_USER_ID:
        command_parts = message.text.split()
        if len(command_parts) == 1:
            data = await asyncio.to_thread(get_all_data) 
            await message.answer(data)
        elif len(command_parts) == 2:
           
            username = command_parts[1]
            data = await asyncio.to_thread(get_user_data, username)
            if data:
                await message.answer(data)
            else:
                await message.answer(f"Пользователь с именем '{username}' не найден.")
        else:
            await message.answer("Некорректный формат команды. Используйте /database или /database <username>.")


@router.message(Command("get_key"))
@db_session 
async def handle_get_key(message: Message):
    if message.chat.id == AUTHORIZED_USER_ID:
        try:
            command_parts = message.text.split()
            if len(command_parts) != 2:
                await message.reply("Пожалуйста, укажите Telegram ID пользователя. Пример: /get_key 123456789")
                return

            username = str(command_parts[1])

            user = User.get(username=username)

            if user:
                if user.access_key:
                    await message.reply(
                        f"VPN-ключ пользователя {username}:\n"
                        f"Статический:{user.access_key}\n"
                        f"Динамический:{user.dynamic_key}\n"
                        f"ID ключа: {user.key_id}",
                    )
                else:
                    await message.reply(f"У пользователя {username} отсутствует VPN-ключ.")
            else:
                await message.reply(f"Пользователь с Telegram ID {username} не найден в базе данных.")
        except Exception as e:
            await message.reply(f"Произошла ошибка: {e}")
            raise


@router.message(Command("del"))
@db_session
async def restart(message: Message):
    if message.chat.id == AUTHORIZED_USER_ID:
        try:
            me = User.get(telegram_id=802171486)
            key_del = await delete_vpn_key(me.key_id)
            clear_data = await asyncio.to_thread(clear_user_data)
            await message.answer(f"{clear_data}\nРезультат удаления ключа: {key_del}")

        except Exception as e:
            await message.answer(f"Произошла ошибка {e}")

@router.message(Command("send_all"))
@db_session
async def send_all(message: Message):
    if message.chat.id == AUTHORIZED_USER_ID:
        command_parts = message.text.split(maxsplit=1)
        if len(command_parts) < 2:
            await message.reply("Пожалуйста, укажите текст сообщения. Пример: /send_all Привет, братья")
            return

        text = command_parts[1]
        failed_users = 0

        for user in User.select():  # Используем генератор, чтобы не загружать всех сразу
            try:
                await bot.send_message(user.telegram_id, text)
            except Exception as e:
                failed_users += 1
                logger.error(f"❌ Не удалось отправить сообщение пользователю {user.telegram_id}: {e}")

        await message.reply(f"✅ Рассылка завершена. Ошибок: {failed_users}")


async def main():
    try:
        start_scheduler()  # Запуск планировщика
        scheduler.start()
        await dp.start_polling(bot)  # Запуск бота
    except KeyboardInterrupt:
        logger.info("Бот остановлен вручную.")
    finally:
        stop_scheduler()  # Корректная остановка планировщика
def signal_handler(sig, frame):
    print('Завершаю работу...')
    # Здесь не нужно использовать asyncio.get_event_loop().stop(), так как мы используем async обработку
    asyncio.get_event_loop().stop()

# Обрабатываем сигнал завершения (Ctrl+C)
signal.signal(signal.SIGINT, signal_handler)

if __name__ == "__main__":
    # Запуск главной асинхронной функции
    asyncio.run(main())

