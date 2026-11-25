import asyncio
import hashlib
import logging
import os
import re
import asyncpg
from aiohttp import web
from aiogram import Bot, Dispatcher, F, types
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.filters import Command, CommandStart
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from telethon import TelegramClient, events
from telethon.sessions import StringSession

logging.basicConfig(level=logging.INFO)


def get_required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Muhit o'zgaruvchisi topilmadi: {name}")
    return value


# Barcha maxfiy kalitlar faqat Render Environment Variables'dan olinadi
API_ID = int(get_required_env("API_ID"))
API_HASH = get_required_env("API_HASH")
BOT_TOKEN = get_required_env("BOT_TOKEN")
SESSION_STRING = get_required_env("SESSION_STRING")
DATABASE_URL = get_required_env("DATABASE_URL")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0").strip() or "0")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
db_pool: asyncpg.Pool | None = None

# O'zbekiston viloyatlari va ularning matndagi kalit so'zlari
REGIONS = {
    "xorazm": ("Xorazm", ["xorazm", "urganch", "xiva", "xonqa", "hazorasp", "gurlan", "shovot", "bog'ot", "yangibozor"]),
    "toshkent": ("Toshkent", ["toshkent", "tashkent", "chirchiq", "olmaliq", "angren", "bekobod", "zangiota"]),
    "samarqand": ("Samarqand", ["samarqand", "urgut", "kattaqo'rg'on", "bulung'ur", "jomboy"]),
    "buxoro": ("Buxoro", ["buxoro", "g'ijduvon", "kogon", "qorako'l", "romitan"]),
    "qashqadaryo": ("Qashqadaryo", ["qashqadaryo", "qarshi", "shahrisabz", "kitob", "g'uzor", "koson"]),
    "surxondaryo": ("Surxondaryo", ["surxondaryo", "termiz", "denov", "sherobod", "boysun"]),
    "navoiy": ("Navoiy", ["navoiy", "zarafshon", "karmana", "nurota"]),
    "jizzax": ("Jizzax", ["jizzax", "zomin", "g'allaorol", "paxtakor"]),
    "sirdaryo": ("Sirdaryo", ["sirdaryo", "guliston", "yangiyer", "shirin"]),
    "fargona": ("Farg'ona", ["farg'ona", "fargona", "qo'qon", "marg'ilon", "quva", "rishton"]),
    "andijon": ("Andijon", ["andijon", "asaka", "shahrixon", "xonobod"]),
    "namangan": ("Namangan", ["namangan", "chust", "pop", "kosonsoy"]),
    "qoraqalpogiston": ("Qoraqalpog'iston", ["qoraqalpog'iston", "nukus", "beruniy", "to'rtko'l", "ellikkala", "xo'jayli"]),
}

# Yuk mashinasi turlari va matndagi kalit so'zlari
TRUCK_TYPES = {
    "all": ("🚛 Barcha mashinalar", []),
    "fura": ("🚚 Fura (Tent / 20t)", ["fura", "tent", "20t", "20 t", "20 tonna", "shalanda", "mega", "pritsep"]),
    "isuzu": ("🚛 Isuzu / MAN (5-10t)", ["isuzu", "isuzi", "man", "kamaz", "zil", "gaz-53", "gaz 53", "5t", "10t", "5 tonna", "10 tonna"]),
    "gazel": ("🚐 Gazel / Labo / Damas", ["gazel", "labo", "damas", "porter", "changan", "bongo", "kichik yuk"]),
    "ref": ("❄️ Refrijerator (Muzlatkich)", ["ref", "refrijerator", "muzlatkich", "xolodilnik", "termo", "muzlatgich"]),
}

user_temp = {}
admin_waiting_broadcast = set()


async def init_db():
    global db_pool
    db_pool = await asyncpg.create_pool(
        dsn=DATABASE_URL,
        min_size=1,
        max_size=5,
        statement_cache_size=0
    )
    async with db_pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS obunachilar (
                user_id BIGINT PRIMARY KEY,
                from_region TEXT NOT NULL,
                to_region TEXT NOT NULL,
                truck_type TEXT DEFAULT 'all',
                active BOOLEAN DEFAULT TRUE,
                updated_at TIMESTAMPTZ DEFAULT NOW()
            );
        """)
        await conn.execute("""
            ALTER TABLE obunachilar
            ADD COLUMN IF NOT EXISTS truck_type TEXT DEFAULT 'all';
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS elonlar (
                id SERIAL PRIMARY KEY,
                chat_id BIGINT,
                message_id BIGINT,
                chat_title TEXT,
                from_region TEXT NOT NULL,
                to_region TEXT NOT NULL,
                truck_type TEXT DEFAULT 'general',
                text_hash TEXT,
                text_body TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                UNIQUE(chat_id, message_id)
            );
        """)
        await conn.execute("""
            ALTER TABLE elonlar
            ADD COLUMN IF NOT EXISTS truck_type TEXT DEFAULT 'general';
        """)
        await conn.execute("""
            ALTER TABLE elonlar
            ADD COLUMN IF NOT EXISTS text_hash TEXT;
        """)
        await conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_elonlar_hash_time
            ON elonlar (text_hash, created_at DESC);
        """)
    logging.info("PostgreSQL (Supabase) bazasi muvaffaqiyatli ulandi!")


