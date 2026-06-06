import os, asyncio, logging
from datetime import datetime, timedelta
import pytz
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from flask import Flask, request
import threading, time

logging.basicConfig(level=logging.INFO)

BOT_TOKEN   = os.environ.get("BOT_TOKEN", "8519255967:AAGJPFIBqCZlDHTWSmsBohfo03swSzWtmAo")
GROUP_ID    = os.environ.get("GROUP_ID", "@doctorashurovclicnicbaza")
ADMIN_IDS   = [int(x) for x in os.environ.get("ADMIN_IDS", "920162633").split(",") if x]
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "https://klinikabot-production.up.railway.app")
TZ          = pytz.timezone("Asia/Tashkent")

CLINIC_NAME    = "Ashurov Clinik"
CLINIC_PHONE   = "+998 91 166 66 96\n📱 +998 90 995 17 77"
CLINIC_ADDRESS = "Toshkent sh., Dormon"

DOCTORS = {
    "1": {"name": "Dr. Ashurov B.A.",   "spec_uz": "Terapevt",     "spec_ru": "Терапевт",     "times": ["09:00","09:30","10:00","10:30","11:00","11:30","14:00","14:30","15:00","15:30"]},
    "2": {"name": "Dr. Xolmatova M.S.", "spec_uz": "Kardiolog",    "spec_ru": "Кардиолог",    "times": ["09:00","10:00","11:00","14:00","15:00","16:00"]},
    "3": {"name": "Dr. Karimov J.R.",   "spec_uz": "Nevropatolog", "spec_ru": "Невропатолог", "times": ["09:00","09:30","10:00","11:00","14:00","15:00"]},
    "4": {"name": "Dr. Yusupova N.K.",  "spec_uz": "Ginekolog",    "spec_ru": "Гинеколог",    "times": ["09:00","10:00","11:00","14:00","15:00"]},
    "5": {"name": "Dr. Nazarov F.B.",   "spec_uz": "Jarroh",       "spec_ru": "Хирург",       "times": ["10:00","11:00","14:00","15:00","16:00"]},
    "6": {"name": "Dr. Tosheva G.M.",   "spec_uz": "Pediatr",      "spec_ru": "Педиатр",      "times": ["09:00","10:00","11:00","14:00","15:00"]},
    "7": {"name": "Dr. Rahimov A.T.",   "spec_uz": "Ortoped",      "spec_ru": "Ортопед",      "times": ["10:00","11:00","14:00","15:00","16:00"]},
}

SERVICES = {
    "uz": [("🔬 Qon tahlili","25,000 so'm"),("🫀 EKG","30,000 so'm"),("🔊 UZI","50,000 so'm"),("👁 Ko'z tekshiruvi","40,000 so'm"),("💉 Ukol","15,000 so'm"),("🩺 Shifokor ko'rigi","50,000 so'm")],
    "ru": [("🔬 Анализ крови","25,000 сум"),("🫀 ЭКГ","30,000 сум"),("🔊 УЗИ","50,000 сум"),("👁 Осмотр глаз","40,000 сум"),("💉 Укол","15,000 сум"),("🩺 Приём врача","50,000 сум")]
}

user_state   = {}
users_db     = {}
appointments = {}
appt_counter = [0]
booked_times = {}
# Har bir shifokor uchun kunlik navbat raqami: {doc_id: {date: count}}
doctor_counters = {}

def get_next_number(doc_id, date):
    if doc_id not in doctor_counters: doctor_counters[doc_id] = {}
    if date not in doctor_counters[doc_id]: doctor_counters[doc_id][date] = 0
    doctor_counters[doc_id][date] += 1
    return doctor_counters[doc_id][date]
ratings      = []  # [{uid, appt_id, rating, comment}]

def get_s(uid): return user_state.get(str(uid), {})
def set_s(uid, s): user_state[str(uid)] = s
def del_s(uid): user_state.pop(str(uid), None)
def is_admin(uid): return int(uid) in ADMIN_IDS
def now_tz(): return datetime.now(TZ)

