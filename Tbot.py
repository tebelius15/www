from telegram import (
    Update,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ConversationHandler,
    CallbackContext,
    CallbackQueryHandler
)
import re
import pymysql
import hashlib
import logging
import time
from datetime import datetime, timedelta

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Конфигурация
TOKEN = '7264575945:AAEb-20r_FrtVEVXK4aAIYnSCVjo-N3fedM'
WEBSITE_LINK = "https://web.tokalki-bar.com/"
ADMIN_CHAT_ID = 7909707902  # ID чата админа для техподдержки

# Deep links
DEEP_LINKS = {
    'balance': 'balance',
    'recovery': 'recovery',
    'support': 'support'
}

DB_CONFIG = {
    'host': 'baza-do-user-20329937-0.k.db.ondigitalocean.com',
    'port': 25060,
    'user': 'baza',
    'password': 'AVNS_ItveeVzcRcSMRCxyQiz',
    'db': 'T',
    'charset': 'utf8mb4',
    'cursorclass': pymysql.cursors.DictCursor
}

CHANNELS = [
    {"name": "Токалки.Бар", "url": "https://t.me/+vgST8DXydacyNzc0"},
    {"name": "TOKALKI", "url": "https://t.me/+5P6aHiY51wUzMmFk"},
    {"name": "Боди массаж Алматы 🔥", "url": "https://t.me/+zpOwD3l5OY02ZmZi"},
    {"name": "Массажистки Алматы", "url": "https://t.me/+bQTshkatsbAzODM0"},
]

# Состояния
PHONE_INPUT, NEW_PASSWORD, SUPPORT_MAIN_MENU, SUPPORT_INPUT, SUPPORT_ATTACHMENT, ASK_ANKETA, ASK_RECEIPT = range(7)

# Ограничения
MAX_TICKETS_PER_HOUR = 3
PASSWORD_CHANGE_COOLDOWN = 3600  # 1 час

# Кэши
password_change_cache = {}

def format_phone(phone):
    """Форматирует номер телефона в стандартный формат"""
    phone = re.sub(r'[^\d+]', '', phone)
    if phone.startswith('7') and len(phone) == 11:
        return f"+7 ({phone[1:4]}) {phone[4:7]} {phone[7:9]} {phone[9:11]}"
    elif phone.startswith('+7') and len(phone) == 12:
        return f"+7 ({phone[2:5]}) {phone[5:8]} {phone[8:10]} {phone[10:12]}"
    return phone

def hash_password(password):
    """Хеширует пароль в MD5"""
    return hashlib.md5(password.encode('utf-8')).hexdigest()

def check_user_in_db(phone):
    """Проверяет наличие пользователя в базе"""
    try:
        connection = pymysql.connect(**DB_CONFIG)
        with connection.cursor() as cursor:
            sql = "SELECT * FROM `b_user` WHERE `LOGIN` = %s"
            cursor.execute(sql, (phone,))
            return cursor.fetchone() is not None
    except Exception as e:
        logger.error(f"Ошибка БД: {e}")
        return False
    finally:
        if 'connection' in locals():
            connection.close()

def update_user_password(phone, new_password):
    """Обновляет пароль пользователя"""
    try:
        hashed_password = hash_password(new_password)
        connection = pymysql.connect(**DB_CONFIG)
        with connection.cursor() as cursor:
            sql = "UPDATE `b_user` SET `PASSWORD` = %s WHERE `LOGIN` = %s"
            cursor.execute(sql, (hashed_password, phone))
            connection.commit()
            return cursor.rowcount > 0
    except Exception as e:
        logger.error(f"Ошибка обновления: {e}")
        return False
    finally:
        if 'connection' in locals():
            connection.close()

def create_ticket(user_id, user_name, message):
    """Создает новое обращение в техподдержку"""
    try:
        connection = pymysql.connect(**DB_CONFIG)
        with connection.cursor() as cursor:
            sql = """
                INSERT INTO `support_tickets` 
                (`user_id`, `user_name`, `message`, `status`, `admin_message_id`) 
                VALUES (%s, %s, %s, 'open', NULL)
            """
            cursor.execute(sql, (user_id, user_name, message))
            connection.commit()
            return cursor.lastrowid
    except Exception as e:
        logger.error(f"Ошибка при создании обращения: {e}")
        return None
    finally:
        if 'connection' in locals():
            connection.close()

