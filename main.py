import os
import logging
import sqlite3
import threading
import math
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
    BotCommand,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)


# ============================================================
# إعدادات المشروع
# ============================================================

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

ADMIN_IDS = {
    int(x.strip())
    for x in os.environ.get("ADMIN_IDS", "").split(",")
    if x.strip().isdigit()
}

CITY_NAME = os.environ.get("CITY_NAME", "القطيفة")

DB_FILE = os.environ.get("DB_FILE", "waselni.db")

PORT = int(os.environ.get("PORT", "10000"))


# ============================================================
# Logging
# ============================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger("waselni")


# ============================================================
# Health Check
# ============================================================

class HealthCheckHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(
            f"وصلني يعمل - {CITY_NAME}".encode("utf-8")
        )

    def log_message(self, format, *args):
        return


def run_health_server():

    server = HTTPServer(
        ("0.0.0.0", PORT),
        HealthCheckHandler
    )

    logger.info(f"Health server running on port {PORT}")

    server.serve_forever()


threading.Thread(
    target=run_health_server,
    daemon=True
).start()


# ============================================================
# Database
# ============================================================

db_lock = threading.Lock()


def get_db():

    conn = sqlite3.connect(
        DB_FILE,
        check_same_thread=False
    )

    conn.row_factory = sqlite3.Row

    return conn


def init_database():

    with db_lock:

        conn = get_db()

        cursor = conn.cursor()

        # المستخدمون
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            telegram_id INTEGER UNIQUE NOT NULL,
            first_name TEXT,
            username TEXT,
            phone TEXT,
            role TEXT DEFAULT 'passenger',
            created_at TEXT
        )
        """)

        # السائقون
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS drivers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER UNIQUE NOT NULL,
            name TEXT NOT NULL,
            phone TEXT,
            car TEXT,
            license TEXT,
            status TEXT DEFAULT 'pending',
            online INTEGER DEFAULT 0,
            latitude REAL,
            longitude REAL,
            rating REAL DEFAULT 5.0,
            total_rides INTEGER DEFAULT 0,
            created_at TEXT
        )
        """)

        # الرحلات
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS rides (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            passenger_id INTEGER NOT NULL,

            pickup_text TEXT,
            destination_text TEXT,

            pickup_lat REAL,
            pickup_lon REAL,

            destination_lat REAL,
            destination_lon REAL,

            estimated_price INTEGER DEFAULT 0,

            status TEXT DEFAULT 'searching',

            driver_id INTEGER,

            created_at TEXT,
            accepted_at TEXT,
            started_at TEXT,
            completed_at TEXT
        )
        """)

        # تقييمات
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS ratings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ride_id INTEGER,
            passenger_id INTEGER,
            driver_id INTEGER,
            rating INTEGER,
            comment TEXT,
            created_at TEXT
        )
        """)

        conn.commit()

        conn.close()


init_database()


# ============================================================
# Helpers
# ============================================================

def now():

    return datetime.utcnow().isoformat()


def save_user(user):

    with db_lock:

        conn = get_db()

        conn.execute("""
        INSERT INTO users
        (
            telegram_id,
            first_name,
            username,
            created_at
        )
        VALUES (?, ?, ?, ?)

        ON CONFLICT(telegram_id)
        DO UPDATE SET
            first_name=excluded.first_name,
            username=excluded.username
        """, (
            user.id,
            user.first_name or "",
            user.username or "",
            now()
        ))

        conn.commit()
        conn.close()


def get_driver(telegram_id):

    conn = get_db()

    row = conn.execute("""
    SELECT *
    FROM drivers
    WHERE telegram_id=?
    """, (telegram_id,)).fetchone()

    conn.close()

    return row


def get_ride(ride_id):

    conn = get_db()

    row = conn.execute("""
    SELECT *
    FROM rides
    WHERE id=?
    """, (ride_id,)).fetchone()

    conn.close()

    return row


# ============================================================
# Keyboards
# ============================================================

def passenger_menu():

    keyboard = [

        ["🚖 طلب رحلة جديدة"],

        ["📍 رحلتي الحالية"],

        ["📜 رحلاتي السابقة"],

        ["🚕 التسجيل كسائق"],

        ["❓ المساعدة"]

    ]

    return ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True,
        is_persistent=True
    )


