import os
import logging
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    filters,
    ContextTypes
)

# خادم ويب وهمي لإرضاء فحص الصحة في Render
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is alive!")

def run_health_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    server.serve_forever()

# تشغيل خادم الصحة في Thread جانبي
threading.Thread(target=run_health_server, daemon=True).start()

# جلب متغيرات البيئة
BOT_TOKEN = os.environ.get("BOT_TOKEN")
DRIVERS_GROUP_ID = int(os.environ.get("DRIVERS_GROUP_ID", 0))

logging.basicConfig(level=logging.INFO)

# مراحل طلب الرحلة
PICKUP, DESTINATION = range(2)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    location_button = KeyboardButton(text="📍 مشاركة موقعي الحالي", request_location=True)
    reply_markup = ReplyKeyboardMarkup([[location_button]], resize_keyboard=True, one_time_keyboard=True)

    await update.message.reply_text(
        "أهلاً بك في خدمة توصيل القطيفة! 🚖\n\n"
        "الخطوة 1️⃣: يرجى تحديد **نقطة الانطلاق**\n"
        "(يمكنك إرسال موقعك المباشر عبر الزر في الأسفل أو كتابة العنوان نصياً):",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )
    return PICKUP

async def get_pickup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.location:
        loc = update.message.location
        context.user_data['pickup'] = f"موقع على الخريطة 📍"
        context.user_data['pickup_location'] = loc
    else:
        context.user_data['pickup'] = update.message.text
        context.user_data['pickup_location'] = None

    await update.message.reply_text(
        "تم تحديد نقطة الانطلاق بنجاح! ✅\n\n"
        "الخطوة 2️⃣: الآن اكتب أو أرسل **نقطة الوصول (الوجهة)**\n"
        "(مثال: المشفى الوطني، ساحة البلدية، شارع السوق...):",
        reply_markup=ReplyKeyboardRemove(),
        parse_mode="Markdown"
    )
    return DESTINATION

async def get_destination(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.location:
        loc = update.message.location
        context.user_data['destination'] = f"موقع على الخريطة 📍"
    else:
        context.user_data['destination'] = update.message.text

    user = update.message.from_user
    order_id = update.message.message_id
    pickup = context.user_data.get('pickup', 'غير محدد')
    destination = context.user_data.get('destination', 'غير محدد')
    pickup_loc = context.user_data.get('pickup_location')

    # حفظ بيانات الطلب
    context.bot_data[order_id] = {
        "passenger_id": user.id,
        "passenger_name": user.first_name,
        "pickup": pickup,
        "destination": destination,
        "status": "pending"
    }

    # تأكيد للراكب
    await update.message.reply_text(
        f"✅ **تم إرسال طلبك بنجاح!**\n\n"
        f"📍 **نقطة الانطلاق:** {pickup}\n"
        f"🏁 **نقطة الوصول:** {destination}\n\n"
        f"جاري البحث عن أقرب سائق... سنخطرك فور قبول الطلب.",
        parse_mode="Markdown"
    )

    # إرسال الطلب لمجموعة السائقين
    keyboard = [[InlineKeyboardButton("✅ قبول الرحلة", callback_data=f"accept_{order_id}")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    # إذا أرسل الراكب موقعه كإحداثيات، يتم إرسال موقع الخريطة أولاً للسائقين
    if pickup_loc:
        await context.bot.send_location(
            chat_id=DRIVERS_GROUP_ID,
            latitude=pickup_loc.latitude,
            longitude=pickup_loc.longitude
        )

    order_text = (
        f"🚗 **طلب رحلة جديد!**\n\n"
        f"👤 **الراكب:** {user.first_name}\n"
        f"📍 **الانطلاق:** {pickup}\n"
        f"🏁 **الوصول:** {destination}\n"
        f"🔢 **رقم الطلب:** #{order_id}"
    )

    await context.bot.send_message(
        chat_id=DRIVERS_GROUP_ID,
        text=order_text,
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "تم إلغاء طلب الرحلة.",
        reply_markup=ReplyKeyboardRemove()
    )
    return ConversationHandler.END

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

    await query.edit_message_text(
        f"✅ **تم قبول الرحلة #{order_id}**\n\n"
        f"👤 **الراكب:** {order['passenger_name']}\n"
        f"📍 **الانطلاق:** {order['pickup']}\n"
        f"🏁 **الوصول:** {order['destination']}\n"
        f"🚕 **الكابتن:** {driver.first_name}",
        parse_mode="Markdown"
    )

    await context.bot.send_message(
        chat_id=order["passenger_id"],
        text=f"🎉 **تم قبول طلبك!**\n\nالكابتن **{driver.first_name}** في طريقه إليك الآن.",
        parse_mode="Markdown"
    )

if __name__ == '__main__':
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            PICKUP: [MessageHandler(filters.LOCATION | (filters.TEXT & ~filters.COMMAND), get_pickup)],
            DESTINATION: [MessageHandler(filters.LOCATION | (filters.TEXT & ~filters.COMMAND), get_destination)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )

    app.add_handler(conv_handler)
    app.add_handler(CallbackQueryHandler(handle_accept, pattern="^accept_"))
    
    app.run_polling()