def get_dates():
    dates, d = [], now_tz().date()
    for i in range(10):
        dd = d + timedelta(days=i)
        if dd.weekday() < 6:
            dates.append(dd.strftime("%d.%m.%Y"))
        if len(dates) == 5: break
    return dates

def get_free_times(doc_id, date):
    all_times = DOCTORS[doc_id]["times"]
    taken = booked_times.get(doc_id, {}).get(date, [])
    return [t for t in all_times if t not in taken]

def book_time(doc_id, date, time):
    if doc_id not in booked_times: booked_times[doc_id] = {}
    if date not in booked_times[doc_id]: booked_times[doc_id][date] = []
    booked_times[doc_id][date].append(time)

def unbook_time(doc_id, date, time):
    try: booked_times[doc_id][date].remove(time)
    except: pass

def get_user_appointments(uid):
    return [a for a in appointments.values() if a["uid"]==uid and a["status"] in ["pending","confirmed"]]

# ─── KLAVIATURALAR ───────────────────────────────────────────
def kb_lang():
    return ReplyKeyboardMarkup([["🇺🇿 O'zbekcha","🇷🇺 Русский"]], resize_keyboard=True, one_time_keyboard=True)

def kb_menu(lang):
    if lang=="ru":
        return ReplyKeyboardMarkup([
            ["📅 Записаться на приём"],
            ["📋 Мои записи","👨‍⚕️ Наши врачи"],
            ["💰 Услуги и цены","📍 Адрес"],
            ["📞 Контакты"]
        ], resize_keyboard=True)
    return ReplyKeyboardMarkup([
        ["📅 Navbat olish"],
        ["📋 Mening navbatlarim","👨‍⚕️ Shifokorlar"],
        ["💰 Xizmatlar va narxlar","📍 Manzil"],
        ["📞 Bog'lanish"]
    ], resize_keyboard=True)

def kb_admin():
    return ReplyKeyboardMarkup([
        ["📋 Bugungi navbatlar","📊 Statistika"],
        ["📢 Xabar yuborish","👨‍⚕️ Shifokor qo'shish"],
        ["👤 Admin qo'shish","⭐ Baholar"],
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
    rows = [[d] for d in get_dates()]
    rows.append(["🔙 Orqaga" if lang=="uz" else "🔙 Назад"])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)

def kb_times(times, lang):
    if not times:
        return ReplyKeyboardMarkup([["🔙 Orqaga" if lang=="uz" else "🔙 Назад"]], resize_keyboard=True)
    rows = [times[i:i+3] for i in range(0, len(times), 3)]
    rows.append(["🔙 Orqaga" if lang=="uz" else "🔙 Назад"])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)

def kb_confirm(lang):
    if lang=="ru": return ReplyKeyboardMarkup([["✅ Подтвердить","❌ Отмена"]], resize_keyboard=True, one_time_keyboard=True)
    return ReplyKeyboardMarkup([["✅ Tasdiqlash","❌ Bekor qilish"]], resize_keyboard=True, one_time_keyboard=True)

def kb_contact(lang):
    btn = KeyboardButton("📱 Raqamni ulashish" if lang=="uz" else "📱 Поделиться номером", request_contact=True)
    return ReplyKeyboardMarkup([[btn]], resize_keyboard=True, one_time_keyboard=True)

def kb_registrar(appt_id):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Tasdiqlash", callback_data=f"confirm_{appt_id}"),
        InlineKeyboardButton("❌ Bekor qilish", callback_data=f"cancel_{appt_id}")
    ]])

def kb_cancel_appt(appt_id, lang):
    txt = "❌ Bekor qilish" if lang=="uz" else "❌ Отменить"
    return InlineKeyboardMarkup([[InlineKeyboardButton(txt, callback_data=f"user_cancel_{appt_id}")]])

def kb_rating():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("⭐ 1", callback_data="rate_1"),
        InlineKeyboardButton("⭐ 2", callback_data="rate_2"),
        InlineKeyboardButton("⭐ 3", callback_data="rate_3"),
        InlineKeyboardButton("⭐ 4", callback_data="rate_4"),
        InlineKeyboardButton("⭐ 5", callback_data="rate_5"),
    ]])

