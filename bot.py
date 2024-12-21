import os
import logging
import shlex
from dotenv import load_dotenv

from telegram import Update
from telegram.ext import Application, CommandHandler, ChatMemberHandler, ContextTypes
from motor.motor_asyncio import AsyncIOMotorClient
from datetime import datetime

# Настройки бота
load_dotenv(dotenv_path='.env.local')

# Настройка логирования
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get('TELEGRAM_TOKEN')
CHANNEL_USERNAME = os.environ.get('CHANNEL_USERNAME')
MONGODB_URI = os.environ.get('MONGODB_URL')
ADMIN_IDS = [int(id) for id in os.environ.get('ADMIN_IDS', '').split(',')]

# Подключение к MongoDB
client = AsyncIOMotorClient(MONGODB_URI)
db = client.lottery_db

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

# Проверка подписки пользователя
async def check_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:

    user_id = update.effective_user.id
    try:
        member = await context.bot.get_chat_member(CHANNEL_USERNAME, user_id)
        return member.status in ['member', 'administrator', 'creator']
    except Exception as e:
        logger.error(f"Ошибка проверки подписки: {e}")
        return False

# Команда старта с поддержкой deep linking
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args and context.args[0].startswith('register_'):
        ticket_number = context.args[0].split('_')[1]
        await register(update, context, ticket_number)
    else:
        await update.message.reply_text("Добро пожаловать! Используйте ссылку с КОДом билета для регистрации.")

# Проверка кода билета
async def check_ticket_code(ticket_number: str) -> bool:
    ticket = await db.tickets.find_one({'_id': ticket_number})

    return bool(ticket)

# Получение описания билета
async def get_ticket_description(ticket_number: str) -> str:
    ticket = await db.tickets.find_one({'_id': ticket_number})

    return ticket['description'] if ticket else None

# Оповестить администраторов о новой регистрации
async def notify_admins(update: Update, context: ContextTypes.DEFAULT_TYPE, ticket_description: str):
    count = await db.participants.count_documents({})
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=f"{ticket_description} и @{update.effective_user.username} участвуют в лотерее! (Всего: { count })"
            )
        except Exception as e:
            logger.error(f"Ошибка отправки уведомления администратору: {e}")

# Команда регистрации
async def register(update: Update, context: ContextTypes.DEFAULT_TYPE, ticket_number=None):
    if not ticket_number:
        if len(context.args) != 1:
            await update.message.reply_text("Используйте: /register КОД_БИЛЕТА")
            return
        ticket_number = context.args[0]
    if not await check_ticket_code(ticket_number):
        await update.message.reply_text("Билет не найден")
        return

    user_id = update.effective_user.id
    username = update.effective_user.username
    user_fullname = update.effective_user.full_name
    ticket_description = await get_ticket_description(ticket_number)

    # Проверка существующей регистрации
    existing_ticket = await db.participants.find_one({'ticket_number': ticket_number})
    if existing_ticket:
        await update.message.reply_text(f"{ ticket_description } уже занят!")
        return

    # Проверка подписки
    is_subscribed = await check_subscription(update, context)

    if is_subscribed:
        # Регистрируем участника
        await db.participants.insert_one({
            'ticket_number': ticket_number,
            'user_id': user_id,
            'username': username,
            'user_fullname': user_fullname,
            'is_subscribed': True,
            'registered_at': datetime.utcnow(),
            'is_winner': False
        })
        await update.message.reply_text(f"Теперь вы участвуете в лотерее! Вам помогает { ticket_description }!")
        await notify_admins(update, context, ticket_description)
    else:
        # Сохраняем в ожидающие
        await db.pending_registrations.insert_one({
            'user_id': user_id,
            'ticket_number': ticket_number,
            'created_at': datetime.utcnow(),
            'is_processed': False
        })
        await update.message.reply_text(
            f"{ ticket_description } зовёт вас в канал {CHANNEL_USERNAME}!"
        )

# Регистрация оффлайн участника
async def register_offline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("У вас нет прав для регистрации участников")
        return

    # Получаем текст сообщения
    message_text = update.message.text

    # Убираем команду из начала сообщения
    command_parts = message_text.split(maxsplit=1)
    if len(command_parts) < 2:
        await update.message.reply_text("Используйте: /register_offline КОД_БИЛЕТА \"ИМЯ\" ТЕЛЕФОН")
        return

    # Разбираем аргументы с учетом кавычек
    try:
        args = shlex.split(command_parts[1])
        if len(args) < 3:
            await update.message.reply_text("Используйте: /register_offline КОД_БИЛЕТА \"ИМЯ\" ТЕЛЕФОН")
            return

        ticket_number = args[0]
        full_name = args[1]  # Теперь имя в кавычках будет одним элементом
        phone = args[2]


    except ValueError as e:
        await update.message.reply_text("Ошибка в формате команды. Проверьте кавычки.")
        return

    if not await check_ticket_code(ticket_number):
        await update.message.reply_text("Билет не найден")
        return

    # Проверка существующей регистрации
    existing_ticket = await db.participants.find_one({'ticket_number': ticket_number})
    if existing_ticket:
        await update.message.reply_text("Этот билет уже зарегистрирован.")
        return

    ticket_description = await get_ticket_description(ticket_number)
    # Регистрация оффлайн участника
    await db.participants.insert_one({
        'ticket_number': ticket_number,
        'full_name': full_name,
        'phone': phone,
        'is_subscribed': True,
        'registered_at': datetime.utcnow(),
        'is_winner': False,
        'is_offline': True
    })

    await update.message.reply_text(
        f"Зарегистрирован оффлайн участник:\n"
        f"Билет: `{ticket_description}`\n"
        f"Имя: {full_name}\n"
        f"Телефон: {phone}"
    )

