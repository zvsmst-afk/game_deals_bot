import logging
import asyncio
import os
from datetime import datetime, timedelta

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

import config
import database
from steam_parser import SteamParser
from egs_parser import EGSParser

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

POST_DELAY = 30
is_checking = False

# ============ REPLY КЛАВИАТУРА ============
def get_main_keyboard():
    keyboard = [
        [KeyboardButton("📊 Статус")],
        [KeyboardButton("🔄 Проверить скидки")],
        [KeyboardButton("🗑 Очистить черновики")],
        [KeyboardButton("⚠️ Очистить ВСЮ базу")],
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# ============ КНОПКИ ВЫБОРА ВРЕМЕНИ ============
def get_time_keyboard(draft_id):
    keyboard = [
        [InlineKeyboardButton("📅 Сейчас", callback_data=f"publish_now_{draft_id}")],
        [InlineKeyboardButton("⏰ Через 5 мин", callback_data=f"publish_delay_{draft_id}_5")],
        [InlineKeyboardButton("⏰ Через 15 мин", callback_data=f"publish_delay_{draft_id}_15")],
        [InlineKeyboardButton("⏰ Через 30 мин", callback_data=f"publish_delay_{draft_id}_30")],
        [InlineKeyboardButton("⏰ Через 1 час", callback_data=f"publish_delay_{draft_id}_60")],
        [InlineKeyboardButton("⏰ Через 3 часа", callback_data=f"publish_delay_{draft_id}_180")],
        [InlineKeyboardButton("⏰ Через 6 часов", callback_data=f"publish_delay_{draft_id}_360")],
        [InlineKeyboardButton("⏰ Завтра в 10:00", callback_data=f"publish_tomorrow_{draft_id}")],
        [InlineKeyboardButton("❌ Отмена", callback_data=f"cancel_publish_{draft_id}")],
    ]
    return InlineKeyboardMarkup(keyboard)

# ============ ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ============
def get_post_text(draft):
    return draft['edited_text'] if draft['edited_text'] else draft['text']

async def send_image_and_text(chat_id, text, image_url):
    """Отправляет картинку и текст в одном сообщении"""
    application = Application.builder().token(config.TOKEN).build()
    
    try:
        if image_url:
            await application.bot.send_photo(
                chat_id=chat_id,
                photo=image_url,
                caption=text,
                parse_mode='HTML',
                disable_web_page_preview=True
            )
            logger.info(f"✅ Отправлено с картинкой: {image_url}")
        else:
            await application.bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode='HTML',
                disable_web_page_preview=True
            )
    except Exception as e:
        logger.error(f"Ошибка отправки: {e}")
        await application.bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode='HTML',
            disable_web_page_preview=True
        )

