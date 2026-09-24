import os
import math
import sqlite3
import logging
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
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
# إعدادات البوت
# ============================================================

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
OWNER_ID = int(os.environ.get("OWNER_ID", "0"))

CITY_NAME = os.environ.get("CITY_NAME", "القطيفة")
DB_FILE = os.environ.get("DB_FILE", "waselni.db")
PORT = int(os.environ.get("PORT", "10000"))

# أقصى مسافة لإرسال الطلب للسائق
MAX_DRIVER_DISTANCE_KM = 10


# ============================================================
# Logging
# ============================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)


# ============================================================
# Health Server - Render
# ============================================================

class HealthHandler(BaseHTTPRequestHandler):

    def do_GET(self):

        self.send_response(200)

        self.send_header(
            "Content-Type",
            "text/plain; charset=utf-8"
        )

        self.end_headers()

        self.wfile.write(
            b"Waselni Bot is running!"
        )

    def log_message(self, format, *args):
        return


def run_health_server():

    try:

        server = HTTPServer(
            ("0.0.0.0", PORT),
            HealthHandler
        )

        logger.info(
            f"Health server running on port {PORT}"
        )

        server.serve_forever()

    except Exception as e:

        logger.error(
            f"Health server error: {e}"
        )


threading.Thread(
    target=run_health_server,
    daemon=True
).start()


# ============================================================
# قاعدة البيانات
# ============================================================

def get_db():

    conn = sqlite3.connect(
        DB_FILE,
        check_same_thread=False
    )

    conn.row_factory = sqlite3.Row

    return conn


def init_db():

    conn = get_db()

    cur = conn.cursor()

    # --------------------------------------------------------
    # المستخدمون
    # --------------------------------------------------------

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            first_name TEXT,
            username TEXT,
            phone TEXT,
            created_at TEXT
        )
    """)

    # --------------------------------------------------------
    # السائقون
    # --------------------------------------------------------

    cur.execute("""
        CREATE TABLE IF NOT EXISTS drivers (
            user_id INTEGER PRIMARY KEY,
            name TEXT,
            phone TEXT,
            car TEXT,
            license TEXT,
            license_file_id TEXT,
            status TEXT DEFAULT 'pending',
            online INTEGER DEFAULT 0,
            lat REAL,
            lon REAL,
            current_ride INTEGER,
            created_at TEXT,
            approved_at TEXT
        )
    """)

    # --------------------------------------------------------
    # الرحلات
    # --------------------------------------------------------

    cur.execute("""
        CREATE TABLE IF NOT EXISTS rides (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            passenger_id INTEGER,
            pickup TEXT,
            pickup_lat REAL,
            pickup_lon REAL,
            price REAL,
            status TEXT DEFAULT 'searching',
            driver_id INTEGER,
            created_at TEXT,
            accepted_at TEXT,
            completed_at TEXT
        )
    """)

    # --------------------------------------------------------
    # التقييمات
    # --------------------------------------------------------

    cur.execute("""
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


init_db()


# ============================================================
# الوقت
# ============================================================

def now():

    return datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )


# ============================================================
# حفظ المستخدم
# ============================================================

def save_user(user):

    conn = get_db()

    conn.execute("""
        INSERT INTO users (
            user_id,
            first_name,
            username,
            created_at
        )
        VALUES (?, ?, ?, ?)

        ON CONFLICT(user_id)
        DO UPDATE SET
            first_name = excluded.first_name,
            username = excluded.username
    """, (
        user.id,
        user.first_name or "",
        user.username or "",
        now()
    ))

    conn.commit()
    conn.close()


# ============================================================
# حساب المسافة
# ============================================================

def haversine(
    lat1,
    lon1,
    lat2,
    lon2
):

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

    dp = math.radians(
        lat2 - lat1
    )

    dl = math.radians(
        lon2 - lon1
    )

    a = (
        math.sin(dp / 2) ** 2
        +
        math.cos(p1)
        *
        math.cos(p2)
        *
        math.sin(dl / 2) ** 2
    )

    return (
        R *
        2 *
        math.atan2(
            math.sqrt(a),
            math.sqrt(1 - a)
        )
    )


# ============================================================
# لوحة الراكب
# ============================================================