# Обработчик подписки на канал
async def track_channel_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result = update.chat_member
    if not result:
        return

    if result.new_chat_member.status == 'member':
        user_id = result.new_chat_member.user.id
        username = result.new_chat_member.user.username
        user_fullname = result.new_chat_member.user.full_name

        # Поиск ожидающей регистрации
        pending = await db.pending_registrations.find_one({
            'user_id': user_id,
            'is_processed': False
        })

        if pending:
            ticket_number = pending['ticket_number']
            ticket_description = await get_ticket_description(ticket_number)

            # Регистрируем участника
            await db.participants.insert_one({
                'ticket_number': ticket_number,
                'user_id': user_id,
                'username': username,
                'is_subscribed': True,
                'registered_at': datetime.utcnow(),
                'is_winner': False
            })

            # Отмечаем регистрацию как обработанную
            await db.pending_registrations.update_one(
                {'_id': pending['_id']},
                {'$set': {'is_processed': True}}
            )

            # Отправляем уведомление
            await context.bot.send_message(
                chat_id=user_id,
                text=f"🎉 Теперь вы участвуете в лотерее! Вам помогает { ticket_description }!"
            )

# Регистрация победителя
async def register_winner(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("У вас нет прав для регистрации победителей")
        return

    if len(context.args) < 2:
        await update.message.reply_text("Используйте: /register_winner КОД_БИЛЕТА НАЗВАНИЕ_ВЫИГРЫША")
        return

    ticket_number = context.args[0]
    prize = " ".join(context.args[1:])

    # Поиск участника
    participant = await db.participants.find_one({'ticket_number': ticket_number})

    if not participant:
        await update.message.reply_text("Билет не найден в базе данных")
        return

    # Отмечаем билет как выигрышный
    await db.participants.update_one(
        {'ticket_number': ticket_number},
        {'$set': {'is_winner': True, 'prize': prize, 'won_at': datetime.utcnow()}}
    )

    ticket_description = await get_ticket_description(ticket_number)
    # Формируем информацию о победителе
    if 'user_id' in participant:  # Онлайн участник
        winner_info = f"@{participant['username']} ({participant['user_fullname']})"
        try:
            await context.bot.send_message(
                chat_id=participant['user_id'],
                text=f"🎉 Ура! { ticket_description } поздравляет вас с победой! Ваш приз — { prize }!"
            )
        except Exception as e:
            logger.error(f"Ошибка отправки сообщения победителю: {e}")
    else:  # Оффлайн участник
        winner_info = f"{participant['full_name']} (тел: {participant['phone']})"

    await update.message.reply_text(
        f"Билет '{ticket_description}' зарегистрирован как выигрышный!\n"
        f"Победитель: {winner_info}\n"
        f"Приз: {prize}"
    )

    # Публикация в канале
    #await context.bot.send_message(
    #    chat_id=CHANNEL_USERNAME,
    #    text=f"🏆 Поздравляем победителя!\nБилет: {ticket_number}"
    #)

# Просмотр списка победителей
async def list_winners(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("У вас нет прав для просмотра списка победителей")
        return

    winners = await db.participants.find({'is_winner': True}).to_list(length=None)

    if not winners:
        await update.message.reply_text("Список победителей пуст")
        return

    winners_text = "🏆 Список победителей:\n\n"
    for winner in winners:
        if 'username' in winner:
            winner_info = f"@{winner['username']}\n{ winner['user_fullname']}"
        else:
            winner_info = f"{winner['full_name']} (тел: {winner['phone']})"
        winners_text += f"Приз: { winner['prize']}\nБилет: {winner['ticket_number']}\n{winner_info}\n\n"

    await update.message.reply_text(winners_text)

def main():
    # Инициализация приложения
    application = Application.builder().token(TOKEN).build()

    # Регистрация обработчиков команд
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("register", register))
    application.add_handler(CommandHandler("register_offline", register_offline))
    application.add_handler(CommandHandler("register_winner", register_winner))
    application.add_handler(CommandHandler("list_winners", list_winners))
    application.add_handler(ChatMemberHandler(track_channel_subscription, ChatMemberHandler.CHAT_MEMBER))

    # Запуск бота
    application.run_polling(allowed_updates=['message', 'chat_member'])

if __name__ == '__main__':
    main()