# ─── GURUHGA YUBORISH ────────────────────────────────────────
async def send_to_group(bot, appt):
    now = now_tz().strftime("%d.%m.%Y %H:%M")
    doc_spec = DOCTORS[appt['doc_id']]['spec_uz']
    queue_num = appt.get('queue_num', '?')
    msg = (f"🏥 *Yangi navbat #{appt['id']} — {CLINIC_NAME}*\n━━━━━━━━━━━━━━\n"
           f"👤 *Ism:* {appt['name']}\n📞 *Tel:* {appt['phone']}\n━━━━━━━━━━━━━━\n"
           f"👨‍⚕️ *{appt['doctor']}* ({doc_spec})\n"
           f"📅 *Sana:* {appt['date']}\n"
           f"🕐 *Vaqt:* {appt['time']}\n"
           f"🔢 *{doc_spec}da {queue_num}-navbat*\n"
           f"━━━━━━━━━━━━━━\n🕐 {now}")
    await bot.send_message(chat_id=GROUP_ID, text=msg, parse_mode="Markdown", reply_markup=kb_registrar(appt['id']))

# ─── ESLATMA TIZIMI ──────────────────────────────────────────
def reminder_worker():
    while True:
        try:
            now = now_tz()
            today = now.strftime("%d.%m.%Y")
            for appt in list(appointments.values()):
                if appt["status"] != "confirmed": continue
                if appt["date"] != today: continue
                if appt.get("reminded"): continue
                try:
                    appt_time = datetime.strptime(f"{today} {appt['time']}", "%d.%m.%Y %H:%M")
                    appt_time = TZ.localize(appt_time)
                    diff = (appt_time - now).total_seconds() / 60
                    if 55 <= diff <= 65:
                        appt["reminded"] = True
                        asyncio.run_coroutine_threadsafe(
                            send_reminder(appt), loop
                        )
                except: pass
        except: pass
        time.sleep(60)

async def send_reminder(appt):
    try:
        await ptb_app.bot.send_message(
            chat_id=appt["uid"],
            text=(f"⏰ *Eslatma!*\n\n"
                  f"Bugun soat *{appt['time']}* da navbatingiz bor.\n"
                  f"👨‍⚕️ {appt['doctor']}\n\n"
                  f"📍 {CLINIC_ADDRESS}\n"
                  f"Vaqtida kelishingizni so'raymiz! 🙏"),
            parse_mode="Markdown"
        )
    except: pass

# ─── BAHOLASH YUBORISH ───────────────────────────────────────
async def send_rating_request(bot, appt):
    try:
        lang = users_db.get(str(appt["uid"]), {}).get("lang","uz")
        text = (f"⭐ *Xizmatimizni baholang!*\n\n"
                f"👨‍⚕️ {appt['doctor']}\n"
                f"📅 {appt['date']}\n\n"
                f"Sizning fikringiz bizga muhim!") if lang=="uz" else (
                f"⭐ *Оцените наш сервис!*\n\n"
                f"👨‍⚕️ {appt['doctor']}\n"
                f"📅 {appt['date']}\n\n"
                f"Ваше мнение важно для нас!")
        set_s(appt["uid"], {**get_s(appt["uid"]), "rating_appt": appt["id"]})
        await bot.send_message(chat_id=appt["uid"], text=text, parse_mode="Markdown", reply_markup=kb_rating())
    except: pass

