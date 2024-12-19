import os
import logging

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
import sqlite3

# Настройки бота
CHANNEL_USERNAME = '@tennis_bolshe'
ADMIN_IDS = [102395366]  # Список ID администраторов

# Настройка логирования
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

def get_db():
    return sqlite3.connect('/data')
    
# Инициализация базы данных
def init_database():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS participants (
            ticket_number TEXT PRIMARY KEY,
            user_id INTEGER NULL,  # Может быть NULL для оффлайн участников
            username TEXT NULL,    # Может быть NULL для оффлайн участников
            full_name TEXT NULL,   # Имя для оффлайн участников
            phone TEXT NULL,       # Телефон для оффлайн участников
            is_subscribed BOOLEAN,
            is_winner BOOLEAN DEFAULT FALSE)
    ''')
    conn.commit()
    conn.close()

# Проверка подписки пользователя
async def check_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user_id = update.effective_user.id
    try:
        member = await context.bot.get_chat_member(CHANNEL_USERNAME, user_id)
        return member.status in ['member', 'administrator', 'creator']
    except Exception as e:
        logger.error(f"Ошибка проверки подписки: {e}")
        return False

def generate_registration_link(ticket_number):
    bot_username = 'your_bot_username'  # Замените на username вашего бота
    deep_link = f'https://t.me/{bot_username}?start=register_{ticket_number}'
    return deep_link

# Команда старта с поддержкой deep linking
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args and context.args[0].startswith('register_'):
        ticket_number = context.args[0].split('_')[1]
        await register(update, context, ticket_number)
    else:
        await update.message.reply_text("Добро пожаловать! Используйте ссылку с номером билета для регистрации.")

# Команда регистрации
async def register(update: Update, context: ContextTypes.DEFAULT_TYPE, ticket_number=None):
    if not ticket_number:
        if len(context.args) != 1:
            await update.message.reply_text("Используйте: /register НОМЕР_БИЛЕТА")
            return
        ticket_number = context.args[0]

    user_id = update.effective_user.id
    username = update.effective_user.username

    # Проверка подписки
    is_subscribed = await check_subscription(update, context)
    if not is_subscribed:
        await update.message.reply_text(f"Для участия необходимо подписаться на канал {CHANNEL_USERNAME}")
        return

    # Сохранение в базу данных
    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT OR REPLACE INTO participants 
            (ticket_number, user_id, username, is_subscribed) 
            VALUES (?, ?, ?, ?)
        ''', (ticket_number, user_id, username, True))
        conn.commit()
        await update.message.reply_text(f"Вы зарегистрированы с билетом {ticket_number}!")
    except sqlite3.IntegrityError:
        await update.message.reply_text("Этот билет уже зарегистрирован.")
    finally:
        conn.close()


# Команда регистрации оффлайн участника (только для админов)
async def register_offline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("У вас нет прав для регистрации участников")
        return

    # Проверка формата команды
    # Пример: /register_offline НОМЕР_БИЛЕТА "Иван Иванов" +79001234567
    if len(context.args) < 3:
        await update.message.reply_text("Используйте: /register_offline НОМЕР_БИЛЕТА \"ИМЯ\" ТЕЛЕФОН")
        return

    ticket_number = context.args[0]
    full_name = context.args[1]
    phone = context.args[2]

    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT INTO participants 
            (ticket_number, full_name, phone, is_subscribed) 
            VALUES (?, ?, ?, ?)
        ''', (ticket_number, full_name, phone, True))
        conn.commit()
        await update.message.reply_text(
            f"Зарегистрирован оффлайн участник:\n"
            f"Билет: {ticket_number}\n"
            f"Имя: {full_name}\n"
            f"Телефон: {phone}"
        )
    except sqlite3.IntegrityError:
        await update.message.reply_text("Этот билет уже зарегистрирован.")
    finally:
        conn.close()


# Команда регистрации выигрышного билета (только для админов)
async def register_winner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("У вас нет прав для регистрации победителей")
        return

    if len(context.args) != 1:
        await update.message.reply_text("Используйте: /register_winner НОМЕР_БИЛЕТА")
        return

    ticket_number = context.args[0]
    conn = get_db()
    cursor = conn.cursor()
    
    try:
        # Проверяем существование билета
        cursor.execute('SELECT * FROM participants WHERE ticket_number = ?', (ticket_number,))
        participant = cursor.fetchone()
        
        if not participant:
            await update.message.reply_text("Билет не найден в базе данных")
            return

        # Отмечаем билет как выигрышный
        cursor.execute('''
            UPDATE participants 
            SET is_winner = TRUE 
            WHERE ticket_number = ?
        ''', (ticket_number,))
        conn.commit()

        # Получаем информацию о победителе
        cursor.execute('''
            SELECT user_id, username, full_name, phone 
            FROM participants 
            WHERE ticket_number = ?
        ''', (ticket_number,))
        winner = cursor.fetchone()
        
        # Формируем сообщение о победителе
        if winner[0]:  # Если есть user_id (онлайн участник)
            winner_info = f"@{winner[1]}"
            # Отправляем личное сообщение победителю
            try:
                await context.bot.send_message(
                    chat_id=winner[0],
                    text=f"🎉 Поздравляем! Ваш билет {ticket_number} выиграл в лотерее!"
                )
            except Exception as e:
                logger.error(f"Ошибка отправки сообщения победителю: {e}")
        else:  # Оффлайн участник
            winner_info = f"{winner[2]} (тел: {winner[3]})"

        await update.message.reply_text(
            f"Билет {ticket_number} зарегистрирован как выигрышный!\n"
            f"Победитель: {winner_info}"
        )

        # Публикация в канале
        await context.bot.send_message(
            chat_id=CHANNEL_USERNAME,
            text=f"🏆 Поздравляем победителя!\nБилет: {ticket_number}"
        )

    except Exception as e:
        await update.message.reply_text(f"Произошла ошибка: {str(e)}")
    finally:
        conn.close()


# Просмотр списка победителей (только для админов)
async def list_winners(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("У вас нет прав для просмотра списка победителей")
        return

    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT ticket_number, username, full_name, phone 
        FROM participants 
        WHERE is_winner = TRUE
    ''')
    winners = cursor.fetchall()
    
    if not winners:
        await update.message.reply_text("Список победителей пуст")
        return

    winners_text = "🏆 Список победителей:\n\n"
    for winner in winners:
        ticket, username, full_name, phone = winner
        if username:
            winner_info = f"@{username}"
        else:
            winner_info = f"{full_name} (тел: {phone})"
        winners_text += f"Билет {ticket}: {winner_info}\n"

    await update.message.reply_text(winners_text)
    conn.close()


def main():
    init_database()
    load_dotenv()

    token = os.environ["TELEGRAM_BOT_TOKEN"]
    
    # Init app
    application = Application.builder().token(token).build()
    
    # Register command handlers
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("register", register))
    application.add_handler(CommandHandler("register_offline", register_offline))
    application.add_handler(CommandHandler("register_winner", register_winner))
    application.add_handler(CommandHandler("list_winners", list_winners))
    
    application.run_polling()


if __name__ == '__main__':
    main()