def passenger_keyboard():

    return ReplyKeyboardMarkup(
        [
            [
                KeyboardButton(
                    "🚕 طلب سيارة"
                )
            ],
            [
                KeyboardButton(
                    "📋 طلباتي"
                ),
                KeyboardButton(
                    "❓ المساعدة"
                )
            ]
        ],
        resize_keyboard=True
    )


# ============================================================
# لوحة السائق
# ============================================================

def driver_keyboard():

    return ReplyKeyboardMarkup(
        [
            [
                KeyboardButton(
                    "🟢 تشغيل"
                ),
                KeyboardButton(
                    "🔴 إيقاف"
                )
            ],
            [
                KeyboardButton(
                    "📍 إرسال موقعي",
                    request_location=True
                )
            ],
            [
                KeyboardButton(
                    "🚕 الرحلة الحالية"
                )
            ],
            [
                KeyboardButton(
                    "📊 إحصائياتي"
                )
            ],
            [
                KeyboardButton(
                    "❓ المساعدة"
                )
            ]
        ],
        resize_keyboard=True
    )


# ============================================================
# لوحة البداية
# ============================================================

def main_keyboard():

    return ReplyKeyboardMarkup(
        [
            [
                KeyboardButton("🚕 راكب"),
                KeyboardButton("🚗 سائق")
            ],
            [
                KeyboardButton("❓ المساعدة")
            ]
        ],
        resize_keyboard=True
    )


# ============================================================
# START
# ============================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user

    save_user(user)

    await update.message.reply_text(
        f"""
🚕 أهلاً بك في بوت وصلني

📍 المنطقة:
{CITY_NAME}

اختر طريقة الاستخدام:
""",
        reply_markup=main_keyboard()
    )


# ============================================================
# قائمة الراكب
# ============================================================

