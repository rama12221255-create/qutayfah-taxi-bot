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

# ----------------- خادم وهمي لمنع إيقاف الاستضافة -----------------
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
DRIVERS_GROUP_ID = int(os.environ.get("DRIVERS_GROUP_ID", -1001234567890))

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# مراحل المحادثات
RIDE_PICKUP = 0
DRIVER_NAME, DRIVER_PHONE, DRIVER_CAR, DRIVER_LICENSE = range(1, 5)

# ----------------- قوائم لوحات المفاتيح (Keyboards) -----------------

def passenger_main_menu():
    """قائمة الركاب الرئيسية - ثابتة ودائمة"""
    keyboard = [
        ["🚖 طلب رحلة جديد"],
        ["🆔 تسجيل كسائق جديد"],
        ["❓ المساعدة والدعم"]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, is_persistent=True)

def driver_menu():
    """قائمة السائق المعتمد - ثابتة ودائمة"""
    keyboard = [
        ["🚖 طلب رحلة جديد"],
        ["📋 بياناتي كـ سائق"],
        ["❓ المساعدة والدعم"]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, is_persistent=True)

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
            f"📞 **رقم هاتفك:** `{driver_info['phone']}`\n\n"
            f"ستصلك طلبات الركاب في مجموعة السائقين لتحديد الكلفة وقبول الرحلات."
        )
        await update.message.reply_text(msg, reply_markup=driver_menu(), parse_mode="Markdown")
    else:
        msg = (
            "أهلاً بك في بوت **وصلني** للرحلات والتوصيل 🚖\n\n"
            "• **للركاب:** يمكنك طلب رحلة مباشرة بالنقر على `🚖 طلب رحلة جديد`.\n"
            "• **للراغبين بالعمل كسائقين:** يمكنك تقديم طلب الانضمام عبر `🆔 تسجيل كسائق جديد`."
        )
        await update.message.reply_text(msg, reply_markup=passenger_main_menu(), parse_mode="Markdown")

# ----------------- مسار طلب رحلة للراكب (بدون وجهة وبدون كلفة) -----------------

async def start_ride_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    location_btn = KeyboardButton(text="📍 مشاركة موقعي الحالي", request_location=True)
    markup = ReplyKeyboardMarkup([[location_btn], ["❌ إلغاء"]], resize_keyboard=True, one_time_keyboard=True)

    await update.message.reply_text(
        "حدد **نقطة الانطلاق** 📍\n"
        "(أرسل موقعك المباشر عبر الخريطة أو اكتب العنوان نصياً):",
        reply_markup=markup,
        parse_mode="Markdown"
    )
    return RIDE_PICKUP

async def get_ride_pickup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "❌ إلغاء":
        return await cancel_conversation(update, context)

    user = update.message.from_user
    order_id = update.message.message_id

    if update.message.location:
        pickup = "موقع محدد على الخريطة 📍"
        pickup_loc = update.message.location
    else:
        pickup = update.message.text
        pickup_loc = None

    if 'orders' not in context.bot_data:
        context.bot_data['orders'] = {}

    context.bot_data['orders'][order_id] = {
        "order_id": order_id,
        "passenger_id": user.id,
        "passenger_name": user.first_name,
        "pickup": pickup,
        "pickup_location": pickup_loc,
        "status": "pending",
        "group_msg_id": None
    }

    await update.message.reply_text(
        f"✅ **تم إرسال طلب الرحلة بنجاح!**\n\n"
        f"📍 **نقطة الانطلاق:** {pickup}\n\n"
        f"جاري البحث عن كابتن وتحديد الكلفة التقديرية... سنخبرك فور قبول الطلب.",
        reply_markup=passenger_main_menu(),
        parse_mode="Markdown"
    )

    # إرسال موقع الانطلاق إن وجد إلى مجموعة السائقين
    if pickup_loc:
        try:
            await context.bot.send_location(
                chat_id=DRIVERS_GROUP_ID,
                latitude=pickup_loc.latitude,
                longitude=pickup_loc.longitude
            )
        except Exception as e:
            logging.error(f"خطأ في إرسال الموقع: {e}")

    accept_btn = InlineKeyboardMarkup([[
        InlineKeyboardButton("💰 تحديد الكلفة وقبول الرحلة", callback_data=f"set_cost_{order_id}")
    ]])

    order_msg = (
        f"🔔 **طلب رحلة جديد! (#طلب_{order_id})**\n\n"
        f"👤 **الراكب:** {user.first_name}\n"
        f"📍 **نقطة الانطلاق:** {pickup}\n\n"
        f"👇 يرجى النقر على الزر أدناه لتحديد الكلفة التقديرية وقبول الطلب."
    )

    sent_msg = await context.bot.send_message(
        chat_id=DRIVERS_GROUP_ID,
        text=order_msg,
        reply_markup=accept_btn,
        parse_mode="Markdown"
    )

    context.bot_data['orders'][order_id]['group_msg_id'] = sent_msg.message_id

    return ConversationHandler.END

