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
    BotCommand
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

# ----------------- خادم وهمي لمنع إيقاف الاستضافة (Render) -----------------
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is active!")

def run_health_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
    server.serve_forever()

threading.Thread(target=run_health_server, daemon=True).start()

# ----------------- المتغيرات الأساسية -----------------
BOT_TOKEN = os.environ.get("BOT_TOKEN", "ضع_توكن_البوت_هنا")
# معرف مجموعة السائقين (يجب أن تبدأ بـ -100)
DRIVERS_GROUP_ID = int(os.environ.get("DRIVERS_GROUP_ID", -1001234567890))

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# مراحل المحادثات
RIDE_PICKUP, RIDE_DESTINATION, RIDE_COST = range(3)
DRIVER_NAME, DRIVER_PHONE, DRIVER_CAR, DRIVER_LICENSE = range(3, 7)

# ----------------- قوائم لوحات المفاتيح (Keyboards) -----------------

def passenger_main_menu():
    """قائمة الركاب الرئيسية"""
    keyboard = [
        ["🚖 طلب رحلة جديد"],
        ["🆔 تسجيل كسائق جديد"],
        ["❓ المساعدة والدعم"]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def driver_menu():
    """قائمة السائق المعتمد"""
    keyboard = [
        ["🚖 طلب رحلة جديد"],
        ["📋 بياناتي كـ سائق"],
        ["❓ المساعدة والدعم"]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# ----------------- ضبط الأوامر البصرية للبوت -----------------

async def post_init(application):
    commands = [
        BotCommand("start", "القائمة الرئيسية"),
        BotCommand("register_driver", "التسجيل كسائق جديد"),
        BotCommand("help", "المساعدة والتعليمات"),
        BotCommand("cancel", "إلغاء العملية الحالية")
    ]
    await application.bot.set_my_commands(commands)

# ----------------- بدء الاستخدام /start -----------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    approved_drivers = context.bot_data.get('approved_drivers', {})

    if user_id in approved_drivers and approved_drivers[user_id].get('status') == 'approved':
        driver_info = approved_drivers[user_id]
        msg = (
            f"أهلاً بك كابتن **{driver_info['name']}** 🚖 في تطبيق **وصلني**!\n\n"
            f"🚘 **سيارتك:** {driver_info['car']}\n"
            f"📞 **رقم هاتفك:** {driver_info['phone']}\n\n"
            f"ستصلك طلبات الركاب في مجموعة السائقين فور إرسالها."
        )
        await update.message.reply_text(msg, reply_markup=driver_menu(), parse_mode="Markdown")
    else:
        msg = (
            "أهلاً بك في بوت **وصلني** للرحلات والتوصيل 🚖\n\n"
            "• **للركاب:** يمكنك طلب رحلة مباشرة بالنقر على `🚖 طلب رحلة جديد`.\n"
            "• **للراغبين بالعمل كسائقين:** يمكنك تقديم طلب الانضمام عبر `🆔 تسجيل كسائق جديد`."
        )
        await update.message.reply_text(msg, reply_markup=passenger_main_menu(), parse_mode="Markdown")

# ----------------- مسار طلب رحلة للراكب -----------------

async def start_ride_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    location_btn = KeyboardButton(text="📍 مشاركة موقعي الحالي", request_location=True)
    markup = ReplyKeyboardMarkup([[location_btn], ["❌ إلغاء"]], resize_keyboard=True, one_time_keyboard=True)

    await update.message.reply_text(
        "الخطوة 1️⃣: حدد **نقطة الانطلاق**\n"
        "(أرسل موقعك المباشر أو اكتب العنوان نصياً):",
        reply_markup=markup,
        parse_mode="Markdown"
    )
    return RIDE_PICKUP

async def get_ride_pickup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "❌ إلغاء":
        return await cancel_conversation(update, context)

    if update.message.location:
        context.user_data['pickup'] = "موقع على الخريطة 📍"
        context.user_data['pickup_location'] = update.message.location
    else:
        context.user_data['pickup'] = update.message.text
        context.user_data['pickup_location'] = None

    cancel_btn = ReplyKeyboardMarkup([["❌ إلغاء"]], resize_keyboard=True)
    await update.message.reply_text(
        "تم تحديد الانطلاق! ✅\n\n"
        "الخطوة 2️⃣: اكتب **نقطة الوصول (الوجهة)**\n"
        "(مثال: المشفى الوطني، ساحة البلدية...):",
        reply_markup=cancel_btn,
        parse_mode="Markdown"
    )
    return RIDE_DESTINATION

async def get_ride_destination(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "❌ إلغاء":
        return await cancel_conversation(update, context)

    context.user_data['destination'] = update.message.text

    cost_buttons = [
        ["15,000 ل.س", "20,000 ل.س"],
        ["25,000 ل.س", "30,000 ل.س"],
        ["❌ إلغاء"]
    ]
    markup = ReplyKeyboardMarkup(cost_buttons, resize_keyboard=True, one_time_keyboard=True)

    await update.message.reply_text(
        "الخطوة 3️⃣: اختر أو اكتب **الكلفة التقديرية للرحلة** 💰:",
        reply_markup=markup,
        parse_mode="Markdown"
    )
    return RIDE_COST

async def get_ride_cost(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "❌ إلغاء":
        return await cancel_conversation(update, context)

    cost = update.message.text
    user = update.message.from_user
    order_id = update.message.message_id

    pickup = context.user_data.get('pickup', 'غير محدد')
    destination = context.user_data.get('destination', 'غير محدد')
    pickup_loc = context.user_data.get('pickup_location')

    # حفظ بيانات الطلب
    if 'orders' not in context.bot_data:
        context.bot_data['orders'] = {}

    context.bot_data['orders'][order_id] = {
        "passenger_id": user.id,
        "passenger_name": user.first_name,
        "pickup": pickup,
        "destination": destination,
        "cost": cost,
        "status": "pending"
    }

    # تأكيد للراكب
    await update.message.reply_text(
        f"✅ **تم إرسال طلب الرحلة بنجاح!**\n\n"
        f"📍 **الانطلاق:** {pickup}\n"
        f"🏁 **الوجهة:** {destination}\n"
        f"💰 **الكلفة التقديرية:** {cost}\n\n"
        f"جاري البحث عن كابتن... سنقوم بتبليغك فور قبول طلبك.",
        reply_markup=passenger_main_menu(),
        parse_mode="Markdown"
    )

    # إرسال الخريطة للمجموعة إن توفرت
    if pickup_loc:
        try:
            await context.bot.send_location(
                chat_id=DRIVERS_GROUP_ID,
                latitude=pickup_loc.latitude,
                longitude=pickup_loc.longitude
            )
        except Exception as e:
            logging.error(f"خطأ في إرسال الموقع: {e}")

    # إرسال تفاصيل الطلب لمجموعة السائقين
    accept_btn = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ قبول الرحلة", callback_data=f"accept_ride_{order_id}")
    ]])

    order_msg = (
        f"🔔 **طلب رحلة جديد! (#طلب_{order_id})**\n\n"
        f"👤 **الراكب:** {user.first_name}\n"
        f"📍 **الانطلاق:** {pickup}\n"
        f"🏁 **الوجهة:** {destination}\n"
        f"💰 **الكلفة التقديرية:** {cost}"
    )

    await context.bot.send_message(
        chat_id=DRIVERS_GROUP_ID,
        text=order_msg,
        reply_markup=accept_btn,
        parse_mode="Markdown"
    )

    return ConversationHandler.END

# ----------------- مسار تسجيل السائق الجديد -----------------

async def start_driver_reg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cancel_btn = ReplyKeyboardMarkup([["❌ إلغاء"]], resize_keyboard=True)
    await update.message.reply_text(
        "📝 **تسجيل كابتن جديد في بوت وصلني**\n\n"
        "الخطوة 1️⃣: أدخل **اسمك الكامل**:",
        reply_markup=cancel_btn,
        parse_mode="Markdown"
    )
    return DRIVER_NAME

async def get_driver_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "❌ إلغاء":
        return await cancel_conversation(update, context)

    context.user_data['reg_name'] = update.message.text
    await update.message.reply_text(
        "الخطوة 2️⃣: أدخل **رقم هاتفك للتواصل** (مثال: 0912345678):",
        parse_mode="Markdown"
    )
    return DRIVER_PHONE

async def get_driver_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "❌ إلغاء":
        return await cancel_conversation(update, context)

    context.user_data['reg_phone'] = update.message.text
    await update.message.reply_text(
        "الخطوة 3️⃣: أدخل **نوع السيارة ولونها ورقم اللوحة**\n"
        "(مثال: كيا ريو - بيضاء - دمشق 123456):",
        parse_mode="Markdown"
    )
    return DRIVER_CAR

async def get_driver_car(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "❌ إلغاء":
        return await cancel_conversation(update, context)

    context.user_data['reg_car'] = update.message.text
    await update.message.reply_text(
        "الخطوة 4️⃣: أدخل **رقم شهادة السواقة (أو أرسل صورة عنها)**:",
        parse_mode="Markdown"
    )
    return DRIVER_LICENSE

async def get_driver_license(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "❌ إلغاء":
        return await cancel_conversation(update, context)

    user = update.message.from_user
    license_info = update.message.text if update.message.text else "تم إرسال صورة/مستند"

    context.user_data['reg_license'] = license_info

    await update.message.reply_text(
        "✅ **تم إرسال طلب تسجيلك بنجاح!**\n"
        "طلبك قيد المراجعة الآن من قبل الإدارة. سيتم إعلامك فور الاعتماد.",
        reply_markup=passenger_main_menu(),
        parse_mode="Markdown"
    )

    approve_markup = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ موافقة واعتماد", callback_data=f"approve_driver_{user.id}"),
            InlineKeyboardButton("❌ رفض الطلب", callback_data=f"reject_driver_{user.id}")
        ]
    ])

    admin_msg = (
        f"📋 **طلب تسجيل سائق جديد!**\n\n"
        f"👤 **الاسم:** {context.user_data['reg_name']}\n"
        f"📞 **الهاتف:** `{context.user_data['reg_phone']}`\n"
        f"🚘 **السيارة:** {context.user_data['reg_car']}\n"
        f"🪪 **شهادة السواقة:** {license_info}\n"
        f"🆔 **المعرف:** @{user.username or 'بدون_معرف'} (ID: `{user.id}`)"
    )

    if 'pending_drivers' not in context.bot_data:
        context.bot_data['pending_drivers'] = {}

    context.bot_data['pending_drivers'][user.id] = {
        "name": context.user_data['reg_name'],
        "phone": context.user_data['reg_phone'],
        "car": context.user_data['reg_car'],
        "license": license_info,
        "user_id": user.id,
        "username": user.username
    }

    await context.bot.send_message(
        chat_id=DRIVERS_GROUP_ID,
        text=admin_msg,
        reply_markup=approve_markup,
        parse_mode="Markdown"
    )

    return ConversationHandler.END