# ─── CALLBACK ────────────────────────────────────────────────
async def on_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cb   = update.callback_query
    data = cb.data
    uid  = cb.from_user.id
    await cb.answer()

    # Registratura tasdiqlashi
    if data.startswith("confirm_") or data.startswith("cancel_"):
        parts    = data.split("_")
        action   = parts[0]
        appt_id  = int(parts[1])
        appt     = appointments.get(appt_id)
        if not appt:
            await cb.edit_message_text("❌ Navbat topilmadi"); return

        admin_name = cb.from_user.first_name or "Registratura"

        if action=="confirm":
            if appt["status"]=="confirmed":
                await cb.answer("Allaqachon tasdiqlangan!", show_alert=True); return
            appt["status"] = "confirmed"
            await cb.edit_message_text(cb.message.text+f"\n\n✅ *Tasdiqlandi* — {admin_name}", parse_mode="Markdown")
            try:
                await ctx.bot.send_message(chat_id=appt["uid"],
                    text=(f"✅ *Navbatingiz tasdiqlandi!*\n\n"
                          f"👨‍⚕️ {appt['doctor']}\n"
                          f"📅 {appt['date']} — soat {appt['time']}\n\n"
                          f"📍 {CLINIC_ADDRESS}\n📞 {CLINIC_PHONE}\n\n"
                          f"⏰ Vaqtida keling!"),
                    parse_mode="Markdown")
            except: pass

        elif action=="cancel":
            if appt["status"]=="cancelled":
                await cb.answer("Allaqachon bekor qilingan!", show_alert=True); return
            appt["status"] = "cancelled"
            unbook_time(appt["doc_id"], appt["date"], appt["time"])
            await cb.edit_message_text(cb.message.text+f"\n\n❌ *Bekor qilindi* — {admin_name}", parse_mode="Markdown")
            try:
                await ctx.bot.send_message(chat_id=appt["uid"],
                    text=(f"❌ *Navbatingiz bekor qilindi*\n\n"
                          f"👨‍⚕️ {appt['doctor']}\n"
                          f"📅 {appt['date']} — {appt['time']}\n\n"
                          f"Qayta navbat olish uchun /start bosing\n📞 {CLINIC_PHONE}"),
                    parse_mode="Markdown")
            except: pass

    # Foydalanuvchi navbatni bekor qilishi
    elif data.startswith("user_cancel_"):
        appt_id = int(data.split("_")[2])
        appt    = appointments.get(appt_id)
        if not appt or appt["uid"]!=uid:
            await cb.answer("❌ Topilmadi", show_alert=True); return
        if appt["status"]=="cancelled":
            await cb.answer("Allaqachon bekor qilingan!", show_alert=True); return
        appt["status"] = "cancelled"
        unbook_time(appt["doc_id"], appt["date"], appt["time"])
        await cb.edit_message_text(f"❌ Navbat bekor qilindi\n\n👨‍⚕️ {appt['doctor']}\n📅 {appt['date']} — {appt['time']}")
        try:
            await ctx.bot.send_message(chat_id=GROUP_ID,
                text=f"❌ Mijoz navbatni bekor qildi\n👤 {appt['name']}\n📅 {appt['date']} — {appt['time']}")
        except: pass

    # Baholash
    elif data.startswith("rate_"):
        star    = int(data.split("_")[1])
        s       = get_s(uid)
        appt_id = s.get("rating_appt")
        stars   = "⭐" * star
        ratings.append({"uid": uid, "appt_id": appt_id, "rating": star})
        set_s(uid, {**s, "rating_appt": None, "rating_step": "comment", "rating_star": star})
        lang = users_db.get(str(uid), {}).get("lang","uz")
        await cb.edit_message_text(
            f"{stars} Rahmat!\n\nIzoh qoldirishni xohlaysizmi? (yoki /start bosing)" if lang=="uz" else
            f"{stars} Спасибо!\n\nХотите оставить комментарий? (или нажмите /start)"
        )

