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

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)


# ============================================================
# Health Check - Render
# ============================================================

class HealthHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"Waselni Bot is running!")

    def log_message(self, format, *args):
        return


def run_health_server():
    try:
        server = HTTPServer(("0.0.0.0", PORT), HealthHandler)
        logger.info(f"Health server running on port {PORT}")
        server.serve_forever()
    except Exception as e:
        logger.error(f"Health server error: {e}")


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

    # المستخدمين
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            first_name TEXT,
            username TEXT,
            phone TEXT,
            created_at TEXT
        )
    """)

    # السائقين
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

    # الرحلات
    cur.execute("""
        CREATE TABLE IF NOT EXISTS rides (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            passenger_id INTEGER,
            pickup TEXT,
            destination TEXT,
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

    # التقييمات
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
# أدوات مساعدة
# ============================================================

def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


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


def haversine(lat1, lon1, lat2, lon2):

    if None in (lat1, lon1, lat2, lon2):
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

    return R * 2 * math.atan2(
        math.sqrt(a),
        math.sqrt(1 - a)
    )


# ============================================================
# لوحات التحكم
# ============================================================

def passenger_keyboard():

    return ReplyKeyboardMarkup(
        [
            [
                KeyboardButton("🚕 طلب سيارة")
            ],
            [
                KeyboardButton("📋 طلباتي"),
                KeyboardButton("❓ المساعدة")
            ]
        ],
        resize_keyboard=True
    )


def driver_keyboard():

    return ReplyKeyboardMarkup(
        [
            [
                KeyboardButton("🟢 تشغيل"),
                KeyboardButton("🔴 إيقاف")
            ],
            [
                KeyboardButton(
                    "📍 مشاركة موقعي",
                    request_location=True
                )
            ],
            [
                KeyboardButton("🚕 الرحلة الحالية")
            ],
            [
                KeyboardButton("📊 إحصائياتي")
            ],
            [
                KeyboardButton("❓ المساعدة")
            ]
        ],
        resize_keyboard=True
    )


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
# /start
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user = update.effective_user

    save_user(user)

    text = f"""
🚕 أهلاً بك في بوت وصلني

📍 المنطقة: {CITY_NAME}

اختر طريقة استخدام البوت:
"""

    await update.message.reply_text(
        text,
        reply_markup=main_keyboard()
    )


# ============================================================
# اختيار راكب
# ============================================================

async def passenger_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(
        "🚕 قائمة الراكب",
        reply_markup=passenger_keyboard()
    )


# ============================================================
# اختيار سائق
# ============================================================

async def driver_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user_id = update.effective_user.id

    conn = get_db()

    driver = conn.execute(
        "SELECT * FROM drivers WHERE user_id=?",
        (user_id,)
    ).fetchone()

    conn.close()

    if not driver:

        await update.message.reply_text(
            "🚗 أنت غير مسجل كسائق.\n\n"
            "اضغط /register_driver للتسجيل."
        )

        return

    if driver["status"] == "pending":

        await update.message.reply_text(
            "⏳ طلب تسجيلك ما زال قيد المراجعة من مالك البوت."
        )

        return

    if driver["status"] == "rejected":

        await update.message.reply_text(
            "❌ تم رفض طلب تسجيلك."
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

    driver = conn.execute(
        "SELECT status FROM drivers WHERE user_id=?",
        (user_id,)
    ).fetchone()

    conn.close()

    if driver:

        if driver["status"] == "approved":
            await update.message.reply_text(
                "✅ أنت مسجل ومعتمد كسائق بالفعل."
            )
            return ConversationHandler.END

        if driver["status"] == "pending":
            await update.message.reply_text(
                "⏳ طلب تسجيلك قيد المراجعة."
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

    context.user_data["driver_name"] = update.message.text

    await update.message.reply_text(
        "📱 أرسل رقم هاتفك:"
    )

    return DRIVER_PHONE


async def driver_phone(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    context.user_data["driver_phone"] = update.message.text

    await update.message.reply_text(
        "🚕 أرسل نوع السيارة + الموديل + اللون:"
    )

    return DRIVER_CAR


async def driver_car(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    context.user_data["driver_car"] = update.message.text

    await update.message.reply_text(
        "🪪 أرسل رقم إجازة/رخصة القيادة.\n\n"
        "يمكنك أيضاً إرسال صورة الرخصة."
    )

    return DRIVER_LICENSE


async def driver_license(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user = update.effective_user

    name = context.user_data.get("driver_name", "")
    phone = context.user_data.get("driver_phone", "")
    car = context.user_data.get("driver_car", "")

    license_text = ""
    license_file_id = None

    # إذا أرسل نص
    if update.message.text:

        license_text = update.message.text

    # إذا أرسل صورة
    elif update.message.photo:

        license_text = "تم إرسال صورة الرخصة"

        license_file_id = (
            update.message.photo[-1].file_id
        )

    else:

        await update.message.reply_text(
            "❌ الرجاء إرسال رقم الرخصة أو صورة الرخصة."
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
            "OWNER_ID غير مضبوط في متغيرات البيئة"
        )

    else:

        try:

            # إذا توجد صورة للرخصة نرسلها للمالك أولاً
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

            logger.info(
                f"تم إرسال طلب السائق {user.id} إلى المالك فقط"
            )

        except Exception as e:

            logger.error(
                f"خطأ في إرسال طلب السائق للمالك: {e}"
            )

    await update.message.reply_text(
        "✅ تم إرسال بياناتك إلى مالك البوت للمراجعة.\n\n"
        "⏳ سيتم إعلامك بعد اتخاذ قرار القبول أو الرفض."
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

    await query.answer()

    # ========================================================
    # المالك فقط
    # ========================================================

    if update.effective_user.id != OWNER_ID:

        await query.answer(
            "⛔ هذا الإجراء متاح لمالك البوت فقط.",
            show_alert=True
        )

        return

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
            "✅ تم قبول السائق بنجاح."
        )

        try:

            await context.bot.send_message(
                chat_id=driver_id,
                text=(
                    "🎉 مبروك!\n\n"
                    "✅ تمت الموافقة على تسجيلك كسائق "
                    "في بوت وصلني.\n\n"
                    "يمكنك الآن الدخول إلى قائمة السائق."
                ),
                reply_markup=driver_keyboard()
            )

        except Exception as e:

            logger.error(
                f"خطأ في إرسال رسالة القبول: {e}"
            )

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
            "❌ تم رفض طلب السائق."
        )

        try:

            await context.bot.send_message(
                chat_id=driver_id,
                text=(
                    "❌ نأسف، تم رفض طلب تسجيلك كسائق "
                    "في بوت وصلني."
                )
            )

        except Exception as e:

            logger.error(
                f"خطأ في إرسال رسالة الرفض: {e}"
            )


# ============================================================
# تشغيل السائق
# ============================================================

async def driver_online(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user_id = update.effective_user.id

    conn = get_db()

    driver = conn.execute(
        "SELECT status FROM drivers WHERE user_id=?",
        (user_id,)
    ).fetchone()

    if not driver:

        conn.close()

        await update.message.reply_text(
            "❌ أنت غير مسجل كسائق."
        )

        return

    if driver["status"] != "approved":

        conn.close()

        await update.message.reply_text(
            "⏳ حسابك لم تتم الموافقة عليه بعد."
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
        "ستصلك طلبات الرحلات."
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
        "🔴 تم إيقاف حالة السائق."
    )


# ============================================================
# مشاركة موقع السائق
# ============================================================

async def driver_location(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    user_id = update.effective_user.id

    if not update.message.location:
        return

    lat = update.message.location.latitude
    lon = update.message.location.longitude

    conn = get_db()

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


# ============================================================
# طلب سيارة - البداية
# ============================================================

RIDE_PICKUP = 10
RIDE_DESTINATION = 11
RIDE_PRICE = 12


async def ride_start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    await update.message.reply_text(
        "🚕 طلب سيارة\n\n"
        "📍 أرسل موقع الانطلاق من خلال زر الموقع، "
        "أو اكتب مكان الانطلاق:"
    )

    return RIDE_PICKUP


# ============================================================
# موقع الانطلاق
# ============================================================

async def ride_pickup(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if update.message.location:

        location = update.message.location

        context.user_data["pickup_lat"] = (
            location.latitude
        )

        context.user_data["pickup_lon"] = (
            location.longitude
        )

        context.user_data["pickup"] = (
            f"الموقع الجغرافي: "
            f"{location.latitude:.6f}, "
            f"{location.longitude:.6f}"
        )

    else:

        context.user_data["pickup"] = (
            update.message.text
        )

        context.user_data["pickup_lat"] = None
        context.user_data["pickup_lon"] = None

    await update.message.reply_text(
        "📍 أرسل مكان الوصول:"
    )

    return RIDE_DESTINATION


# ============================================================
# الوجهة
# ============================================================

async def ride_destination(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    context.user_data["destination"] = (
        update.message.text
    )

    await update.message.reply_text(
        "💰 أرسل أجرة الرحلة:"
    )

    return RIDE_PRICE


# ============================================================
# السعر وإنشاء الرحلة
# ============================================================

async def ride_price(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    try:

        price = float(
            update.message.text.replace(",", ".")
        )

    except ValueError:

        await update.message.reply_text(
            "❌ الرجاء إرسال السعر كرقم.\n"
            "مثال: 50000"
        )

        return RIDE_PRICE

    user_id = update.effective_user.id

    pickup = context.user_data.get(
        "pickup",
        ""
    )

    destination = context.user_data.get(
        "destination",
        ""
    )

    pickup_lat = context.user_data.get(
        "pickup_lat"
    )

    pickup_lon = context.user_data.get(
        "pickup_lon"
    )

    conn = get_db()

    cur = conn.cursor()

    cur.execute("""
        INSERT INTO rides (
            passenger_id,
            pickup,
            destination,
            pickup_lat,
            pickup_lon,
            price,
            status,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, 'searching', ?)
    """, (
        user_id,
        pickup,
        destination,
        pickup_lat,
        pickup_lon,
        price,
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
    """).fetchall()

    conn.close()

    available_drivers = []

    for driver in drivers:

        distance = haversine(
            pickup_lat,
            pickup_lon,
            driver["lat"],
            driver["lon"]
        )

        available_drivers.append(
            (
                distance,
                driver
            )
        )

    available_drivers.sort(
        key=lambda x: x[0]
    )

    # إرسال الطلب إلى أقرب 10 سائقين
    sent_count = 0

    ride_text = f"""
🚕 طلب رحلة جديدة

🆔 رقم الرحلة:
#{ride_id}

📍 الانطلاق:
{pickup}

🏁 الوجهة:
{destination}

💰 الأجرة:
{price:,.0f}

📏 المسافة عنك:
سيتم عرضها حسب موقعك

⚠️ أول سائق يقبل الرحلة يحصل عليها.
"""

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🚕 قبول الرحلة",
                    callback_data=f"accept_ride_{ride_id}"
                )
            ]
        ]
    )

    for distance, driver in available_drivers:

        if sent_count >= 10:
            break

        try:

            await context.bot.send_message(
                chat_id=driver["user_id"],
                text=ride_text,
                reply_markup=keyboard
            )

            sent_count += 1

        except Exception as e:

            logger.error(
                f"خطأ بإرسال الرحلة للسائق "
                f"{driver['user_id']}: {e}"
            )

    await update.message.reply_text(
        f"""
✅ تم إنشاء طلب الرحلة

🆔 رقم الطلب: #{ride_id}

📍 من:
{pickup}

🏁 إلى:
{destination}

💰 الأجرة:
{price:,.0f}

🚕 تم البحث عن سائقين قريبين.

عدد السائقين الذين وصلهم الطلب:
{sent_count}
"""
    )

    context.user_data.clear()

    return ConversationHandler.END


# ============================================================
# قبول الرحلة
# ============================================================

async def accept_ride(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    query = update.callback_query

    await query.answer()

    driver_id = update.effective_user.id

    data = query.data

    ride_id = int(
        data.replace(
            "accept_ride_",
            ""
        )
    )

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
            "❌ أنت لست سائقاً معتمداً.",
            show_alert=True
        )

        return

    # ========================================================
    # قبول ذري للرحلة
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
            "❌ الرحلة تم قبولها من سائق آخر.",
            show_alert=True
        )

        try:
            await query.edit_message_reply_markup(
                reply_markup=None
            )
        except Exception:
            pass

        return

    # ربط الرحلة بالسائق
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

    await query.edit_message_text(
        f"""
✅ تم قبول الرحلة

🆔 الرحلة: #{ride_id}

📍 الانطلاق:
{ride['pickup']}

🏁 الوجهة:
{ride['destination']}

💰 الأجرة:
{ride['price']:,.0f}
"""
    )

    # ========================================================
    # إرسال بيانات السائق للراكب
    # ========================================================

    conn = get_db()

    driver_info = conn.execute("""
        SELECT *
        FROM drivers
        WHERE user_id=?
    """, (
        driver_id,
    )).fetchone()

    conn.close()

    passenger_text = f"""
🚕 تم العثور على سائق!

👤 السائق:
{driver_info['name']}

🚗 السيارة:
{driver_info['car']}

📱 الهاتف:
{driver_info['phone']}

🆔 رقم الرحلة:
#{ride_id}

📍 السائق في طريقه إليك.
"""

    try:

        await context.bot.send_message(
            chat_id=ride["passenger_id"],
            text=passenger_text
        )

    except Exception as e:

        logger.error(
            f"خطأ بإبلاغ الراكب: {e}"
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
        SELECT r.*
        FROM rides r
        JOIN drivers d
          ON d.current_ride = r.id
        WHERE d.user_id=?
          AND r.status='accepted'
    """, (
        driver_id,
    )).fetchone()

    conn.close()

    if not ride:

        await update.message.reply_text(
            "📭 لا توجد لديك رحلة حالياً."
        )

        return

    await update.message.reply_text(
        f"""
🚕 رحلتك الحالية

🆔 رقم الرحلة:
#{ride['id']}

📍 الانطلاق:
{ride['pickup']}

🏁 الوجهة:
{ride['destination']}

💰 الأجرة:
{ride['price']:,.0f}
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

    earnings = conn.execute("""
        SELECT COALESCE(SUM(price), 0) AS total
        FROM rides
        WHERE driver_id=?
          AND status='completed'
    """, (
        driver_id,
    )).fetchone()["total"]

    conn.close()

    await update.message.reply_text(
        f"""
📊 إحصائياتك

🚕 إجمالي الرحلات:
{total}

✅ الرحلات المكتملة:
{completed}

💰 إجمالي الأرباح:
{earnings:,.0f}
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
            "📭 لا توجد لديك طلبات سابقة."
        )

        return

    text = "📋 آخر طلباتك:\n\n"

    for ride in rides:

        text += (
            f"🆔 #{ride['id']}\n"
            f"📍 {ride['pickup']}\n"
            f"🏁 {ride['destination']}\n"
            f"💰 {ride['price']:,.0f}\n"
            f"📌 الحالة: {ride['status']}\n\n"
        )

    await update.message.reply_text(text)


# ============================================================
# إحصائيات المالك
# ============================================================

async def owner_statistics(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if update.effective_user.id != OWNER_ID:

        await update.message.reply_text(
            "⛔ هذا الأمر متاح لمالك البوت فقط."
        )

        return

    conn = get_db()

    users = conn.execute(
        "SELECT COUNT(*) AS count FROM users"
    ).fetchone()["count"]

    drivers = conn.execute(
        "SELECT COUNT(*) AS count FROM drivers"
    ).fetchone()["count"]

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

    rides = conn.execute(
        "SELECT COUNT(*) AS count FROM rides"
    ).fetchone()["count"]

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

⏳ طلبات السائقين قيد المراجعة:
{pending}

🟢 السائقون المتصلون:
{online}

🚕 إجمالي الرحلات:
{rides}

🔎 الرحلات الباحثة عن سائق:
{searching}

🚗 الرحلات المقبولة:
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
اضغط "🚕 طلب سيارة"

🚗 للسائق:
اضغط "🚗 سائق"

📝 تسجيل سائق:
/register_driver

📊 إحصائيات المالك:
/statistics

/start
إعادة تشغيل البوت
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
            "BOT_TOKEN غير موجود في Environment Variables"
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
                    filters.TEXT & ~filters.COMMAND,
                    driver_name
                )
            ],

            DRIVER_PHONE: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    driver_phone
                )
            ],

            DRIVER_CAR: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    driver_car
                )
            ],

            DRIVER_LICENSE: [
                MessageHandler(
                    (
                        filters.TEXT
                        | filters.PHOTO
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
    # طلب الرحلة
    # ========================================================

    ride_conversation = ConversationHandler(

        entry_points=[
            MessageHandler(
                filters.Regex("^🚕 طلب سيارة$"),
                ride_start
            )
        ],

        states={

            RIDE_PICKUP: [
                MessageHandler(
                    filters.LOCATION,
                    ride_pickup
                ),
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    ride_pickup
                )
            ],

            RIDE_DESTINATION: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    ride_destination
                )
            ],

            RIDE_PRICE: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND,
                    ride_price
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
    # أزرار القوائم
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
            filters.Regex("^📍 مشاركة موقعي$")
            & filters.LOCATION,
            driver_location
        )
    )

    # مهم: استقبال أي Location من السائق
    application.add_handler(
        MessageHandler(
            filters.LOCATION,
            driver_location
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
    # أزرار قبول/رفض السائق
    # ========================================================

    application.add_handler(
        CallbackQueryHandler(
            driver_approval,
            pattern=r"^(approve_driver_|reject_driver_)"
        )
    )

    # ========================================================
    # زر قبول الرحلة
    # ========================================================

    application.add_handler(
        CallbackQueryHandler(
            accept_ride,
            pattern=r"^accept_ride_"
        )
    )

    # ========================================================
    # تشغيل
    # ========================================================

    logger.info("🚕 وصلني Bot is starting...")

    application.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    main()