async def send_draft_to_moderation(draft_id, draft):
    """Отправляет черновик в модерацию с картинкой"""
    text = get_post_text(draft)
    
    conn = database.get_db_connection()
    cur = conn.cursor()
    cur.execute('SELECT image_url FROM promotions WHERE id = ?', (draft['promotion_id'],))
    promo = cur.fetchone()
    conn.close()
    
    image_url = promo['image_url'] if promo and promo['image_url'] else None
    
    keyboard = [
        [InlineKeyboardButton("✅ Опубликовать", callback_data=f"publish_{draft_id}")],
        [InlineKeyboardButton("✏️ Редактировать", callback_data=f"edit_{draft_id}")],
        [InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_{draft_id}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    application = Application.builder().token(config.TOKEN).build()
    
    try:
        if image_url:
            await application.bot.send_photo(
                chat_id=config.MODERATION_CHAT_ID,
                photo=image_url,
                caption=text,
                reply_markup=reply_markup,
                parse_mode='HTML',
                disable_web_page_preview=True
            )
        else:
            await application.bot.send_message(
                chat_id=config.MODERATION_CHAT_ID,
                text=text,
                reply_markup=reply_markup,
                parse_mode='HTML',
                disable_web_page_preview=True
            )
    except Exception as e:
        logger.error(f"Ошибка отправки в модерацию: {e}")
        await application.bot.send_message(
            chat_id=config.MODERATION_CHAT_ID,
            text=text,
            reply_markup=reply_markup,
            parse_mode='HTML',
            disable_web_page_preview=True
        )
    
    logger.info(f"⏳ Ожидание {POST_DELAY} секунд перед следующим постом...")
    await asyncio.sleep(POST_DELAY)

# ============ ОБРАБОТЧИКИ ============
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 **Бот для отслеживания скидок**\n\n"
        "Нажмите кнопку внизу экрана, чтобы выбрать действие.",
        reply_markup=get_main_keyboard(),
        parse_mode='Markdown'
    )

async def handle_any_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    
    if text == "📊 Статус":
        await show_status(update)
    elif text == "🔄 Проверить скидки":
        await force_check(update)
    elif text == "🗑 Очистить черновики":
        await clear_drafts(update)
    elif text == "⚠️ Очистить ВСЮ базу":
        await clear_db(update)
    else:
        await update.message.reply_text(
            "🤖 **Главное меню**\n\n"
            "Нажмите кнопку внизу экрана:",
            reply_markup=get_main_keyboard(),
            parse_mode='Markdown'
        )

# ============ ДЕЙСТВИЯ ============
async def show_status(update):
    conn = database.get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM drafts WHERE status = 'pending'")
    pending_count = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM promotions WHERE published = 1")
    published_count = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM drafts WHERE status = 'scheduled'")
    scheduled_count = cur.fetchone()[0]
    conn.close()

    status_text = (
        f"📊 **Статус бота**\n\n"
        f"✅ Бот работает\n"
        f"📅 Интервал проверки: {config.CHECK_INTERVAL} мин.\n"
        f"⏳ Задержка между постами: {POST_DELAY} сек.\n"
        f"🛒 Мониторинг: Steam, Epic Games Store\n\n"
        f"📝 Ожидают модерации: {pending_count}\n"
        f"⏰ Запланировано: {scheduled_count}\n"
        f"📤 Опубликовано: {published_count}"
    )
    
    await update.message.reply_text(
        status_text,
        reply_markup=get_main_keyboard(),
        parse_mode='Markdown'
    )

async def force_check(update):
    global is_checking
    if is_checking:
        await update.message.reply_text(
            "⚠️ Проверка уже выполняется. Подождите...",
            reply_markup=get_main_keyboard()
        )
        return
    
    await update.message.reply_text(
        "🔄 Запускаю принудительную проверку...\n\n"
        "Это может занять 1-2 минуты.",
        reply_markup=get_main_keyboard()
    )
    await check_deals()
    await update.message.reply_text(
        "✅ Проверка завершена! Черновики отправлены в модерацию.",
        reply_markup=get_main_keyboard()
    )

async def clear_drafts(update):
    conn = database.get_db_connection()
    cur = conn.cursor()
    
    cur.execute("SELECT COUNT(*) FROM drafts WHERE status = 'pending'")
    before = cur.fetchone()[0]
    logger.info(f"🔍 До очистки: {before} черновиков")
    
    cur.execute("DELETE FROM drafts WHERE status = 'pending'")
    deleted = cur.rowcount
    
    cur.execute("UPDATE promotions SET notified = 0 WHERE notified = 1")
    
    conn.commit()
    conn.close()
    
    logger.info(f"🗑 Удалено: {deleted} черновиков")
    await update.message.reply_text(
        f"✅ Удалено черновиков: {deleted}\n\n"
        "Все ожидающие модерации черновики удалены.",
        reply_markup=get_main_keyboard()
    )

async def clear_db(update):
    keyboard = [
        [InlineKeyboardButton("✅ Да, удалить всё", callback_data="confirm_clear_db")],
        [InlineKeyboardButton("❌ Отмена", callback_data="cancel_clear_db")]
    ]
    await update.message.reply_text(
        "⚠️ **ВНИМАНИЕ!**\n\n"
        "Вы собираетесь полностью очистить базу данных.\n"
        "Будут удалены ВСЕ черновики и история публикаций.\n\n"
        "Вы уверены?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode='Markdown'
    )

async def confirm_clear_db(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        if os.path.exists(config.DATABASE):
            os.remove(config.DATABASE)
            await query.edit_message_text(
                "✅ База данных полностью очищена.\n\n"
                "Бот будет перезапущен автоматически."
            )
            os._exit(0)
        else:
            await query.edit_message_text(
                "❌ База данных не найдена."
            )
    except Exception as e:
        await query.edit_message_text(
            f"❌ Ошибка: {e}"
        )

async def cancel_clear_db(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        "❌ Очистка отменена.",
        reply_markup=get_main_keyboard()
    )

# ============ МОДЕРАЦИЯ С ОТЛОЖЕННОЙ ПУБЛИКАЦИЕЙ ============
async def publish_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    draft_id = int(query.data.split('_')[1])
    
    draft = database.get_draft(draft_id)
    if not draft:
        await query.edit_message_text("❌ Черновик не найден.")
        return
    
    await query.edit_message_text(
        "⏰ **Выберите время публикации:**\n\n"
        f"Пост: {draft['text'][:100]}...\n\n"
        "Когда отправить в канал?",
        reply_markup=get_time_keyboard(draft_id),
        parse_mode='HTML'
    )

async def schedule_publish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    if data.startswith("cancel_publish_"):
        draft_id = int(data.split('_')[2])
        await query.edit_message_text("❌ Публикация отменена.\n\nЧерновик сохранён для дальнейшей модерации.")
        return
    
    parts = data.split('_')
    draft_id = int(parts[2])
    
    draft = database.get_draft(draft_id)
    if not draft:
        await query.edit_message_text("❌ Черновик не найден.")
        return
    
    conn = database.get_db_connection()
    cur = conn.cursor()
    cur.execute('SELECT image_url FROM promotions WHERE id = ?', (draft['promotion_id'],))
    promo = cur.fetchone()
    conn.close()
    
    image_url = promo['image_url'] if promo and promo['image_url'] else None
    
    text = get_post_text(draft)
    promo_id = draft['promotion_id']
    
    if parts[1] == "now":
        await publish_post_now(query, draft_id, promo_id, text, image_url)
    elif parts[1] == "delay":
        delay_minutes = int(parts[3])
        await schedule_post_with_delay(query, draft_id, promo_id, text, image_url, delay_minutes)
    elif parts[1] == "tomorrow":
        await schedule_post_tomorrow(query, draft_id, promo_id, text, image_url)

async def publish_post_now(query, draft_id, promo_id, text, image_url):
    try:
        await send_image_and_text(
            chat_id=config.MAIN_CHANNEL_ID,
            text=text,
            image_url=image_url
        )
        database.mark_published(draft_id, promo_id)
        await query.edit_message_text("✅ Пост опубликован в канале!")
    except Exception as e:
        logger.error(f"Ошибка публикации: {e}")
        await query.edit_message_text(f"❌ Ошибка публикации: {e}")

async def schedule_post_with_delay(query, draft_id, promo_id, text, image_url, delay_minutes):
    await query.edit_message_text(
        f"⏰ Пост будет опубликован через {delay_minutes} минут.\n\n"
        f"⚠️ Не выключайте бота до этого времени!"
    )
    
    conn = database.get_db_connection()
    cur = conn.cursor()
    cur.execute('UPDATE drafts SET status = "scheduled" WHERE id = ?', (draft_id,))
    conn.commit()
    conn.close()
    
    await asyncio.sleep(delay_minutes * 60)
    
    try:
        await send_image_and_text(
            chat_id=config.MAIN_CHANNEL_ID,
            text=text,
            image_url=image_url
        )
        database.mark_published(draft_id, promo_id)
        logger.info(f"✅ Запланированный пост {draft_id} опубликован")
    except Exception as e:
        logger.error(f"Ошибка запланированной публикации: {e}")

async def schedule_post_tomorrow(query, draft_id, promo_id, text, image_url):
    now = datetime.now()
    tomorrow = now + timedelta(days=1)
    target_time = tomorrow.replace(hour=10, minute=0, second=0, microsecond=0)
    delay_seconds = (target_time - now).total_seconds()
    
    await query.edit_message_text(
        f"⏰ Пост будет опубликован завтра в 10:00.\n\n"
        f"⚠️ Не выключайте бота до этого времени!"
    )
    
    conn = database.get_db_connection()
    cur = conn.cursor()
    cur.execute('UPDATE drafts SET status = "scheduled" WHERE id = ?', (draft_id,))
    conn.commit()
    conn.close()
    
    await asyncio.sleep(delay_seconds)
    
    try:
        await send_image_and_text(
            chat_id=config.MAIN_CHANNEL_ID,
            text=text,
            image_url=image_url
        )
        database.mark_published(draft_id, promo_id)
        logger.info(f"✅ Запланированный пост {draft_id} опубликован завтра в 10:00")
    except Exception as e:
        logger.error(f"Ошибка запланированной публикации: {e}")

async def edit_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    draft_id = int(query.data.split('_')[1])
    
    context.user_data['editing_draft'] = draft_id
    context.user_data['editing_message_id'] = query.message.message_id
    context.user_data['editing_chat_id'] = query.message.chat_id
    
    await query.edit_message_text(
        "✏️ **Отправьте новый текст поста**\n\n"
        "Поддерживается HTML:\n"
        "• `<b>жирный</b>`\n"
        "• `<s>зачёркнутый</s>`\n"
        "• `<a href='ссылка'>текст</a>`\n\n"
        "Просто напишите новый текст в ответ на это сообщение.",
        parse_mode='Markdown'
    )

async def reject_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    draft_id = int(query.data.split('_')[1])
    database.reject_draft(draft_id)
    await query.edit_message_text("❌ Черновик отклонён.")

async def receive_edited_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    draft_id = context.user_data.get('editing_draft')
    if not draft_id:
        await update.message.reply_text("❌ Вы не редактируете ни один черновик.")
        return
    
    new_text = update.message.text
    database.update_draft_text(draft_id, new_text)
    
    keyboard = [
        [InlineKeyboardButton("✅ Опубликовать", callback_data=f"publish_{draft_id}")],
        [InlineKeyboardButton("✏️ Редактировать", callback_data=f"edit_{draft_id}")],
        [InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_{draft_id}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    try:
        chat_id = context.user_data.get('editing_chat_id')
        message_id = context.user_data.get('editing_message_id')
        
        if chat_id and message_id:
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=new_text,
                reply_markup=reply_markup,
                parse_mode='HTML',
                disable_web_page_preview=True
            )
        else:
            await update.message.reply_text(
                new_text,
                reply_markup=reply_markup,
                parse_mode='HTML',
                disable_web_page_preview=True
            )
    except Exception as e:
        logger.error(f"Ошибка обновления сообщения: {e}")
        await update.message.reply_text(
            f"✅ Текст обновлён, но не удалось обновить исходное сообщение.\n\n{new_text}",
            reply_markup=reply_markup,
            parse_mode='HTML',
            disable_web_page_preview=True
        )
    
    context.user_data.pop('editing_draft', None)
    context.user_data.pop('editing_message_id', None)
    context.user_data.pop('editing_chat_id', None)
    
    await update.message.reply_text(
        "✅ Редактирование завершено!",
        reply_markup=get_main_keyboard()
    )

# ============ ОСНОВНАЯ ЛОГИКА ============
async def check_deals():
    global is_checking
    if is_checking:
        logger.info("⚠️ Проверка уже выполняется, пропускаю...")
        return
    is_checking = True
    
    try:
        logger.info("Запуск проверки скидок...")
        steam = SteamParser()
        await steam.check_promotions()
        egs = EGSParser()
        await egs.check_promotions()
        
        drafts = database.get_pending_drafts()
        
        if drafts:
            logger.info(f"📨 Найдено {len(drafts)} черновиков. Отправка с задержкой {POST_DELAY} секунд...")
        
        for d in drafts:
            await send_draft_to_moderation(d['id'], d)
    finally:
        is_checking = False

async def scheduler_worker():
    await check_deals()
    while True:
        await asyncio.sleep(config.CHECK_INTERVAL * 60)
        await check_deals()

async def post_init(application: Application):
    logger.info(f"Планировщик запущен, интервал {config.CHECK_INTERVAL} мин.")
    logger.info(f"⏳ Задержка между постами: {POST_DELAY} секунд")
    asyncio.create_task(scheduler_worker())

# ============ ЗАПУСК ============
def main():
    application = Application.builder().token(config.TOKEN).post_init(post_init).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_any_message))
    application.add_handler(CallbackQueryHandler(publish_callback, pattern="^publish_\\d+$"))
    application.add_handler(CallbackQueryHandler(schedule_publish, pattern="^(publish_now_|publish_delay_|publish_tomorrow_|cancel_publish_)"))
    application.add_handler(CallbackQueryHandler(edit_callback, pattern="^edit_"))
    application.add_handler(CallbackQueryHandler(reject_callback, pattern="^reject_"))
    application.add_handler(CallbackQueryHandler(confirm_clear_db, pattern="^confirm_clear_db"))
    application.add_handler(CallbackQueryHandler(cancel_clear_db, pattern="^cancel_clear_db"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, receive_edited_text))

    logger.info("🚀 Бот запущен и готов к работе!")
    application.run_polling()

if __name__ == '__main__':
    main()