def add_response(ticket_id, admin_id, message):
    """Добавляет ответ администратора к обращению"""
    try:
        connection = pymysql.connect(**DB_CONFIG)
        with connection.cursor() as cursor:
            sql = """
                INSERT INTO `support_responses` 
                (`ticket_id`, `admin_id`, `message`) 
                VALUES (%s, %s, %s)
            """
            cursor.execute(sql, (ticket_id, admin_id, message))
            connection.commit()
            return True
    except Exception as e:
        logger.error(f"Ошибка при добавлении ответа: {e}")
        return False
    finally:
        if 'connection' in locals():
            connection.close()

def get_user_tickets(user_id):
    """Получает все обращения пользователя"""
    try:
        connection = pymysql.connect(**DB_CONFIG)
        with connection.cursor() as cursor:
            sql = """
                SELECT t.*, r.message as response, r.created_at as response_date 
                FROM `support_tickets` t
                LEFT JOIN `support_responses` r ON t.id = r.ticket_id
                WHERE t.user_id = %s
                ORDER BY t.created_at DESC, r.created_at ASC
            """
            cursor.execute(sql, (user_id,))
            
            tickets = {}
            for row in cursor.fetchall():
                if row['id'] not in tickets:
                    tickets[row['id']] = {
                        'id': row['id'],
                        'message': row['message'],
                        'status': row['status'],
                        'created_at': row['created_at'],
                        'responses': []
                    }
                if row['response']:
                    tickets[row['id']]['responses'].append({
                        'message': row['response'],
                        'created_at': row['response_date']
                    })
            
            return list(tickets.values())
    except Exception as e:
        logger.error(f"Ошибка при получении обращений: {e}")
        return []
    finally:
        if 'connection' in locals():
            connection.close()

def delete_ticket(ticket_id, user_id):
    """Удаляет обращение пользователя"""
    try:
        connection = pymysql.connect(**DB_CONFIG)
        with connection.cursor() as cursor:
            # Получаем ID сообщения админа перед удалением
            sql = "SELECT `admin_message_id` FROM `support_tickets` WHERE `id` = %s AND `user_id` = %s"
            cursor.execute(sql, (ticket_id, user_id))
            ticket = cursor.fetchone()
            
            if not ticket:
                return None
                
            admin_message_id = ticket['admin_message_id']
            
            # Удаляем ответы
            sql = "DELETE FROM `support_responses` WHERE `ticket_id` = %s"
            cursor.execute(sql, (ticket_id,))
            
            # Удаляем обращение
            sql = "DELETE FROM `support_tickets` WHERE `id` = %s AND `user_id` = %s"
            cursor.execute(sql, (ticket_id, user_id))
            
            connection.commit()
            return admin_message_id
    except Exception as e:
        logger.error(f"Ошибка при удалении обращения: {e}")
        return None
    finally:
        if 'connection' in locals():
            connection.close()

def check_anketa_exists(anketa_number):
    """Проверяет наличие анкеты в базе"""
    try:
        connection = pymysql.connect(**DB_CONFIG)
        with connection.cursor() as cursor:
            sql = "SELECT * FROM `b_iblock_element` WHERE `id` = %s"
            cursor.execute(sql, (anketa_number,))
            return cursor.fetchone() is not None
    except Exception as e:
        logger.error(f"Ошибка при проверке анкеты: {e}")
        return False
    finally:
        if 'connection' in locals():
            connection.close()

def count_recent_tickets(user_id):
    """Считает обращения пользователя за последний час"""
    try:
        connection = pymysql.connect(**DB_CONFIG)
        with connection.cursor() as cursor:
            sql = """
                SELECT COUNT(*) as count 
                FROM `support_tickets` 
                WHERE `user_id` = %s AND `created_at` > NOW() - INTERVAL 1 HOUR
            """
            cursor.execute(sql, (user_id,))
            return cursor.fetchone()['count']
    except Exception as e:
        logger.error(f"Ошибка при подсчете обращений: {e}")
        return 0
    finally:
        if 'connection' in locals():
            connection.close()

def save_admin_message_id(ticket_id, message_id):
    """Сохраняет ID сообщения админа"""
    try:
        connection = pymysql.connect(**DB_CONFIG)
        with connection.cursor() as cursor:
            sql = "UPDATE `support_tickets` SET `admin_message_id` = %s WHERE `id` = %s"
            cursor.execute(sql, (message_id, ticket_id))
            connection.commit()
    except Exception as e:
        logger.error(f"Ошибка при сохранении ID сообщения: {e}")
    finally:
        if 'connection' in locals():
            connection.close()

