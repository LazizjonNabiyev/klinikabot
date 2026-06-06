import os, asyncio, logging
from datetime import datetime, timedelta
import pytz
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from flask import Flask, request

logging.basicConfig(level=logging.INFO)

BOT_TOKEN   = os.environ.get("BOT_TOKEN", "8519255967:AAGJPFIBqCZlDHTWSmsBohfo03swSzWtmAo")
GROUP_ID    = os.environ.get("GROUP_ID", "@doctorashurovclicnicbaza")   # Navbatlar keladigan guruh
ADMIN_IDS   = [int(x) for x in os.environ.get("ADMIN_IDS", "920162633").split(",") if x]
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "")
TZ          = pytz.timezone("Asia/Tashkent")

# ─── MA'LUMOTLAR ─────────────────────────────────────────────
CLINIC_NAME = "Ashurov Clinik"
CLINIC_PHONE = "+998 91 166 66 96, +998 90 995 17 77"
CLINIC_ADDRESS = "Toshkent sh., Dormon"

DOCTORS = {
    "1": {"name": "Dr. Ashurov B.A.", "spec_uz": "Terapevt", "spec_ru": "Терапевт", "times": ["09:00","09:30","10:00","10:30","11:00","11:30","14:00","14:30","15:00","15:30"]},
    "2": {"name": "Dr. Xolmatova M.S.", "spec_uz": "Kardiolog", "spec_ru": "Кардиолог", "times": ["09:00","10:00","11:00","14:00","15:00","16:00"]},
    "3": {"name": "Dr. Karimov J.R.", "spec_uz": "Nevropatolog", "spec_ru": "Невропатолог", "times": ["09:00","09:30","10:00","11:00","14:00","15:00"]},
    "4": {"name": "Dr. Yusupova N.K.", "spec_uz": "Ginekolog", "spec_ru": "Гинеколог", "times": ["09:00","10:00","11:00","14:00","15:00"]},
    "5": {"name": "Dr. Nazarov F.B.", "spec_uz": "Jarroh", "spec_ru": "Хирург", "times": ["10:00","11:00","14:00","15:00","16:00"]},
    "6": {"name": "Dr. Tosheva G.M.", "spec_uz": "Pediatr", "spec_ru": "Педиатр", "times": ["09:00","10:00","11:00","14:00","15:00"]},
    "7": {"name": "Dr. Rahimov A.T.", "spec_uz": "Ortoped", "spec_ru": "Ортопед", "times": ["10:00","11:00","14:00","15:00","16:00"]},
}

SERVICES = {
    "uz": [
        ("🔬 Qon tahlili", "25,000 so'm"),
        ("🫀 EKG", "30,000 so'm"),
        ("🔊 UZI", "50,000 so'm"),
        ("👁 Ko'z tekshiruvi", "40,000 so'm"),
        ("💉 Ukol", "15,000 so'm"),
        ("🩺 Shifokor ko'rigi", "50,000 so'm"),
    ],
    "ru": [
        ("🔬 Анализ крови", "25,000 сум"),
        ("🫀 ЭКГ", "30,000 сум"),
        ("🔊 УЗИ", "50,000 сум"),
        ("👁 Осмотр глаз", "40,000 сум"),
        ("💉 Укол", "15,000 сум"),
        ("🩺 Приём врача", "50,000 сум"),
    ]
}

# ─── STATE ───────────────────────────────────────────────────
user_state = {}
users_db   = {}   # {uid: {name, phone, lang}}
appointments = [] # [{uid, name, phone, doctor, date, time, status}]

def get_s(uid): return user_state.get(str(uid), {})
def set_s(uid, s): user_state[str(uid)] = s
def del_s(uid): user_state.pop(str(uid), None)
def is_admin(uid): return int(uid) in ADMIN_IDS
def now_tz(): return datetime.now(TZ)

def get_dates():
    dates = []
    d = now_tz().date()
    for i in range(7):
        dd = d + timedelta(days=i)
        if dd.weekday() < 6:  # Dushanba-Shanba
            dates.append(dd.strftime("%d.%m.%Y"))
    return dates[:5]

# ─── KLAVIATURALAR ───────────────────────────────────────────
def kb_lang():
    return ReplyKeyboardMarkup([["🇺🇿 O'zbekcha","🇷🇺 Русский"]], resize_keyboard=True, one_time_keyboard=True)