async def passenger_menu(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(
        "🚕 قائمة الراكب",
        reply_markup=passenger_keyboard()
    )


# ============================================================
# قائمة السائق
# ============================================================

async def driver_menu(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user_id = update.effective_user.id

    conn = get_db()

    driver = conn.execute("""
        SELECT *
        FROM drivers
        WHERE user_id=?
    """, (
        user_id,
    )).fetchone()

    conn.close()

    if not driver:

        await update.message.reply_text(
            "🚗 أنت غير مسجل كسائق.\n\n"
            "استخدم الأمر:\n"
            "/register_driver"
        )

        return

    if driver["status"] == "pending":

        await update.message.reply_text(
            "⏳ طلب تسجيلك ما زال قيد المراجعة من المالك."
        )

        return

    if driver["status"] == "rejected":

        await update.message.reply_text(
            "❌ تم رفض تسجيلك كسائق."
        )

        return

    await update.message.reply_text(
        "🚗 لوحة السائق",
        reply_markup=driver_keyboard()
    )


# ============================================================
# تسجيل السائق
# ============================================================

DRIVER_NAME = 1
DRIVER_PHONE = 2
DRIVER_CAR = 3
DRIVER_LICENSE = 4


async def register_driver_start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user_id = update.effective_user.id

    conn = get_db()

    driver = conn.execute("""
        SELECT status
        FROM drivers
        WHERE user_id=?
    """, (
        user_id,
    )).fetchone()

    conn.close()

    if driver:

        if driver["status"] == "approved":

            await update.message.reply_text(
                "✅ أنت سائق معتمد بالفعل."
            )

            return ConversationHandler.END

        if driver["status"] == "pending":

            await update.message.reply_text(
                "⏳ طلبك قيد المراجعة من المالك."
            )

            return ConversationHandler.END

    await update.message.reply_text(
        "🚗 تسجيل سائق جديد\n\n"
        "أرسل اسمك الكامل:"
    )

    return DRIVER_NAME


async def driver_name(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    context.user_data["driver_name"] = (
        update.message.text
    )

    await update.message.reply_text(
        "📱 أرسل رقم هاتفك:"
    )

    return DRIVER_PHONE


async def driver_phone(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    context.user_data["driver_phone"] = (
        update.message.text
    )

    await update.message.reply_text(
        "🚕 أرسل نوع السيارة والموديل واللون:"
    )

    return DRIVER_CAR


async def driver_car(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    context.user_data["driver_car"] = (
        update.message.text
    )

    await update.message.reply_text(
        "🪪 أرسل رقم الرخصة أو صورة الرخصة:"
    )

    return DRIVER_LICENSE


async def driver_license(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user

    name = context.user_data.get(
        "driver_name",
        ""
    )

    phone = context.user_data.get(
        "driver_phone",
        ""
    )

    car = context.user_data.get(
        "driver_car",
        ""
    )

    license_text = ""
    license_file_id = None

    if update.message.text:

        license_text = update.message.text

    elif update.message.photo:

        license_text = "صورة الرخصة مرفقة"

        license_file_id = (
            update.message.photo[-1].file_id
        )

    else:

        await update.message.reply_text(
            "❌ أرسل رقم الرخصة أو صورة الرخصة."
        )

        return DRIVER_LICENSE

    conn = get_db()

    conn.execute("""
        INSERT INTO drivers (
            user_id,
            name,
            phone,
            car,
            license,
            license_file_id,
            status,
            online,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, 'pending', 0, ?)

        ON CONFLICT(user_id)
        DO UPDATE SET
            name=excluded.name,
            phone=excluded.phone,
            car=excluded.car,
            license=excluded.license,
            license_file_id=excluded.license_file_id,
            status='pending'
    """, (
        user.id,
        name,
        phone,
        car,
        license_text,
        license_file_id,
        now()
    ))

    conn.commit()
    conn.close()

    # ========================================================
    # إرسال بيانات السائق للمالك فقط
    # ========================================================

    owner_text = f"""
🚗 طلب تسجيل سائق جديد

👤 الاسم:
{name}

📱 الهاتف:
{phone}

🚕 السيارة:
{car}

🪪 الرخصة:
{license_text}

🆔 Telegram ID:
{user.id}

📅 التاريخ:
{now()}

⚠️ الحالة:
بانتظار موافقة المالك
"""

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ قبول السائق",
                    callback_data=f"approve_driver_{user.id}"
                ),
                InlineKeyboardButton(
                    "❌ رفض",
                    callback_data=f"reject_driver_{user.id}"
                )
            ]
        ]
    )

    if OWNER_ID == 0:

        logger.error(
            "OWNER_ID غير مضبوط!"
        )

    else:

        try:

            if license_file_id:

                await context.bot.send_photo(
                    chat_id=OWNER_ID,
                    photo=license_file_id,
                    caption=owner_text,
                    reply_markup=keyboard
                )

            else:

                await context.bot.send_message(
                    chat_id=OWNER_ID,
                    text=owner_text,
                    reply_markup=keyboard
                )

        except Exception as e:

            logger.error(
                f"خطأ في إرسال بيانات السائق: {e}"
            )

    await update.message.reply_text(
        "✅ تم إرسال طلب التسجيل إلى المالك.\n\n"
        "⏳ انتظر الموافقة."
    )

    context.user_data.clear()

    return ConversationHandler.END


# ============================================================
# قبول / رفض السائق
# ============================================================

async def driver_approval(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    if update.effective_user.id != OWNER_ID:

        await query.answer(
            "⛔ هذا الإجراء للمالك فقط.",
            show_alert=True
        )

        return

    await query.answer()

    data = query.data

    if data.startswith("approve_driver_"):

        driver_id = int(
            data.replace(
                "approve_driver_",
                ""
            )
        )

        conn = get_db()

        conn.execute("""
            UPDATE drivers
            SET status='approved',
                approved_at=?
            WHERE user_id=?
        """, (
            now(),
            driver_id
        ))

        conn.commit()
        conn.close()

        await query.edit_message_text(
            "✅ تم قبول السائق."
        )

        try:

            await context.bot.send_message(
                chat_id=driver_id,
                text=(
                    "🎉 مبروك!\n\n"
                    "✅ تمت الموافقة على تسجيلك كسائق "
                    "في بوت وصلني.\n\n"
                    "اضغط 🚗 سائق للدخول إلى لوحة السائق."
                ),
                reply_markup=driver_keyboard()
            )

        except Exception as e:

            logger.error(e)

    elif data.startswith("reject_driver_"):

        driver_id = int(
            data.replace(
                "reject_driver_",
                ""
            )
        )

        conn = get_db()

        conn.execute("""
            UPDATE drivers
            SET status='rejected',
                online=0
            WHERE user_id=?
        """, (
            driver_id,
        ))

        conn.commit()
        conn.close()

        await query.edit_message_text(
            "❌ تم رفض السائق."
        )

        try:

            await context.bot.send_message(
                chat_id=driver_id,
                text=(
                    "❌ تم رفض طلب تسجيلك كسائق."
                )
            )

        except Exception as e:

            logger.error(e)


# ============================================================
# تشغيل السائق
# ============================================================

async def driver_online(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user_id = update.effective_user.id

    conn = get_db()

    driver = conn.execute("""
        SELECT status
        FROM drivers
        WHERE user_id=?
    """, (
        user_id,
    )).fetchone()

    if not driver:

        conn.close()

        await update.message.reply_text(
            "❌ أنت غير مسجل كسائق."
        )

        return

    if driver["status"] != "approved":

        conn.close()

        await update.message.reply_text(
            "⏳ حسابك لم تتم الموافقة عليه."
        )

        return

    conn.execute("""
        UPDATE drivers
        SET online=1
        WHERE user_id=?
    """, (
        user_id,
    ))

    conn.commit()
    conn.close()

    await update.message.reply_text(
        "🟢 تم تشغيل حالة السائق.\n\n"
        "📍 اضغط الآن على «إرسال موقعي» "
        "حتى تصلك الطلبات القريبة.",
        reply_markup=driver_keyboard()
    )


# ============================================================
# إيقاف السائق
# ============================================================

async def driver_offline(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user_id = update.effective_user.id

    conn = get_db()

    conn.execute("""
        UPDATE drivers
        SET online=0
        WHERE user_id=?
    """, (
        user_id,
    ))

    conn.commit()
    conn.close()

    await update.message.reply_text(
        "🔴 تم إيقاف استقبال الطلبات."
    )


# ============================================================
# موقع السائق
# ============================================================

async def driver_location(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user_id = update.effective_user.id

    location = update.message.location

    if not location:
        return

    lat = location.latitude
    lon = location.longitude

    conn = get_db()

    driver = conn.execute("""
        SELECT status, online
        FROM drivers
        WHERE user_id=?
    """, (
        user_id,
    )).fetchone()

    if not driver:

        conn.close()

        await update.message.reply_text(
            "❌ أنت غير مسجل كسائق."
        )

        return

    conn.execute("""
        UPDATE drivers
        SET lat=?,
            lon=?
        WHERE user_id=?
    """, (
        lat,
        lon,
        user_id
    ))

    conn.commit()
    conn.close()

    await update.message.reply_text(
        "📍 تم تحديث موقعك بنجاح."
    )

    # إذا كان السائق متصلاً، أرسل له الطلبات القريبة
    if (
        driver["status"] == "approved"
        and
        driver["online"] == 1
    ):

        await send_nearby_rides(
            context,
            user_id,
            lat,
            lon
        )


# ============================================================
# إرسال الطلبات القريبة للسائق
# ============================================================

async def send_nearby_rides(
    context,
    driver_id,
    driver_lat,
    driver_lon
):

    conn = get_db()

    rides = conn.execute("""
        SELECT *
        FROM rides
        WHERE status='searching'
        ORDER BY id DESC
        LIMIT 30
    """).fetchall()

    conn.close()

    for ride in rides:

        distance = haversine(
            driver_lat,
            driver_lon,
            ride["pickup_lat"],
            ride["pickup_lon"]
        )

        if distance > MAX_DRIVER_DISTANCE_KM:
            continue

        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "🚕 تنفيذ الطلب",
                        callback_data=f"accept_ride_{ride['id']}"
                    )
                ]
            ]
        )

        text = f"""
🚕 طلب سيارة قريب منك

🆔 رقم الطلب:
#{ride['id']}

📍 موقع الراكب:
{ride['pickup']}

📏 المسافة منك:
{distance:.2f} كم

💰 الأجرة:
🤝 يتم الاتفاق عليها مع الراكب عند الركوب.

اضغط «🚕 تنفيذ الطلب» لقبول الطلب.
"""

        try:

            await context.bot.send_message(
                chat_id=driver_id,
                text=text,
                reply_markup=keyboard
            )

        except Exception as e:

            logger.error(
                f"خطأ بإرسال الطلب للسائق: {e}"
            )


# ============================================================
# طلب سيارة
# ============================================================

RIDE_PICKUP = 10


async def ride_start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    keyboard = ReplyKeyboardMarkup(
        [
            [
                KeyboardButton(
                    "📍 إرسال موقعي",
                    request_location=True
                )
            ],
            [
                KeyboardButton(
                    "❌ إلغاء"
                )
            ]
        ],
        resize_keyboard=True,
        one_time_keyboard=True
    )

    await update.message.reply_text(
        "🚕 طلب سيارة\n\n"
        "اضغط على زر «📍 إرسال موقعي» "
        "لإرسال موقعك مباشرة.",
        reply_markup=keyboard
    )

    return RIDE_PICKUP


# ============================================================
# موقع الراكب
# ============================================================

async def ride_pickup(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not update.message.location:

        await update.message.reply_text(
            "📍 الرجاء الضغط على زر «إرسال موقعي»."
        )

        return RIDE_PICKUP

    location = update.message.location

    user_id = update.effective_user.id

    pickup_lat = location.latitude
    pickup_lon = location.longitude

    pickup = (
        f"{pickup_lat:.6f}, "
        f"{pickup_lon:.6f}"
    )

    # ========================================================
    # التأكد من عدم وجود طلب نشط
    # ========================================================

    conn = get_db()

    active_ride = conn.execute("""
        SELECT id
        FROM rides
        WHERE passenger_id=?
          AND status IN ('searching', 'accepted')
        ORDER BY id DESC
        LIMIT 1
    """, (
        user_id,
    )).fetchone()

    if active_ride:

        conn.close()

        await update.message.reply_text(
            f"⚠️ لديك طلب نشط بالفعل رقم #{active_ride['id']}."
        )

        return ConversationHandler.END

    # ========================================================
    # إنشاء الطلب
    # ========================================================

    cur = conn.cursor()

    cur.execute("""
        INSERT INTO rides (
            passenger_id,
            pickup,
            pickup_lat,
            pickup_lon,
            price,
            status,
            created_at
        )
        VALUES (?, ?, ?, ?, NULL, 'searching', ?)
    """, (
        user_id,
        pickup,
        pickup_lat,
        pickup_lon,
        now()
    ))

    ride_id = cur.lastrowid

    conn.commit()
    conn.close()

    # ========================================================
    # البحث عن السائقين
    # ========================================================

    conn = get_db()

    drivers = conn.execute("""
        SELECT *
        FROM drivers
        WHERE status='approved'
          AND online=1
          AND lat IS NOT NULL
          AND lon IS NOT NULL
    """).fetchall()

    conn.close()

    nearby = []

    for driver in drivers:

        distance = haversine(
            pickup_lat,
            pickup_lon,
            driver["lat"],
            driver["lon"]
        )

        if distance <= MAX_DRIVER_DISTANCE_KM:

            nearby.append(
                (
                    distance,
                    driver
                )
            )

    nearby.sort(
        key=lambda x: x[0]
    )

    sent_count = 0

    # ========================================================
    # إرسال الطلب لأقرب السائقين
    # ========================================================

    for distance, driver in nearby[:10]:

        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "🚕 تنفيذ الطلب",
                        callback_data=f"accept_ride_{ride_id}"
                    )
                ]
            ]
        )

        text = f"""
🚕 طلب سيارة جديد

🆔 رقم الطلب:
#{ride_id}

📍 موقع الراكب:
{pickup}

📏 المسافة منك:
{distance:.2f} كم

💰 الأجرة:
🤝 يتم الاتفاق عليها مع الراكب عند الركوب.

اضغط «🚕 تنفيذ الطلب» لقبول الطلب.
"""

        try:

            await context.bot.send_message(
                chat_id=driver["user_id"],
                text=text,
                reply_markup=keyboard
            )

            sent_count += 1

        except Exception as e:

            logger.error(
                f"خطأ بإرسال الطلب: {e}"
            )

    # ========================================================
    # رسالة الراكب
    # ========================================================

    await update.message.reply_text(
        f"""
✅ تم إرسال طلبك.

🆔 رقم الطلب:
#{ride_id}

📍 تم تحديد موقعك بنجاح.

🚕 بانتظار سائق لتنفيذ الطلب.

💰 الأجرة:
🤝 يتم الاتفاق مع السائق عند الركوب.

👥 عدد السائقين الذين وصلهم الطلب:
{sent_count}
""",
        reply_markup=passenger_keyboard()
    )

    context.user_data.clear()

    return ConversationHandler.END