async def cleanup_old_cargos():
    """3 kundan eski e'lonlarni bazadan avtomatik tozalab turadi."""
    while True:
        try:
            await asyncio.sleep(6 * 3600)
            if db_pool:
                deleted = await db_pool.execute(
                    "DELETE FROM elonlar WHERE created_at < NOW() - INTERVAL '3 days'"
                )
                logging.info(f"Baza tozalandi (3 kundan eski e'lonlar): {deleted}")
        except Exception as e:
            logging.error(f"Bazani tozalashda xato: {e}")


def make_text_hash(text: str) -> str:
    """E'lon matnini normallashtirib yagona SHA-256 iz yaratadi."""
    normalized = re.sub(r"https?://\S+|@\w+", "", text.lower())
    normalized = re.sub(r"[^\w\d]+", "", normalized)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def build_regions_keyboard(prefix: str) -> InlineKeyboardMarkup:
    buttons = []
    row = []
    for key, (label, _) in REGIONS.items():
        row.append(InlineKeyboardButton(text=label, callback_data=f"{prefix}:{key}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def build_trucks_keyboard() -> InlineKeyboardMarkup:
    buttons = []
    for key, (label, _) in TRUCK_TYPES.items():
        buttons.append([InlineKeyboardButton(text=label, callback_data=f"truck:{key}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def build_admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📊 Statistika", callback_data="admin:stats"),
            InlineKeyboardButton(text="🔥 Top yo'nalishlar", callback_data="admin:top")
        ],
        [InlineKeyboardButton(text="📢 Barchaga xabar yuborish", callback_data="admin:broadcast")]
    ])


# ================= ADMIN PANEL =================

@dp.message(Command("admin"))
async def cmd_admin(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    admin_waiting_broadcast.discard(message.from_user.id)
    await message.answer(
        "🛠 <b>Admin boshqaruv paneli</b>\n\nKerakli bo'limni tanlang:",
        reply_markup=build_admin_keyboard(),
        parse_mode="HTML"
    )


@dp.callback_query(F.data == "admin:home")
async def admin_home(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    admin_waiting_broadcast.discard(callback.from_user.id)
    await callback.message.edit_text(
        "🛠 <b>Admin boshqaruv paneli</b>\n\nKerakli bo'limni tanlang:",
        reply_markup=build_admin_keyboard(),
        parse_mode="HTML"
    )


@dp.callback_query(F.data == "admin:stats")
async def admin_stats(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID or not db_pool:
        return

    total_users = await db_pool.fetchval("SELECT COUNT(*) FROM obunachilar") or 0
    active_users = await db_pool.fetchval("SELECT COUNT(*) FROM obunachilar WHERE active = TRUE") or 0
    inactive_users = total_users - active_users
    total_cargos = await db_pool.fetchval("SELECT COUNT(*) FROM elonlar") or 0
    today_cargos = await db_pool.fetchval(
        "SELECT COUNT(*) FROM elonlar WHERE created_at >= NOW() - INTERVAL '24 hours'"
    ) or 0

    text = (
        "📊 <b>Bot jonli statistikasi:</b>\n\n"
        f"👥 Jami foydalanuvchilar: <b>{total_users}</b>\n"
        f"✅ Faol qidiruvdagilar: <b>{active_users}</b>\n"
        f"⏸ To'xtatgan / bloklaganlar: <b>{inactive_users}</b>\n\n"
        f"📦 So'nggi 24 soatdagi yuklar: <b>{today_cargos}</b>\n"
        f"🗄 Bazadagi jami yuklar (3 kunlik): <b>{total_cargos}</b>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Yangilash", callback_data="admin:stats")],
        [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="admin:home")]
    ])
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")