# ----------------- تحديد الكلفة والقبول من قبل السائق -----------------

async def handle_set_cost_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    driver_user = query.from_user
    order_id = int(query.data.rsplit("_", 1)[1])

    approved_drivers = context.bot_data.get('approved_drivers', {})

    if driver_user.id not in approved_drivers or approved_drivers[driver_user.id].get('status') != 'approved':
        await query.answer("⚠️ عذراً! يجب أن تكون سائقاً معتمداً لتحديد الكلفة وقبول الرحلات.", show_alert=True)
        return

    orders = context.bot_data.get('orders', {})
    order = orders.get(order_id)

    if not order or order.get('status') != 'pending':
        await query.answer("⚠️ عذراً، تم قبول هذه الرحلة مسبقاً من قبل سائق آخر!", show_alert=True)
        return

    await query.answer()

    # حفظ معرّف الطلب في جلسة السائق
    context.user_data['pending_cost_order_id'] = order_id

    # أزرار كلفة سريعة مع إمكانية الكتابة النصية في خاص البوت
    quick_costs = [
        [InlineKeyboardButton("15,000 ل.س", callback_data=f"costval_{order_id}_15,000 ل.س"),
         InlineKeyboardButton("20,000 ل.س", callback_data=f"costval_{order_id}_20,000 ل.س")],
        [InlineKeyboardButton("25,000 ل.س", callback_data=f"costval_{order_id}_25,000 ل.س"),
         InlineKeyboardButton("30,000 ل.س", callback_data=f"costval_{order_id}_30,000 ل.س")]
    ]
    markup = InlineKeyboardMarkup(quick_costs)

    try:
        await context.bot.send_message(
            chat_id=driver_user.id,
            text=f"🚖 **تحديد الكلفة التقديرية للطلب (#طلب_{order_id}):**\n\n"
                 f"📍 **نقطة الانطلاق:** {order['pickup']}\n\n"
                 f"اختر الكلفة من الأزرار السريعة أدناه، أو **اكتب المبلغ نصياً** وأرسله هنا مباشرة:",
            reply_markup=markup,
            parse_mode="Markdown"
        )
    except Exception:
        await context.bot.send_message(
            chat_id=DRIVERS_GROUP_ID,
            text=f"⚠️ الكابتن [{driver_user.first_name}](tg://user?id={driver_user.id}) يرجى بدء المحادثة في الخاص مع البوت أولاً لتمكن من إدخال الكلفة!",
            parse_mode="Markdown"
        )