# ============================================================
# تنفيذ الطلب
# ============================================================

async def accept_ride(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    driver_id = update.effective_user.id

    # ========================================================
    # التحقق من السائق
    # ========================================================

    conn = get_db()

    driver = conn.execute("""
        SELECT *
        FROM drivers
        WHERE user_id=?
          AND status='approved'
    """, (
        driver_id,
    )).fetchone()

    if not driver:

        conn.close()

        await query.answer(
            "❌ يجب أن تكون سائقاً معتمداً.",
            show_alert=True
        )

        return

    # ========================================================
    # منع أخذ رحلة ثانية
    # ========================================================

    if driver["current_ride"]:

        conn.close()

        await query.answer(
            "⚠️ لديك رحلة حالية بالفعل.",
            show_alert=True
        )

        return

    ride_id = int(
        query.data.replace(
            "accept_ride_",
            ""
        )
    )

    # ========================================================
    # تنفيذ الطلب بشكل ذري
    # ========================================================

    cur = conn.cursor()

    cur.execute("""
        UPDATE rides
        SET status='accepted',
            driver_id=?,
            accepted_at=?
        WHERE id=?
          AND status='searching'
    """, (
        driver_id,
        now(),
        ride_id
    ))

    if cur.rowcount == 0:

        conn.close()

        await query.answer(
            "❌ تم تنفيذ الطلب من سائق آخر.",
            show_alert=True
        )

        try:

            await query.edit_message_reply_markup(
                reply_markup=None
            )

        except Exception:
            pass

        return

    # ========================================================
    # ربط الرحلة بالسائق
    # ========================================================

    conn.execute("""
        UPDATE drivers
        SET current_ride=?
        WHERE user_id=?
    """, (
        ride_id,
        driver_id
    ))

    ride = conn.execute("""
        SELECT *
        FROM rides
        WHERE id=?
    """, (
        ride_id,
    )).fetchone()

    conn.commit()
    conn.close()

    await query.answer(
        "✅ تم تنفيذ الطلب."
    )

    await query.edit_message_text(
        f"""
✅ تم تنفيذ الطلب

🆔 رقم الطلب:
#{ride_id}

📍 موقع الراكب:
{ride['pickup']}

💰 الأجرة:
🤝 يتم الاتفاق مع الراكب عند الركوب.

🚕 توجه إلى موقع الراكب.
"""
    )

    # ========================================================
    # إبلاغ الراكب
    # ========================================================

    try:

        await context.bot.send_message(
            chat_id=ride["passenger_id"],
            text=f"""
🚕 تم تنفيذ طلبك!

🆔 رقم الطلب:
#{ride_id}

👤 السائق:
{driver['name']}

🚗 السيارة:
{driver['car']}

📱 الهاتف:
{driver['phone']}

💰 الأجرة:
🤝 يتم الاتفاق عليها مع السائق عند الركوب.

📍 السائق توجه إلى موقعك.
"""
        )

        # إرسال موقع السائق للراكب
        if (
            driver["lat"] is not None
            and
            driver["lon"] is not None
        ):

            await context.bot.send_location(
                chat_id=ride["passenger_id"],
                latitude=driver["lat"],
                longitude=driver["lon"]
            )

    except Exception as e:

        logger.error(
            f"خطأ في إبلاغ الراكب: {e}"
        )


# ============================================================
# الرحلة الحالية للسائق
# ============================================================

async def current_ride(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    driver_id = update.effective_user.id

    conn = get_db()

    ride = conn.execute("""
        SELECT *
        FROM rides
        WHERE driver_id=?
          AND status='accepted'
        ORDER BY id DESC
        LIMIT 1
    """, (
        driver_id,
    )).fetchone()

    conn.close()

    if not ride:

        await update.message.reply_text(
            "📭 لا توجد لديك رحلة حالية."
        )

        return

    await update.message.reply_text(
        f"""
🚕 الرحلة الحالية

🆔 رقم الطلب:
#{ride['id']}

📍 موقع الراكب:
{ride['pickup']}

💰 الأجرة:
🤝 يتم الاتفاق عليها عند الركوب.
"""
    )


# ============================================================
# إحصائيات السائق
# ============================================================

async def driver_statistics(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    driver_id = update.effective_user.id

    conn = get_db()

    total = conn.execute("""
        SELECT COUNT(*) AS count
        FROM rides
        WHERE driver_id=?
    """, (
        driver_id,
    )).fetchone()["count"]

    completed = conn.execute("""
        SELECT COUNT(*) AS count
        FROM rides
        WHERE driver_id=?
          AND status='completed'
    """, (
        driver_id,
    )).fetchone()["count"]

    conn.close()

    await update.message.reply_text(
        f"""
📊 إحصائياتك

🚕 إجمالي الرحلات:
{total}

✅ الرحلات المكتملة:
{completed}

💰 الأجرة:
يتم الاتفاق عليها مباشرة بين السائق والراكب.
"""
    )


# ============================================================
# طلبات الراكب
# ============================================================

async def passenger_rides(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user_id = update.effective_user.id

    conn = get_db()

    rides = conn.execute("""
        SELECT *
        FROM rides
        WHERE passenger_id=?
        ORDER BY id DESC
        LIMIT 10
    """, (
        user_id,
    )).fetchall()

    conn.close()

    if not rides:

        await update.message.reply_text(
            "📭 لا توجد لديك طلبات."
        )

        return

    text = "📋 طلباتك:\n\n"

    for ride in rides:

        text += (
            f"🆔 #{ride['id']}\n"
            f"📍 الموقع: {ride['pickup']}\n"
            f"📌 الحالة: {ride['status']}\n"
            f"💰 الأجرة: يتم الاتفاق عند الركوب\n\n"
        )

    await update.message.reply_text(
        text
    )


# ============================================================
# إحصائيات المالك
# ============================================================

async def owner_statistics(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if update.effective_user.id != OWNER_ID:

        await update.message.reply_text(
            "⛔ هذا الأمر للمالك فقط."
        )

        return

    conn = get_db()

    users = conn.execute("""
        SELECT COUNT(*) AS count
        FROM users
    """).fetchone()["count"]

    drivers = conn.execute("""
        SELECT COUNT(*) AS count
        FROM drivers
    """).fetchone()["count"]

    approved = conn.execute("""
        SELECT COUNT(*) AS count
        FROM drivers
        WHERE status='approved'
    """).fetchone()["count"]

    pending = conn.execute("""
        SELECT COUNT(*) AS count
        FROM drivers
        WHERE status='pending'
    """).fetchone()["count"]

    online = conn.execute("""
        SELECT COUNT(*) AS count
        FROM drivers
        WHERE status='approved'
          AND online=1
    """).fetchone()["count"]

    rides = conn.execute("""
        SELECT COUNT(*) AS count
        FROM rides
    """).fetchone()["count"]

    searching = conn.execute("""
        SELECT COUNT(*) AS count
        FROM rides
        WHERE status='searching'
    """).fetchone()["count"]

    accepted = conn.execute("""
        SELECT COUNT(*) AS count
        FROM rides
        WHERE status='accepted'
    """).fetchone()["count"]

    conn.close()

    await update.message.reply_text(
        f"""
📊 إحصائيات وصلني

👥 المستخدمون:
{users}

🚗 السائقون:
{drivers}

✅ السائقون المعتمدون:
{approved}

⏳ طلبات قيد المراجعة:
{pending}

🟢 السائقون المتصلون:
{online}

🚕 إجمالي الطلبات:
{rides}

🔎 بانتظار سائق:
{searching}

🚗 تم تنفيذها:
{accepted}
"""
    )


# ============================================================
# المساعدة
# ============================================================

async def help_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(
        f"""
❓ مساعدة - وصلني

📍 المنطقة:
{CITY_NAME}

🚕 للراكب:

1️⃣ اضغط:
🚕 طلب سيارة

2️⃣ اضغط:
📍 إرسال موقعي

3️⃣ انتظر السائق.

💰 الأجرة يتم الاتفاق عليها
بين الراكب والسائق عند الركوب.

🚗 للسائق:

1️⃣ اضغط:
🟢 تشغيل

2️⃣ اضغط:
📍 إرسال موقعي

3️⃣ ستظهر لك الطلبات القريبة.

4️⃣ اضغط:
🚕 تنفيذ الطلب

📝 تسجيل سائق:
/register_driver

📊 إحصائيات المالك:
/statistics
"""
    )


# ============================================================
# إلغاء
# ============================================================

async def cancel(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    context.user_data.clear()

    await update.message.reply_text(
        "❌ تم إلغاء العملية.",
        reply_markup=main_keyboard()
    )

    return ConversationHandler.END


# ============================================================
# تشغيل البوت
# ============================================================

def main():

    if not BOT_TOKEN:

        raise RuntimeError(
            "BOT_TOKEN غير موجود!"
        )

    if OWNER_ID == 0:

        logger.warning(
            "⚠️ OWNER_ID غير مضبوط!"
        )

    application = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        .build()
    )

    # ========================================================
    # تسجيل السائق
    # ========================================================

    driver_registration = ConversationHandler(

        entry_points=[
            CommandHandler(
                "register_driver",
                register_driver_start
            )
        ],

        states={

            DRIVER_NAME: [
                MessageHandler(
                    filters.TEXT
                    & ~filters.COMMAND,
                    driver_name
                )
            ],

            DRIVER_PHONE: [
                MessageHandler(
                    filters.TEXT
                    & ~filters.COMMAND,
                    driver_phone
                )
            ],

            DRIVER_CAR: [
                MessageHandler(
                    filters.TEXT
                    & ~filters.COMMAND,
                    driver_car
                )
            ],

            DRIVER_LICENSE: [
                MessageHandler(
                    (
                        filters.TEXT
                        |
                        filters.PHOTO
                    )
                    & ~filters.COMMAND,
                    driver_license
                )
            ]
        },

        fallbacks=[
            CommandHandler(
                "cancel",
                cancel
            )
        ]
    )

    # ========================================================
    # طلب السيارة
    # ========================================================

    ride_conversation = ConversationHandler(

        entry_points=[
            MessageHandler(
                filters.Regex(
                    "^🚕 طلب سيارة$"
                ),
                ride_start
            )
        ],

        states={

            RIDE_PICKUP: [
                MessageHandler(
                    filters.LOCATION,
                    ride_pickup
                )
            ]
        },

        fallbacks=[
            CommandHandler(
                "cancel",
                cancel
            ),

            MessageHandler(
                filters.Regex(
                    "^❌ إلغاء$"
                ),
                cancel
            )
        ]
    )

    # ========================================================
    # الأوامر
    # ========================================================

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
        CommandHandler(
            "statistics",
            owner_statistics
        )
    )

    application.add_handler(
        driver_registration
    )

    application.add_handler(
        ride_conversation
    )

    # ========================================================
    # القوائم
    # ========================================================

    application.add_handler(
        MessageHandler(
            filters.Regex("^🚕 راكب$"),
            passenger_menu
        )
    )

    application.add_handler(
        MessageHandler(
            filters.Regex("^🚗 سائق$"),
            driver_menu
        )
    )

    application.add_handler(
        MessageHandler(
            filters.Regex("^🟢 تشغيل$"),
            driver_online
        )
    )

    application.add_handler(
        MessageHandler(
            filters.Regex("^🔴 إيقاف$"),
            driver_offline
        )
    )

    application.add_handler(
        MessageHandler(
            filters.Regex("^🚕 الرحلة الحالية$"),
            current_ride
        )
    )

    application.add_handler(
        MessageHandler(
            filters.Regex("^📊 إحصائياتي$"),
            driver_statistics
        )
    )

    application.add_handler(
        MessageHandler(
            filters.Regex("^📋 طلباتي$"),
            passenger_rides
        )
    )

    application.add_handler(
        MessageHandler(
            filters.Regex("^❓ المساعدة$"),
            help_command
        )
    )

    # ========================================================
    # استقبال الموقع
    # ========================================================

    application.add_handler(
        MessageHandler(
            filters.LOCATION,
            driver_location
        )
    )

    # ========================================================
    # قبول / رفض السائق
    # ========================================================

    application.add_handler(
        CallbackQueryHandler(
            driver_approval,
            pattern=r"^(approve_driver_|reject_driver_)"
        )
    )

    # ========================================================
    # تنفيذ الطلب
    # ========================================================

    application.add_handler(
        CallbackQueryHandler(
            accept_ride,
            pattern=r"^accept_ride_"
        )
    )

    logger.info(
        "🚕 وصلني Bot started successfully"
    )

    application.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    main()