@dp.callback_query(F.data == "admin:top")
async def admin_top_routes(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID or not db_pool:
        return

    top_subs = await db_pool.fetch("""
        SELECT from_region, to_region, COUNT(*) AS cnt
        FROM obunachilar
        WHERE active = TRUE
        GROUP BY from_region, to_region
        ORDER BY cnt DESC
        LIMIT 5
    """)
    top_cargos = await db_pool.fetch("""
        SELECT from_region, to_region, COUNT(*) AS cnt
        FROM elonlar
        WHERE created_at >= NOW() - INTERVAL '3 days'
        GROUP BY from_region, to_region
        ORDER BY cnt DESC
        LIMIT 5
    """)

    subs_lines = []
    for i, r in enumerate(top_subs, 1):
        f_n = REGIONS.get(r["from_region"], (r["from_region"],))[0]
        t_n = REGIONS.get(r["to_region"], (r["to_region"],))[0]
        subs_lines.append(f"{i}. {f_n} ➔ {t_n} — <b>{r['cnt']} ta</b> haydovchi")

    cargo_lines = []
    for i, r in enumerate(top_cargos, 1):
        f_n = REGIONS.get(r["from_region"], (r["from_region"],))[0]
        t_n = REGIONS.get(r["to_region"], (r["to_region"],))[0]
        cargo_lines.append(f"{i}. {f_n} ➔ {t_n} — <b>{r['cnt']} ta</b> yuk")

    subs_block = "\n".join(subs_lines) if subs_lines else "Hozircha ma'lumot yo'q"
    cargo_block = "\n".join(cargo_lines) if cargo_lines else "Hozircha ma'lumot yo'q"

    text = (
        "🔥 <b>Eng talabgir yo'nalishlar (Top 5):</b>\n\n"
        f"🚛 <b>Faol haydovchilar bo'yicha:</b>\n{subs_block}\n\n"
        f"📦 <b>So'nggi 3 kundagi yuklar bo'yicha:</b>\n{cargo_block}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ Orqaga", callback_data="admin:home")]
    ])
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")


@dp.callback_query(F.data == "admin:broadcast")
async def admin_broadcast_prompt(callback: types.CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return
    admin_waiting_broadcast.add(callback.from_user.id)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Bekor qilish", callback_data="admin:home")]
    ])
    await callback.message.edit_text(
        "📢 <b>Ommaviy xabar yuborish</b>\n\n"
        "Barcha foydalanuvchilarga yubormoqchi bo'lgan xabaringizni (matn, rasm yoki video) shu yerga yozib yuboring:",
        reply_markup=kb,
        parse_mode="HTML"
    )


@dp.message(F.from_user.id == ADMIN_ID)
async def handle_admin_broadcast_message(message: types.Message):
    if message.from_user.id not in admin_waiting_broadcast:
        return
    if message.text and message.text.startswith("/"):
        return

    admin_waiting_broadcast.discard(message.from_user.id)
    if not db_pool:
        return

    rows = await db_pool.fetch("SELECT user_id FROM obunachilar")
    total = len(rows)
    sent = 0
    blocked = 0

    status_msg = await message.answer(f"⏳ Xabar <b>{total}</b> ta foydalanuvchiga yuborilmoqda...", parse_mode="HTML")

    for row in rows:
        uid = row["user_id"]
        try:
            await message.copy_to(chat_id=uid)
            sent += 1
            await asyncio.sleep(0.05)
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after)
            try:
                await message.copy_to(chat_id=uid)
                sent += 1
            except Exception:
                blocked += 1
        except TelegramForbiddenError:
            blocked += 1
            await db_pool.execute("UPDATE obunachilar SET active = FALSE WHERE user_id = $1", uid)
        except Exception:
            blocked += 1

    await status_msg.edit_text(
        f"✅ <b>Xabar tarqatish yakunlandi!</b>\n\n"
        f"📨 Yetkazildi: <b>{sent}</b>\n"
        f"🚫 Bloklagan / xato: <b>{blocked}</b>",
        reply_markup=build_admin_keyboard(),
        parse_mode="HTML"
    )


# ================= ASOSIY FOYDALANUVCHI MENYUSI =================