async def handle_private_text_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة إدخال السائق للكلفة نصياً في المحادثة الخاصة"""
    order_id = context.user_data.get('pending_cost_order_id')
    if order_id:
        cost_text = update.message.text
        user_id = update.effective_user.id
        await finalize_ride_acceptance(update, context, order_id, user_id, cost_text)
        context.user_data['pending_cost_order_id'] = None

async def handle_cost_button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """معالجة اختيار السائق للكلفة عبر الأزرار السريعة"""
    query = update.callback_query
    data_parts = query.data.split("_", 2)
    order_id = int(data_parts[1])
    cost_text = data_parts[2]

    await query.answer()
    await finalize_ride_acceptance(update, context, order_id, query.from_user.id, cost_text)

async def finalize_ride_acceptance(update: Update, context: ContextTypes.DEFAULT_TYPE, order_id: int, driver_id: int, cost_text: str):
    orders = context.bot_data.get('orders', {})
    order = orders.get(order_id)

    if not order or order.get('status') != 'pending':
        msg = "⚠️ عذراً، تم قبول هذه الرحلة مسبقاً من قبل سائق آخر!"
        if update.callback_query:
            await update.callback_query.edit_message_text(msg)
        elif update.message:
            await update.message.reply_text(msg)
        return

    approved_drivers = context.bot_data.get('approved_drivers', {})
    driver_info = approved_drivers.get(driver_id)

    if not driver_info:
        return

    order['status'] = 'accepted'
    order['cost'] = cost_text
    order['driver_id'] = driver_id

    # 1. تحديث الرسالة في مجموعة السائقين
    group_msg_text = (
        f"✅ **تم قبول الرحلة (#طلب_{order_id})**\n\n"
        f"👤 **الراكب:** {order['passenger_name']}\n"
        f"📍 **الانطلاق:** {order['pickup']}\n"
        f"💰 **الكلفة التقديرية:** {cost_text}\n\n"
        f"🚖 **الكابتن:** {driver_info['name']}\n"
        f"📞 **هاتف السائق:** `{driver_info['phone']}`\n"
        f"🚘 **السيارة:** {driver_info['car']}"
    )

    try:
        await context.bot.edit_message_text(
            chat_id=DRIVERS_GROUP_ID,
            message_id=order['group_msg_id'],
            text=group_msg_text,
            parse_mode="Markdown"
        )
    except Exception as e:
        logging.error(f"خطأ في تعديل رسالة المجموعة: {e}")

    # 2. تأكيد للسائق
    confirm_driver_msg = (
        f"✅ **تم إرسال قبولك وتحديد الكلفة بنجاح!**\n\n"
        f"💰 **الكلفة المحددة:** {cost_text}\n"
        f"📍 **نقطة الانطلاق:** {order['pickup']}\n"
        f"👤 **اسم الراكب:** {order['passenger_name']}"
    )
    if update.callback_query:
        await update.callback_query.edit_message_text(confirm_driver_msg, parse_mode="Markdown")
    elif update.message:
        await update.message.reply_text(confirm_driver_msg, parse_mode="Markdown")

    # 3. إشعار للراكب مع إظهار القائمة الرئيسية
    passenger_notification = (
        f"🎉 **تم قبول طلبك! الكابتن {driver_info['name']} في طريقه إليك** 🚖\n\n"
        f"👤 **اسم السائق:** {driver_info['name']}\n"
        f"📞 **رقم الهاتف:** `{driver_info['phone']}`\n"
        f"🚘 **نوع السيارة:** {driver_info['car']}\n"
        f"💰 **الكلفة التقديرية للرحلة:** {cost_text}\n\n"
        f"📍 **نقطة الانطلاق:** {order['pickup']}\n\n"
        f"نتمنى لك رحلة آمنة وسعيدة! 😊"
    )

    await context.bot.send_message(
        chat_id=order['passenger_id'],
        text=passenger_notification,
        reply_markup=passenger_main_menu(),
        parse_mode="Markdown"
    )

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
                 f"تم قبول وتفعيل حسابك كسائق معتمد في بوت **وصلني**. يمكنك الآن قبول الرحلات وتحديد الكلفة مباشرة من مجموعة السائقين!",
            reply_markup=driver_menu(),
            parse_mode="Markdown"
        )

    elif action == "reject_driver":
        del context.bot_data['pending_drivers'][target_user_id]
        await query.edit_message_text(f"❌ تم رفض طلب تسجيل السائق: {pending['name']}")

        await context.bot.send_message(
            chat_id=target_user_id,
            text="عذراً، تم رفض طلب تسجيلك كسائق حالياً. يمكنك التواصل مع الدعم لمزيد من التفاصيل.",
            reply_markup=passenger_main_menu()
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
        await update.message.reply_text(msg, reply_markup=driver_menu(), parse_mode="Markdown")
    else:
        msg = "أنت غير مسجل ككابتن بعد. يمكنك التسجيل بالضغط على `🆔 تسجيل كسائق جديد`."
        await update.message.reply_text(msg, reply_markup=passenger_main_menu(), parse_mode="Markdown")

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "❓ **دليل استخدام بوت وصلني:**\n\n"
        "1️⃣ **للركاب:** اضغط `🚖 طلب رحلة جديد` وقم بإرسال موقع الانطلاق فقط.\n"
        "2️⃣ **للسائقين:** اضغط `🆔 تسجيل كسائق جديد` وأدخل بياناتك. بعد الموافقة ستتمكن من تحديد كلفة الرحلة وقبول الطلبات بنقرة زر!"
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

    ride_handler = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex("^🚖 طلب رحلة جديد$"), start_ride_request)
        ],
        states={
            RIDE_PICKUP: [MessageHandler(filters.LOCATION | (filters.TEXT & ~filters.COMMAND), get_ride_pickup)],
        },
        fallbacks=[
            CommandHandler('cancel', cancel_conversation),
            MessageHandler(filters.Regex("^❌ إلغاء$"), cancel_conversation)
        ],
    )

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

    app.add_handler(CallbackQueryHandler(handle_driver_approval, pattern="^(approve_driver|reject_driver)_"))
    app.add_handler(CallbackQueryHandler(handle_set_cost_click, pattern="^set_cost_"))
    app.add_handler(CallbackQueryHandler(handle_cost_button_click, pattern="^costval_"))
    
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE, handle_private_text_messages))

    app.run_polling()