# ----------------- معالجة موافقة / رفض السائق -----------------

async def handle_driver_approval(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data
    action, target_user_id_str = data.rsplit("_", 1)
    target_user_id = int(target_user_id_str)

    pending = context.bot_data.get('pending_drivers', {}).get(target_user_id)

    if not pending:
        await query.edit_message_text("⚠️ لم يتم العثور على الطلب أو تم معالجته مسبقاً.")
        return

    if 'approved_drivers' not in context.bot_data:
        context.bot_data['approved_drivers'] = {}

    if action == "approve_driver":
        pending['status'] = 'approved'
        context.bot_data['approved_drivers'][target_user_id] = pending
        del context.bot_data['pending_drivers'][target_user_id]

        await query.edit_message_text(
            f"✅ **تم اعتماد السائق بنجاح!**\n\n"
            f"👤 **الاسم:** {pending['name']}\n"
            f"📞 **الهاتف:** `{pending['phone']}`\n"
            f"🚘 **السيارة:** {pending['car']}",
            parse_mode="Markdown"
        )

        await context.bot.send_message(
            chat_id=target_user_id,
            text=f"🎉 **تهانينا كابتن {pending['name']}!**\n"
                 f"تم قبول وتفعيل حسابك كسائق معتمد في بوت **وصلني**. يمكنك الآن قبول الرحلات مباشرة من مجموعة السائقين!",
            reply_markup=driver_menu(),
            parse_mode="Markdown"
        )

    elif action == "reject_driver":
        del context.bot_data['pending_drivers'][target_user_id]
        await query.edit_message_text(f"❌ تم رفض طلب تسجيل السائق: {pending['name']}")

        await context.bot.send_message(
            chat_id=target_user_id,
            text="عذراً، تم رفض طلب تسجيلك كسائق حالياً. يمكنك التواصل مع الدعم لمزيد من التفاصيل."
        )

# ----------------- معالجة قبول الرحلة من السائق -----------------

async def handle_ride_acceptance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    driver_user = query.from_user
    order_id = int(query.data.rsplit("_", 1)[1])

    approved_drivers = context.bot_data.get('approved_drivers', {})

    # التحقق من اعتماد السائق
    if driver_user.id not in approved_drivers or approved_drivers[driver_user.id].get('status') != 'approved':
        await query.answer("⚠️ عذراً! يجب أن تكون سائقاً معتمداً ومقبولاً للتمكن من قبول الرحلات.", show_alert=True)
        return

    await query.answer()

    orders = context.bot_data.get('orders', {})
    order = orders.get(order_id)

    if not order or order.get('status') != 'pending':
        await query.edit_message_text("⚠️ عذراً، تم قبول هذه الرحلة مسبقاً من قبل سائق آخر!")
        return

    # تحديث حالة الطلب
    order['status'] = 'accepted'
    driver_info = approved_drivers[driver_user.id]

    # 1. تحديث الرسالة في مجموعة السائقين
    await query.edit_message_text(
        f"✅ **تم قبول الرحلة (#طلب_{order_id})**\n\n"
        f"👤 **الراكب:** {order['passenger_name']}\n"
        f"📍 **الانطلاق:** {order['pickup']}\n"
        f"🏁 **الوجهة:** {order['destination']}\n"
        f"💰 **الكلفة:** {order['cost']}\n\n"
        f"🚖 **الكابتن:** {driver_info['name']}\n"
        f"📞 **هاتف السائق:** `{driver_info['phone']}`\n"
        f"🚘 **السيارة:** {driver_info['car']}",
        parse_mode="Markdown"
    )

    # 2. إرسال بيانات السائق الكاملة والتكلفة إلى الراكب مباشرة
    passenger_notification = (
        f"🎉 **تم قبول طلبك! الكابتن في طريقه إليك** 🚖\n\n"
        f"👤 **اسم السائق:** {driver_info['name']}\n"
        f"📞 **رقم الهاتف:** `{driver_info['phone']}`\n"
        f"🚘 **نوع السيارة:** {driver_info['car']}\n"
        f"💰 **التكلفة المقدرة:** {order['cost']}\n\n"
        f"📍 **الانطلاق:** {order['pickup']}\n"
        f"🏁 **الوجهة:** {order['destination']}\n\n"
        f"نتمنى لك رحلة آمنة وسعيدة! 😊"
    )

    await context.bot.send_message(
        chat_id=order['passenger_id'],
        text=passenger_notification,
        parse_mode="Markdown"
    )

# ----------------- عرض البيانات والمساعدة -----------------

async def show_driver_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    approved_drivers = context.bot_data.get('approved_drivers', {})

    if user_id in approved_drivers:
        d = approved_drivers[user_id]
        msg = (
            f"📋 **بياناتك المسجلة ككابتن:**\n\n"
            f"👤 **الاسم:** {d['name']}\n"
            f"📞 **الهاتف:** `{d['phone']}`\n"
            f"🚘 **السيارة:** {d['car']}\n"
            f"🪪 **الشهادة:** {d['license']}\n"
            f"🟢 **الحالة:** حساب معتمد ونشط"
        )
    else:
        msg = "أنت غير مسجل ككابتن بعد. يمكنك التسجيل بالضغط على `🆔 تسجيل كسائق جديد`."

    await update.message.reply_text(msg, parse_mode="Markdown")

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "❓ **دليل استخدام بوت وصلني:**\n\n"
        "1️⃣ **للركاب:** اضغط `🚖 طلب رحلة جديد` واتبع الخطوات الثلاث (الانطلاق، الوجهة، السعر التقديري).\n"
        "2️⃣ **للسائقين:** اضغط `🆔 تسجيل كسائق جديد` وأدخل بياناتك. بعد الموافقة ستتمكن من قبول الطلبات مباشرة بنقرة زر!"
    )
    await update.message.reply_text(help_text, reply_markup=passenger_main_menu(), parse_mode="Markdown")