def kb_menu(lang):
    if lang=="ru":
        return ReplyKeyboardMarkup([
            ["📅 Записаться на приём"],
            ["👨‍⚕️ Наши врачи","💰 Услуги и цены"],
            ["📍 Адрес","📞 Контакты"],
        ], resize_keyboard=True)
    return ReplyKeyboardMarkup([
        ["📅 Navbat olish"],
        ["👨‍⚕️ Shifokorlar","💰 Xizmatlar va narxlar"],
        ["📍 Manzil","📞 Bog'lanish"],
    ], resize_keyboard=True)

def kb_admin():
    return ReplyKeyboardMarkup([
        ["📋 Bugungi navbatlar","📊 Statistika"],
        ["👨‍⚕️ Shifokor qo'shish","👤 Admin qo'shish"],
        ["🔙 Chiqish"]
    ], resize_keyboard=True)

def kb_back(lang):
    return ReplyKeyboardMarkup([["🔙 Orqaga" if lang=="uz" else "🔙 Назад"]], resize_keyboard=True, one_time_keyboard=True)

def kb_doctors(lang):
    rows = []
    for did, d in DOCTORS.items():
        spec = d["spec_uz"] if lang=="uz" else d["spec_ru"]
        rows.append([f"{d['name']} — {spec}"])
    rows.append(["🔙 Orqaga" if lang=="uz" else "🔙 Назад"])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)

def kb_dates(lang):
    dates = get_dates()
    rows = [[d] for d in dates]
    rows.append(["🔙 Orqaga" if lang=="uz" else "🔙 Назад"])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)

def kb_times(times, lang):
    rows = [times[i:i+3] for i in range(0, len(times), 3)]
    rows.append(["🔙 Orqaga" if lang=="uz" else "🔙 Назад"])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)

def kb_confirm(lang):
    if lang=="ru":
        return ReplyKeyboardMarkup([["✅ Подтвердить","❌ Отмена"]], resize_keyboard=True, one_time_keyboard=True)
    return ReplyKeyboardMarkup([["✅ Tasdiqlash","❌ Bekor qilish"]], resize_keyboard=True, one_time_keyboard=True)

def kb_contact(lang):
    btn = KeyboardButton("📱 Raqamni ulashish" if lang=="uz" else "📱 Поделиться номером", request_contact=True)
    return ReplyKeyboardMarkup([[btn]], resize_keyboard=True, one_time_keyboard=True)

# contact import
from telegram import KeyboardButton

# ─── GURUHGA YUBORISH ────────────────────────────────────────
async def send_to_group(bot, appt):
    now = now_tz().strftime("%d.%m.%Y %H:%M")
    msg = (
        f"🏥 *Yangi navbat — {CLINIC_NAME}*\n"
        f"━━━━━━━━━━━━━━\n"
        f"👤 *Ism:* {appt['name']}\n"
        f"📞 *Tel:* {appt['phone']}\n"
        f"━━━━━━━━━━━━━━\n"
        f"👨‍⚕️ *Shifokor:* {appt['doctor']}\n"
        f"📅 *Sana:* {appt['date']}\n"
        f"🕐 *Vaqt:* {appt['time']}\n"
        f"━━━━━━━━━━━━━━\n"
        f"🕐 Yuborildi: {now}\n"
        f"🆔 Foydalanuvchi: {appt['uid']}"
    )
    await bot.send_message(chat_id=GROUP_ID, text=msg, parse_mode="Markdown")

# ─── KUNLIK HISOBOT ──────────────────────────────────────────
async def send_daily_report(bot):
    today = now_tz().strftime("%d.%m.%Y")
    today_appts = [a for a in appointments if a["date"]==today]
    if not today_appts:
        text = f"📊 *{today} — Bugungi navbatlar yo'q*"
    else:
        text = f"📊 *{today} — Bugungi navbatlar: {len(today_appts)} ta*\n\n"
        for i, a in enumerate(today_appts, 1):
            text += f"{i}. {a['time']} — {a['name']} ({a['phone']})\n   👨‍⚕️ {a['doctor']}\n\n"
    for aid in ADMIN_IDS:
        try: await bot.send_message(chat_id=aid, text=text, parse_mode="Markdown")
        except: pass