@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    active_text = ""

    if db_pool:
        row = await db_pool.fetchrow(
            "SELECT from_region, to_region, truck_type, active FROM obunachilar WHERE user_id = $1",
            user_id
        )
        if row and row["active"] and row["from_region"] in REGIONS and row["to_region"] in REGIONS:
            f_name = REGIONS[row["from_region"]][0]
            t_name = REGIONS[row["to_region"]][0]
            tr_key = row["truck_type"] if row["truck_type"] in TRUCK_TYPES else "all"
            tr_name = TRUCK_TYPES[tr_key][0]
            active_text = (
                f"\n\n✅ Hozirgi faol sozlamangiz:\n"
                f"📍 Yo'nalish: <b>{f_name} ➔ {t_name}</b>\n"
                f"🚛 Mashina: <b>{tr_name}</b>"
            )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚛 Yo'nalish tanlash (Qayerdan -> Qayerga)", callback_data="choose_route")],
        [InlineKeyboardButton(text="🛑 Qidiruvni to'xtatish", callback_data="stop_search")]
    ])
    await message.answer(
        "Assalomu alaykum! <b>Tezkor Yuk</b> botiga xush kelibsiz.\n\n"
        f"Kerakli viloyatlararo yo'nalish va mashina turini tanlang — kanallarga yangi yuk e'loni tushishi bilan sizga yuboraman.{active_text}",
        reply_markup=kb,
        parse_mode="HTML"
    )


@dp.callback_query(F.data == "choose_route")
async def step_from(callback: types.CallbackQuery):
    await callback.message.edit_text(
        "📍 <b>1-qadam: QAYERDAN</b> yuk olmoqchisiz? Viloyatni tanlang:",
        reply_markup=build_regions_keyboard("from"),
        parse_mode="HTML"
    )


@dp.callback_query(F.data.startswith("from:"))
async def step_to(callback: types.CallbackQuery):
    from_key = callback.data.split(":")[1]
    user_temp[callback.from_user.id] = {"from": from_key}
    from_name = REGIONS[from_key][0]
    await callback.message.edit_text(
        f"✅ Qayerdan: <b>{from_name}</b>\n\n"
        f"🏁 <b>2-qadam: QAYERGA</b> borishingizni tanlang:",
        reply_markup=build_regions_keyboard("to"),
        parse_mode="HTML"
    )


@dp.callback_query(F.data.startswith("to:"))
async def step_truck(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    to_key = callback.data.split(":")[1]
    data = user_temp.get(user_id)

    if not data or "from" not in data:
        await callback.answer("Avval 'Qayerdan' viloyatini tanlang!", show_alert=True)
        return

    data["to"] = to_key
    from_name = REGIONS[data["from"]][0]
    to_name = REGIONS[to_key][0]

    await callback.message.edit_text(
        f"✅ Yo'nalish: <b>{from_name} ➔ {to_name}</b>\n\n"
        f"🚛 <b>3-qadam:</b> Qaysi turdagi mashina uchun yuk kerak?",
        reply_markup=build_trucks_keyboard(),
        parse_mode="HTML"
    )


@dp.callback_query(F.data.startswith("truck:"))
async def save_route(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    truck_key = callback.data.split(":")[1]
    data = user_temp.get(user_id)

    if not data or "from" not in data or "to" not in data:
        await callback.answer("Avval yo'nalishni tanlang!", show_alert=True)
        return

    from_key = data["from"]
    to_key = data["to"]
    if truck_key not in TRUCK_TYPES:
        truck_key = "all"

    if db_pool:
        await db_pool.execute("""
            INSERT INTO obunachilar (user_id, from_region, to_region, truck_type, active, updated_at)
            VALUES ($1, $2, $3, $4, TRUE, NOW())
            ON CONFLICT (user_id) DO UPDATE SET
                from_region = EXCLUDED.from_region,
                to_region = EXCLUDED.to_region,
                truck_type = EXCLUDED.truck_type,
                active = TRUE,
                updated_at = NOW();
        """, user_id, from_key, to_key, truck_key)

    from_name = REGIONS[from_key][0]
    to_name = REGIONS[to_key][0]
    truck_name = TRUCK_TYPES[truck_key][0]

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Yo'nalish / Mashinani o'zgartirish", callback_data="choose_route")],
        [InlineKeyboardButton(text="🛑 Qidiruvni to'xtatish", callback_data="stop_search")]
    ])
    await callback.message.edit_text(
        f"🎯 Sozlamalar faollashtirildi va bazaga saqlandi!\n\n"
        f"📍 Yo'nalish: <b>{from_name} ➔ {to_name}</b>\n"
        f"🚛 Mashina turi: <b>{truck_name}</b>\n\n"
        f"Shu moslikdagi yangi yuk chiqishi bilan darhol xabar beraman.",
        reply_markup=kb,
        parse_mode="HTML"
    )


@dp.callback_query(F.data == "stop_search")
async def stop_search(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if db_pool:
        await db_pool.execute(
            "UPDATE obunachilar SET active = FALSE, updated_at = NOW() WHERE user_id = $1",
            user_id
        )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚛 Yangi yo'nalish tanlash", callback_data="choose_route")]
    ])
    await callback.message.edit_text("⏸ Qidiruv to'xtatildi. Istalgan vaqt qayta yoqishingiz mumkin.", reply_markup=kb)


