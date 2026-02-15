import asyncio
import logging
import sqlite3
import json
import os
from datetime import datetime, timezone
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardRemove, FSInputFile
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = "7987418199:AAFaJvb5RLtfzF77qST1PXsEi6VxNTCyxG8"
ADMIN_ID = 7838075449  # ← ТВОЙ ID
DB_FILE = "valentine_bot.db"

EMOJIS = {
    "love":   "5420403281950172517",
    "fire":   "5424972470023104089",
    "flirt":  "5253649454401073265",
    "secret": "5197289102541608554",
}

TITLES = {
    "love":   "Тебе пришла романтическая валентинка!",
    "fire":   "Тебе пришла страстная валентинка!",
    "flirt":  "Тебе пришла флирт валентинка!",
    "secret": "Тебе пришла анонимная валентинка!",
}

BUTTON_TEXTS = {
    "love":   "Романтика",
    "fire":   "Страсть",
    "flirt":  "Флирт",
    "secret": "Аноним",
}

RECEIVED_EMOJI = "5393210594163699785"
SENT_EMOJI    = "5429501538806548545"

bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

stats = {}
valentines = {}
button_configs = {
    "love":   {"style": "success",  "emoji_id": EMOJIS["love"]},
    "fire":   {"style": "danger",   "emoji_id": EMOJIS["fire"]},
    "flirt":  {"style": "primary",  "emoji_id": EMOJIS["flirt"]},
    "secret": {"style": "primary",  "emoji_id": EMOJIS["secret"]},
}
BOT_USERNAME = None

class Valentine(StatesGroup):
    text   = State()
    photo  = State()
    type_  = State()

class Admin(StatesGroup):
    broadcast_text        = State()
    broadcast_button_text = State()
    broadcast_button_url  = State()