# ─── ASOSIY HANDLER ──────────────────────────────────────────
async def handle_update(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.from_user: return
    uid  = msg.from_user.id
    text = (msg.text or "").strip()
    s    = get_s(uid)
    lang = s.get("lang","uz")

    # /start
    if text=="/start":
        del_s(uid)
        await msg.reply_text("🌐 Tilni tanlang / Выберите язык:", reply_markup=kb_lang())
        return

    # Admin
    if is_admin(uid) and text=="/admin":
        set_s(uid,{**s,"admin_mode":True})
        await msg.reply_text("🔧 Admin Panel:", reply_markup=kb_admin())
        return

    if is_admin(uid) and text=="/hisobot":
        await send_daily_report(ctx.bot)
        return

    if is_admin(uid) and text.startswith("/reply "):
        parts=text.split(" ",2)
        if len(parts)==3:
            try:
                await ctx.bot.send_message(chat_id=int(parts[1]),text=f"📩 {CLINIC_NAME}:\n\n{parts[2]}")
                await msg.reply_text("✅ Yuborildi!")
            except: await msg.reply_text("❌ Xato")
        return

    # Admin panel
    if s.get("admin_mode"):
        if text=="🔙 Chiqish":
            set_s(uid,{"lang":lang})
            await msg.reply_text("Asosiy menyu:", reply_markup=kb_menu(lang))
            return

        if text=="📋 Bugungi navbatlar":
            today=now_tz().strftime("%d.%m.%Y")
            ta=[a for a in appointments if a["date"]==today]
            if not ta:
                await msg.reply_text("Bugun navbat yo'q")
                return
            result=f"📋 Bugun ({today}) — {len(ta)} ta navbat:\n\n"
            for i,a in enumerate(ta,1):
                result+=f"{i}. {a['time']} — {a['name']}\n📞 {a['phone']}\n👨‍⚕️ {a['doctor']}\n\n"
            await msg.reply_text(result)
            return

        if text=="📊 Statistika":
            today=now_tz().strftime("%d.%m.%Y")
            today_count=len([a for a in appointments if a["date"]==today])
            total=len(appointments)
            users_count=len(users_db)
            await msg.reply_text(
                f"📊 Statistika\n\n"
                f"👥 Ro'yxatdan o'tganlar: {users_count}\n"
                f"📅 Bugungi navbatlar: {today_count}\n"
                f"📦 Jami navbatlar: {total}\n"
                f"👤 Adminlar: {len(ADMIN_IDS)}"
            )
            return

        if text=="👤 Admin qo'shish":
            set_s(uid,{**s,"admin_step":"add_admin"})
            await msg.reply_text("Yangi admin Telegram ID:")
            return

        if s.get("admin_step")=="add_admin":
            try:
                ADMIN_IDS.append(int(text))
                set_s(uid,{**s,"admin_step":None})
                await msg.reply_text(f"✅ {text} admin qilindi!", reply_markup=kb_admin())
            except: await msg.reply_text("❌ Raqam kiriting")
            return

        if text=="👨‍⚕️ Shifokor qo'shish":
            set_s(uid,{**s,"admin_step":"doc_name"})
            await msg.reply_text("Shifokor to'liq ismi (Dr. Familiya A.B.):")
            return

        if s.get("admin_step")=="doc_name":
            set_s(uid,{**s,"admin_step":"doc_spec","doc_name":text})
            await msg.reply_text("Mutaxassislik (o'zbek tilida):")
            return

        if s.get("admin_step")=="doc_spec":
            new_id=str(len(DOCTORS)+1)
            DOCTORS[new_id]={"name":s["doc_name"],"spec_uz":text,"spec_ru":text,"times":["09:00","10:00","11:00","14:00","15:00"]}
            set_s(uid,{**s,"admin_step":None})
            await msg.reply_text(f"✅ {s['doc_name']} qo'shildi!", reply_markup=kb_admin())
            return

    # Til tanlash
    if text=="🇺🇿 O'zbekcha":
        set_s(uid,{"lang":"uz"})
        name=msg.from_user.first_name or "Do'stim"
        if str(uid) not in users_db:
            set_s(uid,{"lang":"uz","step":"get_name"})
            await msg.reply_text(f"Salom, {name}! 👋\n\nRo'yxatdan o'tish uchun ismingizni kiriting:")
        else:
            set_s(uid,{"lang":"uz","step":"menu"})
            await msg.reply_text(f"🏥 *{CLINIC_NAME}*\n\nSalom, {users_db[str(uid)]['name']}!", parse_mode="Markdown", reply_markup=kb_menu("uz"))
        return

    if text=="🇷🇺 Русский":
        set_s(uid,{"lang":"ru"})
        name=msg.from_user.first_name or "Друг"
        if str(uid) not in users_db:
            set_s(uid,{"lang":"ru","step":"get_name"})
            await msg.reply_text(f"Привет, {name}! 👋\n\nВведите ваше имя для регистрации:")
        else:
            set_s(uid,{"lang":"ru","step":"menu"})
            await msg.reply_text(f"🏥 *{CLINIC_NAME}*\n\nПривет, {users_db[str(uid)]['name']}!", parse_mode="Markdown", reply_markup=kb_menu("ru"))
        return

    # Ro'yxatdan o'tish
    if s.get("step")=="get_name":
        set_s(uid,{**s,"step":"get_phone","reg_name":text})
        prompt="📞 Telefon raqamingizni ulashing:" if lang=="uz" else "📞 Поделитесь номером телефона:"
        await msg.reply_text(prompt, reply_markup=kb_contact(lang))
        return

    if s.get("step")=="get_phone":
        phone=""
        if msg.contact: phone=msg.contact.phone_number
        elif text: phone=text
        if not phone:
            await msg.reply_text("📞 Iltimos telefon raqam yuboring")
            return
        users_db[str(uid)]={"name":s["reg_name"],"phone":phone,"lang":lang}
        set_s(uid,{"lang":lang,"step":"menu"})
        welcome="✅ Ro'yxatdan o'tdingiz!\n\n" if lang=="uz" else "✅ Вы зарегистрированы!\n\n"
        await msg.reply_text(welcome+f"🏥 {CLINIC_NAME}", reply_markup=kb_menu(lang))
        # Guruhga xabar
        try:
            await ctx.bot.send_message(
                chat_id=GROUP_ID,
                text=f"👤 *Yangi foydalanuvchi*\n\n"
                     f"Ism: {s['reg_name']}\nTel: {phone}\n"
                     f"Telegram: @{msg.from_user.username or '—'}\n"
                     f"ID: {uid}",
                parse_mode="Markdown"
            )
        except: pass
        return

    # Orqaga
    if text in ["🔙 Orqaga","🔙 Назад"]:
        set_s(uid,{"lang":lang,"step":"menu"})
        await msg.reply_text("Asosiy menyu:" if lang=="uz" else "Главное меню:", reply_markup=kb_menu(lang))
        return

    # Navbat olish
    if text in ["📅 Navbat olish","📅 Записаться на приём"]:
        if str(uid) not in users_db:
            set_s(uid,{"lang":lang,"step":"get_name"})
            await msg.reply_text("Avval ro'yxatdan o'ting. Ismingizni kiriting:" if lang=="uz" else "Сначала зарегистрируйтесь. Введите имя:")
            return
        set_s(uid,{**s,"step":"choose_doctor"})
        prompt="👨‍⚕️ Shifokorni tanlang:" if lang=="uz" else "👨‍⚕️ Выберите врача:"
        await msg.reply_text(prompt, reply_markup=kb_doctors(lang))
        return

    # Shifokor tanlash
    if s.get("step")=="choose_doctor":
        chosen=None
        for did,d in DOCTORS.items():
            spec=d["spec_uz"] if lang=="uz" else d["spec_ru"]
            if text==f"{d['name']} — {spec}":
                chosen=(did,d)
                break
        if not chosen:
            await msg.reply_text("Iltimos shifokorni tanlang:" if lang=="uz" else "Выберите врача:", reply_markup=kb_doctors(lang))
            return
        set_s(uid,{**s,"step":"choose_date","doc_id":chosen[0],"doc_name":chosen[1]["name"]})
        prompt="📅 Sanani tanlang:" if lang=="uz" else "📅 Выберите дату:"
        await msg.reply_text(prompt, reply_markup=kb_dates(lang))
        return

    # Sana tanlash
    if s.get("step")=="choose_date":
        if text not in get_dates():
            await msg.reply_text("Sanani tanlang:" if lang=="uz" else "Выберите дату:", reply_markup=kb_dates(lang))
            return
        doc=DOCTORS[s["doc_id"]]
        set_s(uid,{**s,"step":"choose_time","date":text})
        prompt="🕐 Vaqtni tanlang:" if lang=="uz" else "🕐 Выберите время:"
        await msg.reply_text(prompt, reply_markup=kb_times(doc["times"],lang))
        return

    # Vaqt tanlash
    if s.get("step")=="choose_time":
        doc=DOCTORS[s["doc_id"]]
        if text not in doc["times"]:
            await msg.reply_text("Vaqtni tanlang:" if lang=="uz" else "Выберите время:", reply_markup=kb_times(doc["times"],lang))
            return
        set_s(uid,{**s,"step":"confirm","time":text})
        user=users_db[str(uid)]
        spec=doc["spec_uz"] if lang=="uz" else doc["spec_ru"]
        summary=(
            f"📋 *Navbat ma'lumotlari:*\n\n" if lang=="uz" else f"📋 *Данные записи:*\n\n"
        )
        summary+=(
            f"👤 {user['name']}\n"
            f"📞 {user['phone']}\n"
            f"👨‍⚕️ {doc['name']} ({spec})\n"
            f"📅 {s['date']}\n"
            f"🕐 {text}\n\n"
        )
        summary+=("✅ Tasdiqlaysizmi?" if lang=="uz" else "✅ Подтверждаете?")
        await msg.reply_text(summary, parse_mode="Markdown", reply_markup=kb_confirm(lang))
        return

    # Tasdiqlash
    if s.get("step")=="confirm":
        if text in ["✅ Tasdiqlash","✅ Подтвердить"]:
            user=users_db[str(uid)]
            doc=DOCTORS[s["doc_id"]]
            appt={
                "uid":uid,
                "name":user["name"],
                "phone":user["phone"],
                "doctor":doc["name"],
                "date":s["date"],
                "time":s["time"],
                "status":"active"
            }
            appointments.append(appt)
            await send_to_group(ctx.bot,appt)
            set_s(uid,{"lang":lang,"step":"menu"})
            ok=(
                f"✅ *Navbat tasdiqlandi!*\n\n"
                f"📅 {s['date']} soat {s['time']}\n"
                f"👨‍⚕️ {doc['name']}\n\n"
                f"📍 {CLINIC_ADDRESS}\n"
                f"📞 {CLINIC_PHONE}"
            ) if lang=="uz" else (
                f"✅ *Запись подтверждена!*\n\n"
                f"📅 {s['date']} в {s['time']}\n"
                f"👨‍⚕️ {doc['name']}\n\n"
                f"📍 {CLINIC_ADDRESS}\n"
                f"📞 {CLINIC_PHONE}"
            )
            await msg.reply_text(ok, parse_mode="Markdown", reply_markup=kb_menu(lang))
        else:
            set_s(uid,{"lang":lang,"step":"menu"})
            await msg.reply_text("❌ Bekor qilindi" if lang=="uz" else "❌ Отменено", reply_markup=kb_menu(lang))
        return

    # Shifokorlar
    if text in ["👨‍⚕️ Shifokorlar","👨‍⚕️ Наши врачи"]:
        result="👨‍⚕️ *Bizning shifokorlar:*\n\n" if lang=="uz" else "👨‍⚕️ *Наши врачи:*\n\n"
        for d in DOCTORS.values():
            spec=d["spec_uz"] if lang=="uz" else d["spec_ru"]
            times=", ".join(d["times"][:3])+"..."
            result+=f"• *{d['name']}*\n  {spec}\n  🕐 {times}\n\n"
        await msg.reply_text(result, parse_mode="Markdown")
        return

    # Xizmatlar
    if text in ["💰 Xizmatlar va narxlar","💰 Услуги и цены"]:
        result="💰 *Xizmatlar va narxlar:*\n\n" if lang=="uz" else "💰 *Услуги и цены:*\n\n"
        for name,price in SERVICES[lang]:
            result+=f"{name} — *{price}*\n"
        await msg.reply_text(result, parse_mode="Markdown")
        return

    # Manzil
    if text in ["📍 Manzil","📍 Адрес"]:
        await msg.reply_text(f"📍 *{CLINIC_NAME}*\n\n{CLINIC_ADDRESS}\n📞 {CLINIC_PHONE}", parse_mode="Markdown")
        return

    # Bog'lanish
    if text in ["📞 Bog'lanish","📞 Контакты"]:
        await msg.reply_text(f"📞 *Bog'lanish*\n\n📱 {CLINIC_PHONE}", parse_mode="Markdown")
        return

    await msg.reply_text("🌐 Tilni tanlang / Выберите язык:", reply_markup=kb_lang())


# ─── Flask + Webhook ─────────────────────────────────────────
flask_app = Flask(__name__)
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

ptb_app = Application.builder().token(BOT_TOKEN).updater(None).build()
ptb_app.add_handler(CommandHandler("start", handle_update))
ptb_app.add_handler(MessageHandler(filters.ALL, handle_update))

async def init():
    await ptb_app.initialize()
    await ptb_app.start()
    await ptb_app.bot.set_webhook(url=f"{WEBHOOK_URL}/webhook", drop_pending_updates=True)
    print(f"✅ {CLINIC_NAME} boti ishga tushdi!")

loop.run_until_complete(init())

@flask_app.route("/", methods=["GET"])
def index():
    return f"{CLINIC_NAME} Bot — Ishlayapti!", 200

@flask_app.route("/webhook", methods=["POST"])
def webhook():
    data=request.get_json(force=True)
    update=Update.de_json(data, ptb_app.bot)
    loop.run_until_complete(ptb_app.process_update(update))
    return "OK", 200

if __name__=="__main__":
    port=int(os.environ.get("PORT",5000))
    flask_app.run(host="0.0.0.0", port=port)