def driver_menu():

    keyboard = [

        ["🚕 حالة السائق"],

        ["📍 مشاركة موقعي"],

        ["📋 رحلاتي"],

        ["👤 بياناتي"],

        ["❓ المساعدة"]

    ]

    return ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True,
        is_persistent=True
    )


def admin_menu():

    keyboard = [

        ["📊 إحصائيات"],

        ["👨‍✈️ طلبات السائقين"],

        ["🚖 الرحلات الحالية"],

        ["❓ المساعدة"]

    ]

    return ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True,
        is_persistent=True
    )


# ============================================================
# Conversation States
# ============================================================

(
    RIDE_PICKUP,
    RIDE_DESTINATION,
    RIDE_PRICE,

    DRIVER_NAME,
    DRIVER_PHONE,
    DRIVER_CAR,
    DRIVER_LICENSE,

    RATING
) = range(8)


# ============================================================
# /start
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user = update.effective_user

    save_user(user)

    driver = get_driver(user.id)

    if driver and driver["status"] == "approved":

        await update.message.reply_text(

            f"أهلاً بك كابتن {driver['name']} 🚕\n\n"

            f"🚖 نظام وصلني - {CITY_NAME}\n\n"

            f"🚗 السيارة: {driver['car']}\n"
            f"⭐ التقييم: {driver['rating']:.1f}\n"
            f"🚘 الرحلات: {driver['total_rides']}\n\n"

            "يمكنك الآن استقبال الرحلات القريبة منك.",

            reply_markup=driver_menu()
        )

        return

    await update.message.reply_text(

        f"أهلاً بك في بوت وصلني 🚖\n"
        f"لخدمات التكسي في {CITY_NAME}\n\n"

        "يمكنك طلب سيارة بسهولة من القائمة.\n\n"

        "🚖 طلب رحلة جديدة\n"
        "🚕 التسجيل كسائق\n"
        "📍 متابعة الرحلة\n"
        "⭐ تقييم السائق",

        reply_markup=passenger_menu()
    )


# ============================================================
# Passenger - Start Ride
# ============================================================

async def start_ride(update: Update, context: ContextTypes.DEFAULT_TYPE):

    location_button = KeyboardButton(
        "📍 مشاركة موقعي",
        request_location=True
    )

    keyboard = [
        [location_button],
        ["❌ إلغاء"]
    ]

    await update.message.reply_text(

        "🚖 إنشاء رحلة جديدة\n\n"

        "الخطوة 1 من 3\n\n"

        "📍 أرسل موقع الانطلاق.\n"
        "يمكنك الضغط على «مشاركة موقعي» "
        "أو كتابة العنوان.",

        reply_markup=ReplyKeyboardMarkup(
            keyboard,
            resize_keyboard=True,
            one_time_keyboard=True
        )
    )

    return RIDE_PICKUP


