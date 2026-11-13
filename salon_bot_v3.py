"""
ДЕМО-БОТ ДЛЯ САЛОНА КРАСОТЫ
==========================
ИИ-бот для записи клиентов 24/7

Возможности:
  - Запись на услугу (выбор услуги, мастера, времени)
  - ИИ-ответы на свободные вопросы по базе знаний салона
  - Напоминания (демонстрация логики)
  - Уведомления администратору о новых записях
  - Контакты и информация о салоне

НАСТРОЙКА:
  1. pip install aiogram openai python-dotenv
  2. Токен @BotFather и ключ ProxyAPI — в файл .env рядом со скриптом:
       TELEGRAM_BOT_TOKEN=...
       ADMIN_ID=ваш_telegram_id (узнать у @userinfobot)
       LLM_PROVIDER=proxyapi
       LLM_API_KEY=...
       LLM_MODEL=anthropic/claude-haiku-5-5
  3. Настройте данные салона в файле salon_config.json (рядом со скриптом)
  4. Запустите: python salon_bot.py
  Без ключа LLM бот работает в базовом режиме (готовые ответы по базе знаний).

ТИРАЖИРОВАНИЕ:
  Скопируйте файлы, заполните salon_config.json под новый салон — готово.
  Каждый новый салон = новый токен от BotFather + новые данные в конфиге.
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

# ============================================================
#  КОНФИГУРАЦИЯ САЛОНА — из salon_config.json рядом со скриптом
#  Новый салон = заполненный salon_config.json + новый токен BotFather
# ============================================================

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))  # Вставьте ваш Telegram ID в .env

from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parent / "salon_config.json"
with open(CONFIG_PATH, encoding="utf-8") as _f:
    CFG = json.load(_f)

SALON = CFG["salon"]
SALON_NAME = SALON["name"]
SERVICES = CFG["services"]
MASTERS = CFG["masters"]
TIME_SLOTS = CFG["time_slots"]
PROMOTIONS = CFG["promotions"]

# «Любой мастер» не дублирует список услуг в конфиге: подставляем все услуги
if MASTERS.get("any", {}).get("services") == "*":
    MASTERS["any"]["services"] = list(SERVICES.keys())

def apply_placeholders(text: str) -> str:
    """Подставляет данные салона в плейсхолдеры вида {address}, {phone}."""
    return text.format(**SALON)

# ============================================================
#  БАЗА ЗНАНИЙ ДЛЯ ИИ-ОТВЕТОВ (из конфига; {address} и т.п. подставляются)
# ============================================================

KNOWLEDGE_BASE = [
    {**item, "answer": apply_placeholders(item["answer"])}
    for item in CFG["knowledge_base"]
]

# ============================================================
#  LLM-СЛОЙ (ProxyAPI, модель из .env)
# ============================================================

LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "anthropic/claude-haiku-5-5")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.proxyapi.ru/v1")
LLM_ENABLED = bool(LLM_API_KEY)

if LLM_ENABLED:
    llm_client = OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)
else:
    llm_client = None

SYSTEM_PROMPT = (
    f"Ты — дружелюбный администратор салона красоты «{SALON_NAME}». "
    "Ты отвечаешь клиентам бота салона.\n\n"
    "ЖЁСТКИЕ ПРАВИЛА:\n"
    "1. Отвечай ТОЛЬКО фактами из базы знаний салона. Не придумывай цены, услуги, время, имена мастеров и адреса.\n"
    "2. Если точного ответа в базе знаний нет — не фантазируй: скажи, что уточнишь у администратора, "
    "и предложи позвонить по телефону салона или записаться.\n"
    "3. Никогда не обещай скидок и акций, кроме перечисленных в базе знаний.\n"
    "4. Не обсуждай темы, не относящиеся к салону (политика, погода, новости) — вежливо возвращай к сервису.\n"
    "5. Отвечай по-русски, на «вы», коротко и по делу: 1–4 предложения, дружелюбный тон.\n"
    "6. Если клиент просит время вне расписания салона — не подтверждай его, предложи ближайший слот из графика работы.\n"
    "7. Если клиент настаивает на исключении (скидка 50%, срочный визит вне графика) — вежливо откажись и предложи связаться с администратором.\n"
    "8. У тебя нет доступа к истории посещений клиента. Если клиент ссылается на прошлый визит («как в прошлый раз»), не подтверждай его и не описывай детали, которых не знаешь: просто предложи записаться и уточнить.\n"
    "9. Не используй markdown-разметку (звёздочки **, решётки #): отвечай обычным текстом, списки — через тире."
)


def build_kb_context() -> str:
    """Собирает компактный контекст: услуги, мастера, база знаний, акции."""
    lines = ["САЛОН:", f"Название: {SALON['name']}", f"Адрес: {SALON['address']}",
             f"Телефон: {SALON['phone']}", f"Часы работы: {SALON['hours']}",
             f"Instagram: {SALON['instagram']}", "", "УСЛУГИ И ЦЕНЫ:"]
    for svc in SERVICES.values():
        lines.append(f"- {svc['name']}: {svc['price']} ₽, {svc['duration']} мин")
    lines.append("")
    lines.append("МАСТЕРА:")
    for m in MASTERS.values():
        if m["name"] != "Любой мастер":
            services = ", ".join(SERVICES[s]["name"] for s in m["services"])
            lines.append(f"- {m['name']} ({m['role']}): {services}")
    lines.append("")
    lines.append("АКЦИИ:")
    for promo in PROMOTIONS:
        lines.append(f"- {promo}")
    lines.append("")
    lines.append("ОТВЕТЫ НА ЧАСТЫЕ ВОПРОСЫ:")
    for item in KNOWLEDGE_BASE:
        lines.append(f"[{', '.join(item['keywords'][:3])}] {item['answer']}")
    return "\n".join(lines)


KB_CONTEXT = build_kb_context()


def _llm_call_once(question: str) -> str:
    resp = llm_client.chat.completions.create(
        model=LLM_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"БАЗА ЗНАНИЙ САЛОНА:\n\n{KB_CONTEXT}\n\nВОПРОС КЛИЕНТА:\n{question}"},
        ],
        temperature=0.3,
        max_tokens=300,
        timeout=30,
    )
    return resp.choices[0].message.content


async def llm_answer(question: str) -> str | None:
    """Возвращает ответ LLM или None, если LLM недоступен (fallback на старый текст)."""
    if not LLM_ENABLED:
        return None
    for attempt in range(2):
        try:
            return await asyncio.to_thread(_llm_call_once, question)
        except Exception as e:
            logging.warning(f"LLM attempt {attempt + 1} failed: {e}")
    return None


# ============================================================
#  ЛОГИКА БОТА
# ============================================================

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()


class BookingState(StatesGroup):
    service = State()
    master = State()
    timeslot = State()
    confirm = State()


# --- Стартовое меню ---

def main_menu_keyboard() -> ReplyKeyboardMarkup:
    kb = [
        [KeyboardButton(text="💇 Записаться")],
        [KeyboardButton(text="💬 Задать вопрос"), KeyboardButton(text="📍 Контакты")],
        [KeyboardButton(text="🎁 Акции")],
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)


@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    text = (
        f"Здравствуйте! 🌸\n\n"
        f"Добро пожаловать в {SALON['name']}!\n"
        f"Я — ИИ-ассистент салона. Помогу записаться, "
        f"отвечу на вопросы и подскажу по акциям.\n\n"
        f"Что вас интересует?"
    )
    await message.answer(text, reply_markup=main_menu_keyboard())


# --- Запись на услугу ---

def services_keyboard() -> InlineKeyboardMarkup:
    rows = []
    for sid, svc in SERVICES.items():
        rows.append([InlineKeyboardButton(
            text=f"{svc['name']} — {svc['price']} ₽",
            callback_data=f"svc_{sid}",
        )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def masters_keyboard(service_id: str) -> InlineKeyboardMarkup:
    rows = []
    for mid, m in MASTERS.items():
        if service_id in m["services"]:
            rows.append([InlineKeyboardButton(
                text=f"{m['name']} — {m['role']}",
                callback_data=f"mst_{mid}",
            )])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def timeslots_keyboard() -> InlineKeyboardMarkup:
    rows = []
    row = []
    for i, slot in enumerate(TIME_SLOTS):
        row.append(InlineKeyboardButton(text=slot, callback_data=f"time_{slot}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(text="⬅️ Назад к услугам", callback_data="back_svc")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтвердить запись", callback_data="confirm_yes")],
        [InlineKeyboardButton(text="❌ Отменить", callback_data="confirm_no")],
    ])


@dp.message(F.text == "💇 Записаться")
async def start_booking(message: Message, state: FSMContext):
    await state.set_state(BookingState.service)
    await message.answer(
        "Выберите услугу:",
        reply_markup=services_keyboard(),
    )


@dp.callback_query(F.data == "back_svc")
async def back_to_services(callback: CallbackQuery, state: FSMContext):
    await state.set_state(BookingState.service)
    await callback.message.edit_text("Выберите услугу:", reply_markup=services_keyboard())
    await callback.answer()


@dp.callback_query(BookingState.service, F.data.startswith("svc_"))
async def select_service(callback: CallbackQuery, state: FSMContext):
    service_id = callback.data.replace("svc_", "")
    if service_id not in SERVICES:
        await callback.answer("Услуга не найдена")
        return
    svc = SERVICES[service_id]
    await state.update_data(service_id=service_id, service_name=svc["name"],
                            service_price=svc["price"], service_duration=svc["duration"])
    await state.set_state(BookingState.master)
    await callback.message.edit_text(
        f"Услуга: {svc['name']} — {svc['price']} ₽ ({svc['duration']} мин)\n\n"
        f"Выберите мастера:",
        reply_markup=masters_keyboard(service_id),
    )
    await callback.answer()


@dp.callback_query(BookingState.master, F.data.startswith("mst_"))
async def select_master(callback: CallbackQuery, state: FSMContext):
    master_id = callback.data.replace("mst_", "")
    if master_id not in MASTERS:
        await callback.answer("Мастер не найден")
        return
    m = MASTERS[master_id]
    await state.update_data(master_id=master_id, master_name=m["name"])
    await state.set_state(BookingState.timeslot)
    await callback.message.edit_text(
        f"Мастер: {m['name']}\n\nВыберите удобное время:",
        reply_markup=timeslots_keyboard(),
    )
    await callback.answer()


@dp.callback_query(BookingState.timeslot, F.data.startswith("time_"))
async def select_timeslot(callback: CallbackQuery, state: FSMContext):
    timeslot = callback.data.replace("time_", "")
    data = await state.get_data()
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%d.%m.%Y")
    await state.update_data(timeslot=timeslot, date=tomorrow)
    await state.set_state(BookingState.confirm)
    await callback.message.edit_text(
        f"Проверьте запись:\n\n"
        f"📅 Дата: {tomorrow}\n"
        f"⏰ Время: {timeslot}\n"
        f"💇 Услуга: {data['service_name']}\n"
        f"💰 Стоимость: {data['service_price']} ₽\n"
        f"👩 Мастер: {data['master_name']}\n\n"
        f"Всё верно?",
        reply_markup=confirm_keyboard(),
    )
    await callback.answer()


@dp.callback_query(BookingState.confirm, F.data == "confirm_yes")
async def confirm_booking(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await state.clear()

    # Уведомление администратору
    admin_text = (
        f"🔔 НОВАЯ ЗАПИСЬ\n\n"
        f"📅 Дата: {data.get('date', '—')}\n"
        f"⏰ Время: {data.get('timeslot', '—')}\n"
        f"💇 Услуга: {data.get('service_name', '—')}\n"
        f"💰 Цена: {data.get('service_price', '—')} ₽\n"
        f"👩 Мастер: {data.get('master_name', '—')}\n\n"
        f"👤 Клиент: {callback.from_user.full_name}\n"
        f"📱 Username: @{callback.from_user.username or 'нет'}\n"
        f"🆔 ID: {callback.from_user.id}"
    )
    try:
        await bot.send_message(ADMIN_ID, admin_text)
    except Exception:
        pass  # В демо-режиме может не работать без реального ADMIN_ID

    await callback.message.edit_text(
        f"✅ Вы записаны!\n\n"
        f"📅 {data.get('date', '—')} в {data.get('timeslot', '—')}\n"
        f"💇 {data.get('service_name', '—')}\n"
        f"👩 Мастер: {data.get('master_name', '—')}\n\n"
        f"Напомню о визите за день до записи.\n"
        f"Если нужно перенести — пишите {SALON['phone']}.\n\n"
        f"До встречи в {SALON['name']}! 🌸"
    )
    await callback.message.answer(
        "Чем ещё могу помочь?", reply_markup=main_menu_keyboard()
    )
    await callback.answer()


@dp.callback_query(BookingState.confirm, F.data == "confirm_no")
async def cancel_booking(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("Запись отменена. Начните заново, когда будете готовы.")
    await callback.message.answer("Чем ещё могу помочь?", reply_markup=main_menu_keyboard())
    await callback.answer()


# --- ИИ-ответы на свободные вопросы ---

def find_answer(text: str) -> str | None:
    text_lower = text.lower().strip()
    for item in KNOWLEDGE_BASE:
        for kw in item["keywords"]:
            if kw in text_lower:
                return item["answer"]
    return None


@dp.message(F.text == "💬 Задать вопрос")
async def ask_question_prompt(message: Message):
    await message.answer(
        "Задайте любой вопрос — я отвечу!\n\n"
        "Например:\n"
        "• «Сколько стоит стрижка?»\n"
        "• «Где вы находитесь?»\n"
        "• «До скольки вы работаете?»\n"
        "• «Есть ли парковка?»\n"
        "• «Какие у вас акции?»"
    )


@dp.message(F.text == "📍 Контакты")
async def show_contacts(message: Message):
    text = (
        f"📍 {SALON['name']}\n\n"
        f"Адрес: {SALON['address']}\n"
        f"Телефон: {SALON['phone']}\n"
        f"Часы работы: {SALON['hours']}\n"
        f"Instagram: {SALON['instagram']}"
    )
    await message.answer(text)


@dp.message(F.text == "🎁 Акции")
async def show_promotions(message: Message):
    lines = ["🎁 Акции этого месяца:", ""]
    lines += [f"• {promo}" for promo in PROMOTIONS]
    lines += ["", "Записаться можно прямо здесь — нажмите «Записаться» 👇"]
    await message.answer("\n".join(lines))


# --- Обработка свободного текста (ИИ-ответы) ---

@dp.message()
async def handle_free_text(message: Message):
    # 1-й слой: точные совпадения по базе знаний (без затрат на LLM)
    answer = find_answer(message.text)
    if not answer:
        # 2-й слой: свободный вопрос — реальный LLM
        answer = await llm_answer(message.text)
    if answer:
        await message.answer(answer, reply_markup=main_menu_keyboard())
    else:
        await message.answer(
            "Я не нашёл ответ на этот вопрос 🤔\n\n"
            f"Позвоните нам: {SALON['phone']}\n"
            f"Или напишите в Instagram: {SALON['instagram']}\n\n"
            "А пока — могу помочь записаться! Нажмите «Записаться» 👇",
            reply_markup=main_menu_keyboard(),
        )


# --- Запуск ---

async def main():
    print(f"Бот салона '{SALON['name']}' запущен!")
    print(f"Администратор ID: {ADMIN_ID}")
    print(f"Услуг в меню: {len(SERVICES)}")
    print(f"Мастеров: {len(MASTERS)}")
    print(f"Слотов времени: {len(TIME_SLOTS)}")
    print(f"Тем в базе знаний: {len(KNOWLEDGE_BASE)}")
    print("---")
    import aiogram
    while True:
        try:
            await dp.start_polling(bot)
        except aiogram.exceptions.TelegramNetworkError:
            print("Сеть до Telegram недоступна. Повтор через 15 секунд... (не закрывайте окно)")
            await asyncio.sleep(15)


if __name__ == "__main__":
    asyncio.run(main())
