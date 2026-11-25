# 🚚 Tezkor Yuk 24/7 — Viloyatlararo Yuk Tashish Agregator Boti

**Tezkor Yuk 24/7** (`@tezkoryuk_uzbot`) — O'zbekistonning barcha viloyatlari o'rtasidagi yuk e'lonlarini real vaqt rejimida Telegram kanallaridan yig'uvchi, tahlil qiluvchi va haydovchilarga mos yo'nalish hamda mashina turi bo'yicha saralab yetkazib beruvchi asinxron Telegram bot tizimi.

---

## 🚀 Asosiy imkoniyatlar

- **Real-time kanal monitoringi (`Telethon`):** Ochib qo'yilgan logistika kanallaridagi yangi e'lonlarni soniyalar ichida o'qib oladi.
- **Aqlli matn tahlili (`Regex`):** Tartibsiz yozilgan e'lon matnidan **"Qayerdan"** va **"Qayerga"** viloyatlarini hamda kerakli **transport turini** (Fura, Isuzu, Labo, Gazel va b.) avtomatik ajratib oladi.
- **Dublikatlarni filtrlash (`SHA-256`):** E'lon matnini tozalab (`URL`, `@username`, belgilar), uning SHA-256 hash qiymatini yaratadi va bir xil e'lonning turli kanallardan 6 soat ichida qayta yuborilishining oldini oladi.
- **Doimiy ma'lumotlar bazasi (`PostgreSQL`):** Obunachilar sozlamalari va yuklar tarixi bulutli PostgreSQL (Supabase) bazasida `asyncpg` connection pool orqali saqlanadi.
- **Avtomatik baza tozalash (`Background Task`):** Asosiy bot ishiga xalaqit bermagan holda har 6 soatda 3 kundan eskirgan e'lonlarni avtomatik o'chirib boradi.
- **Admin Panel:** Faol foydalanuvchilar statistikasi, bazadagi e'lonlar sonini kuzatish va barcha foydalanuvchilarga xabar yuborish (`broadcast`) imkoniyati.
- **24/7 Cloud Hosting:** Render.com Web Service, `aiohttp` health-check serveri va UptimeRobot monitoringi orqali uzluksiz ishlashga moslashtirilgan.

---

## 🛠 Texnologiyalar steki

- **Til:** Python 3.12 (Asinxron arxitektura — `asyncio`)
- **Bot Framework:** `aiogram` 3.15
- **Userbot / MTProto Client:** `Telethon`
- **Ma'lumotlar bazasi:** PostgreSQL (`asyncpg`)
- **Veb-server (Health Check):** `aiohttp`
- **Deploy va Infratuzilma:** GitHub, Render.com, UptimeRobot

---

## ⚙️ Loyihani lokal ishga tushirish

1. **Repozitoriyni yuklab oling:**
   ```bash
   git clone [https://github.com/juvatkhonovv-cloud/tezkoryuk-bot.git](https://github.com/juvatkhonovv-cloud/tezkoryuk-bot.git)
   cd tezkoryuk-bot