async def cancel_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "تم إلغاء العملية والعودة للقائمة الرئيسية.",
        reply_markup=passenger_main_menu()
    )
    return ConversationHandler.END

# ----------------- التشغيل الرئيسي -----------------

if __name__ == '__main__':
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()

    # معالج محادثة طلب الرحلة
    ride_handler = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex("^🚖 طلب رحلة جديد$"), start_ride_request)
        ],
        states={
            RIDE_PICKUP: [MessageHandler(filters.LOCATION | (filters.TEXT & ~filters.COMMAND), get_ride_pickup)],
            RIDE_DESTINATION: [MessageHandler(filters.LOCATION | (filters.TEXT & ~filters.COMMAND), get_ride_destination)],
            RIDE_COST: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_ride_cost)],
        },
        fallbacks=[
            CommandHandler('cancel', cancel_conversation),
            MessageHandler(filters.Regex("^❌ إلغاء$"), cancel_conversation)
        ],
    )

    # معالج محادثة تسجيل السائق
    driver_reg_handler = ConversationHandler(
        entry_points=[
            CommandHandler('register_driver', start_driver_reg),
            MessageHandler(filters.Regex("^🆔 تسجيل كسائق جديد$"), start_driver_reg)
        ],
        states={
            DRIVER_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_driver_name)],
            DRIVER_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_driver_phone)],
            DRIVER_CAR: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_driver_car)],
            DRIVER_LICENSE: [MessageHandler(filters.TEXT | filters.PHOTO | filters.ATTACHMENT, get_driver_license)],
        },
        fallbacks=[
            CommandHandler('cancel', cancel_conversation),
            MessageHandler(filters.Regex("^❌ إلغاء$"), cancel_conversation)
        ],
    )

    app.add_handler(ride_handler)
    app.add_handler(driver_reg_handler)

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(MessageHandler(filters.Regex("^📋 بياناتي كـ سائق$"), show_driver_info))
    app.add_handler(MessageHandler(filters.Regex("^❓ المساعدة والدعم$"), help_cmd))

    # معالجة أزرار الموافقة على السائقين وقبول الرحلات
    app.add_handler(CallbackQueryHandler(handle_driver_approval, pattern="^(approve_driver|reject_driver)_"))
    app.add_handler(CallbackQueryHandler(handle_ride_acceptance, pattern="^accept_ride_"))

    app.run_polling()
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