async def get_pickup(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if update.message.text == "❌ إلغاء":

        return await cancel(update, context)

    if update.message.location:

        location = update.message.location

        context.user_data["pickup_lat"] = location.latitude
        context.user_data["pickup_lon"] = location.longitude

        context.user_data["pickup_text"] = (
            f"موقع GPS "
            f"({location.latitude:.6f}, "
            f"{location.longitude:.6f})"
        )

    else:

        context.user_data["pickup_text"] = update.message.text

        context.user_data["pickup_lat"] = None
        context.user_data["pickup_lon"] = None

    await update.message.reply_text(

        "✅ تم تحديد نقطة الانطلاق.\n\n"

        "الخطوة 2 من 3\n\n"

        "🏁 اكتب مكان الوصول.\n\n"

        "مثال:\n"
        "المشفى الوطني\n"
        "ساحة البلدية\n"
        "المنطقة الصناعية",

        reply_markup=ReplyKeyboardMarkup(
            [["❌ إلغاء"]],
            resize_keyboard=True
        )
    )

    return RIDE_DESTINATION


# ============================================================
# Destination
# ============================================================

async def get_destination(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if update.message.text == "❌ إلغاء":

        return await cancel(update, context)

    context.user_data["destination_text"] = update.message.text

    keyboard = [
        ["15000", "20000"],
        ["25000", "30000"],
        ["❌ إلغاء"]
    ]

    await update.message.reply_text(

        "الخطوة 3 من 3\n\n"

        "💰 حدد السعر التقديري للرحلة.\n\n"

        "يمكنك اختيار أحد الأسعار أو كتابة السعر بنفسك.",

        reply_markup=ReplyKeyboardMarkup(
            keyboard,
            resize_keyboard=True
        )
    )

    return RIDE_PRICE


# ============================================================
# Create Ride
# ============================================================

async def create_ride(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if update.message.text == "❌ إلغاء":

        return await cancel(update, context)

    try:

        price = int(
            update.message.text
            .replace(",", "")
            .replace("ل.س", "")
            .strip()
        )

    except ValueError:

        await update.message.reply_text(
            "⚠️ الرجاء إدخال السعر كرقم فقط.\nمثال: 20000"
        )

        return RIDE_PRICE

    user = update.effective_user

    pickup_text = context.user_data.get(
        "pickup_text",
        "غير محدد"
    )

    destination_text = context.user_data.get(
        "destination_text",
        "غير محدد"
    )

    pickup_lat = context.user_data.get("pickup_lat")
    pickup_lon = context.user_data.get("pickup_lon")

    # إنشاء الرحلة
    with db_lock:

        conn = get_db()

        cursor = conn.cursor()

        cursor.execute("""
        INSERT INTO rides
        (
            passenger_id,
            pickup_text,
            destination_text,
            pickup_lat,
            pickup_lon,
            estimated_price,
            status,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (

            user.id,
            pickup_text,
            destination_text,
            pickup_lat,
            pickup_lon,
            price,
            "searching",
            now()

        ))

        ride_id = cursor.lastrowid

        conn.commit()

        conn.close()

    # تنظيف البيانات المؤقتة
    context.user_data.clear()

    await update.message.reply_text(

        f"✅ تم إنشاء طلب الرحلة رقم #{ride_id}\n\n"

        f"📍 الانطلاق:\n{pickup_text}\n\n"

        f"🏁 الوجهة:\n{destination_text}\n\n"

        f"💰 السعر:\n{price:,} ل.س\n\n"

        "🔎 جاري البحث عن أقرب كابتن...\n\n"

        "سنخبرك فور قبول الرحلة.",

        reply_markup=passenger_menu()
    )

    # إرسال للسائقين القريبين
    await send_ride_to_drivers(
        context,
        ride_id
    )

    return ConversationHandler.END


# ============================================================
# Find Nearby Drivers
# ============================================================

def distance_km(lat1, lon1, lat2, lon2):

    if None in (
        lat1,
        lon1,
        lat2,
        lon2
    ):
        return 999999

    R = 6371

    p1 = math.radians(lat1)
    p2 = math.radians(lat2)

    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)

    a = (
        math.sin(dp / 2) ** 2
        +
        math.cos(p1)
        * math.cos(p2)
        * math.sin(dl / 2) ** 2
    )

    return 2 * R * math.asin(math.sqrt(a))


def find_nearby_drivers(
    latitude,
    longitude,
    radius_km=10
):

    conn = get_db()

    drivers = conn.execute("""
    SELECT *
    FROM drivers
    WHERE status='approved'
    AND online=1
    AND latitude IS NOT NULL
    AND longitude IS NOT NULL
    """).fetchall()

    conn.close()

    result = []

    for driver in drivers:

        distance = distance_km(
            latitude,
            longitude,
            driver["latitude"],
            driver["longitude"]
        )

        if distance <= radius_km:

            result.append(
                (
                    driver,
                    distance
                )
            )

    result.sort(
        key=lambda x: x[1]
    )

    return result[:10]


# ============================================================
# Send Ride To Drivers
# ============================================================

async def send_ride_to_drivers(
    context,
    ride_id
):

    ride = get_ride(ride_id)

    if not ride:
        return

    drivers = find_nearby_drivers(
        ride["pickup_lat"],
        ride["pickup_lon"]
    )

    # إذا لم يكن لدى الراكب GPS
    if ride["pickup_lat"] is None:

        conn = get_db()

        drivers_rows = conn.execute("""
        SELECT *
        FROM drivers
        WHERE status='approved'
        AND online=1
        LIMIT 10
        """).fetchall()

        conn.close()

        drivers = [
            (driver, 0)
            for driver in drivers_rows
        ]

    for driver, distance in drivers:

        keyboard = InlineKeyboardMarkup([

            [
                InlineKeyboardButton(
                    "✅ قبول الرحلة",
                    callback_data=f"accept_{ride_id}"
                )
            ],

            [
                InlineKeyboardButton(
                    "❌ تجاهل",
                    callback_data=f"ignore_{ride_id}"
                )
            ]

        ])

        text = (

            f"🔔 طلب رحلة جديد\n\n"

            f"🆔 الرحلة: #{ride_id}\n\n"

            f"📍 الانطلاق:\n"
            f"{ride['pickup_text']}\n\n"

            f"🏁 الوجهة:\n"
            f"{ride['destination_text']}\n\n"

            f"💰 السعر:\n"
            f"{ride['estimated_price']:,} ل.س\n\n"

            f"📏 المسافة منك:\n"
            f"{distance:.1f} كم\n\n"

            "هل تريد قبول الرحلة؟"

        )

        try:

            await context.bot.send_message(
                chat_id=driver["telegram_id"],
                text=text,
                reply_markup=keyboard
            )

        except Exception as e:

            logger.error(
                f"Driver notification error: {e}"
            )


# ============================================================
# Driver Registration
# ============================================================

async def start_driver_registration(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    existing = get_driver(
        update.effective_user.id
    )

    if existing:

        await update.message.reply_text(

            f"لديك طلب تسجيل موجود مسبقاً.\n\n"
            f"الحالة: {existing['status']}",

            reply_markup=passenger_menu()
        )

        return ConversationHandler.END

    await update.message.reply_text(

        "🚕 تسجيل كابتن جديد\n\n"

        "الخطوة 1 من 4\n\n"

        "👤 اكتب اسمك الكامل:",

        reply_markup=ReplyKeyboardMarkup(
            [["❌ إلغاء"]],
            resize_keyboard=True
        )
    )

    return DRIVER_NAME


async def driver_name(update, context):

    if update.message.text == "❌ إلغاء":

        return await cancel(update, context)

    context.user_data["driver_name"] = update.message.text

    await update.message.reply_text(
        "📞 أرسل رقم هاتفك:"
    )

    return DRIVER_PHONE


async def driver_phone(update, context):

    if update.message.text == "❌ إلغاء":

        return await cancel(update, context)

    context.user_data["driver_phone"] = update.message.text

    await update.message.reply_text(

        "🚗 اكتب معلومات السيارة.\n\n"
        "مثال:\n"
        "كيا ريو - أبيض - دمشق 123456"

    )

    return DRIVER_CAR


async def driver_car(update, context):

    if update.message.text == "❌ إلغاء":

        return await cancel(update, context)

    context.user_data["driver_car"] = update.message.text

    await update.message.reply_text(
        "🪪 أرسل رقم شهادة السواقة:"
    )

    return DRIVER_LICENSE


async def driver_license(update, context):

    if update.message.text == "❌ إلغاء":

        return await cancel(update, context)

    user = update.effective_user

    license_number = update.message.text

    name = context.user_data["driver_name"]
    phone = context.user_data["driver_phone"]
    car = context.user_data["driver_car"]

    with db_lock:

        conn = get_db()

        conn.execute("""
        INSERT OR REPLACE INTO drivers
        (
            telegram_id,
            name,
            phone,
            car,
            license,
            status,
            online,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (

            user.id,
            name,
            phone,
            car,
            license_number,
            "pending",
            0,
            now()

        ))

        conn.commit()

        conn.close()

    await update.message.reply_text(

        "✅ تم إرسال طلب التسجيل.\n\n"

        "سيتم مراجعته من الإدارة.\n"
        "بعد الموافقة سيصبح بإمكانك استقبال الرحلات.",

        reply_markup=passenger_menu()
    )

    # إرسال الطلب إلى الإدارة
    keyboard = InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
                "✅ اعتماد",
                callback_data=f"approve_{user.id}"
            ),

            InlineKeyboardButton(
                "❌ رفض",
                callback_data=f"reject_{user.id}"
            )
        ]

    ])

    admin_text = (

        "🚕 طلب سائق جديد\n\n"

        f"👤 الاسم: {name}\n"
        f"📞 الهاتف: {phone}\n"
        f"🚗 السيارة: {car}\n"
        f"🪪 الرخصة: {license_number}\n"
        f"🆔 Telegram ID: {user.id}\n"
        f"@{user.username or 'بدون_معرف'}"

    )

    for admin_id in ADMIN_IDS:

        try:

            await context.bot.send_message(
                chat_id=admin_id,
                text=admin_text,
                reply_markup=keyboard
            )

        except Exception as e:

            logger.error(e)

    context.user_data.clear()

    return ConversationHandler.END