# ─── ASOSIY HANDLER ──────────────────────────────────────────
async def handle_update(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    msg  = update.message
    if not msg or not msg.from_user: return
    uid  = msg.from_user.id
    text = (msg.text or "").strip()
    s    = get_s(uid)
    lang = s.get("lang","uz")

    if text=="/start":
        del_s(uid)
        await msg.reply_text("🌐 Tilni tanlang / Выберите язык:", reply_markup=kb_lang())
        return

    if is_admin(uid) and text=="/admin":
        set_s(uid,{**s,"admin_mode":True})
        await msg.reply_text("🔧 Admin Panel:", reply_markup=kb_admin())
        return

    if is_admin(uid) and text.startswith("/reply "):
        parts=text.split(" ",2)
        if len(parts)==3:
            try:
                await ctx.bot.send_message(chat_id=int(parts[1]),text=f"📩 {CLINIC_NAME}:\n\n{parts[2]}")
                await msg.reply_text("✅ Yuborildi!")
            except: await msg.reply_text("❌ Xato")
        return

    # Izoh (baholashdan keyin)
    if s.get("rating_step")=="comment":
        ratings[-1]["comment"] = text
        set_s(uid,{**s,"rating_step":None})
        star = s.get("rating_star",5)
        # Adminga yuborish
        for aid in ADMIN_IDS:
            try:
                await ctx.bot.send_message(chat_id=aid,
                    text=f"⭐ *Yangi baho*\n\n{'⭐'*star} ({star}/5)\n"
                         f"👤 {users_db.get(str(uid),{}).get('name','—')}\n"
                         f"💬 {text}")
            except: pass
        await msg.reply_text("🙏 Fikringiz uchun rahmat!", reply_markup=kb_menu(lang))
        return

    # Admin panel
    if s.get("admin_mode"):
        if text=="🔙 Chiqish":
            set_s(uid,{"lang":lang})
            await msg.reply_text("Asosiy menyu:", reply_markup=kb_menu(lang)); return

        if text=="📋 Bugungi navbatlar":
            today=now_tz().strftime("%d.%m.%Y")
            ta=sorted([a for a in appointments.values() if a["date"]==today], key=lambda x: x["time"])
            if not ta: await msg.reply_text("Bugun navbat yo'q"); return
            result=f"📋 Bugun ({today}) — {len(ta)} ta:\n\n"
            for a in ta:
                st="✅" if a["status"]=="confirmed" else "❌" if a["status"]=="cancelled" else "⏳"
                result+=f"{st} {a['time']} — {a['name']}\n📞 {a['phone']}\n👨‍⚕️ {a['doctor']}\n\n"
            await msg.reply_text(result); return

        if text=="📊 Statistika":
            today=now_tz().strftime("%d.%m.%Y")
            today_c=len([a for a in appointments.values() if a["date"]==today])
            confirmed=len([a for a in appointments.values() if a["status"]=="confirmed"])
            avg_rating=round(sum(r["rating"] for r in ratings)/len(ratings),1) if ratings else "—"
            await msg.reply_text(
                f"📊 *Statistika*\n\n"
                f"👥 Ro'yxatdan o'tganlar: {len(users_db)}\n"
                f"📅 Bugungi navbatlar: {today_c}\n"
                f"✅ Tasdiqlangan: {confirmed}\n"
                f"📦 Jami navbatlar: {len(appointments)}\n"
                f"⭐ O'rtacha baho: {avg_rating}\n"
                f"👤 Adminlar: {len(ADMIN_IDS)}",
                parse_mode="Markdown"); return

        if text=="⭐ Baholar":
            if not ratings: await msg.reply_text("Hozircha baho yo'q"); return
            avg=round(sum(r["rating"] for r in ratings)/len(ratings),1)
            result=f"⭐ *Baholar* — O'rtacha: {avg}/5\n\n"
            for r in ratings[-10:]:
                name=users_db.get(str(r["uid"]),{}).get("name","—")
                result+=f"{'⭐'*r['rating']} — {name}\n"
                if r.get("comment"): result+=f"💬 {r['comment']}\n"
                result+="\n"
            await msg.reply_text(result, parse_mode="Markdown"); return

        if text=="📢 Xabar yuborish":
            set_s(uid,{**s,"admin_step":"broadcast"})
            await msg.reply_text(f"📢 Barcha {len(users_db)} ta foydalanuvchiga yuboriladigan xabarni yozing:"); return

        if s.get("admin_step")=="broadcast":
            count=0
            for u_id in users_db:
                try:
                    await ctx.bot.send_message(chat_id=int(u_id), text=f"📢 {CLINIC_NAME}:\n\n{text}")
                    count+=1
                except: pass
            set_s(uid,{**s,"admin_step":None})
            await msg.reply_text(f"✅ {count} ta foydalanuvchiga yuborildi!", reply_markup=kb_admin()); return

        if text=="👤 Admin qo'shish":
            set_s(uid,{**s,"admin_step":"add_admin"})
            await msg.reply_text("Yangi admin Telegram ID:"); return

        if s.get("admin_step")=="add_admin":
            try:
                ADMIN_IDS.append(int(text))
                set_s(uid,{**s,"admin_step":None})
                await msg.reply_text(f"✅ {text} admin qilindi!", reply_markup=kb_admin())
            except: await msg.reply_text("❌ Raqam kiriting")
            return

        if text=="👨‍⚕️ Shifokor qo'shish":
            set_s(uid,{**s,"admin_step":"doc_name"})
            await msg.reply_text("Shifokor to'liq ismi:"); return
        if s.get("admin_step")=="doc_name":
            set_s(uid,{**s,"admin_step":"doc_spec","doc_name":text})
            await msg.reply_text("Mutaxassislik:"); return
        if s.get("admin_step")=="doc_spec":
            new_id=str(len(DOCTORS)+1)
            DOCTORS[new_id]={"name":s["doc_name"],"spec_uz":text,"spec_ru":text,"times":["09:00","10:00","11:00","14:00","15:00"]}
            set_s(uid,{**s,"admin_step":None})
            await msg.reply_text(f"✅ {s['doc_name']} qo'shildi!", reply_markup=kb_admin()); return

    # Til tanlash
    if text=="🇺🇿 O'zbekcha":
        set_s(uid,{"lang":"uz"})
        name=msg.from_user.first_name or "Do'stim"
        if str(uid) not in users_db:
            set_s(uid,{"lang":"uz","step":"get_name"})
            await msg.reply_text(f"Salom, {name}! 👋\n\nTo'liq ismingizni kiriting:")
        else:
            set_s(uid,{"lang":"uz","step":"menu"})
            await msg.reply_text(f"🏥 {CLINIC_NAME}\n\nSalom, {users_db[str(uid)]['name']}!", reply_markup=kb_menu("uz"))
        return

    if text=="🇷🇺 Русский":
        set_s(uid,{"lang":"ru"})
        name=msg.from_user.first_name or "Друг"
        if str(uid) not in users_db:
            set_s(uid,{"lang":"ru","step":"get_name"})
            await msg.reply_text(f"Привет, {name}! 👋\n\nВведите ваше полное имя:")
        else:
            set_s(uid,{"lang":"ru","step":"menu"})
            await msg.reply_text(f"🏥 {CLINIC_NAME}\n\nПривет, {users_db[str(uid)]['name']}!", reply_markup=kb_menu("ru"))
        return

    # Ro'yxatdan o'tish
    if s.get("step")=="get_name":
        set_s(uid,{**s,"step":"get_phone","reg_name":text})
        await msg.reply_text("📞 Telefon raqamingizni ulashing:" if lang=="uz" else "📞 Поделитесь номером:", reply_markup=kb_contact(lang))
        return

    if s.get("step")=="get_phone":
        phone=msg.contact.phone_number if msg.contact else text
        if not phone: await msg.reply_text("📞 Raqam yuboring"); return
        users_db[str(uid)]={"name":s["reg_name"],"phone":phone,"lang":lang}
        set_s(uid,{"lang":lang,"step":"menu"})
        await msg.reply_text("✅ Ro'yxatdan o'tdingiz!\n\n🏥 "+CLINIC_NAME if lang=="uz" else "✅ Вы зарегистрированы!", reply_markup=kb_menu(lang))
        try:
            await ctx.bot.send_message(chat_id=GROUP_ID,
                text=f"👤 *Yangi foydalanuvchi*\n\nIsm: {s['reg_name']}\nTel: {phone}\nTelegram: @{msg.from_user.username or '—'}\nID: {uid}",
                parse_mode="Markdown")
        except: pass
        return

    if text in ["🔙 Orqaga","🔙 Назад"]:
        set_s(uid,{"lang":lang,"step":"menu"})
        await msg.reply_text("Asosiy menyu:" if lang=="uz" else "Главное меню:", reply_markup=kb_menu(lang)); return

    # Mening navbatlarim
    if text in ["📋 Mening navbatlarim","📋 Мои записи"]:
        my_appts = get_user_appointments(uid)
        if not my_appts:
            await msg.reply_text("Sizda hozircha navbat yo'q" if lang=="uz" else "У вас нет записей"); return
        for a in my_appts:
            st = "⏳ Kutilmoqda" if a["status"]=="pending" else "✅ Tasdiqlangan"
            txt = f"{st}\n👨‍⚕️ {a['doctor']}\n📅 {a['date']} — {a['time']}"
            await msg.reply_text(txt, reply_markup=kb_cancel_appt(a["id"], lang))
        return

    # Navbat olish
    if text in ["📅 Navbat olish","📅 Записаться на приём"]:
        if str(uid) not in users_db:
            set_s(uid,{"lang":lang,"step":"get_name"})
            await msg.reply_text("Avval ismingizni kiriting:" if lang=="uz" else "Введите имя:"); return
        set_s(uid,{**s,"step":"choose_doctor"})
        await msg.reply_text("👨‍⚕️ Shifokorni tanlang:" if lang=="uz" else "👨‍⚕️ Выберите врача:", reply_markup=kb_doctors(lang)); return

    if s.get("step")=="choose_doctor":
        chosen=None
        for did,d in DOCTORS.items():
            spec=d["spec_uz"] if lang=="uz" else d["spec_ru"]
            if text==f"{d['name']} — {spec}": chosen=(did,d); break
        if not chosen:
            await msg.reply_text("Shifokorni tanlang:", reply_markup=kb_doctors(lang)); return
        set_s(uid,{**s,"step":"choose_date","doc_id":chosen[0],"doc_name":chosen[1]["name"]})
        await msg.reply_text("📅 Sanani tanlang:" if lang=="uz" else "📅 Выберите дату:", reply_markup=kb_dates(lang)); return

    if s.get("step")=="choose_date":
        if text not in get_dates():
            await msg.reply_text("Sanani tanlang:", reply_markup=kb_dates(lang)); return
        free=get_free_times(s["doc_id"], text)
        if not free:
            await msg.reply_text("😔 Bu kun barcha vaqtlar band. Boshqa kun tanlang:" if lang=="uz" else "😔 Все места заняты:", reply_markup=kb_dates(lang)); return
        set_s(uid,{**s,"step":"choose_time","date":text})
        await msg.reply_text("🕐 Vaqtni tanlang:" if lang=="uz" else "🕐 Выберите время:", reply_markup=kb_times(free,lang)); return

    if s.get("step")=="choose_time":
        free=get_free_times(s["doc_id"], s["date"])
        if text not in free:
            if not free:
                await msg.reply_text("😔 Barcha vaqtlar band:", reply_markup=kb_dates(lang))
                set_s(uid,{**s,"step":"choose_date"}); return
            await msg.reply_text("Vaqtni tanlang:", reply_markup=kb_times(free,lang)); return
        set_s(uid,{**s,"step":"confirm","time":text})
        doc=DOCTORS[s["doc_id"]]
        spec=doc["spec_uz"] if lang=="uz" else doc["spec_ru"]
        user=users_db[str(uid)]
        summary=f"📋 *Navbat ma'lumotlari:*\n\n" if lang=="uz" else f"📋 *Данные записи:*\n\n"
        summary+=f"👤 {user['name']}\n📞 {user['phone']}\n👨‍⚕️ {doc['name']} ({spec})\n📅 {s['date']}\n🕐 {text}\n\n"
        summary+="✅ Tasdiqlaysizmi?" if lang=="uz" else "✅ Подтверждаете?"
        await msg.reply_text(summary, parse_mode="Markdown", reply_markup=kb_confirm(lang)); return

    if s.get("step")=="confirm":
        if text in ["✅ Tasdiqlash","✅ Подтвердить"]:
            user=users_db[str(uid)]
            doc=DOCTORS[s["doc_id"]]
            appt_counter[0]+=1
            aid=appt_counter[0]
            queue_num = get_next_number(s["doc_id"], s["date"])
            appt={"id":aid,"uid":uid,"name":user["name"],"phone":user["phone"],
                  "doctor":doc["name"],"doc_id":s["doc_id"],"date":s["date"],"time":s["time"],"status":"pending","queue_num":queue_num}
            appointments[aid]=appt
            book_time(s["doc_id"],s["date"],s["time"])
            await send_to_group(ctx.bot,appt)
            set_s(uid,{"lang":lang,"step":"menu"})
            await msg.reply_text(
                f"⏳ *Navbatingiz yuborildi!*\n\n👨‍⚕️ {doc['name']}\n📅 {s['date']} — {s['time']}\n\nTasdiqlangandan so'ng xabar olasiz 📲" if lang=="uz" else
                f"⏳ *Запись отправлена!*\n\n👨‍⚕️ {doc['name']}\n📅 {s['date']} — {s['time']}\n\nПосле подтверждения вы получите уведомление 📲",
                parse_mode="Markdown", reply_markup=kb_menu(lang))
        else:
            set_s(uid,{"lang":lang,"step":"menu"})
            await msg.reply_text("❌ Bekor qilindi" if lang=="uz" else "❌ Отменено", reply_markup=kb_menu(lang))
        return

    if text in ["👨‍⚕️ Shifokorlar","👨‍⚕️ Наши врачи"]:
        result="👨‍⚕️ *Bizning shifokorlar:*\n\n" if lang=="uz" else "👨‍⚕️ *Наши врачи:*\n\n"
        for d in DOCTORS.values():
            spec=d["spec_uz"] if lang=="uz" else d["spec_ru"]
            result+=f"• *{d['name']}*\n  {spec}\n\n"
        await msg.reply_text(result, parse_mode="Markdown"); return

    if text in ["💰 Xizmatlar va narxlar","💰 Услуги и цены"]:
        result="💰 *Xizmatlar:*\n\n" if lang=="uz" else "💰 *Услуги и цены:*\n\n"
        for name,price in SERVICES[lang]: result+=f"{name} — *{price}*\n"
        await msg.reply_text(result, parse_mode="Markdown"); return

    if text in ["📍 Manzil","📍 Адрес"]:
        await msg.reply_text(f"📍 *{CLINIC_NAME}*\n\n{CLINIC_ADDRESS}\n📞 {CLINIC_PHONE}", parse_mode="Markdown"); return

    if text in ["📞 Bog'lanish","📞 Контакты"]:
        await msg.reply_text(f"📞 *Bog'lanish*\n\n📱 {CLINIC_PHONE}", parse_mode="Markdown"); return

    await msg.reply_text("🌐 Tilni tanlang / Выберите язык:", reply_markup=kb_lang())


# ─── Flask + PTB ─────────────────────────────────────────────
flask_app = Flask(__name__)
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

ptb_app = Application.builder().token(BOT_TOKEN).updater(None).build()
ptb_app.add_handler(CommandHandler("start", handle_update))
ptb_app.add_handler(CallbackQueryHandler(on_callback))
ptb_app.add_handler(MessageHandler(filters.ALL, handle_update))

async def init():
    await ptb_app.initialize()
    await ptb_app.start()
    await ptb_app.bot.set_webhook(url=f"{WEBHOOK_URL}/webhook", drop_pending_updates=True)
    print(f"✅ {CLINIC_NAME} boti ishga tushdi!")

loop.run_until_complete(init())

# Eslatma thread
reminder_thread = threading.Thread(target=reminder_worker, daemon=True)
reminder_thread.start()

@flask_app.route("/", methods=["GET"])
def index(): return f"{CLINIC_NAME} — Ishlayapti! ✅", 200

@flask_app.route("/webhook", methods=["POST"])
def webhook():
    data=request.get_json(force=True)
    update=Update.de_json(data, ptb_app.bot)
    loop.run_until_complete(ptb_app.process_update(update))
    return "OK", 200

if __name__=="__main__":
    port=int(os.environ.get("PORT",8080))
    flask_app.run(host="0.0.0.0", port=port)