def get_ticket_info(ticket_id):
    """Получает информацию о конкретном обращении"""
    try:
        connection = pymysql.connect(**DB_CONFIG)
        with connection.cursor() as cursor:
            sql = "SELECT * FROM `support_tickets` WHERE `id` = %s"
            cursor.execute(sql, (ticket_id,))
            return cursor.fetchone()
    except Exception as e:
        logger.error(f"Ошибка получения информации о обращении: {e}")
        return None
    finally:
        if 'connection' in locals():
            connection.close()

def get_last_ticket_time(user_id):
    """Возвращает время последнего обращения"""
    try:
        connection = pymysql.connect(**DB_CONFIG)
        with connection.cursor() as cursor:
            sql = """
                SELECT UNIX_TIMESTAMP(`created_at`) as timestamp 
                FROM `support_tickets` 
                WHERE `user_id` = %s 
                ORDER BY `created_at` DESC LIMIT 1
            """
            cursor.execute(sql, (user_id,))
            result = cursor.fetchone()
            return result['timestamp'] if result else 0
    except Exception as e:
        logger.error(f"Ошибка получения времени обращения: {e}")
        return 0
    finally:
        if 'connection' in locals():
            connection.close()

async def kanali(update: Update, context: CallbackContext):
    """Отправляет список каналов"""
    keyboard = [
        [InlineKeyboardButton(channel["name"], url=channel["url"])]
        for channel in CHANNELS
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("📢 Наши каналы:", reply_markup=reply_markup)

async def link(update: Update, context: CallbackContext):
    """Отправляет ссылку на сайт"""
    await update.message.reply_text(
        f"🌐 Актуальная ссылка на сайт:\n\n{WEBSITE_LINK}",
        disable_web_page_preview=True
    )
            
async def start(update: Update, context: CallbackContext):
    """Обработчик команды /start"""
    # Очищаем данные пользователя
    context.user_data.clear()
    
    # Обработка deep links
    if context.args:
        deep_link = context.args[0].lower()
        
        if deep_link == DEEP_LINKS['balance']:
            return await balans(update, context)
        elif deep_link == DEEP_LINKS['recovery']:
            return await start_password_recovery(update, context)
        elif deep_link == DEEP_LINKS['support']:
            return await support_menu(update, context)
    
    # Стандартное меню
    keyboard = [
        ['Актуальная ссылка на сайт'],
        ['Пополнить баланс'],
        ['Наши каналы'],
        ['Восстановить пароль', 'Техподдержка']
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text('Выберите действие:', reply_markup=reply_markup)

async def balans(update: Update, context: CallbackContext):
    """Начинает процесс пополнения баланса"""
    keyboard = [['Отменить пополнение']]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(
        'Укажите <b>номер анкеты</b> для пополнения баланса (только цифры):',
        parse_mode='HTML',
        reply_markup=reply_markup
    )
    return ASK_ANKETA

async def handle_anketa(update: Update, context: CallbackContext):
    """Обрабатывает номер анкеты"""
    if update.message.text == 'Отменить пополнение':
        return await cancel_payment(update, context)
    
    anketa_number = update.message.text

    if not re.match(r'^\d+$', anketa_number):
        await update.message.reply_text(
            '❌ Номер анкеты должен содержать только цифры. Попробуйте еще раз:',
            reply_markup=ReplyKeyboardMarkup([['Отменить пополнение']], resize_keyboard=True)
        )
        return ASK_ANKETA

    if check_anketa_exists(anketa_number):
        context.user_data['anketa_number'] = anketa_number
        await update.message.reply_text(
            'Карта - <b>4400 4344 2442 4411</b> 💳\n\n'
            'Минимальная сумма для пополнения 1.000 тг.\n'
            'Пополняем без комиссий в течение 10 минут.\n\n'
            '<b>После оплаты отправьте чек в данный чат.</b> 🧾',
            parse_mode='HTML',
            reply_markup=ReplyKeyboardMarkup([['Отменить пополнение']], resize_keyboard=True)
        )
        return ASK_RECEIPT
    else:
        await update.message.reply_text(
            '❌ Аккаунт с анкетой не найден. Попробуйте еще раз:',
            parse_mode='HTML',
            reply_markup=ReplyKeyboardMarkup([['Отменить пополнение']], resize_keyboard=True)
        )
        return ASK_ANKETA

async def handle_receipt(update: Update, context: CallbackContext):
    """Обрабатывает чек об оплате"""
    if update.message.text == 'Отменить пополнение':
        return await cancel_payment(update, context)
    
    if not (update.message.document or update.message.photo):
        await update.message.reply_text(
            '❌ Пожалуйста, отправьте чек оплаты в виде изображения или файла.',
            reply_markup=ReplyKeyboardMarkup([['Отменить пополнение']], resize_keyboard=True)
        )
        return ASK_RECEIPT

    anketa_number = context.user_data['anketa_number']
    user = update.message.from_user
    user_info = f"Имя: {user.first_name}\nUsername: @{user.username}" if user.username else f"Имя: {user.first_name}"

    if update.message.document:
        file_id = update.message.document.file_id
        await context.bot.send_document(
            chat_id=ADMIN_CHAT_ID,
            document=file_id,
            caption=f"Чек для Анкеты: {anketa_number}\nКонтакт пользователя:\n{user_info}"
        )
    elif update.message.photo:
        file_id = update.message.photo[-1].file_id
        await context.bot.send_photo(
            chat_id=ADMIN_CHAT_ID,
            photo=file_id,
            caption=f"Чек для Анкеты: {anketa_number}\nКонтакт пользователя:\n{user_info}"
        )

    await update.message.reply_text(
        'Спасибо! Ваш платеж будет обработан в течение 10 минут. ✅',
        reply_markup=ReplyKeyboardMarkup([
            ['Актуальная ссылка на сайт'],
            ['Пополнить баланс'],
            ['Наши каналы'],
            ['Восстановить пароль', 'Техподдержка']
        ], resize_keyboard=True)
    )
    return ConversationHandler.END

async def cancel_payment(update: Update, context: CallbackContext):
    """Отменяет пополнение баланса"""
    await update.message.reply_text(
        '❌ Пополнение баланса отменено.',
        reply_markup=ReplyKeyboardMarkup([
            ['Актуальная ссылка на сайт'],
            ['Пополнить баланс'],
            ['Наши каналы'],
            ['Восстановить пароль', 'Техподдержка']
        ], resize_keyboard=True)
    )
    return ConversationHandler.END

async def start_password_recovery(update: Update, context: CallbackContext):
    """Начинает процесс восстановления пароля"""
    user_id = update.effective_user.id
    
    # Проверяем время последней смены пароля
    last_change = password_change_cache.get(user_id)
    if last_change and time.time() - last_change < PASSWORD_CHANGE_COOLDOWN:
        remaining = int((last_change + PASSWORD_CHANGE_COOLDOWN - time.time()) / 60)
        await update.message.reply_text(
            f"⚠️ Смена пароля возможна раз в час. Попробуйте через {remaining} минут.",
            reply_markup=ReplyKeyboardMarkup([
                ['Актуальная ссылка на сайт'],
                ['Пополнить баланс'],
                ['Наши каналы'],
                ['Восстановить пароль', 'Техподдержка']
            ], resize_keyboard=True)
        )
        return ConversationHandler.END
    
    keyboard = [
        [KeyboardButton("Поделиться номером", request_contact=True)],
        ["Отмена"]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
    
    await update.message.reply_text(
        "📱 Для восстановления пароля нажмите кнопку, чтобы поделиться номером:",
        reply_markup=reply_markup
    )
    return PHONE_INPUT

async def process_phone_input(update: Update, context: CallbackContext):
    """Обрабатывает ввод номера телефона"""
    if update.message.text and update.message.text.lower() == "отмена":
        return await cancel(update, context)
    
    if not update.message.contact:
        await update.message.reply_text(
            "❌ Для продолжения необходимо поделиться номером через кнопку ниже:",
            reply_markup=ReplyKeyboardMarkup([
                [KeyboardButton("Поделиться номером", request_contact=True)],
                ["Отмена"]
            ], resize_keyboard=True, one_time_keyboard=True)
        )
        return PHONE_INPUT
    
    phone_number = update.message.contact.phone_number
    formatted_phone = format_phone(phone_number)
    
    if not check_user_in_db(formatted_phone):
        await update.message.reply_text(
            f"❌ Ваш номер: <b>{formatted_phone}</b> не зарегистрирован на сайте Токалки БАР.",
            parse_mode='HTML',
            reply_markup=ReplyKeyboardMarkup([
                ['Актуальная ссылка на сайт'],
                ['Пополнить баланс'],
                ['Наши каналы'],
                ['Восстановить пароль', 'Техподдержка']
            ], resize_keyboard=True)
        )
        return ConversationHandler.END
    
    context.user_data['phone'] = formatted_phone
    
    await update.message.reply_text(
        f"✅ Ваш номер: <b>{formatted_phone}</b> подтвержден.\n\n"
        "Введите новый пароль (минимум 4 символа):",
        parse_mode='HTML',
        reply_markup=ReplyKeyboardMarkup([["Отмена"]], resize_keyboard=True)
    )
    return NEW_PASSWORD

async def process_new_password(update: Update, context: CallbackContext):
    """Обрабатывает новый пароль"""
    if update.message.text and update.message.text.lower() == "отмена":
        return await cancel(update, context)
    
    new_password = update.message.text.strip()
    
    if len(new_password) < 4:
        await update.message.reply_text(
            "❌ Пароль слишком короткий! Минимум 4 символа. Введите еще раз:",
            reply_markup=ReplyKeyboardMarkup([["Отмена"]], resize_keyboard=True)
        )
        return NEW_PASSWORD
    
    phone = context.user_data['phone']
    user_id = update.effective_user.id
    
    if update_user_password(phone, new_password):
        password_change_cache[user_id] = time.time()
        
        await update.message.reply_text(
            "✅ <b>Пароль успешно изменен!</b>\n\n"
            f"<b>Логин</b>: <code>{phone}</code>\n"
            f"<b>Пароль</b>: <code>{new_password}</code>\n\n"
            f"Личный кабинет: {WEBSITE_LINK}cabinet/",
            parse_mode='HTML',
            disable_web_page_preview=True,
            reply_markup=ReplyKeyboardMarkup([
                ['Актуальная ссылка на сайт'],
                ['Пополнить баланс'],
                ['Наши каналы'],
                ['Восстановить пароль', 'Техподдержка']
            ], resize_keyboard=True)
        )
    else:
        await update.message.reply_text(
            "❌ Ошибка при изменении пароля. Возможно указали действующий пароль, попробуйте позже.",
            reply_markup=ReplyKeyboardMarkup([
                ['Актуальная ссылка на сайт'],
                ['Пополнить баланс'],
                ['Наши каналы'],
                ['Восстановить пароль', 'Техподдержка']
            ], resize_keyboard=True)
        )
    
    return ConversationHandler.END

async def support_menu(update: Update, context: CallbackContext):
    """Показывает меню техподдержки"""
    # Очищаем данные пользователя, связанные с поддержкой
    context.user_data.pop('support_message', None)
    
    keyboard = [
        ['Создать обращение'],
        ['Мои обращения'],
        ['Назад']
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    # Проверяем, не было ли это повторным вызовом
    if update.message.text == 'Техподдержка' and context.user_data.get('in_support'):
        return SUPPORT_MAIN_MENU
    
    context.user_data['in_support'] = True
    await update.message.reply_text(
        '📩 Меню техподдержки:',
        reply_markup=reply_markup
    )
    return SUPPORT_MAIN_MENU

async def handle_back_from_support(update: Update, context: CallbackContext):
    """Обрабатывает кнопку Назад в техподдержке"""
    # Полностью завершаем текущий разговор
    context.user_data.pop('in_support', None)
    await update.message.reply_text(
        "Возвращаемся в главное меню...",
        reply_markup=ReplyKeyboardMarkup([
            ['Актуальная ссылка на сайт'],
            ['Пополнить баланс'],
            ['Наши каналы'],
            ['Восстановить пароль', 'Техподдержка']
        ], resize_keyboard=True)
    )
    return ConversationHandler.END

async def start_support(update: Update, context: CallbackContext):
    """Начинает создание обращения"""
    user_id = update.effective_user.id
    recent_tickets = count_recent_tickets(user_id)
    
    if recent_tickets >= MAX_TICKETS_PER_HOUR:
        last_ticket_time = get_last_ticket_time(user_id)
        if last_ticket_time:
            remaining_time = 60 - int((time.time() - last_ticket_time) // 60)
            await update.message.reply_text(
                f"❌ Вы можете создавать не более 3 обращений в час. "
                f"Попробуйте через {remaining_time} минут.",
                reply_markup=ReplyKeyboardMarkup([
                    ['Мои обращения'],
                    ['Назад']
                ], resize_keyboard=True)
            )
        else:
            await update.message.reply_text(
                "❌ Вы можете создавать не более 3 обращений в час.",
                reply_markup=ReplyKeyboardMarkup([
                    ['Мои обращения'],
                    ['Назад']
                ], resize_keyboard=True)
            )
        return SUPPORT_MAIN_MENU
    
    await update.message.reply_text(
        "✍️ Опишите вашу проблему максимально подробно:",
        reply_markup=ReplyKeyboardMarkup([['Отмена']], resize_keyboard=True)
    )
    return SUPPORT_INPUT

async def process_support_message(update: Update, context: CallbackContext):
    """Обрабатывает сообщение для техподдержки"""
    if update.message.text == 'Отмена':
        # Возвращаем в меню техподдержки, а не в главное меню
        return await support_menu(update, context)
    
    context.user_data['support_message'] = update.message.text
    await update.message.reply_text(
        "📎 Прикрепите файл или фото, если необходимо (или нажмите 'Пропустить'):",
        reply_markup=ReplyKeyboardMarkup([['Пропустить']], resize_keyboard=True)
    )
    return SUPPORT_ATTACHMENT

async def process_support_attachment(update: Update, context: CallbackContext):
    """Обрабатывает вложение для техподдержки"""
    user = update.effective_user
    attachment = None
    
    if update.message.text != 'Пропустить':
        if update.message.photo:
            attachment = {'type': 'photo', 'file_id': update.message.photo[-1].file_id}
        elif update.message.document:
            attachment = {'type': 'document', 'file_id': update.message.document.file_id}
        else:
            await update.message.reply_text(
                "❌ Пожалуйста, отправьте файл или фото, либо нажмите 'Пропустить'",
                reply_markup=ReplyKeyboardMarkup([['Пропустить']], resize_keyboard=True)
            )
            return SUPPORT_ATTACHMENT
    
    # Создаем обращение
    ticket_id = create_ticket(user.id, user.full_name, context.user_data['support_message'])
    
    if not ticket_id:
        await update.message.reply_text("❌ Ошибка при создании обращения")
        return await start(update, context)
    
    # Отправляем сообщение админу
    try:
        admin_msg = await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=f"📩 Новое обращение #{ticket_id}\n\n"
                 f"👤 {user.full_name} (@{user.username or 'нет'})\n"
                 f"🆔 {user.id}\n\n"
                 f"✉️ {context.user_data['support_message']}",
            parse_mode='HTML'
        )
        
        # Сохраняем ID сообщения админа
        save_admin_message_id(ticket_id, admin_msg.message_id)
        
        # Отправляем вложение если есть
        if attachment:
            if attachment['type'] == 'photo':
                await context.bot.send_photo(
                    chat_id=ADMIN_CHAT_ID,
                    photo=attachment['file_id'],
                    caption=f"📎 Вложение к обращению #{ticket_id}",
                    reply_to_message_id=admin_msg.message_id
                )
            else:
                await context.bot.send_document(
                    chat_id=ADMIN_CHAT_ID,
                    document=attachment['file_id'],
                    caption=f"📎 Вложение к обращению #{ticket_id}",
                    reply_to_message_id=admin_msg.message_id
                )
    except Exception as e:
        logger.error(f"Ошибка отправки сообщения админу: {e}")
    
    await update.message.reply_text(
        f"✅ Обращение #{ticket_id} создано! Ответ придёт в этот чат.",
        reply_markup=ReplyKeyboardMarkup([
            ['Актуальная ссылка на сайт'],
            ['Пополнить баланс'],
            ['Наши каналы'],
            ['Восстановить пароль', 'Техподдержка']
        ], resize_keyboard=True)
    )
    context.user_data.pop('in_support', None)
    return ConversationHandler.END

async def show_my_tickets(update: Update, context: CallbackContext):
    """Показывает обращения пользователя"""
    user = update.effective_user
    tickets = get_user_tickets(user.id)
    
    if not tickets:
        await update.message.reply_text(
            "У вас пока нет обращений в техподдержку.",
            reply_markup=ReplyKeyboardMarkup([
                ['Создать обращение'],
                ['Назад']
            ], resize_keyboard=True)
        )
        return SUPPORT_MAIN_MENU
    
    for ticket in tickets:
        status_text = {
            'open': '⏳ Ожидает ответа',
            'answered': '✅ Отвечено',
            'closed': '❌ Закрыто'
        }.get(ticket['status'], ticket['status'])
        
        message_text = (
            f"🆔 Обращение <b>#{ticket['id']}</b>\n"
            f"📅 Дата: {ticket['created_at'].strftime('%d.%m.%Y %H:%M')}\n"
            f"📌 Статус: {status_text}\n\n"
            f"✍️ Ваше сообщение:\n{ticket['message']}"
        )
        
        # Добавляем ответы
        if ticket.get('responses'):
            for response in ticket['responses']:
                message_text += (
                    f"\n\n📩 <b>Ответ поддержки</b> ({response['created_at'].strftime('%d.%m.%Y %H:%M')}):\n"
                    f"{response['message']}"
                )
        
        # Кнопка удаления
        keyboard = [
            [InlineKeyboardButton("❌ Удалить", callback_data=f"delete_ticket_{ticket['id']}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            message_text,
            parse_mode='HTML',
            reply_markup=reply_markup
        )
    
    keyboard = [
        ['Создать обращение'],
        ['Назад']
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(
        "Выберите действие:",
        reply_markup=reply_markup
    )
    return SUPPORT_MAIN_MENU

async def delete_ticket_handler(update: Update, context: CallbackContext):
    """Обрабатывает удаление обращения"""
    query = update.callback_query
    await query.answer()
    
    if not query.data.startswith('delete_ticket_'):
        return
    
    ticket_id = int(query.data.split('_')[-1])
    user_id = query.from_user.id
    
    # Удаляем обращение и получаем ID сообщения админа
    admin_message_id = delete_ticket(ticket_id, user_id)
    
    if admin_message_id is not None:
        # Пытаемся удалить сообщение у админа
        try:
            await context.bot.delete_message(
                chat_id=ADMIN_CHAT_ID,
                message_id=admin_message_id
            )
        except Exception as e:
            logger.error(f"Ошибка удаления сообщения у админа: {e}")
        
        await query.edit_message_text(f"❌ Обращение #{ticket_id} удалено")
    else:
        await query.answer("Не удалось удалить обращение", show_alert=True)
    
    # Возвращаем пользователя в меню техподдержки
    keyboard = [
        ['Создать обращение'],
        ['Мои обращения'],
        ['Назад']
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await context.bot.send_message(
        chat_id=user_id,
        text="📩 Меню техподдержки:",
        reply_markup=reply_markup
    )
    return SUPPORT_MAIN_MENU

async def admin_reply_to_ticket(update: Update, context: CallbackContext):
    """Обрабатывает ответ админа на обращение"""
    if not update.message.reply_to_message:
        await update.message.reply_text("❌ Отвечайте на сообщение с обращением пользователя.")
        return
    
    replied_msg = update.message.reply_to_message.text
    
    # Парсим номер обращения
    ticket_id = None
    try:
        match = re.search(r'#(\d+)', replied_msg)
        if match:
            ticket_id = int(match.group(1))
    except (AttributeError, ValueError) as e:
        logger.error(f"Ошибка парсинга номера обращения: {e}")
        await update.message.reply_text(
            "❌ Не удалось определить номер обращения.",
            reply_to_message_id=update.message.message_id
        )
        return
    
    if not ticket_id:
        await update.message.reply_text(
            "❌ Не найден номер обращения в сообщении.",
            reply_to_message_id=update.message.message_id
        )
        return
    
    # Добавляем ответ в базу
    admin = update.effective_user
    success = add_response(
        ticket_id=ticket_id,
        admin_id=admin.id,
        message=update.message.text
    )
    
    if not success:
        await update.message.reply_text(
            "❌ Ошибка при сохранении ответа.",
            reply_to_message_id=update.message.message_id
        )
        return
    
    # Получаем информацию о тикете
    ticket = get_ticket_info(ticket_id)
    if not ticket:
        await update.message.reply_text(
            "❌ Обращение не найдено в базе.",
            reply_to_message_id=update.message.message_id
        )
        return
    
    # Обновляем статус обращения
    try:
        connection = pymysql.connect(**DB_CONFIG)
        with connection.cursor() as cursor:
            sql = "UPDATE `support_tickets` SET `status` = 'answered' WHERE `id` = %s"
            cursor.execute(sql, (ticket_id,))
            connection.commit()
    except Exception as e:
        logger.error(f"Ошибка обновления статуса обращения: {e}")
    
    # Отправляем ответ пользователю
    try:
        await context.bot.send_message(
            chat_id=ticket['user_id'],
            text=f"📩 <b>Ответ на ваше обращение #{ticket_id}</b>\n\n"
                 f"💬 Ваше сообщение:\n{ticket['message']}\n\n"
                 f"📣 Ответ поддержки:\n{update.message.text}\n\n"
                 f"Для продолжения диалога создайте новое обращение.",
            parse_mode='HTML'
        )
        
        await update.message.reply_text(
            f"✅ Ответ на обращение #{ticket_id} отправлен пользователю.",
            reply_to_message_id=update.message.message_id
        )
    except Exception as e:
        logger.error(f"Ошибка отправки ответа пользователю: {e}")
        await update.message.reply_text(
            f"❌ Не удалось отправить ответ пользователю. Возможно, он заблокировал бота.",
            reply_to_message_id=update.message.message_id
        )

async def cancel(update: Update, context: CallbackContext):
    """Отменяет текущее действие"""
    await update.message.reply_text(
        "⚠️ Действие отменено",
        reply_markup=ReplyKeyboardMarkup([
            ['Актуальная ссылка на сайт'],
            ['Пополнить баланс'],
            ['Наши каналы'],
            ['Восстановить пароль', 'Техподдержка']
        ], resize_keyboard=True)
    )
    return ConversationHandler.END

def main():
    """Запускает бота"""
    app = ApplicationBuilder().token(TOKEN).build()

    # Обработчики команд
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("link", link))
    app.add_handler(CommandHandler("channels", kanali))
    
    # Обработчики сообщений
    app.add_handler(MessageHandler(filters.Regex('^Актуальная ссылка на сайт$'), link))
    app.add_handler(MessageHandler(filters.Regex('^Наши каналы$'), kanali))
    
    # Восстановление пароля
    password_recovery_handler = ConversationHandler(
        entry_points=[
            CommandHandler("recover", start_password_recovery),
            MessageHandler(filters.Regex('^Восстановить пароль$'), start_password_recovery)
        ],
        states={
            PHONE_INPUT: [MessageHandler(filters.CONTACT | filters.TEXT & ~filters.COMMAND, process_phone_input)],
            NEW_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_new_password)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )
    app.add_handler(password_recovery_handler)
    
    # Пополнение баланса
    balance_handler = ConversationHandler(
        entry_points=[
            CommandHandler("balans", balans),
            MessageHandler(filters.Regex('^Пополнить баланс$'), balans)
        ],
        states={
            ASK_ANKETA: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_anketa),
                MessageHandler(filters.COMMAND, cancel_payment)
            ],
            ASK_RECEIPT: [
                MessageHandler(filters.ALL & ~filters.COMMAND, handle_receipt),
                MessageHandler(filters.COMMAND, cancel_payment)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_payment)]
    )
    app.add_handler(balance_handler)
    
    # Техподдержка
    support_conv_handler = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex('^Техподдержка$'), support_menu),
        ],
        states={
            SUPPORT_MAIN_MENU: [
                MessageHandler(filters.Regex('^Создать обращение$'), start_support),
                MessageHandler(filters.Regex('^Мои обращения$'), show_my_tickets),
                MessageHandler(filters.Regex('^Назад$'), handle_back_from_support)
            ],
            SUPPORT_INPUT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, process_support_message)
            ],
            SUPPORT_ATTACHMENT: [
                MessageHandler(filters.PHOTO | filters.Document.ALL, process_support_attachment),
                MessageHandler(filters.Regex('^Пропустить$'), process_support_attachment)
            ]
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )
    app.add_handler(support_conv_handler)
    
    # Обработчик удаления обращений
    app.add_handler(CallbackQueryHandler(delete_ticket_handler, pattern='^delete_ticket_'))
    
    # Обработчик ответов админа
    app.add_handler(MessageHandler(
        filters.Chat(ADMIN_CHAT_ID) & filters.REPLY,
        admin_reply_to_ticket
    ))

    # Запуск бота
    app.run_polling()

if __name__ == '__main__':
    main()