def detect_route(text: str):
    """Matndan qaysi viloyatdan qaysi viloyatga ekanligini aniqlaydi."""
    clean = text.lower().replace("’", "'").replace("‘", "'").replace("`", "'")
    found = []
    for key, (_, keywords) in REGIONS.items():
        for kw in keywords:
            match = re.search(rf"\b{re.escape(kw)}", clean)
            if match:
                found.append((match.start(), key))
                break
    found.sort(key=lambda x: x[0])
    if len(found) >= 2 and found[0][1] != found[1][1]:
        return found[0][1], found[1][1]
    return None, None


def detect_truck_type(text: str) -> str:
    """Matndan mashina turini aniqlaydi. Topilmasa 'general' qaytaradi."""
    clean = text.lower().replace("’", "'").replace("‘", "'").replace("`", "'")
    for key in ("ref", "fura", "isuzu", "gazel"):
        _, keywords = TRUCK_TYPES[key]
        for kw in keywords:
            if re.search(rf"\b{re.escape(kw)}", clean):
                return key
    return "general"


# Telethon Userbot — kanallar va guruhlardan e'lonlarni kuzatish
client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)


@client.on(events.NewMessage(incoming=True))
async def handle_new_cargo(event):
    try:
        if event.is_private:
            return
        text = event.raw_text
        if not text or len(text) < 10:
            return

        from_reg, to_reg = detect_route(text)
        if not from_reg or not to_reg:
            return

        detected_truck = detect_truck_type(text)
        text_hash = make_text_hash(text)

        chat = await event.get_chat()
        chat_title = getattr(chat, "title", "Yuk kanali")
        username = getattr(chat, "username", None)
        link = f"\n🔗 <a href='https://t.me/{username}/{event.id}'>E'longa o'tish</a>" if username else ""

        if db_pool:
            # Oxirgi 6 soat ichida boshqa kanal/guruhdan aynan shu matn tushgan-tushmaganini tekshirish
            duplicate = await db_pool.fetchval("""
                SELECT 1 FROM elonlar
                WHERE text_hash = $1
                  AND created_at >= NOW() - INTERVAL '6 hours'
                LIMIT 1;
            """, text_hash)
            if duplicate:
                return

            inserted = await db_pool.fetchval("""
                INSERT INTO elonlar (chat_id, message_id, chat_title, from_region, to_region, truck_type, text_hash, text_body)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                ON CONFLICT (chat_id, message_id) DO NOTHING
                RETURNING id;
            """, event.chat_id, event.id, chat_title, from_reg, to_reg, detected_truck, text_hash, text[:2000])
            if not inserted:
                return

        truck_badge = ""
        if detected_truck in TRUCK_TYPES:
            truck_badge = f"\n🚛 Mashina: {TRUCK_TYPES[detected_truck][0]}"

        msg_body = (
            f"🆕 <b>Yangi yuk! ({REGIONS[from_reg][0]} ➔ {REGIONS[to_reg][0]})</b>"
            f"{truck_badge}\n"
            f"📢 Manba: {chat_title}\n\n"
            f"{text[:1500]}{link}"
        )

        if db_pool:
            subscribers = await db_pool.fetch(
                "SELECT user_id, truck_type FROM obunachilar WHERE active = TRUE AND from_region = $1 AND to_region = $2",
                from_reg, to_reg
            )
            for row in subscribers:
                sub_truck = row["truck_type"] or "all"
                if sub_truck != "all" and detected_truck != "general" and sub_truck != detected_truck:
                    continue

                uid = row["user_id"]
                try:
                    await bot.send_message(uid, msg_body, parse_mode="HTML", disable_web_page_preview=True)
                except TelegramForbiddenError:
                    await db_pool.execute("UPDATE obunachilar SET active = FALSE WHERE user_id = $1", uid)
                except TelegramRetryAfter as e:
                    await asyncio.sleep(e.retry_after)
                except Exception as e:
                    logging.error(f"User {uid} ga yuborishda xato: {e}")
    except Exception as e:
        logging.error(f"E'lonni qayta ishlashda kutilmagan xato: {e}")


# Render.com va UptimeRobot uchun veb-server
async def health_check(request):
    return web.Response(text="TezkorYuk Bot 24/7 ishlamoqda!")


async def start_web_server():
    app = web.Application()
    app.router.add_get("/", health_check)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logging.info(f"Web server {port}-portda ishga tushdi.")


async def main():
    await init_db()
    asyncio.create_task(cleanup_old_cargos())
    await start_web_server()
    await client.start()
    logging.info("Telethon Userbot muvaffaqiyatli ulandi!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())