# ── БАЗА ────────────────────────────────────────────────────────────────
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            sent INTEGER DEFAULT 0,
            received INTEGER DEFAULT 0
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS valentines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            receiver_id INTEGER NOT NULL,
            text TEXT NOT NULL,
            photo TEXT,
            type TEXT NOT NULL,
            sender_id INTEGER
        )
    ''')
    conn.commit()
    conn.close()

def migrate_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(valentines)")
    columns = {col[1] for col in cursor.fetchall()}
    if 'receiver_id' not in columns:
        logger.info("Миграция: добавляем receiver_id")
        cursor.execute("ALTER TABLE valentines ADD COLUMN receiver_id INTEGER")
        conn.commit()
    conn.close()

def load_db():
    global stats, valentines
    stats = {}
    valentines = {}

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute("SELECT user_id, sent, received FROM users")
    for uid, sent, rec in cursor.fetchall():
        stats[uid] = {"sent": sent, "received": rec}

    cursor.execute("SELECT receiver_id, text, photo, type, sender_id FROM valentines")
    for rid, text, photo, typ, sid in cursor.fetchall():
        valentines.setdefault(rid, []).append({
            "text": text,
            "photo": photo,
            "type": typ,
            "sender_id": sid
        })

    conn.close()
    logger.info(f"БД загружена: {len(stats)} пользователей, {sum(len(v) for v in valentines.values())} валентинок")

def save_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    for uid, data in stats.items():
        cursor.execute(
            "INSERT OR REPLACE INTO users (user_id, sent, received) VALUES (?, ?, ?)",
            (uid, data["sent"], data["received"])
        )

    cursor.execute("DELETE FROM valentines")
    for rid, vals in valentines.items():
        for v in vals:
            cursor.execute(
                "INSERT INTO valentines (receiver_id, text, photo, type, sender_id) VALUES (?, ?, ?, ?, ?)",
                (rid, v["text"], v.get("photo"), v["type"], v.get("sender_id"))
            )

    conn.commit()
    conn.close()
    logger.info("База сохранена")

init_db()
migrate_db()
load_db()

# ── КЛАВИАТУРЫ ──────────────────────────────────────────────────────────
def types_kb():
    kb = []
    for v_type, cfg in button_configs.items():
        btn = InlineKeyboardButton(
            text=BUTTON_TEXTS[v_type],
            callback_data=f"type_{v_type}",
            icon_custom_emoji_id=cfg["emoji_id"],
            style=cfg["style"]
        )
        kb.append([btn])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def main_menu_kb(uid: int):
    link = f"https://t.me/{BOT_USERNAME}?start=sendQuestion-{uid}"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Скопировать ссылку", url=link)],
        [InlineKeyboardButton(text="🔗 Поделиться ссылкой", url=f"https://t.me/share/url?url={link}&text=Пришли%20мне%20валентинку!")],
        [InlineKeyboardButton(text="📨 Мои валентинки", callback_data="show_inbox")],
    ])

# ── СТАРТ ───────────────────────────────────────────────────────────────
@dp.message(CommandStart())
async def start_handler(m: Message, state: FSMContext):
    global BOT_USERNAME
    if BOT_USERNAME is None:
        BOT_USERNAME = (await bot.get_me()).username

    args = m.text.split(maxsplit=1)
    payload = args[1] if len(args) > 1 else None

    uid = m.from_user.id
    stats.setdefault(uid, {"sent": 0, "received": 0})
    valentines.setdefault(uid, [])
    save_db()

    if payload and payload.startswith("sendQuestion-"):
        try:
            target_id = int(payload.split("-", 1)[1])
        except:
            await m.answer("Ссылка повреждена или некорректна 😕")
            return

        if target_id == uid:
            await m.answer("Это твоя собственная ссылка 😄\nРазмести её, чтобы другие могли присылать тебе валентинки.")
            return

        await state.clear()
        await state.update_data(receiver=target_id, is_reply=False)
        await state.set_state(Valentine.text)
        await m.answer(
            "<b>Напиши текст валентинки</b> (до 2000 символов)\n\n"
            "Получатель не увидит твоё имя — полная анонимность.",
            reply_markup=ReplyKeyboardRemove(remove_keyboard=True)
        )
        return

    await m.answer(
        f"💌 <b>ПОЛУЧАЙ АНОНИМНЫЕ ВАЛЕНТИНКИ ПРЯМО СЕЙЧАС!</b>\n\n"
        f"Твоя ссылка:\nhttps://t.me/{BOT_USERNAME}?start=sendQuestion-{uid}\n\n"
        "Размести эту ссылку в профиле / историях и получай сообщения! 💘",
        reply_markup=main_menu_kb(uid),
        disable_web_page_preview=True
    )

# ── ВВОД ТЕКСТА ─────────────────────────────────────────────────────────
@dp.message(Valentine.text)
async def process_text(m: Message, state: FSMContext):
    text = m.text.strip()
    if not text:
        await m.answer("Пустое сообщение нельзя отправить 😅")
        return

    if len(text) > 2000:
        await m.answer("Текст слишком длинный (максимум 2000 символов)")
        return

    await state.update_data(text=text)

    data = await state.get_data()
    is_reply = data.get("is_reply", False)

    if is_reply:
        await state.set_state(Valentine.photo)
        await m.answer(
            "Можешь прикрепить фото к ответу (по желанию)\n"
            "Или напиши /skip чтобы отправить без фото"
        )
    else:
        await state.set_state(Valentine.photo)
        await m.answer(
            "Можешь отправить фото к валентинке (по желанию)\n"
            "Или напиши /skip, чтобы перейти к выбору типа"
        )

# ── ФОТО / SKIP ─────────────────────────────────────────────────────────
@dp.message(Valentine.photo, F.text == "/skip")
async def skip_photo(m: Message, state: FSMContext):
    await state.update_data(photo=None)
    data = await state.get_data()
    is_reply = data.get("is_reply", False)

    if is_reply:
        await send_valentine_reply(m, state)
    else:
        await state.set_state(Valentine.type_)
        await m.answer("<b>Выбери тип валентинки:</b>", reply_markup=types_kb())

@dp.message(Valentine.photo, F.photo)
async def process_photo(m: Message, state: FSMContext):
    photo_id = m.photo[-1].file_id
    await state.update_data(photo=photo_id)
    data = await state.get_data()
    is_reply = data.get("is_reply", False)

    if is_reply:
        await send_valentine_reply(m, state)
    else:
        await state.set_state(Valentine.type_)
        await m.answer("<b>Выбери тип валентинки:</b>", reply_markup=types_kb())

# ── ОТПРАВКА ВАЛЕНТИНКИ ─────────────────────────────────────────────────
@dp.callback_query(Valentine.type_, F.data.startswith("type_"))
async def send_valentine(c: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    text = data.get("text", "").strip()
    photo_id = data.get("photo")
    receiver = data.get("receiver")

    if not text or not receiver:
        await c.answer("Ошибка — начни заново", show_alert=True)
        await state.clear()
        return

    v_type = c.data.removeprefix("type_")
    title = TITLES.get(v_type, "Тебе пришла валентинка!")

    msg_text = f'<tg-emoji emoji-id="{RECEIVED_EMOJI}">💌</tg-emoji> <b>{title}</b>\n\n<b>{text}</b>'

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Ответить", callback_data=f"reply-{c.from_user.id}")]
    ])

    try:
        if photo_id:
            await bot.send_photo(receiver, photo_id, caption=msg_text, reply_markup=kb)
        else:
            await bot.send_message(receiver, msg_text, reply_markup=kb)
    except TelegramForbiddenError:
        await c.answer("Получатель заблокировал бота 😔", show_alert=True)
    except TelegramBadRequest as e:
        logger.warning(f"Bad Request: {e}")
        await bot.send_message(receiver, f"<b>{title}</b>\n\n<b>{text}</b>", reply_markup=kb)

    sender = c.from_user.id
    stats.setdefault(sender, {"sent": 0, "received": 0})
    stats.setdefault(receiver, {"sent": 0, "received": 0})
    stats[sender]["sent"] += 1
    stats[receiver]["received"] += 1

    valentines.setdefault(receiver, []).append({
        "text": text,
        "photo": photo_id,
        "type": v_type,
        "sender_id": sender
    })

    save_db()

    await state.clear()
    await c.message.edit_text(f'<tg-emoji emoji-id="{SENT_EMOJI}">✅</tg-emoji> Валентинка успешно отправлена!')
    await c.answer()

# ── ОТВЕТ ───────────────────────────────────────────────────────────────
@dp.callback_query(F.data.startswith("reply-"))
async def handle_reply(c: CallbackQuery, state: FSMContext):
    try:
        original_sender_id = int(c.data.split("-")[1])
    except:
        await c.answer("Ошибка", show_alert=True)
        return

    await state.clear()
    await state.update_data(receiver=original_sender_id, is_reply=True)
    await state.set_state(Valentine.text)
    await c.message.answer("<b>Напиши текст ответа</b> (анонимно)")
    await c.answer()


async def send_valentine_reply(m: Message, state: FSMContext):
    data = await state.get_data()
    text = data.get("text", "").strip()
    photo_id = data.get("photo")
    receiver = data.get("receiver")

    if not text or not receiver:
        await m.answer("Ошибка — текст или получатель потерян")
        await state.clear()
        return

    title = "Тебе пришел ответ на валентинку!"

    msg_text = f'<tg-emoji emoji-id="{RECEIVED_EMOJI}">💌</tg-emoji> <b>{title}</b>\n\n<b>{text}</b>'

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Ответить", callback_data=f"reply-{m.from_user.id}")]
    ])

    try:
        if photo_id:
            await bot.send_photo(receiver, photo_id, caption=msg_text, reply_markup=kb)
        else:
            await bot.send_message(receiver, msg_text, reply_markup=kb)
    except TelegramForbiddenError:
        await m.answer("Получатель заблокировал бота 😔")
    except TelegramBadRequest as e:
        logger.warning(f"Bad Request: {e}")
        await bot.send_message(receiver, f"<b>{title}</b>\n\n<b>{text}</b>", reply_markup=kb)

    sender = m.from_user.id
    stats.setdefault(sender, {"sent": 0, "received": 0})
    stats.setdefault(receiver, {"sent": 0, "received": 0})
    stats[sender]["sent"] += 1
    stats[receiver]["received"] += 1

    valentines.setdefault(receiver, []).append({
        "text": text,
        "photo": photo_id,
        "type": "reply",
        "sender_id": sender
    })

    save_db()

    await state.clear()
    await m.answer(f'<tg-emoji emoji-id="{SENT_EMOJI}">✅</tg-emoji> Ответ успешно отправлен!')

# ── МОИ ВАЛЕНТИНКИ ──────────────────────────────────────────────────────
@dp.callback_query(F.data == "show_inbox")
async def show_inbox(c: CallbackQuery):
    uid = c.from_user.id
    vals = valentines.get(uid, [])
    if not vals:
        await c.message.answer("У тебя пока нет валентинок 😔")
        await c.answer()
        return

    kb = []
    row = []
    for i in range(len(vals)):
        row.append(InlineKeyboardButton(text=str(i+1), callback_data=f"view-{i}"))
        if len(row) == 5:
            kb.append(row)
            row = []
    if row:
        kb.append(row)

    await c.message.answer("Твои валентинки:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await c.answer()

@dp.callback_query(F.data.startswith("view-"))
async def view_valentine(c: CallbackQuery):
    uid = c.from_user.id
    try:
        idx = int(c.data.split("-")[1])
    except:
        await c.answer("Ошибка", show_alert=True)
        return

    vals = valentines.get(uid, [])
    if idx >= len(vals):
        await c.answer("Валентинка не найдена", show_alert=True)
        return

    val = vals[idx]
    title = TITLES.get(val["type"], "Валентинка") if val["type"] != "reply" else "Ответ на валентинку"

    msg_text = f'<tg-emoji emoji-id="{RECEIVED_EMOJI}">💌</tg-emoji> <b>{title}</b>\n\n<b>{val["text"]}</b>'

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Ответить", callback_data=f"reply-{val.get('sender_id', 0)}")]
    ])

    if val.get("photo"):
        await bot.send_photo(uid, val["photo"], caption=msg_text, reply_markup=kb)
    else:
        await bot.send_message(uid, msg_text, reply_markup=kb)

    await c.answer()

# ── АДМИН-ПАНЕЛЬ ────────────────────────────────────────────────────────
@dp.message(Command("admin"))
async def admin_panel(m: Message):
    if m.from_user.id != ADMIN_ID:
        await m.answer("Доступ запрещён 😡")
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📤 Рассылка", callback_data="admin_broadcast")],
        [InlineKeyboardButton(text="📥 Скачать БД (JSON)", callback_data="admin_download_json")],
        [InlineKeyboardButton(text="📥 Скачать БД (TXT)", callback_data="admin_download_txt")],
    ])
    await m.answer("Админ-панель:", reply_markup=kb)

# ── РАССЫЛКА ────────────────────────────────────────────────────────────
@dp.callback_query(F.data == "admin_broadcast")
async def start_broadcast(c: CallbackQuery, state: FSMContext):
    if c.from_user.id != ADMIN_ID:
        await c.answer("Нет доступа", show_alert=True)
        return

    await state.clear()
    await state.set_state(Admin.broadcast_text)
    await c.message.answer("Введи текст рассылки (HTML):")
    await c.answer()


@dp.message(Admin.broadcast_text)
async def process_broadcast_text(m: Message, state: FSMContext):
    if m.from_user.id != ADMIN_ID:
        return

    text = m.html_text.strip()
    if not text:
        await m.answer("Текст пустой")
        return

    await state.update_data(broadcast_text=text)
    await state.set_state(Admin.broadcast_button_text)
    await m.answer("Текст кнопки? (/skip — без)")


@dp.message(Admin.broadcast_button_text)
async def process_broadcast_button_text(m: Message, state: FSMContext):
    if m.from_user.id != ADMIN_ID:
        return

    text = m.text.strip()
    if text.lower() == "/skip":
        await state.update_data(button_text=None, button_url=None)
        await do_broadcast(m, state)
        return

    await state.update_data(button_text=text)
    await state.set_state(Admin.broadcast_button_url)
    await m.answer("Ссылка для кнопки:")


@dp.message(Admin.broadcast_button_url)
async def process_broadcast_button_url(m: Message, state: FSMContext):
    if m.from_user.id != ADMIN_ID:
        return

    url = m.text.strip()
    if not url.startswith(("http://", "https://")):
        await m.answer("Неверная ссылка")
        return

    await state.update_data(button_url=url)
    await do_broadcast(m, state)


async def do_broadcast(m: Message, state: FSMContext):
    data = await state.get_data()
    text = data.get("broadcast_text", "")
    button_text = data.get("button_text")
    button_url = data.get("button_url")

    if not text:
        await m.answer("Текст пустой")
        await state.clear()
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users")
    users = [r[0] for r in cursor.fetchall()]
    conn.close()

    total = len(users)
    if total == 0:
        await m.answer("Нет пользователей в базе")
        await state.clear()
        return

    kb = None
    if button_text and button_url:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=button_text, url=button_url)]
        ])

    success = blocked = errors = 0

    for uid in users:
        try:
            await bot.send_message(uid, text, reply_markup=kb, disable_web_page_preview=True)
            success += 1
        except TelegramForbiddenError:
            blocked += 1
        except Exception as e:
            errors += 1
            logger.error(f"Рассылка ошибка {uid}: {e}")

    await m.answer(
        f"Рассылка завершена\n"
        f"Всего: {total}\n"
        f"Успешно: {success}\n"
        f"Заблокировали: {blocked}\n"
        f"Ошибки: {errors}"
    )
    await state.clear()

# ── СКАЧИВАНИЕ БД ──────────────────────────────────────────────────────
@dp.callback_query(F.data == "admin_download_json")
async def download_json(c: CallbackQuery):
    if c.from_user.id != ADMIN_ID:
        await c.answer("Нет доступа", show_alert=True)
        return

    try:
        data = {
            "exported_at": datetime.now(timezone.UTC).isoformat(),
            "users": [{"user_id": uid, **d} for uid, d in stats.items()],
            "valentines": [
                {"receiver_id": uid, **val}
                for uid, vals in valentines.items()
                for val in vals
            ]
        }

        filename = f"valentine_db_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(filename, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        await bot.send_document(c.from_user.id, FSInputFile(filename))
        os.remove(filename)
        await c.answer("JSON отправлен")
    except Exception as e:
        logger.error(f"JSON ошибка: {e}")
        await c.message.answer("Ошибка при создании JSON")
        await c.answer()


@dp.callback_query(F.data == "admin_download_txt")
async def download_txt(c: CallbackQuery):
    if c.from_user.id != ADMIN_ID:
        await c.answer("Нет доступа", show_alert=True)
        return

    try:
        lines = [f"Экспорт — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"]
        lines.append(f"Пользователей: {len(stats)}")
        lines.append(f"Валентинок: {sum(len(v) for v in valentines.values())}\n")

        lines.append("ПОЛЬЗОВАТЕЛИ")
        for uid, d in stats.items():
            lines.append(f"{uid} | sent:{d['sent']} | rec:{d['received']}")

        lines.append("\nВАЛЕНТИНКИ")
        cnt = 1
        for uid, vals in valentines.items():
            for v in vals:
                lines.append(f"{cnt} | {uid} | {v['type']} | от {v.get('sender_id','anon')}")
                lines.append(f"   {v['text'][:120]}{'...' if len(v['text'])>120 else ''}")
                lines.append("")
                cnt += 1

        filename = f"valentine_db_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        with open(filename, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        await bot.send_document(c.from_user.id, FSInputFile(filename))
        os.remove(filename)
        await c.answer("TXT отправлен")
    except Exception as e:
        logger.error(f"TXT ошибка: {e}")
        await c.message.answer("Ошибка при создании TXT")
        await c.answer()

async def main():
    init_db()
    migrate_db()
    load_db()
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())

if __name__ == "__main__":
    asyncio.run(main())