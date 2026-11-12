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
  1. pip install aiogram
  2. Получите токен у @BotFather в Telegram
  3. Вставьте токен в BOT_TOKEN ниже
  4. Вставьте ID администратора в ADMIN_ID (узнать у @userinfobot)
  5. Настройте данные салона в блоке КОНФИГУРАЦИЯ
  6. Запустите: python salon_bot.py

ТИРАЖИРОВАНИЕ:
  Скопируйте файл, поменяйте КОНФИГУРАЦИЮ под новый салон — готово.
  Каждый новый салон = новый токен от BotFather + новые данные в конфиге.
"""

import asyncio
import logging
from datetime import datetime, timedelta

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
#  КОНФИГУРАЦИЯ САЛОНА — меняйте под каждый новый салон
# ============================================================

BOT_TOKEN = "ВСТАВЬТЕ_ТОКЕН_ОТ_BOTFATHER"
ADMIN_ID = 123456789  # Вставьте ваш Telegram ID

SALON = {
    "name": "Студия красоты «Элеганс»",
    "address": "г. Миасс, пр. Макеева, 12",
    "phone": "+7 (351) 555-12-34",
    "hours": "Пн–Сб: 9:00–20:00, Вс: 10:00–18:00",
    "instagram": "@elegans_salon",
}

# Услуги салона
SERVICES = {
    "haircut": {"name": "Женская стрижка", "price": 1500, "duration": 60},
    "coloring": {"name": "Окрашивание", "price": 3500, "duration": 120},
    "manicure": {"name": "Маникюр + покрытие", "price": 2000, "duration": 90},
    "pedicure": {"name": "Педикюр", "price": 2500, "duration": 90},
    "brows": {"name": "Брови: коррекция + окрашивание", "price": 800, "duration": 30},
    "lashes": {"name": "Наращивание ресниц", "price": 2500, "duration": 120},
}

# Мастера салона
MASTERS = {
    "anna": {"name": "Анна", "role": "Парикмахер-стилист", "services": ["haircut", "coloring"]},
    "elena": {"name": "Елена", "role": "Мастер маникюра", "services": ["manicure", "pedicure"]},
    "maria": {"name": "Мария", "role": "Бровист / Лэшмейкер", "services": ["brows", "lashes"]},
    "any": {"name": "Любой мастер", "role": "Подберём свободного", "services": list(SERVICES.keys())},
}

# Доступные слоты времени
TIME_SLOTS = [
    "10:00", "11:00", "12:00", "13:00", "14:00",
    "15:00", "16:00", "17:00", "18:00", "19:00",
]

# ============================================================
#  БАЗА ЗНАНИЙ ДЛЯ ИИ-ОТВЕТОВ (ключевые слова → ответ)
# ============================================================

KNOWLEDGE_BASE = [
    {
        "keywords": ["цен", "стоим", "сколько стоит", "прайс", "цена"],
        "answer": (
            "Наш прайс:\n"
            "• Женская стрижка — 1 500 ₽\n"
            "• Окрашивание — от 3 500 ₽\n"
            "• Маникюр + покрытие — 2 000 ₽\n"
            "• Педикюр — 2 500 ₽\n"
            "• Брови — 800 ₽\n"
            "• Ресницы — от 2 500 ₽\n\n"
            "Точную стоимость мастер назовёт после консультации. "
            "Записаться можно прямо здесь — нажмите «Записаться» 👇"
        ),
    },
    {
        "keywords": ["адрес", "где вы", "как доехать", "находитесь"],
        "answer": (
            f"Мы находимся: {SALON['address']}\n"
            f"Телефон: {SALON['phone']}\n"
            f"Instagram: {SALON['instagram']}"
        ),
    },
    {
        "keywords": ["час", "работа", "когда вы", "график", "время работы"],
        "answer": f"Часы работы: {SALON['hours']}",
    },
    {
        "keywords": ["запис", "записаться", "запись", "хочу на", "нужно записать"],
        "answer": (
            "Записаться очень просто! Нажмите кнопку «Записаться» ниже — "
            "выберете услугу, мастера и удобное время за 30 секунд. 👇"
        ),
    },
    {
        "keywords": ["отмен", "перенести", "перенос", "не смогу прийти", "отмена"],
        "answer": (
            "Чтобы отменить или перенести запись, напишите нам: "
            f"{SALON['phone']} или в Instagram {SALON['instagram']}. "
            "Пожалуйста, сообщите об отмене заранее!"
        ),
    },
    {
        "keywords": ["парковка", "где поставить", "машина", "авто"],
        "answer": "Парковка во дворе — 10 мест, бесплатно. Вход со стороны пр. Макеева.",
    },
    {
        "keywords": ["оплата", "как платить", "карта", "наличные", "перевод"],
        "answer": "Принимаем наличные, карты и переводы (СБП, перевод на карту). Оплата после услуги.",
    },
    {
        "keywords": ["детск", "ребенок", "дети", "с ребенком"],
        "answer": "Да, мы принимаем детей с 5 лет. Детская стрижка — 800 ₽.",
    },
    {
        "keywords": ["акци", "скидк", "промо", "бонус"],
        "answer": (
            "Акции этого месяца:\n"
            "• Скидка 15% на первое посещение\n"
            "• Каждая 6-я стрижка — бесплатно\n"
            "• Приведи подругу — обе получите −10%"
        ),
    },
    {
        "keywords": ["кори", "ковид", "санитар", "безопасност", "чистота"],
        "answer": "Все инструменты проходят стерилизацию в сухожаровом шкафу. Рабочие места дезинфицируются после каждого клиента.",
    },
]

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
    text = (
        "🎁 Акции этого месяца:\n\n"
        "• Скидка 15% на первое посещение\n"
        "• Каждая 6-я стрижка — бесплатно\n"
        "• Приведи подругу — обе получите −10%\n"
        "• Подарочный сертификат от 1 000 ₽\n\n"
        f"Записаться можно прямо здесь — нажмите «Записаться» 👇"
    )
    await message.answer(text)


# --- Обработка свободного текста (ИИ-ответы) ---

@dp.message()
async def handle_free_text(message: Message):
    answer = find_answer(message.text)
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
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
