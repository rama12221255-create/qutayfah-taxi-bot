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
PICKUP, DESTINATION, COST = range(3)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    location_button = KeyboardButton(text="📍 مشاركة موقعي الحالي", request_location=True)
    reply_markup = ReplyKeyboardMarkup([[location_button]], resize_keyboard=True, one_time_keyboard=True)

    await update.message.reply_text(
        "أهلاً بك في خدمة توصيل القطيفة! 🚖\n\n"
        "الخطوة 1️⃣: حدد **نقطة الانطلاق**\n"
        "(أرسل موقعك المباشر أو اكتب العنوان نصياً):",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )
    return PICKUP

async def get_pickup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.location:
        loc = update.message.location
        context.user_data['pickup'] = "موقع على الخريطة 📍"
        context.user_data['pickup_location'] = loc
    else:
        context.user_data['pickup'] = update.message.text
        context.user_data['pickup_location'] = None

    await update.message.reply_text(
        "تم تحديد نقطة الانطلاق بنجاح! ✅\n\n"
        "الخطوة 2️⃣: اكتب أو أرسل **نقطة الوصول (الوجهة)**\n"
        "(مثال: المشفى الوطني، ساحة البلدية، شارع السوق...):",
        reply_markup=ReplyKeyboardRemove(),
        parse_mode="Markdown"
    )
    return DESTINATION

async def get_destination(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.location:
        context.user_data['destination'] = "موقع على الخريطة 📍"
    else:
        context.user_data['destination'] = update.message.text

    # أزرار سريعة للكلفة التقديرية
    cost_buttons = [
        ["15,000 ل.س", "20,000 ل.س"],
        ["25,000 ل.س", "30,000 ل.س"]
    ]
    reply_markup = ReplyKeyboardMarkup(cost_buttons, resize_keyboard=True, one_time_keyboard=True)

    await update.message.reply_text(
        "الخطوة 3️⃣: اختر أو اكتب **الكلفة التقديرية للرحلة** 💰\n"
        "(يمكنك اختيار مبلغ من الأزرار الأدناه أو كتابة مبلغ آخر):",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )
    return COST

async def get_cost(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cost = update.message.text
    context.user_data['cost'] = cost

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
        "cost": cost,
        "status": "pending"
    }

    # تأكيد للراكب
    await update.message.reply_text(
        f"✅ **تم إرسال طلبك بنجاح!**\n\n"
        f"📍 **الانطلاق:** {pickup}\n"
        f"🏁 **الوصول:** {destination}\n"
        f"💰 **الكلفة التقديرية:** {cost}\n\n"
        f"جاري البحث عن أقرب سائق... سنخطرك فور قبول الطلب.",
        reply_markup=ReplyKeyboardRemove(),
        parse_mode="Markdown"
    )

    # إرسال موقع الانطلاق كخريطة أولاً إذا كان متوفراً
    if pickup_loc:
        await context.bot.send_location(
            chat_id=DRIVERS_GROUP_ID,
            latitude=pickup_loc.latitude,
            longitude=pickup_loc.longitude
        )

    # إرسال تفاصيل الطلب لمجموعة السائقين
    keyboard = [[InlineKeyboardButton("✅ قبول الرحلة", callback_data=f"accept_{order_id}")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    order_text = (
        f"🚗 **طلب رحلة جديد!**\n\n"
        f"👤 **الراكب:** {user.first_name}\n"
        f"📍 **الانطلاق:** {pickup}\n"
        f"🏁 **الوصول:** {destination}\n"
        f"💰 **الكلفة التقديرية:** {cost}\n"
        f"🔢 **رقم الطلب:** #{order_id}"
    )

    await context.bot.send_message(
        chat_id=DRIVERS_GROUP_ID,
        text=order_text,
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

    return ConversationHandler.END

async def set_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """أمر ليقوم السائق بتسجيل رقم هاتفه في البوت"""
    if not context.args:
        await update.message.reply_text(
            "⚠️ **طريقة التسجيل:**\n"
            "اكتب الأمر متبوعاً برقم هاتفك، مثال:\n"
            "`/phone 0912345678`",
            parse_mode="Markdown"
        )
        return

    phone = context.args[0]
    user_id = update.message.from_user.id
    
    if 'driver_phones' not in context.bot_data:
        context.bot_data['driver_phones'] = {}
        
    context.bot_data['driver_phones'][user_id] = phone

    await update.message.reply_text(
        f"✅ تم حفظ رقم هاتفك بنجاح: `{phone}`\n"
        f"سيتم إظهار هذا الرقم للركاب عند قبولك لأي رحلة.",
        parse_mode="Markdown"
    )

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

    # جلب رقم هاتف السائق إن وجد
    driver_phones = context.bot_data.get('driver_phones', {})
    driver_phone = driver_phones.get(driver.id, "غير مسجل (يمكن الاتصال عبر تلغرام)")

    driver_username = f"@{driver.username}" if driver.username else "لا يوجد اسم مستخدم"

    # تحديث الرسالة في مجموعة السائقين
    await query.edit_message_text(
        f"✅ **تم قبول الرحلة #{order_id}**\n\n"
        f"👤 **الراكب:** {order['passenger_name']}\n"
        f"📍 **الانطلاق:** {order['pickup']}\n"
        f"🏁 **الوصول:** {order['destination']}\n"
        f"💰 **الكلفة:** {order['cost']}\n"
        f"🚕 **الكابتن:** {driver.first_name}",
        parse_mode="Markdown"
    )

    # إرسال تفاصيل السائق الكاملة للراكب
    passenger_msg = (
        f"🎉 **تم قبول طلبك!**\n\n"
        f"🚕 **الكابتن:** {driver.first_name}\n"
        f"📞 **رقم الهاتف:** `{driver_phone}`\n"
        f"💬 **حساب تلغرام:** {driver_username}\n"
        f"💰 **الكلفة التقديرية:** {order['cost']}\n\n"
        f"الكابتن في طريقه إليك الآن!"
    )

    await context.bot.send_message(
        chat_id=order["passenger_id"],
        text=passenger_msg,
        parse_mode="Markdown"
    )

if __name__ == '__main__':
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            PICKUP: [MessageHandler(filters.LOCATION | (filters.TEXT & ~filters.COMMAND), get_pickup)],
            DESTINATION: [MessageHandler(filters.LOCATION | (filters.TEXT & ~filters.COMMAND), get_destination)],
            COST: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_cost)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )

    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("phone", set_phone))
    app.add_handler(CallbackQueryHandler(handle_accept, pattern="^accept_"))
    
    app.run_polling()
