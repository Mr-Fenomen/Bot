import telebot
from telebot import types
from docx import Document
import math
import time
import pandas as pd

TOKEN = "8217368325:AAHl5khixxhe-nwWLFv49on9mi76If5BuQk"
bot = telebot.TeleBot(TOKEN)

# Активные данные
tests = {}          # {chat_id: {"packages": [...]} }
user_data = {}      # {chat_id: {user_id: {"score": int, "index": int, "pkg": int}}}
leaderboard = {}    # {chat_id: {user_id: score}}

# ================== Парсер Word ==================
def parse_docx_custom(filename):
    doc = Document(filename)
    text = "\n".join(p.text.strip() for p in doc.paragraphs if p.text.strip())
    blocks = text.split("++++++")
    questions = []

    for b in blocks:
        lines = [line.strip() for line in b.split("======") if line.strip()]
        if len(lines) < 2:
            continue
        question = lines[0]
        options = []
        correct = None
        for opt in lines[1:]:
            if opt.startswith("#"):
                correct = opt.replace("#", "").strip()
                options.append(correct)
            else:
                options.append(opt)
        if correct:
            questions.append((question, options, correct))
    return questions

# ================== Разделение на пакеты ==================
def split_packages(questions):
    n = math.ceil(len(questions) / 25)
    packages = [questions[i*25:(i+1)*25] for i in range(n)]
    if len(packages[-1]) < 25:
        need = 25 - len(packages[-1])
        packages[-1].extend(questions[:need])
    return packages

# ================== Команды ==================
@bot.message_handler(commands=['start'])
def start(message):
    bot.reply_to(message, "👋 Привет! Отправь файл .docx с тестами в формате с '++++++' и '======'. После этого я создам тесты.")

@bot.message_handler(content_types=['document'])
def handle_doc(message):
    chat_id = message.chat.id
    file_info = bot.get_file(message.document.file_id)
    file_data = bot.download_file(file_info.file_path)
    filename = message.document.file_name
    with open(filename, 'wb') as f:
        f.write(file_data)

    bot.reply_to(message, "📄 Файл получен, обрабатываю...")
    try:
        questions = parse_docx_custom(filename)
        if not questions:
            bot.reply_to(message, "❌ Не удалось найти вопросы.")
            return
        packages = split_packages(questions)
        tests[chat_id] = {"packages": packages}
        bot.reply_to(message, f"✅ Найдено {len(questions)} вопросов.\n📦 Разбито на {len(packages)} пакетов по 25 тестов.")
        show_package_menu(chat_id)
    except Exception as e:
        bot.reply_to(message, f"Ошибка: {e}")

def show_package_menu(chat_id):
    markup = types.InlineKeyboardMarkup()
    for i in range(len(tests[chat_id]["packages"])):
        markup.add(types.InlineKeyboardButton(f"📘 Пакет {i+1}", callback_data=f"pkg_{i}"))
    bot.send_message(chat_id, "Выбери пакет для прохождения теста:", reply_markup=markup)

# ================== Начало теста ==================
def start_test(chat_id, user_id, pkg_index):
    if chat_id not in tests:
        bot.send_message(chat_id, "❌ Сначала отправь файл.")
        return
    user_data.setdefault(chat_id, {})[user_id] = {"score": 0, "index": 0, "pkg": pkg_index, "start": time.time()}
    send_question(chat_id, user_id)

def send_question(chat_id, user_id):
    pkg_index = user_data[chat_id][user_id]["pkg"]
    pkg = tests[chat_id]["packages"][pkg_index]
    idx = user_data[chat_id][user_id]["index"]

    if idx >= len(pkg):
        finish_test(chat_id, user_id)
        return

    q, opts, correct = pkg[idx]
    markup = types.InlineKeyboardMarkup()
    for opt in opts:
        markup.add(types.InlineKeyboardButton(opt, callback_data=f"{user_id}:{opt}:{correct}"))

    bot.send_message(chat_id, f"❓ *{q}*", parse_mode="Markdown", reply_markup=markup)

# ================== Проверка ответа ==================
@bot.callback_query_handler(func=lambda call: True)
def handle_callback(call):
    data = call.data
    chat_id = call.message.chat.id

    if data.startswith("pkg_"):
        pkg_index = int(data.split("_")[1])
        start_test(chat_id, call.from_user.id, pkg_index)
        bot.answer_callback_query(call.id, f"Пакет {pkg_index+1} выбран ✅")
        return

    try:
        user_id, answer, correct = data.split(":")
        user_id = int(user_id)

        if call.from_user.id != user_id:
            bot.answer_callback_query(call.id, "❌ Это не твой вопрос.")
            return

        udata = user_data[chat_id][user_id]
        if answer.strip() == correct.strip():
            udata["score"] += 1
            bot.answer_callback_query(call.id, "✅ Верно!")
        else:
            bot.answer_callback_query(call.id, f"❌ Неверно. Правильный ответ: {correct}")

        udata["index"] += 1
        send_question(chat_id, user_id)
    except Exception as e:
        bot.answer_callback_query(call.id, f"Ошибка: {e}")

# ================== Завершение теста ==================
def finish_test(chat_id, user_id):
    udata = user_data[chat_id][user_id]
    total = udata["index"]
    score = udata["score"]
    duration = round(time.time() - udata["start"])
    username = bot.get_chat_member(chat_id, user_id).user.first_name

    leaderboard.setdefault(chat_id, {})[username] = score
    bot.send_message(chat_id,
        f"🏁 {username} закончил тест!\n"
        f"✅ Правильных ответов: {score}/{total}\n"
        f"⏱ Время: {duration} сек.")

    show_leaderboard(chat_id)

# ================== Таблица лидеров ==================
def show_leaderboard(chat_id):
    if chat_id not in leaderboard or not leaderboard[chat_id]:
        bot.send_message(chat_id, "Пока нет результатов.")
        return
    table = sorted(leaderboard[chat_id].items(), key=lambda x: x[1], reverse=True)
    text = "🏆 *Таблица лидеров:*\n\n"
    for i, (name, score) in enumerate(table, start=1):
        text += f"{i}. {name} — {score} баллов\n"
    bot.send_message(chat_id, text, parse_mode="Markdown")