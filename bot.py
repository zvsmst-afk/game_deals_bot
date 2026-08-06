import logging
import asyncio
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

import config
import database
from steam_parser import SteamParser
from egs_parser import EGSParser

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_post_text(draft):
    return draft['edited_text'] if draft['edited_text'] else draft['text']

async def send_draft_to_moderation(draft_id, draft):
    application = Application.builder().token(config.TOKEN).build()
    text = get_post_text(draft)
    keyboard = [
        [InlineKeyboardButton("✅ Опубликовать", callback_data=f"publish_{draft_id}"),
         InlineKeyboardButton("✏️ Редактировать", callback_data=f"edit_{draft_id}")],
        [InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_{draft_id}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await application.bot.send_message(
        chat_id=config.MODERATION_CHAT_ID,
        text=text,
        reply_markup=reply_markup,
        parse_mode='Markdown',
        disable_web_page_preview=False
    )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 Бот запущен и отслеживает скидки.\n"
        "Новые посты будут приходить в этот чат на модерацию.\n\n"
        "Доступные команды:\n"
        "/check - принудительная проверка скидок\n"
        "/status - статус бота"
    )

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "✅ Бот работает.\n"
        f"📊 Интервал проверки: {config.CHECK_INTERVAL} мин.\n"
        "🛒 Мониторинг: Steam, Epic Games Store"
    )

async def force_check(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔄 Запускаю принудительную проверку...")
    await check_deals()
    await update.message.reply_text("✅ Проверка завершена. Черновики отправлены в модерацию.")

async def publish_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    draft_id = int(query.data.split('_')[1])
    draft = database.get_draft(draft_id)
    if not draft:
        await query.edit_message_text("Черновик не найден.")
        return
    text = get_post_text(draft)
    promo_id = draft['promotion_id']
    try:
        await context.bot.send_message(
            chat_id=config.MAIN_CHANNEL_ID,
            text=text,
            parse_mode='Markdown',
            disable_web_page_preview=False
        )
        database.mark_published(draft_id, promo_id)
        await query.edit_message_text("✅ Пост опубликован в канале.")
    except Exception as e:
        logger.error(f"Ошибка публикации: {e}")
        await query.edit_message_text(f"❌ Ошибка публикации: {e}")

async def edit_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    draft_id = int(query.data.split('_')[1])
    context.user_data['editing_draft'] = draft_id
    await query.edit_message_text(
        "✏️ Отправьте новый текст поста (можно с Markdown).\n"
        "После отправки я обновлю черновик."
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
        await update.message.reply_text("Вы не редактируете ни один черновик.")
        return
    new_text = update.message.text
    database.update_draft_text(draft_id, new_text)
    context.user_data.pop('editing_draft', None)
    await update.message.reply_text("✅ Текст черновика обновлён. Теперь нажмите кнопку «Опубликовать» на исходном сообщении.")

async def check_deals():
    logger.info("Запуск проверки скидок...")
    steam = SteamParser()
    await steam.check_promotions()
    egs = EGSParser()
    await egs.check_promotions()
    conn = database.get_db_connection()
    cur = conn.cursor()
    cur.execute('''
        SELECT d.* FROM drafts d
        WHERE d.status = 'pending' AND d.sent_to_channel = 0
    ''')
    drafts = cur.fetchall()
    conn.close()
    for d in drafts:
        await send_draft_to_moderation(d['id'], d)

async def scheduler_worker():
    """Фоновый процесс для периодической проверки"""
    await check_deals()
    while True:
        await asyncio.sleep(config.CHECK_INTERVAL * 60)
        await check_deals()

async def post_init(application: Application):
    """Запускается после инициализации бота"""
    logger.info(f"Планировщик запущен, интервал {config.CHECK_INTERVAL} мин.")
    asyncio.create_task(scheduler_worker())

def main():
    application = Application.builder().token(config.TOKEN).post_init(post_init).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("check", force_check))
    application.add_handler(CallbackQueryHandler(publish_callback, pattern="^publish_"))
    application.add_handler(CallbackQueryHandler(edit_callback, pattern="^edit_"))
    application.add_handler(CallbackQueryHandler(reject_callback, pattern="^reject_"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, receive_edited_text))

    logger.info("Бот запущен и готов к работе!")
    application.run_polling()

if __name__ == '__main__':
    main()