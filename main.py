import asyncio
import logging
import sqlite3
import re
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandObject
from aiogram.utils.keyboard import InlineKeyboardBuilder
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

import os
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")

if not TOKEN:
    raise ValueError("BOT_TOKEN не найден! Создайте .env файл с токеном.")

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN)
dp = Dispatcher()
scheduler = AsyncIOScheduler(timezone="Europe/Moscow")

# --- БАЗА ДАННЫХ ---

def init_db():
    conn = sqlite3.connect("todo_pro.db")
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            exec_time TEXT,
            category TEXT,
            message_text TEXT,
            is_done INTEGER DEFAULT 0
        )
    ''')
    conn.commit()
    conn.close()

def add_reminder(chat_id, exec_time, category, text):
    conn = sqlite3.connect("todo_pro.db")
    cursor = conn.cursor()
    cursor.execute("INSERT INTO reminders (chat_id, exec_time, category, message_text) VALUES (?, ?, ?, ?)",
                   (chat_id, exec_time, category, text))
    item_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return item_id

def update_task_text(task_id, new_text):
    conn = sqlite3.connect("todo_pro.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE reminders SET message_text = ? WHERE id = ?", (new_text, task_id))
    conn.commit()
    conn.close()

def get_reminders(chat_id, status=0):
    conn = sqlite3.connect("todo_pro.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id, exec_time, category, message_text FROM reminders WHERE chat_id = ? AND is_done = ?", (chat_id, status))
    rows = cursor.fetchall()
    conn.close()
    return rows

def update_status(task_id, status=1):
    conn = sqlite3.connect("todo_pro.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE reminders SET is_done = ? WHERE id = ?", (status, task_id))
    conn.commit()
    conn.close()

def delete_task(task_id):
    conn = sqlite3.connect("todo_pro.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM reminders WHERE id = ?", (task_id,))
    conn.commit()
    conn.close()

def task_exists(task_id, chat_id):
    conn = sqlite3.connect("todo_pro.db")
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM reminders WHERE id = ? AND chat_id = ?", (task_id, chat_id))
    result = cursor.fetchone()
    conn.close()
    return result is not None

# --- ЛОГИКА БОТА ---

def create_main_keyboard():
    """Создает главную клавиатуру с кнопками"""
    builder = InlineKeyboardBuilder()
    builder.button(text="📝 Создать задачу", callback_data="create_task")
    builder.button(text="📋 Список задач", callback_data="list_tasks")
    builder.button(text="✏️ Редактировать", callback_data="edit_task")
    builder.button(text="🗑️ Удалить", callback_data="delete_task")
    builder.button(text="❓ Помощь", callback_data="help")
    builder.adjust(2, 2, 1)
    return builder.as_markup()

def create_examples_keyboard():
    """Создает клавиатуру с примерами"""
    builder = InlineKeyboardBuilder()
    builder.button(text="⏰ Ежедневное", callback_data="example_daily")
    builder.button(text="📅 По дням недели", callback_data="example_weekly")
    builder.button(text="🗓️ По числам", callback_data="example_monthly")
    builder.button(text="🔙 Назад", callback_data="back_main")
    builder.adjust(2, 2)
    return builder.as_markup()

def create_command_keyboard():
    """Создает клавиатуру с командами для вставки"""
    builder = InlineKeyboardBuilder()
    builder.button(text="📝 Создать задачу", callback_data="cmd_remind")
    builder.button(text="📋 Список задач", callback_data="cmd_list")
    builder.button(text="✏️ Редактировать", callback_data="cmd_edit")
    builder.button(text="🗑️ Удалить", callback_data="cmd_delete")
    builder.button(text="❓ Помощь", callback_data="cmd_help")
    builder.adjust(2, 2, 1)
    return builder.as_markup()

def create_daily_examples_keyboard():
    """Создает клавиатуру с примерами ежедневных команд"""
    builder = InlineKeyboardBuilder()
    builder.button(text="☕ Утренний кофе", callback_data="daily_coffee")
    builder.button(text="💼 Обед", callback_data="daily_lunch")
    builder.button(text="🌙 Время сна", callback_data="daily_sleep")
    builder.button(text="🔙 Назад", callback_data="create_task")
    builder.adjust(2, 2)
    return builder.as_markup()

def create_weekly_examples_keyboard():
    """Создает клавиатуру с примерами еженедельных команд"""
    builder = InlineKeyboardBuilder()
    builder.button(text="📅 Понедельник", callback_data="weekly_monday")
    builder.button(text="🏋️ Вторник", callback_data="weekly_tuesday")
    builder.button(text="🎬 Суббота", callback_data="weekly_saturday")
    builder.button(text="👨‍👩‍👧‍👦 Воскресенье", callback_data="weekly_sunday")
    builder.button(text="🔙 Назад", callback_data="create_task")
    builder.adjust(2, 2, 1)
    return builder.as_markup()

def create_monthly_examples_keyboard():
    """Создает клавиатуру с примерами ежемесячных команд"""
    builder = InlineKeyboardBuilder()
    builder.button(text="💰 Аренда", callback_data="monthly_rent")
    builder.button(text="💸 Зарплата", callback_data="monthly_salary")
    builder.button(text="🎂 День рождения", callback_data="monthly_birthday")
    builder.button(text="📊 Отчет", callback_data="monthly_report")
    builder.button(text="🔙 Назад", callback_data="create_task")
    builder.adjust(2, 2, 1)
    return builder.as_markup()

async def send_reminder_job(chat_id: int, category: str, text: str, task_id: int):
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Выполнено", callback_data=f"done_{task_id}")
    await bot.send_message(chat_id, f"🔔 **НАПОМИНАНИЕ [{category}]**\n{text}", reply_markup=builder.as_markup(), parse_mode="Markdown")

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    welcome_text = (
        "🎉 **Добро пожаловать в ToDoList Bot!**\n\n"
        "🤖 Ваш умный помощник для управления задачами\n\n"
        "💡 **Что я умею:**\n"
        "• Создавать напоминания на разное время\n"
        "• Отслеживать выполнение задач\n"
        "• Редактировать и удалять задачи\n"
        "• Присылать уведомления в нужное время\n\n"
        "🚀 **Нажмите на кнопку ниже чтобы начать!**\n\n"
        "💬 **Или используйте кнопки для быстрой вставки команд:**"
    )
    await message.answer(welcome_text, reply_markup=create_command_keyboard(), parse_mode="Markdown")

@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    help_text = (
        "📖 **Подробная инструкция**\n\n"
        "🕐 **Форматы времени:**\n"
        "• `15:30` - ежедневно в 15:30\n"
        "• `пн 10:00` - каждый понедельник в 10:00\n"
        "• `15 18:00` - 15-го числа каждого месяца в 18:00\n\n"
        "📝 **Создание задачи:**\n"
        "`/remind время категория текст задачи`\n\n"
        "🔧 **Другие команды:**\n"
        "• `/list` - показать все задачи\n"
        "• `/edit ID новый_текст` - изменить задачу\n"
        "• `/delete ID` - удалить задачу\n\n"
        "📅 **Дни недели:** пн, вт, ср, чт, пт, сб, вс\n"
        "🔢 **Числа месяца:** от 1 до 31\n\n"
        "💡 **Совет:** Используйте кнопки для удобства!"
    )
    await message.answer(help_text, reply_markup=create_command_keyboard(), parse_mode="Markdown")

def parse_time_input(time_input):
    """Парсит различные форматы времени и даты"""
    moscow_tz = pytz.timezone("Europe/Moscow")
    now = datetime.now(moscow_tz)
    
    # Формат: ЧЧ:ММ (ежедневное)
    if re.match(r'^\d{1,2}:\d{2}$', time_input):
        time_obj = datetime.strptime(time_input, "%H:%M").time()
        run_date = now.replace(hour=time_obj.hour, minute=time_obj.minute, second=0, microsecond=0)
        if run_date <= now:
            run_date = run_date + timedelta(days=1)
        return run_date, "ежедневно", time_input
    
    # Формат: день недели время (пн 15:00, вт 10:30 и т.д.)
    elif re.match(r'^(пн|вт|ср|чт|пт|сб|вс)\s+\d{1,2}:\d{2}$', time_input.lower()):
        day_map = {'пн': 0, 'вт': 1, 'ср': 2, 'чт': 3, 'пт': 4, 'сб': 5, 'вс': 6}
        parts = time_input.lower().split()
        day_name = parts[0]
        time_str = parts[1]
        
        time_obj = datetime.strptime(time_str, "%H:%M").time()
        target_weekday = day_map[day_name]
        
        # Находим следующую нужную дату
        days_ahead = (target_weekday - now.weekday()) % 7
        if days_ahead == 0:  # Если сегодня этот день
            run_date = now.replace(hour=time_obj.hour, minute=time_obj.minute, second=0, microsecond=0)
            if run_date <= now:
                days_ahead = 7  # Переносим на следующую неделю
        
        run_date = now + timedelta(days=days_ahead)
        run_date = run_date.replace(hour=time_obj.hour, minute=time_obj.minute, second=0, microsecond=0)
        
        return run_date, f"по {day_name}", time_input
    
    # Формат: число месяца время (15 18:00, 1 09:00 и т.д.)
    elif re.match(r'^\d{1,2}\s+\d{1,2}:\d{2}$', time_input):
        parts = time_input.split()
        day_num = int(parts[0])
        time_str = parts[1]
        
        if day_num < 1 or day_num > 31:
            raise ValueError("Число месяца должно быть от 1 до 31")
        
        time_obj = datetime.strptime(time_str, "%H:%M").time()
        
        # Пробуем текущий месяц
        try:
            run_date = now.replace(day=day_num, hour=time_obj.hour, minute=time_obj.minute, second=0, microsecond=0)
            if run_date <= now:
                # Если дата прошла, пробуем следующий месяц
                if now.month == 12:
                    run_date = run_date.replace(year=now.year + 1, month=1)
                else:
                    run_date = run_date.replace(month=now.month + 1)
        except ValueError:
            # Если в текущем месяце нет такого дня (например, 30 февраля)
            if now.month == 12:
                run_date = now.replace(year=now.year + 1, month=1, day=day_num, 
                                     hour=time_obj.hour, minute=time_obj.minute, second=0, microsecond=0)
            else:
                run_date = now.replace(month=now.month + 1, day=day_num, 
                                     hour=time_obj.hour, minute=time_obj.minute, second=0, microsecond=0)
        
        return run_date, f"{day_num} числа", time_input
    
    else:
        raise ValueError("Неверный формат времени. Используйте: ЧЧ:ММ, ДД ЧЧ:ММ или ДН ЧЧ:ММ")

@dp.message(Command("remind"))
async def cmd_remind(message: types.Message, command: CommandObject):
    try:
        if not command.args:
            return await message.answer("Формат: `/remind время категория текст`")
        
        # Разделяем аргументы
        args = command.args.split(" ", 2)
        if len(args) < 3:
            return await message.answer("Формат: `/remind время категория текст`")
        
        time_input, category, text = args
        
        # Парсим время
        run_date, schedule_type, display_time = parse_time_input(time_input)
        
        # Сохраняем в БД
        task_id = add_reminder(message.chat.id, display_time, category.upper(), text)
        
        # Добавляем в планировщик
        scheduler.add_job(
            send_reminder_job, 
            "date", 
            run_date=run_date, 
            args=[message.chat.id, category.upper(), text, task_id]
        )
        
        await message.answer(
            f"✅ Задача №{task_id} [{category.upper()}] создана\n"
            f"📅 {schedule_type} в {display_time}\n"
            f"📝 {text}"
        )
        
    except ValueError as e:
        await message.answer(f"❌ Ошибка формата: {str(e)}")
    except Exception as e:
        await message.answer(f"❌ Ошибка при создании задачи: {str(e)}")

@dp.message(Command("edit"))
async def cmd_edit(message: types.Message, command: CommandObject):
    try:
        if not command.args or len(command.args.split(" ", 1)) < 2:
            return await message.answer("Ошибка! Используй: `/edit ID новый_текст`")
            
        task_id_str, new_text = command.args.split(" ", 1)
        task_id = int(task_id_str)
        
        # Проверяем существование задачи
        if not task_exists(task_id, message.chat.id):
            return await message.answer(f"Задача №{task_id} не найдена!")
            
        update_task_text(task_id, new_text)
        await message.answer(f"✏️ Текст задачи №{task_id} изменен на: {new_text}")
    except ValueError:
        await message.answer("Ошибка! ID должен быть числом. Используйте: `/edit ID новый_текст`")
    except Exception as e:
        await message.answer(f"Ошибка при редактировании: {str(e)}")

@dp.message(Command("list"))
async def cmd_list(message: types.Message):
    try:
        tasks = get_reminders(message.chat.id, status=0)
        if not tasks: 
            return await message.answer("Активных задач нет.")
        
        res = "📋 **Твои задачи:**\n"
        for tid, ttime, tcat, ttext in tasks:
            res += f"🆔 `{tid}` | 🕒 {ttime} | 🏷 #{tcat}\n└ {ttext}\n\n"
        await message.answer(res, parse_mode="Markdown")
    except Exception as e:
        await message.answer(f"Ошибка при получении списка: {str(e)}")

@dp.callback_query(F.data == "create_task")
async def callback_create_task(callback: types.CallbackQuery):
    examples_text = (
        "📝 **Создание новой задачи**\n\n"
        "Выберите тип задачи или нажмите кнопку для быстрой вставки команды:\n\n"
        "💡 **Готовые команды - просто нажмите и отправьте!**"
    )
    await callback.message.edit_text(examples_text, reply_markup=create_examples_keyboard(), parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "example_daily")
async def callback_example_daily(callback: types.CallbackQuery):
    example_text = (
        "⏰ **Ежедневные напоминания**\n\n"
        "� **Нажмите на кнопку ниже - команда вставится автоматически!**\n\n"
        "� **Примеры ежедневных задач:**"
    )
    await callback.message.edit_text(example_text, reply_markup=create_daily_examples_keyboard(), parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "example_weekly")
async def callback_example_weekly(callback: types.CallbackQuery):
    example_text = (
        "📅 **Напоминания по дням недели**\n\n"
        "� **Нажмите на кнопку ниже - команда вставится автоматически!**\n\n"
        "� **Примеры еженедельных задач:**"
    )
    await callback.message.edit_text(example_text, reply_markup=create_weekly_examples_keyboard(), parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "example_monthly")
async def callback_example_monthly(callback: types.CallbackQuery):
    example_text = (
        "🗓️ **Напоминания по числам месяца**\n\n"
        "� **Нажмите на кнопку ниже - команда вставится автоматически!**\n\n"
    )
    await callback.message.edit_text(example_text, reply_markup=create_monthly_examples_keyboard(), parse_mode="Markdown")
    await callback.answer()

# Обработчики для кнопок с командами
@dp.callback_query(F.data.startswith("cmd_"))
async def callback_commands(callback: types.CallbackQuery):
    command = callback.data.replace("cmd_", "")
    
    if command == "remind":
        await callback.message.edit_text(
            "📝 **Создание задачи**\n\n"
            "💡 **Выберите тип задачи ниже:**",
            reply_markup=create_examples_keyboard(),
            parse_mode="Markdown"
        )
    elif command == "list":
        await callback.message.edit_text(
            "📋 **Список задач**\n\n"
            "💡 **Нажмите чтобы увидеть все задачи:**",
            reply_markup=InlineKeyboardBuilder().button(
                text="📋 Показать задачи", callback_data="send_cmd:/list"
            ).as_markup(),
            parse_mode="Markdown"
        )
    elif command == "edit":
        await callback.message.edit_text(
            "✏️ **Редактирование задачи**\n\n"
            "📝 **Формат:** `/edit ID новый_текст`\n\n"
            "💡 **Сначала посмотрите список задач!**",
            reply_markup=InlineKeyboardBuilder().button(
                text="📋 Список задач", callback_data="send_cmd:/list"
            ).as_markup(),
            parse_mode="Markdown"
        )
    elif command == "delete":
        await callback.message.edit_text(
            "🗑️ **Удаление задачи**\n\n"
            "📝 **Формат:** `/delete ID`\n\n"
            "💡 **Сначала посмотрите список задач!**",
            reply_markup=InlineKeyboardBuilder().button(
                text="📋 Список задач", callback_data="send_cmd:/list"
            ).as_markup(),
            parse_mode="Markdown"
        )
    elif command == "help":
        await callback.message.edit_text(
            "❓ **Помощь**\n\n"
            "💡 **Нажмите чтобы увидеть подробную инструкцию:**",
            reply_markup=InlineKeyboardBuilder().button(
                text="📖 Подробная помощь", callback_data="send_cmd:/help"
            ).as_markup(),
            parse_mode="Markdown"
        )
    
    await callback.answer()

# Обработчик для отправки команд
@dp.callback_query(F.data.startswith("send_cmd:"))
async def callback_send_command(callback: types.CallbackQuery):
    command = callback.data.replace("send_cmd:", "")
    
    # Отправляем команду от имени пользователя
    await bot.send_message(
        callback.message.chat.id,
        f"💡 **Команда готова к отправке:**\n\n`{command}`\n\n"
        f"✨ **Нажмите чтобы отправить или скопируйте:**",
        reply_markup=InlineKeyboardBuilder().button(
            text="📤 Отправить команду", callback_data=f"execute_cmd:{command}"
        ).as_markup(),
        parse_mode="Markdown"
    )
    await callback.answer()

# Обработчик для выполнения команд
@dp.callback_query(F.data.startswith("execute_cmd:"))
async def callback_execute_command(callback: types.CallbackQuery):
    command = callback.data.replace("execute_cmd:", "")
    
    # Создаем искусственное сообщение с командой
    message = types.Message(
        message_id=callback.message.message_id,
        date=callback.message.date,
        chat=callback.message.chat,
        from_user=callback.from_user,
        text=command,
        content_type="text"
    )
    
    # Обрабатываем команду
    if command.startswith("/remind"):
        # Создаем объект CommandObject
        args = command.replace("/remind ", "", 1)
        command_obj = CommandObject(prefix="/", command="remind", args=args)
        await cmd_remind(message, command_obj)
    elif command == "/list":
        await cmd_list(message)
    elif command.startswith("/help"):
        await cmd_help(message)
    
    await callback.answer()

@dp.callback_query(F.data == "list_tasks")
async def callback_list_tasks(callback: types.CallbackQuery):
    try:
        tasks = get_reminders(callback.message.chat.id, status=0)
        if not tasks:
            result_text = "📋 **У вас нет активных задач**\n\n💡 Создайте первую задачу с помощью кнопки ниже!"
        else:
            result_text = "📋 **Ваши активные задачи:**\n\n"
            for tid, ttime, tcat, ttext in tasks:
                result_text += f"🆔 `{tid}` | 🕒 {ttime} | 🏷 #{tcat}\n└ {ttext}\n\n"
        
        await callback.message.edit_text(result_text, reply_markup=create_command_keyboard(), parse_mode="Markdown")
        await callback.answer()
    except Exception as e:
        await callback.message.edit_text(f"❌ Ошибка: {str(e)}", reply_markup=create_command_keyboard())
        await callback.answer()

@dp.callback_query(F.data == "edit_task")
async def callback_edit_task(callback: types.CallbackQuery):
    edit_text = (
        "✏️ **Редактирование задачи**\n\n"
        "📝 **Формат:** `/edit ID новый_текст`\n\n"
        "🔍 **Сначала посмотрите список задач**, чтобы узнать ID\n\n"
        "💡 **Пример:** `/edit 3 Новое описание задачи`"
    )
    await callback.message.edit_text(edit_text, reply_markup=create_main_keyboard(), parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "delete_task")
async def callback_delete_task(callback: types.CallbackQuery):
    delete_text = (
        "🗑️ **Удаление задачи**\n\n"
        "📝 **Формат:** `/delete ID`\n\n"
        "🔍 **Сначала посмотрите список задач**, чтобы узнать ID\n\n"
        "💡 **Пример:** `/delete 3`\n\n"
        "⚠️ **Внимание:** удаление необратимо!"
    )
    await callback.message.edit_text(delete_text, reply_markup=create_main_keyboard(), parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "help")
async def callback_help(callback: types.CallbackQuery):
    help_text = (
        "❓ **Помощь и инструкция**\n\n"
        "🤖 **Я ваш персональный помощник для задач!**\n\n"
        "🎯 **Основные возможности:**\n"
        "• 📝 Создавать напоминания\n"
        "• 📋 Просматривать список задач\n"
        "• ✏️ Редактировать текст задач\n"
        "• 🗑️ Удалять ненужные задачи\n"
        "• 🔔 Получать уведомления\n\n"
        "📖 **Подробная инструкция:** /help\n"
        "🔄 **Главное меню:** нажмите кнопку ниже"
    )
    await callback.message.edit_text(help_text, reply_markup=create_main_keyboard(), parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data == "back_main")
async def callback_back_main(callback: types.CallbackQuery):
    main_text = (
        "🎉 **Главное меню**\n\n"
        "🚀 **Выберите действие:**"
    )
    await callback.message.edit_text(main_text, reply_markup=create_main_keyboard(), parse_mode="Markdown")
    await callback.answer()

@dp.callback_query(F.data.startswith("done_"))
async def callbacks_done(callback: types.CallbackQuery):
    try:
        task_id = int(callback.data.split("_")[1])
        update_status(task_id, status=1)
        await callback.message.edit_text(
            f"✅ Задача №{task_id} выполнена!\n\n"
            "🔄 Вернуться в главное меню:",
            reply_markup=create_main_keyboard(),
            parse_mode="Markdown"
        )
        await callback.answer()
    except ValueError:
        await callback.message.edit_text("❌ Ошибка: неверный ID задачи", reply_markup=create_main_keyboard())
        await callback.answer()
    except Exception as e:
        await callback.message.edit_text(f"❌ Ошибка: {str(e)}", reply_markup=create_main_keyboard())
        await callback.answer()

@dp.message(Command("delete"))
async def cmd_delete(message: types.Message, command: CommandObject):
    try:
        if not command.args:
            return await message.answer("Ошибка! Используй: `/delete ID`")
            
        task_id = int(command.args.strip())
        
        # Проверяем существование задачи
        if not task_exists(task_id, message.chat.id):
            return await message.answer(f"Задача №{task_id} не найдена!")
            
        delete_task(task_id)
        await message.answer(f"🗑️ Задача №{task_id} удалена!")
    except ValueError:
        await message.answer("Ошибка! ID должен быть числом. Используйте: `/delete ID`")
    except Exception as e:
        await message.answer(f"Ошибка при удалении: {str(e)}")

async def main():
    init_db()
    scheduler.start()
    
    # Очистка вебхуков перед запуском
    await bot.delete_webhook(drop_pending_updates=True)
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())