# ============================================================
# Admin Driver Approval
# ============================================================

async def driver_approval(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()

    if query.from_user.id not in ADMIN_IDS:

        await query.answer(
            "غير مصرح لك.",
            show_alert=True
        )

        return

    action, user_id_text = query.data.split("_")

    driver_id = int(user_id_text)

    driver = get_driver(driver_id)

    if not driver:

        await query.edit_message_text(
            "❌ لم يتم العثور على السائق."
        )

        return

    if action == "approve":

        with db_lock:

            conn = get_db()

            conn.execute("""
            UPDATE drivers
            SET status='approved'
            WHERE telegram_id=?
            """, (driver_id,))

            conn.commit()

            conn.close()

        await query.edit_message_text(

            "✅ تم اعتماد السائق.\n\n"

            f"👤 {driver['name']}\n"
            f"🚗 {driver['car']}"

        )

        await context.bot.send_message(

            chat_id=driver_id,

            text=(

                f"🎉 أهلاً بك كابتن {driver['name']}!\n\n"

                "تم اعتماد حسابك كسائق في وصلني 🚕\n\n"

                "يمكنك الآن تشغيل حالة السائق "
                "واستقبال الرحلات."

            ),

            reply_markup=driver_menu()
        )

    else:

        with db_lock:

            conn = get_db()

            conn.execute("""
            UPDATE drivers
            SET status='rejected'
            WHERE telegram_id=?
            """, (driver_id,))

            conn.commit()

            conn.close()

        await query.edit_message_text(
            f"❌ تم رفض طلب {driver['name']}."
        )

        await context.bot.send_message(

            chat_id=driver_id,

            text="❌ تم رفض طلب التسجيل كسائق."
        )


# ============================================================
# Driver Online / Offline
# ============================================================

async def driver_status(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user_id = update.effective_user.id

    driver = get_driver(user_id)

    if not driver or driver["status"] != "approved":

        await update.message.reply_text(
            "⚠️ أنت لست سائقاً معتمداً."
        )

        return

    current = driver["online"]

    new_status = 0 if current else 1

    with db_lock:

        conn = get_db()

        conn.execute("""
        UPDATE drivers
        SET online=?
        WHERE telegram_id=?
        """, (
            new_status,
            user_id
        ))

        conn.commit()

        conn.close()

    if new_status:

        text = (
            "🟢 أصبحت متاحاً الآن.\n\n"
            "ستصلك طلبات الرحلات."
        )

    else:

        text = (
            "🔴 تم إيقاف استقبال الرحلات."
        )

    await update.message.reply_text(
        text,
        reply_markup=driver_menu()
    )


# ============================================================
# Driver Location
# ============================================================

async def driver_location(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user_id = update.effective_user.id

    driver = get_driver(user_id)

    if not driver or driver["status"] != "approved":

        await update.message.reply_text(
            "⚠️ هذه الخاصية للسائقين المعتمدين فقط."
        )

        return

    if not update.message.location:

        return

    location = update.message.location

    with db_lock:

        conn = get_db()

        conn.execute("""
        UPDATE drivers
        SET latitude=?,
            longitude=?,
            online=1
        WHERE telegram_id=?
        """, (

            location.latitude,
            location.longitude,
            user_id

        ))

        conn.commit()

        conn.close()

    await update.message.reply_text(

        "📍 تم تحديث موقعك.\n"
        "🟢 أنت الآن متاح لاستقبال الرحلات.",

        reply_markup=driver_menu()
    )


# ============================================================
# Accept Ride
# ============================================================

async def accept_ride(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()

    driver_user = query.from_user

    driver = get_driver(
        driver_user.id
    )

    if not driver or driver["status"] != "approved":

        await query.answer(
            "⚠️ يجب أن تكون سائقاً معتمداً.",
            show_alert=True
        )

        return

    ride_id = int(
        query.data.split("_")[1]
    )

    # عملية ذرية لمنع قبول الرحلة من سائقين
    with db_lock:

        conn = get_db()

        cursor = conn.cursor()

        cursor.execute("""
        UPDATE rides

        SET
            status='accepted',
            driver_id=?,
            accepted_at=?

        WHERE id=?
        AND status='searching'
        """, (

            driver_user.id,
            now(),
            ride_id

        ))

        updated = cursor.rowcount

        conn.commit()

        conn.close()

    if updated == 0:

        await query.edit_message_text(

            "⚠️ هذه الرحلة لم تعد متاحة.\n"
            "تم قبولها من سائق آخر."

        )

        return

    # السائق يصبح مشغولاً
    with db_lock:

        conn = get_db()

        conn.execute("""
        UPDATE drivers
        SET online=0
        WHERE telegram_id=?
        """, (driver_user.id,))

        conn.commit()

        conn.close()

    ride = get_ride(ride_id)

    await query.edit_message_text(

        f"✅ تم قبول الرحلة #{ride_id}\n\n"

        f"📍 الانطلاق:\n"
        f"{ride['pickup_text']}\n\n"

        f"🏁 الوجهة:\n"
        f"{ride['destination_text']}\n\n"

        f"💰 السعر:\n"
        f"{ride['estimated_price']:,} ل.س\n\n"

        "🚖 توجه إلى الراكب."

    )

    # إرسال للراكب
    try:

        await context.bot.send_message(

            chat_id=ride["passenger_id"],

            text=(

                "🎉 تم العثور على كابتن!\n\n"

                f"👤 السائق: {driver['name']}\n"
                f"🚗 السيارة: {driver['car']}\n"
                f"⭐ التقييم: {driver['rating']:.1f}\n"
                f"📞 الهاتف: {driver['phone']}\n\n"

                f"💰 السعر: "
                f"{ride['estimated_price']:,} ل.س\n\n"

                "🚖 السائق في طريقه إليك."

            )

        )

    except Exception as e:

        logger.error(e)


# ============================================================
# Ignore Ride
# ============================================================

async def ignore_ride(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer(
        "تم تجاهل الطلب."
    )

    try:

        await query.edit_message_reply_markup(
            reply_markup=None
        )

    except Exception:
        pass


# ============================================================
# Current Ride
# ============================================================

async def current_ride(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user_id = update.effective_user.id

    conn = get_db()

    ride = conn.execute("""
    SELECT *
    FROM rides
    WHERE passenger_id=?
    AND status IN (
        'searching',
        'accepted',
        'started'
    )
    ORDER BY id DESC
    LIMIT 1
    """, (user_id,)).fetchone()

    conn.close()

    if not ride:

        await update.message.reply_text(
            "لا توجد لديك رحلة حالية."
        )

        return

    status_names = {

        "searching": "🔎 جاري البحث عن سائق",

        "accepted": "🚕 تم قبول الرحلة",

        "started": "🚖 الرحلة جارية"

    }

    text = (

        f"🚖 رحلتك #{ride['id']}\n\n"

        f"📍 الانطلاق:\n"
        f"{ride['pickup_text']}\n\n"

        f"🏁 الوجهة:\n"
        f"{ride['destination_text']}\n\n"

        f"💰 السعر:\n"
        f"{ride['estimated_price']:,} ل.س\n\n"

        f"الحالة:\n"
        f"{status_names.get(ride['status'], ride['status'])}"

    )

    if ride["driver_id"]:

        driver = get_driver(
            ride["driver_id"]
        )

        if driver:

            text += (

                "\n\n🚕 بيانات الكابتن\n\n"

                f"👤 {driver['name']}\n"
                f"🚗 {driver['car']}\n"
                f"📞 {driver['phone']}\n"
                f"⭐ {driver['rating']:.1f}"

            )

    await update.message.reply_text(
        text,
        reply_markup=passenger_menu()
    )


# ============================================================
# Driver Info
# ============================================================

async def driver_info(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    driver = get_driver(
        update.effective_user.id
    )

    if not driver:

        await update.message.reply_text(
            "أنت غير مسجل كسائق."
        )

        return

    await update.message.reply_text(

        "👤 بيانات الكابتن\n\n"

        f"الاسم: {driver['name']}\n"
        f"الهاتف: {driver['phone']}\n"
        f"السيارة: {driver['car']}\n"
        f"الرخصة: {driver['license']}\n\n"

        f"الحالة: {driver['status']}\n"
        f"متاح: {'🟢 نعم' if driver['online'] else '🔴 لا'}\n"
        f"⭐ التقييم: {driver['rating']:.1f}\n"
        f"🚖 الرحلات: {driver['total_rides']}",

        reply_markup=driver_menu()
    )


# ============================================================
# Admin Statistics
# ============================================================

async def statistics(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if update.effective_user.id not in ADMIN_IDS:

        return

    conn = get_db()

    users = conn.execute(
        "SELECT COUNT(*) FROM users"
    ).fetchone()[0]

    drivers = conn.execute(
        "SELECT COUNT(*) FROM drivers WHERE status='approved'"
    ).fetchone()[0]

    online = conn.execute(
        "SELECT COUNT(*) FROM drivers WHERE status='approved' AND online=1"
    ).fetchone()[0]

    rides = conn.execute(
        "SELECT COUNT(*) FROM rides"
    ).fetchone()[0]

    active = conn.execute("""
    SELECT COUNT(*)
    FROM rides
    WHERE status IN ('searching','accepted','started')
    """).fetchone()[0]

    conn.close()

    await update.message.reply_text(

        f"📊 إحصائيات وصلني - {CITY_NAME}\n\n"

        f"👥 المستخدمون: {users}\n"
        f"👨‍✈️ السائقون المعتمدون: {drivers}\n"
        f"🟢 السائقون المتاحون: {online}\n"
        f"🚖 إجمالي الرحلات: {rides}\n"
        f"🔵 الرحلات الحالية: {active}",

        reply_markup=admin_menu()
    )


# ============================================================
# Help
# ============================================================

async def help_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(

        "❓ مساعدة وصلني\n\n"

        "🚖 للراكب:\n"
        "اضغط «طلب رحلة جديدة» واتبع الخطوات.\n\n"

        "🚕 للسائق:\n"
        "سجل كسائق، وبعد اعتماد الحساب شغل حالة السائق وشارك موقعك.\n\n"

        "📍 الموقع:\n"
        "يستخدم الموقع لتحديد أقرب السائقين.\n\n"

        "☎️ الدعم:\n"
        "يمكنك التواصل مع إدارة وصلني.",

        reply_markup=passenger_menu()
    )


# ============================================================
# Cancel
# ============================================================

async def cancel(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    context.user_data.clear()

    await update.message.reply_text(

        "❌ تم إلغاء العملية.",

        reply_markup=passenger_menu()
    )

    return ConversationHandler.END


# ============================================================
# Bot Commands
# ============================================================

async def post_init(application):

    commands = [

        BotCommand(
            "start",
            "القائمة الرئيسية"
        ),

        BotCommand(
            "ride",
            "طلب رحلة"
        ),

        BotCommand(
            "register_driver",
            "التسجيل كسائق"
        ),

        BotCommand(
            "help",
            "المساعدة"
        ),

        BotCommand(
            "cancel",
            "إلغاء"
        )

    ]

    await application.bot.set_my_commands(
        commands
    )


# ============================================================
# Main
# ============================================================

def main():

    if not BOT_TOKEN:

        raise RuntimeError(
            "BOT_TOKEN غير موجود في متغيرات البيئة."
        )

    application = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    # --------------------------------------------------------
    # Passenger Ride Conversation
    # --------------------------------------------------------

    ride_handler = ConversationHandler(

        entry_points=[

            CommandHandler(
                "ride",
                start_ride
            ),

            MessageHandler(
                filters.Regex(
                    "^🚖 طلب رحلة جديدة$"
                ),
                start_ride
            )

        ],

        states={

            RIDE_PICKUP: [

                MessageHandler(
                    filters.LOCATION |
                    (
                        filters.TEXT &
                        ~filters.COMMAND
                    ),
                    get_pickup
                )

            ],

            RIDE_DESTINATION: [

                MessageHandler(
                    filters.TEXT &
                    ~filters.COMMAND,
                    get_destination
                )

            ],

            RIDE_PRICE: [

                MessageHandler(
                    filters.TEXT &
                    ~filters.COMMAND,
                    create_ride
                )

            ]

        },

        fallbacks=[

            CommandHandler(
                "cancel",
                cancel
            ),

            MessageHandler(
                filters.Regex("^❌ إلغاء$"),
                cancel
            )

        ]

    )

    # --------------------------------------------------------
    # Driver Registration
    # --------------------------------------------------------

    driver_handler = ConversationHandler(

        entry_points=[

            CommandHandler(
                "register_driver",
                start_driver_registration
            ),

            MessageHandler(
                filters.Regex(
                    "^🚕 التسجيل كسائق$"
                ),
                start_driver_registration
            )

        ],

        states={

            DRIVER_NAME: [

                MessageHandler(
                    filters.TEXT &
                    ~filters.COMMAND,
                    driver_name
                )

            ],

            DRIVER_PHONE: [

                MessageHandler(
                    filters.TEXT &
                    ~filters.COMMAND,
                    driver_phone
                )

            ],

            DRIVER_CAR: [

                MessageHandler(
                    filters.TEXT &
                    ~filters.COMMAND,
                    driver_car
                )

            ],

            DRIVER_LICENSE: [

                MessageHandler(
                    filters.TEXT &
                    ~filters.COMMAND,
                    driver_license
                )

            ]

        },

        fallbacks=[

            CommandHandler(
                "cancel",
                cancel
            ),

            MessageHandler(
                filters.Regex("^❌ إلغاء$"),
                cancel
            )

        ]

    )

    # --------------------------------------------------------
    # Add handlers
    # --------------------------------------------------------

    application.add_handler(
        ride_handler
    )

    application.add_handler(
        driver_handler
    )

    application.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    application.add_handler(
        CommandHandler(
            "help",
            help_command
        )
    )

    application.add_handler(
        MessageHandler(
            filters.Regex("^📍 رحلتي الحالية$"),
            current_ride
        )
    )

    application.add_handler(
        MessageHandler(
            filters.Regex("^🚕 حالة السائق$"),
            driver_status
        )
    )

    application.add_handler(
        MessageHandler(
            filters.Regex("^📍 مشاركة موقعي$") &
            filters.LOCATION,
            driver_location
        )
    )

    # استقبال موقع السائق حتى لو أرسله بدون الضغط على الزر
    application.add_handler(
        MessageHandler(
            filters.LOCATION,
            driver_location
        )
    )

    application.add_handler(
        MessageHandler(
            filters.Regex("^👤 بياناتي$"),
            driver_info
        )
    )

    application.add_handler(
        MessageHandler(
            filters.Regex("^❓ المساعدة$"),
            help_command
        )
    )

    application.add_handler(
        MessageHandler(
            filters.Regex("^📊 إحصائيات$"),
            statistics
        )
    )

    # --------------------------------------------------------
    # Callback buttons
    # --------------------------------------------------------

    application.add_handler(

        CallbackQueryHandler(
            driver_approval,
            pattern=r"^(approve|reject)_\d+$"
        )

    )

    application.add_handler(

        CallbackQueryHandler(
            accept_ride,
            pattern=r"^accept_\d+$"
        )

    )

    application.add_handler(

        CallbackQueryHandler(
            ignore_ride,
            pattern=r"^ignore_\d+$"
        )

    )

    logger.info(
        f"🚖 Waselni started - {CITY_NAME}"
    )

    application.run_polling(
        drop_pending_updates=True
    )


# ============================================================
# Start
# ============================================================

if __name__ == "__main__":

    main()
