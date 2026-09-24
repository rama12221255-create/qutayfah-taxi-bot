import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

# جلب البيانات الحساسة من متغيرات البيئة في السيرفر
BOT_TOKEN = os.environ.get("BOT_TOKEN")
DRIVERS_GROUP_ID = int(os.environ.get("DRIVERS_GROUP_ID", 0))

logging.basicConfig(level=logging.INFO)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "أهلاً بك في خدمة توصيل القطيفة!\nيرجى مشاركة موقعك الجغرافي الحالي عبر تلغرام لبدء طلب سيارة."
    )

async def handle_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    location = update.message.location
    order_id = update.message.message_id
    
    context.bot_data[order_id] = {
        "passenger_id": user.id,
        "passenger_name": user.first_name,
        "status": "pending"
    }

    keyboard = [[InlineKeyboardButton("✅ قبول الرحلة", callback_data=f"accept_{order_id}")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # إرسال موقع الراكب لمجموعة السائقين
    await context.bot.send_location(
        chat_id=DRIVERS_GROUP_ID,
        latitude=location.latitude,
        longitude=location.longitude
    )
    await context.bot.send_message(
        chat_id=DRIVERS_GROUP_ID,
        text=f"🚗 **طلب رحلة جديد!**\nالراكب: {user.first_name}\nالطلب رقم: #{order_id}",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

    await update.message.reply_text("جاري البحث عن أقرب سائق في القطيفة... سنخطرك فور قبول الطلب.")

async def handle_accept(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    driver = query.from_user
    order_id = int(query.data.split("_")[1])
    order = context.bot_data.get(order_id)

    if not order or order["status"] != "pending":
        await query.edit_message_text("⚠️ عذراً، تم قبول هذه الرحلة من قبل سائق آخر!")
        return

    order["status"] = "accepted"

    await query.edit_message_text(f"✅ تم قبول الرحلة #{order_id} بواسطة الكابتن: {driver.first_name}")

    await context.bot.send_message(
        chat_id=order["passenger_id"],
        text=f"🎉 تم قبول طلبك!\nالكابتن {driver.first_name} في طريقه إليك."
    )

if __name__ == '__main__':
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.LOCATION, handle_location))
    app.add_handler(CallbackQueryHandler(handle_accept, pattern="^accept_"))
    app.run_polling()
