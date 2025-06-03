import telebot
from telebot import types
from models import get_db, DailyReport, Plan, EmotionalReport, Recommendation, PlanItem, PlanItemType, PlanItemStatus # Добавлены PlanItem, PlanItemType, PlanItemStatus, Recommendation
from sqlalchemy.orm import Session
from sqlalchemy import desc
from datetime import datetime, date
import config
import g4f
import random

# Инициализация бота
bot = telebot.TeleBot(config.TELEGRAM_BOT_TOKEN)

# Словари для хранения данных от пользователя в процессе заполнения
user_data = {}
plan_data = {}
emotional_data = {}
view_data = {}

# Состояния для каждого пользователя
user_state = {}
plan_state = {}
emotional_state = {}
view_state = {}

# Определение состояний
(
    ENERGY_LEVEL, ENERGY_BOOSTERS, TOP_TASKS, LESSON, GRATITUDE, NEGATIVE_EVENTS, REPORT_DONE,
    PLAN_MAIN_GOALS, PLAN_PLEASURE_MEANING, PLAN_OBSTACLE_STRATEGY,
    PLAN_ADDITIONAL_1, PLAN_ADDITIONAL_2, # Эти переменные не используются в коде ниже, но оставлены для полноты diff
    PLAN_DONE,
    EMOTION_SITUATION, EMOTION_THOUGHT, EMOTION_FEELINGS, 
    EMOTION_CORRECTION_CHOICE, EMOTION_CORRECTION_CUSTOM, EMOTION_NEW_FEELINGS, EMOTION_IMPACT,
    WAITING_FOR_EMOTIONAL_ACTION, EMOTIONAL_DONE, 
    VIEW_DATE
) = map(chr, range(65, 65 + 23)) # Увеличено на 3 для новых состояний эмоций

def get_user_id(message):
    return message.from_user.id

# Список дополнительных вопросов с их ключами для plan_data
ADDITIONAL_PLAN_QUESTIONS = {
    "long_term_benefit": "Какое одно действие, совершенное сегодня, принесет наибольшую пользу в долгосрочной перспективе?",
    "strengths_utilization": "Как вы можете использовать свои сильные стороны для достижения завтрашних целей?",
    "new_skill_application": "Какой новый полезный навык или знание вы хотели бы применить завтра?",
    "self_care_time": "Как вы можете сегодня уделить время заботе о себе (физически или эмоционально)?",
    "ideal_day_first_step": "Если бы сегодняшний день был идеальным, как бы он выглядел? Какое первое небольшое действие вы можете предпринять, чтобы приблизиться к этому идеалу?"
}

# Подсказки для коррекции в эмоциональном отчете
CORRECTION_HINTS = {
    "reframe": "Переосмыслить ситуацию с другой точки зрения.",
    "breathing": "Сделать несколько глубоких вдохов и выдохов.",
    "strengths": "Напомнить себе о своих сильных сторонах.",
    "friend_advice": "Спросить себя: что бы я посоветовал другу в такой ситуации?",
    "pause": "Сделать короткую паузу, сменить обстановку.",
    "self_compassion": "Проявить к себе сострадание и понимание."
}

# Выбираем случайные дополнительные вопросы
def get_random_additional_questions():
    return random.sample(list(ADDITIONAL_PLAN_QUESTIONS.items()), 2)

# Обработчик команды /start
@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "Привет! Доступные команды:\n/report - Ежедневный отчет\n/plan - План на день\n/emotional - Запись эмоц. события\n/recommends - Быстрые рекомендации\n/weekly_recommends - Еженедельный обзор\n/monthly_recommends - Ежемесячный обзор\n/view - Просмотр данных за дату")

# Обработчики для /report
@bot.message_handler(commands=['report'])
def start_report(message):
    user_id = get_user_id(message)
    user_data[user_id] = {}
    user_state[user_id] = ENERGY_LEVEL
    bot.send_message(user_id, "Оцените ваш уровень энергии сегодня (1-10):")

@bot.message_handler(func=lambda message: user_state.get(get_user_id(message)) == ENERGY_LEVEL)
def process_energy_level(message):
    user_id = get_user_id(message)
    if message.text.isdigit() and 1 <= int(message.text) <= 10:
        user_data[user_id]['energy_level'] = int(message.text)
        user_state[user_id] = ENERGY_BOOSTERS
        bot.send_message(user_id, "Что сегодня дало вам энергию?")
    else:
        bot.reply_to(message, "Пожалуйста, введите число от 1 до 10.")

@bot.message_handler(func=lambda message: user_state.get(get_user_id(message)) == ENERGY_BOOSTERS)
def process_energy_boosters(message):
    user_id = get_user_id(message)
    user_data[user_id]['energy_boosters'] = message.text
    user_state[user_id] = TOP_TASKS
    bot.send_message(user_id, "Какое главное достижение дня?")

@bot.message_handler(func=lambda message: user_state.get(get_user_id(message)) == TOP_TASKS)
def process_top_tasks(message):
    user_id = get_user_id(message)
    user_data[user_id]['top_achievement'] = message.text
    user_state[user_id] = LESSON
    bot.send_message(user_id, "Что вы узнали сегодня?")

@bot.message_handler(func=lambda message: user_state.get(get_user_id(message)) == LESSON)
def process_lesson(message):
    user_id = get_user_id(message)
    user_data[user_id]['lesson_learned'] = message.text
    user_state[user_id] = GRATITUDE
    bot.send_message(user_id, "Напишите три благодарности!")

@bot.message_handler(func=lambda message: user_state.get(get_user_id(message)) == GRATITUDE)
def process_gratitude(message):
    user_id = get_user_id(message)
    user_data[user_id]['gratitude_items'] = message.text
    user_state[user_id] = NEGATIVE_EVENTS
    bot.send_message(user_id, "Опишите три трудности или негативных события.")

@bot.message_handler(func=lambda message: user_state.get(get_user_id(message)) == NEGATIVE_EVENTS)
def process_negative_events(message):
    user_id = get_user_id(message)
    user_data[user_id]['negative_events'] = message.text
    user_state[user_id] = REPORT_DONE
    # Автоматическое сохранение отчета
    try:
        db = next(get_db())
        daily_report = DailyReport(
            user_id=user_id,
            date=datetime.utcnow().date(),
            energy_level=user_data[user_id].get('energy_level'),
            energy_boosters=user_data[user_id].get('energy_boosters'),
            top_achievement=user_data[user_id].get('top_achievement'),
            lesson_learned=user_data[user_id].get('lesson_learned'),
            gratitude_items=user_data[user_id].get('gratitude_items'),
            negative_events=user_data[user_id].get('negative_events')
        )
        db.add(daily_report)
        db.commit()
        bot.send_message(user_id, "Ежедневный отчет сохранен.\nНажмите /start для новых действий.")
    except Exception as e:
        bot.send_message(user_id, f"Произошла ошибка при сохранении отчета: {e}\nНажмите /start для новых действий.")
    finally:
        if 'db' in locals():
            db.close()
        del user_data[user_id]
        del user_state[user_id]

# Обработчики для /plan
@bot.message_handler(commands=['plan'])
def start_plan(message):
    user_id = get_user_id(message)
    plan_data[user_id] = {}
    plan_data[user_id]['additional_questions'] = get_random_additional_questions() # Сохраняем выбранные вопросы с ключами
    plan_state[user_id] = PLAN_MAIN_GOALS
    bot.send_message(user_id, "Каковы ваши главные цели/задачи на сегодня, которые действительно важны для вас?")

@bot.message_handler(func=lambda message: plan_state.get(get_user_id(message)) == PLAN_MAIN_GOALS)
def process_plan_main_goals(message):
    user_id = get_user_id(message)
    plan_data[user_id]['main_goals'] = message.text
    plan_state[user_id] = PLAN_PLEASURE_MEANING
    bot.send_message(user_id, "Как вы можете сделать сегодняшний день более приятным и наполненным смыслом? Какое небольшое действие вы можете запланировать для этого?")

@bot.message_handler(func=lambda message: plan_state.get(get_user_id(message)) == PLAN_PLEASURE_MEANING)
def process_plan_pleasure_meaning(message):
    user_id = get_user_id(message)
    plan_data[user_id]['pleasure_meaning'] = message.text
    plan_state[user_id] = PLAN_OBSTACLE_STRATEGY
    bot.send_message(user_id, "Предвидя возможные отвлекающие факторы или периоды низкой мотивации, какой конкретный и простой шаг вы предпримете, чтобы вернуться к своим планам?")

@bot.message_handler(func=lambda message: plan_state.get(get_user_id(message)) == PLAN_OBSTACLE_STRATEGY)
def process_plan_obstacle_strategy(message):
    user_id = get_user_id(message)
    plan_data[user_id]['obstacle_strategy'] = message.text
    additional_questions = plan_data[user_id]['additional_questions']
    if additional_questions:
        plan_state[user_id] = PLAN_ADDITIONAL_1
        plan_data[user_id]['current_additional_key'] = additional_questions[0][0]
        bot.send_message(user_id, additional_questions[0][1]) # Убедитесь, что берем [0][1]
    else:
        plan_state[user_id] = PLAN_DONE
        save_plan_data(message)

@bot.message_handler(func=lambda message: plan_state.get(get_user_id(message)) == PLAN_ADDITIONAL_1)
def process_plan_additional_1(message):
    user_id = get_user_id(message)
    current_key = plan_data[user_id].get('current_additional_key')
    if current_key:
        plan_data[user_id][current_key] = message.text
    additional_questions = plan_data[user_id]['additional_questions']
    if len(additional_questions) > 1:
        plan_state[user_id] = PLAN_ADDITIONAL_2
        plan_data[user_id]['current_additional_key'] = additional_questions[1][0]
        bot.send_message(user_id, additional_questions[1][1]) # Убедитесь, что берем [1][1]
    else:
        plan_state[user_id] = PLAN_DONE
        save_plan_data(message)

@bot.message_handler(func=lambda message: plan_state.get(get_user_id(message)) == PLAN_ADDITIONAL_2)
def process_plan_additional_2(message):
    user_id = get_user_id(message)
    current_key = plan_data[user_id].get('current_additional_key')
    if current_key:
        plan_data[user_id][current_key] = message.text
    plan_state[user_id] = PLAN_DONE
    save_plan_data(message)

def save_plan_data(message):
    user_id = get_user_id(message)
    try:
        db = next(get_db())
        current_plan_data = plan_data[user_id]
        
        # Format main_goals similar to web_app.py
        # Assuming user might enter comma-separated or newline-separated goals
        raw_main_goals = current_plan_data.get('main_goals', '')
        if raw_main_goals:
            goal_texts = [goal.strip() for goal in raw_main_goals.replace(',', '\n').split('\n') if goal.strip()]
            main_goals_json = json.dumps([{"text": goal} for goal in goal_texts])
        else:
            main_goals_json = json.dumps([])

        # Map bot's plan_data keys to Plan model fields
        # The bot asks 5 questions: main_goals, pleasure_meaning, obstacle_strategy, and 2 random.
        # Plan model has main_goals + 5 morning_qX fields.
        # We map them sequentially. morning_q6_health_care might be left null by the bot.
        plan = Plan(
            user_id=user_id,
            date=datetime.utcnow().date(),
            main_goals=main_goals_json,
            morning_q2_improve_day=current_plan_data.get('pleasure_meaning'),
            morning_q3_mindset=current_plan_data.get('obstacle_strategy'),
            # The 'additional_questions' list stores tuples of (key, question_text)
            # We need to get the value associated with the key of the first random question
            morning_q4_help_others=current_plan_data.get(current_plan_data['additional_questions'][0][0]) if len(current_plan_data.get('additional_questions', [])) > 0 else None,
            # And the second random question
            morning_q5_inspiration=current_plan_data.get(current_plan_data['additional_questions'][1][0]) if len(current_plan_data.get('additional_questions', [])) > 1 else None
            # morning_q6_health_care will be null if not explicitly set
        )
        db.add(plan)
        db.commit()
        bot.send_message(user_id, "План на сегодня сохранен.\nНажмите /start для новых действий.")
    except Exception as e:
        bot.send_message(user_id, f"Произошла ошибка при сохранении плана: {e}\nНажмите /start для новых действий.")
    finally:
        if 'db' in locals():
            db.close()
        del plan_data[user_id]
        del plan_state[user_id]

# Обработчик команды /emotional
@bot.message_handler(commands=['emotional'])
def start_emotional_report(message):
    user_id = get_user_id(message)
    emotional_data[user_id] = []
    emotional_data[user_id].append({})
    emotional_state[user_id] = EMOTION_SITUATION
    bot.send_message(user_id, f"Событие 1:\nСитуация: Краткое описание произошедшего.")

@bot.message_handler(func=lambda message: emotional_state.get(get_user_id(message)) == EMOTION_SITUATION)
def process_emotion_situation(message):
    user_id = get_user_id(message)
    current_event_index = len(emotional_data[user_id]) - 1
    emotional_data[user_id][current_event_index]['situation'] = message.text
    emotional_state[user_id] = EMOTION_THOUGHT
    bot.send_message(user_id, "Мысль: Какие мысли были в тот момент?")

@bot.message_handler(func=lambda message: emotional_state.get(get_user_id(message)) == EMOTION_THOUGHT)
def process_emotion_thought(message):
    user_id = get_user_id(message)
    current_event_index = len(emotional_data[user_id]) - 1
    emotional_data[user_id][current_event_index]['thought'] = message.text
    emotional_state[user_id] = EMOTION_FEELINGS
    bot.send_message(user_id, "Чувства: Какие эмоции и физические ощущения вы испытали?")

@bot.message_handler(func=lambda message: emotional_state.get(get_user_id(message)) == EMOTION_FEELINGS)
def process_emotion_feelings(message):
    user_id = get_user_id(message)
    current_event_index = len(emotional_data[user_id]) - 1
    emotional_data[user_id][current_event_index]['feelings'] = message.text
    emotional_state[user_id] = EMOTION_CORRECTION_CHOICE

    markup = types.InlineKeyboardMarkup()
    for key, text in CORRECTION_HINTS.items():
        markup.add(types.InlineKeyboardButton(text, callback_data=f"hint_{key}"))
    markup.add(types.InlineKeyboardButton("Написать свой вариант", callback_data="custom_correction"))
    markup.add(types.InlineKeyboardButton("Пропустить коррекцию", callback_data="skip_correction"))
    bot.send_message(user_id, "Коррекция: Какую коррекцию мысли или поведения вы применили или могли бы применить? Выберите подсказку, напишите свой вариант или пропустите:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('hint_') and emotional_state.get(get_user_id(call.message)) == EMOTION_CORRECTION_CHOICE)
def process_correction_hint(call):
    user_id = get_user_id(call.message)
    hint_key = call.data.split('_')[1]
    hint_text = CORRECTION_HINTS[hint_key]
    
    current_event_index = len(emotional_data[user_id]) - 1
    emotional_data[user_id][current_event_index]['correction'] = hint_text
    emotional_data[user_id][current_event_index]['correction_hint_used'] = hint_key
    
    bot.edit_message_text(chat_id=user_id, message_id=call.message.message_id, text=f"Выбрана коррекция: {hint_text}")
    emotional_state[user_id] = EMOTION_NEW_FEELINGS
    bot.send_message(user_id, "Новые чувства: Какие новые чувства или изменения в состоянии вы заметили после коррекции?")

@bot.callback_query_handler(func=lambda call: call.data == 'custom_correction' and emotional_state.get(get_user_id(call.message)) == EMOTION_CORRECTION_CHOICE)
def process_custom_correction_choice(call):
    user_id = get_user_id(call.message)
    bot.edit_message_text(chat_id=user_id, message_id=call.message.message_id, text="Коррекция: Напишите свой вариант коррекции.")
    emotional_state[user_id] = EMOTION_CORRECTION_CUSTOM

@bot.callback_query_handler(func=lambda call: call.data == 'skip_correction' and emotional_state.get(get_user_id(call.message)) == EMOTION_CORRECTION_CHOICE)
def process_skip_correction(call):
    user_id = get_user_id(call.message)
    current_event_index = len(emotional_data[user_id]) - 1
    emotional_data[user_id][current_event_index]['correction'] = None
    emotional_data[user_id][current_event_index]['correction_hint_used'] = None
    bot.edit_message_text(chat_id=user_id, message_id=call.message.message_id, text="Коррекция пропущена.")
    emotional_state[user_id] = EMOTION_NEW_FEELINGS # Сразу к новым чувствам, т.к. коррекции не было
    bot.send_message(user_id, "Новые чувства: Какие новые чувства или изменения в состоянии вы заметили (если были)? Если коррекции не было, можете описать текущее состояние или нажать 'Пропустить'.") # Уточнил вопрос

@bot.message_handler(func=lambda message: emotional_state.get(get_user_id(message)) == EMOTION_CORRECTION_CUSTOM)
def process_emotion_correction_custom_text(message):
    user_id = get_user_id(message)
    current_event_index = len(emotional_data[user_id]) - 1
    emotional_data[user_id][current_event_index]['correction'] = message.text
    emotional_data[user_id][current_event_index]['correction_hint_used'] = "custom"
    emotional_state[user_id] = EMOTION_NEW_FEELINGS
    bot.send_message(user_id, "Новые чувства: Какие новые чувства или изменения в состоянии вы заметили после коррекции?")

@bot.message_handler(func=lambda message: emotional_state.get(get_user_id(message)) == EMOTION_NEW_FEELINGS)
def process_emotion_new_feelings(message):
    user_id = get_user_id(message)
    current_event_index = len(emotional_data[user_id]) - 1
    # Если пользователь нажал "Пропустить" на предыдущем шаге, он может написать "Пропустить" и здесь
    if message.text.lower() == "пропустить" and emotional_data[user_id][current_event_index].get('correction') is None:
        emotional_data[user_id][current_event_index]['new_feelings'] = None
    else:
        emotional_data[user_id][current_event_index]['new_feelings'] = message.text
    emotional_state[user_id] = EMOTION_IMPACT
    bot.send_message(user_id, "Итог: Как это событие повлияло на вас или ваше поведение? Чему научило?")

@bot.message_handler(func=lambda message: emotional_state.get(get_user_id(message)) == EMOTION_IMPACT)
def process_emotion_impact(message):
    user_id = get_user_id(message)
    current_event_index = len(emotional_data[user_id]) - 1
    emotional_data[user_id][current_event_index]['impact'] = message.text
    emotional_state[user_id] = WAITING_FOR_EMOTIONAL_ACTION

    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, one_time_keyboard=True)
    markup.add(types.KeyboardButton("Добавить еще событие"))
    markup.add(types.KeyboardButton("Завершить отчет об эмоциях"))
    bot.send_message(user_id, "Событие зафиксировано. Хотите добавить еще одно или завершить отчет?", reply_markup=markup)

@bot.message_handler(func=lambda message: emotional_state.get(get_user_id(message)) == WAITING_FOR_EMOTIONAL_ACTION, regexp="Завершить отчет об эмоциях")
def finish_emotional_report(message):
    user_id = get_user_id(message)
    emotional_state[user_id] = EMOTIONAL_DONE
    bot.send_message(user_id, "Отчет об эмоциональных спадах завершен. Нажмите /save_emotional чтобы сохранить.")

@bot.message_handler(func=lambda message: emotional_state.get(get_user_id(message)) == WAITING_FOR_EMOTIONAL_ACTION, regexp="Добавить еще событие")
def add_another_emotional_event(message):
    user_id = get_user_id(message)
    emotional_data[user_id].append({}) # Добавляем новый пустой словарь для следующего события
    emotional_state[user_id] = EMOTION_SITUATION
    bot.send_message(user_id, f"Событие {len(emotional_data[user_id])}:\nСитуация: Краткое описание произошедшего.")

@bot.message_handler(commands=['save_emotional'], func=lambda message: emotional_state.get(get_user_id(message)) == EMOTIONAL_DONE)
def save_emotional_report(message):
    user_id = get_user_id(message)
    emotional_events = emotional_data.get(user_id)
    if emotional_events:
        try:
            db = next(get_db())
            for event in emotional_events:
                emotional_report = EmotionalReport(
                    user_id=user_id,
                    date=datetime.utcnow().date(),
                    situation=event.get('situation'),
                    thought=event.get('thought'),
                    feelings=event.get('feelings'),
                    correction=event.get('correction'),
                    correction_hint_used=event.get('correction_hint_used'),
                    new_feelings=event.get('new_feelings'),
                    impact=event.get('impact'),
                )
                db.add(emotional_report)
            db.commit()
            bot.send_message(user_id, "Ваш отчет об эмоциональных спадах сохранен.\nНажмите /start для новых действий.")
        except Exception as e:
            bot.send_message(user_id, f"Произошла ошибка при сохранении эмоционального отчета: {e}\nНажмите /start для новых действий.")
        finally:
            if 'db' in locals():
                db.close()
        del emotional_data[user_id]
        del emotional_state[user_id]
    else:
        bot.send_message(user_id, "Нет данных для сохранения эмоционального отчета. Пожалуйста, сначала заполните отчет командой /emotional.\nНажмите /start для новых действий.")

@bot.message_handler(commands=['recommends'])
def get_recommendations(message):
    user_id = get_user_id(message)
    bot.send_chat_action(user_id, 'typing')  # Показываем, что бот печатает

    try:
        db = next(get_db())
        # Получаем самые свежие данные пользователя
        latest_report = db.query(DailyReport).filter(DailyReport.user_id == user_id).order_by(desc(DailyReport.date)).first()
        latest_plan = db.query(Plan).filter(Plan.user_id == user_id).order_by(desc(Plan.date)).first()
        latest_emotional = db.query(EmotionalReport).filter(EmotionalReport.user_id == user_id).order_by(desc(EmotionalReport.date)).first()
        # Получаем данные из PlanItem
        plan_items = db.query(PlanItem).filter(PlanItem.user_id == user_id).order_by(PlanItem.item_type, desc(PlanItem.created_at)).all()
        prompt = "Проанализируй мои стратегические цели и последние записи. Твоя задача - дать мне два структурированных совета. Отвечай на русском языке.\n\n"

        if plan_items:
            prompt += "**Мои стратегические цели и задачи (из Планировщика):**\n"
            missions = [pi for pi in plan_items if pi.item_type == PlanItemType.MISSION]
            projects = [pi for pi in plan_items if pi.item_type == PlanItemType.PROJECT and pi.status != PlanItemStatus.DONE and pi.status != PlanItemStatus.CANCELLED]
            goals = [pi for pi in plan_items if pi.item_type == PlanItemType.GOAL and pi.status != PlanItemStatus.DONE and pi.status != PlanItemStatus.CANCELLED]
            tasks = [pi for pi in plan_items if pi.item_type == PlanItemType.TASK and pi.status in (PlanItemStatus.TODO, PlanItemStatus.IN_PROGRESS)]

            if missions:
                prompt += "  Миссии:\n"
                for item in missions[:2]: prompt += f"    - {item.name}\n"
            if projects:
                prompt += "  Активные проекты:\n"
                for item in projects[:3]: prompt += f"    - {item.name} (Статус: {item.status.value if item.status else 'Не указан'})\n"
            if goals:
                prompt += "  Ключевые цели:\n"
                for item in goals[:3]: prompt += f"    - {item.name} (Статус: {item.status.value if item.status else 'Не указан'})\n"
            if tasks:
                prompt += "  Задачи в фокусе:\n"
                for item in tasks[:3]: prompt += f"    - {item.name} (Статус: {item.status.value if item.status else 'Не указан'})\n"
            prompt += "---\n"
        else:
            prompt += "Нет данных из долгосрочного планировщика.\n---\n"

        if latest_report:
            prompt += f"**Отчет за {latest_report.date}:**\n"
            prompt += f"Уровень энергии: {latest_report.energy_level}\n"
            prompt += f"Что дало энергию: {latest_report.energy_boosters}\n"
            prompt += f"Главное достижение: {latest_report.top_achievement}\n"
            prompt += f"Узнал: {latest_report.lesson_learned}\n"
            prompt += f"Благодарности: {latest_report.gratitude_items}\n"
            prompt += f"Трудности: {latest_report.negative_events}\n"
            if latest_report.tomorrow_better:
                prompt += f"Планы на завтра: {latest_report.tomorrow_better}\n"
            prompt += "---\n"
        else:
            prompt += "Нет свежего ежедневного отчета.\n"

        if latest_plan:
            prompt += f"**План на день ({latest_plan.date}):**\n"
            if latest_plan.main_goals:
                prompt += f"Главные цели: {latest_plan.main_goals}\n"
            if latest_plan.pleasure_meaning:
                prompt += f"Приятное и значимое действие: {latest_plan.pleasure_meaning}\n"
            if latest_plan.obstacle_strategy:
                prompt += f"Стратегия против препятствий: {latest_plan.obstacle_strategy}\n"
            if latest_plan.long_term_benefit:
                prompt += f"Долгосрочная выгода: {latest_plan.long_term_benefit}\n"
            if latest_plan.strengths_utilization:
                prompt += f"Использование сильных сторон: {latest_plan.strengths_utilization}\n"
            if latest_plan.new_skill_application:
                prompt += f"Применение нового навыка: {latest_plan.new_skill_application}\n"
            if latest_plan.self_care_time:
                prompt += f"Время для заботы о себе: {latest_plan.self_care_time}\n"
            if latest_plan.ideal_day_first_step:
                prompt += f"Первый шаг к идеальному дню: {latest_plan.ideal_day_first_step}\n"
            prompt += "---\n"
        else:
            prompt += "Нет свежего плана.\n"

        if latest_emotional:
            prompt += f"**Последнее эмоциональное событие ({latest_emotional.date}):**\n"
            prompt += f"Ситуация: {latest_emotional.situation}\n"
            prompt += f"Мысль: {latest_emotional.thought}\n"
            prompt += f"Чувства: {latest_emotional.feelings}\n"
            if latest_emotional.correction:
                prompt += f"Коррекция: {latest_emotional.correction}\n"
            if latest_emotional.new_feelings:
                prompt += f"Новые чувства: {latest_emotional.new_feelings}\n"
            prompt += f"Итог: {latest_emotional.impact}\n"
            prompt += "---\n"
        else:
            prompt += "Нет свежих записей об эмоциональных событиях.\n"

        prompt += "\n\n**Запрос на советы:**\n"
        prompt += "Учитывая эту информацию, дай мне два кратких и действенных совета:\n\n"
        prompt += "1.  **Совет на сегодня/завтра:** Что я могу сделать для улучшения самочувствия или продуктивности в ближайшее время (на основе последних отчетов, планов, эмоций)?\n\n"
        prompt += "2.  **Совет по целям:** Как мне лучше сфокусироваться или продвинуться в моих стратегических задачах из планировщика?\n\n"
        prompt += "Пожалуйста, будь конкретен и давай советы в позитивном ключе."

        response = g4f.ChatCompletion.create(
            model=g4f.models.default,  # Вы можете выбрать другую модель из g4f.models
            messages=[{"role": "user", "content": prompt}],
        )

        bot.send_message(user_id, f"Вот некоторые рекомендации:\n{response}\nНажмите /start для новых действий.", parse_mode='Markdown')

    except Exception as e:
        bot.send_message(user_id, f"Произошла ошибка при получении рекомендаций: {e}\nНажмите /start для новых действий.")
    finally:
        if 'db' in locals():
            db.close()

# Обработчик команды /weekly_recommends
@bot.message_handler(commands=['weekly_recommends'])
def get_weekly_recommendations_bot(message):
    user_id = get_user_id(message)
    bot.send_chat_action(user_id, 'typing')
    bot.send_message(user_id, "Готовлю для вас еженедельный обзор... Это может занять некоторое время.")

    try:
        db = next(get_db())
        HISTORY_LIMIT_WEEKLY = 7

        daily_reports = db.query(DailyReport).filter(DailyReport.user_id == user_id).order_by(desc(DailyReport.date)).limit(HISTORY_LIMIT_WEEKLY).all()
        plans = db.query(Plan).filter(Plan.user_id == user_id).order_by(desc(Plan.date)).limit(HISTORY_LIMIT_WEEKLY).all()
        emotional_reports_history = db.query(EmotionalReport).filter(EmotionalReport.user_id == user_id).order_by(desc(EmotionalReport.date)).limit(HISTORY_LIMIT_WEEKLY * 2).all()
        plan_items = db.query(PlanItem).filter(PlanItem.user_id == user_id).order_by(PlanItem.item_type, desc(PlanItem.created_at)).all()

        prompt = "Проанализируй мои записи за последнюю неделю и мои стратегические цели. Твоя задача - выступить в роли коуча по продуктивности и благополучию и предоставить мне еженедельный обзор и рекомендации. Отвечай на русском языке, используя Markdown для форматирования.\n\n"

        if plan_items:
            prompt += "**Мои стратегические цели и задачи (из Планировщика):**\n"
            missions = [pi for pi in plan_items if pi.item_type == PlanItemType.MISSION]
            projects = [pi for pi in plan_items if pi.item_type == PlanItemType.PROJECT and pi.status != PlanItemStatus.DONE and pi.status != PlanItemStatus.CANCELLED]
            goals = [pi for pi in plan_items if pi.item_type == PlanItemType.GOAL and pi.status != PlanItemStatus.DONE and pi.status != PlanItemStatus.CANCELLED]
            if missions: prompt += f"  Миссии: {', '.join([m.name for m in missions[:2]])}\n"
            if projects: prompt += f"  Активные проекты: {', '.join([p.name for p in projects[:3]])}\n"
            if goals: prompt += f"  Ключевые цели: {', '.join([g.name for g in goals[:3]])}\n"
            prompt += "---\n"
        else:
            prompt += "Нет данных из долгосрочного планировщика.\n---\n"

        if daily_reports:
            prompt += "**История ежедневных отчетов (за последнюю неделю, от старых к новым):**\n"
            for report in reversed(daily_reports):
                prompt += f"  Отчет за {report.date}: Достижения - {report.top_achievement}, Трудности - {report.negative_events}\n" # Используем поля из старой структуры отчета бота
            prompt += "---\n"
        else: prompt += "Нет ежедневных отчетов за последнюю неделю.\n"

        if plans:
            prompt += "\n**История планов на день (за последнюю неделю, от старых к новым):**\n"
            for plan_item_db in reversed(plans):
                prompt += f"  План на {plan_item_db.date}: Главные цели - {plan_item_db.main_goals}\n"
            prompt += "---\n"
        else: prompt += "Нет планов на день за последнюю неделю.\n"

        if emotional_reports_history:
            prompt += "\n**История эмоциональных событий (недавние):**\n"
            for er in reversed(emotional_reports_history[:5]):
                prompt += f"  Событие ({er.date}): {er.situation} -> Мысль: {er.thought} -> Чувства: {er.feelings} -> Коррекция: {er.correction if er.correction else '-'}\n"
            prompt += "---\n"
        else: prompt += "Нет недавних эмоциональных событий.\n"

        prompt += "\n\n**Запрос на Еженедельный Обзор и Рекомендации (для Telegram):**\n"
        prompt += "Пожалуйста, предоставь структурированный ответ (используй Markdown, но старайся быть кратким для Telegram):\n1. **Обзор Прошедшей Недели:** Ключевые успехи и трудности.\n2. **Прогресс по Целям:** Как дела с главными целями/проектами?\n3. **Советы на Следующую Неделю:** 1-2 фокуса и 1 совет по благополучию.\n"

        response = g4f.ChatCompletion.create(
            model=g4f.models.default,
            messages=[{"role": "user", "content": prompt}],
        )
        bot.send_message(user_id, f"**Ваш Еженедельный Обзор:**\n{response}\n\nНажмите /start для новых действий.", parse_mode='Markdown')
    except Exception as e:
        bot.send_message(user_id, f"Произошла ошибка при подготовке еженедельного обзора: {e}\nНажмите /start для новых действий.")
    finally:
        if 'db' in locals():
            db.close()

# Обработчик команды /monthly_recommends
@bot.message_handler(commands=['monthly_recommends'])
def get_monthly_recommendations_bot(message):
    user_id = get_user_id(message)
    bot.send_chat_action(user_id, 'typing')
    bot.send_message(user_id, "Готовлю для вас ежемесячный стратегический обзор... Это может занять довольно много времени (до нескольких минут). Пожалуйста, подождите.")

    try:
        db = next(get_db())
        HISTORY_LIMIT_MONTHLY = 30 # Анализируем данные за последние 30 дней

        plan_items = db.query(PlanItem).filter(PlanItem.user_id == user_id).order_by(PlanItem.item_type, desc(PlanItem.created_at)).all()
        daily_reports = db.query(DailyReport).filter(DailyReport.user_id == user_id).order_by(desc(DailyReport.date)).limit(HISTORY_LIMIT_MONTHLY).all()

        prompt = "Проведи глубокий стратегический анализ моих долгосрочных целей и активностей за последний месяц. Твоя роль - стратегический коуч. Предоставь структурированный ежемесячный обзор и рекомендации. Отвечай на русском языке, используя Markdown (старайся быть кратким для Telegram).\n\n"

        if plan_items:
            prompt += "**Мои стратегические цели и задачи (из Планировщика - ключевое):**\n"
            missions = [pi for pi in plan_items if pi.item_type == PlanItemType.MISSION]
            projects = [pi for pi in plan_items if pi.item_type == PlanItemType.PROJECT]
            goals = [pi for pi in plan_items if pi.item_type == PlanItemType.GOAL]

            if missions: prompt += f"  Миссии: {', '.join([m.name for m in missions[:2]])}\n" # Первые 2
            if projects:
                prompt += "  Проекты (статус):\n"
                for p in projects[:3]: prompt += f"    - {p.name} ({p.status.value if p.status else 'Не указан'})\n" # Первые 3
            if goals:
                prompt += "  Ключевые цели (статус):\n"
                for g in goals[:3]: prompt += f"    - {g.name} ({g.status.value if g.status else 'Не указан'})\n" # Первые 3
            prompt += "---\n"
        else:
            prompt += "Нет данных из долгосрочного планировщика.\n---\n"

        if daily_reports:
            prompt += "**Обзор ежедневных отчетов (за последний месяц - несколько примеров):**\n"
            for report in reversed(daily_reports[:3]): # 3 последних как срез
                prompt += f"  Отчет за {report.date}: Достижения - {report.top_achievement}, Трудности - {report.negative_events}\n"
            if len(daily_reports) > 3: prompt += "  ... и другие отчеты.\n"
            prompt += "---\n"
        else: prompt += "Нет ежедневных отчетов за последний месяц для детального анализа.\n"

        prompt += "\n\n**Запрос на Ежемесячный Стратегический Обзор (для Telegram):**\n"
        prompt += "Пожалуйста, предоставь краткий структурированный ответ (Markdown):\n1. **Анализ Миссий/Проектов:** Главные выводы по прогрессу.\n2. **Общие Тренды:** Ключевые паттерны продуктивности/благополучия.\n3. **Стратегические Советы на След. Месяц:**\n    a. 1-2 приоритета.\n    b. 1 совет по улучшению подходов.\n    c. 1 вопрос для рефлексии.\n"

        response = g4f.ChatCompletion.create(
            model=g4f.models.gpt_4, # Используем более мощную модель
            messages=[{"role": "user", "content": prompt}],
        )
        bot.send_message(user_id, f"**Ваш Ежемесячный Стратегический Обзор:**\n{response}\n\nНажмите /start для новых действий.", parse_mode='Markdown')
    except Exception as e:
        bot.send_message(user_id, f"Произошла ошибка при подготовке ежемесячного обзора: {e}\nПожалуйста, попробуйте позже или проверьте логи.\nНажмите /start для новых действий.")
    finally:
        if 'db' in locals():
            db.close()



# Обработчик команды /view
@bot.message_handler(commands=['view'])
def start_view(message):
    user_id = get_user_id(message)
    view_data[user_id] = {}
    view_state[user_id] = VIEW_DATE
    bot.send_message(user_id, "На какую дату вы хотите просмотреть данные? Пожалуйста, введите дату в формате ГГГГ-ММ-ДД:")

@bot.message_handler(func=lambda message: view_state.get(get_user_id(message)) == VIEW_DATE)
def process_view_date(message):
    user_id = get_user_id(message)
    try:
        view_date = datetime.strptime(message.text, '%Y-%m-%d').date()
        view_data[user_id]['view_date'] = view_date
        view_state[user_id] = None # Сбрасываем состояние просмотра
        send_data_for_date(message, view_date)
    except ValueError:
        bot.reply_to(message, "Некорректный формат даты. Пожалуйста, введите дату в формате ГГГГ-ММ-ДД:")
    except Exception as e:
        bot.reply_to(message, f"Произошла ошибка при обработке даты: {e}")

def send_data_for_date(message, view_date):
    user_id = get_user_id(message)
    try:
        db = next(get_db())
        report = db.query(DailyReport).filter(DailyReport.user_id == user_id, DailyReport.date == view_date).first()
        plan = db.query(Plan).filter(Plan.user_id == user_id, Plan.date == view_date).first()
        emotional_reports = db.query(EmotionalReport).filter(EmotionalReport.user_id == user_id, EmotionalReport.date == view_date).all()

        output = f"**Данные за {view_date}:**\n\n"

        if report:
            output += "**Ежедневный отчет:**\n"
            output += f"Уровень энергии: {report.energy_level}\n"
            output += f"Что дало энергию: {report.energy_boosters}\n"
            output += f"Главное достижение: {report.top_achievement}\n"
            output += f"Узнал: {report.lesson_learned}\n"
            output += f"Благодарности: {report.gratitude_items}\n"
            output += f"Трудности: {report.negative_events}\n\n"
        else:
            output += "**Ежедневный отчет:** Нет данных за эту дату.\n\n"

        if plan:
            output += "**План на день:**\n"
            output += f"Главные цели: {plan.main_goals}\n"
            output += f"Приятное и значимое действие: {plan.pleasure_meaning}\n"
            output += f"Стратегия против препятствий: {plan.obstacle_strategy}\n"
            if plan.long_term_benefit:
                output += f"Долгосрочная выгода: {plan.long_term_benefit}\n"
            if plan.strengths_utilization:
                output += f"Использование сильных сторон: {plan.strengths_utilization}\n"
            if plan.new_skill_application:
                output += f"Применение нового навыка: {plan.new_skill_application}\n"
            if plan.self_care_time:
                output += f"Время для заботы о себе: {plan.self_care_time}\n"
            if plan.ideal_day_first_step:
                output += f"Первый шаг к идеальному дню: {plan.ideal_day_first_step}\n\n"
        else:
            output += "**План на день:** Нет данных за эту дату.\n\n"

        if emotional_reports:
            output += "**Эмоциональные события:**\n"
            for i, emo in enumerate(emotional_reports):
                output += f"Событие {i+1}:\n"
                output += f"Ситуация: {emo.situation}\n"
                output += f"Мысль: {emo.thought}\n"
                output += f"Чувства: {emo.feelings}\n"
                if emo.correction:
                    output += f"Коррекция: {emo.correction}\n"
                if emo.correction_hint_used:
                    output += f"Подсказка для коррекции: {emo.correction_hint_used}\n"
                if emo.new_feelings:
                    output += f"Новые чувства: {emo.new_feelings}\n"
                output += f"Итог: {emo.impact}\n\n"
        else:
            output += "**Эмоциональные события:** Нет данных за эту дату.\n."

        bot.send_message(user_id, output, parse_mode='Markdown')

    except Exception as e:
        bot.send_message(user_id, f"Произошла ошибка при получении данных за {view_date}: {e}")
    finally:
        bot.send_message(user_id, f"\nНажмите /start для новых действий.")
        if 'db' in locals():
            db.close()

# Универсальный обработчик команды /cancel (остается без изменений)
@bot.message_handler(commands=['cancel'])
def cancel_process(message):
    user_id = get_user_id(message)
    if user_id in user_state:
        del user_data[user_id]
        del user_state[user_id]
        bot.send_message(user_id, "Заполнение отчета отменено.\nНажмите /start для новых действий.")
    elif user_id in plan_state:
        del plan_data[user_id]
        del plan_state[user_id]
        bot.send_message(user_id, "Планирование на завтра отменено.\nНажмите /start для новых действий.")
    elif user_id in emotional_state:
        del emotional_data[user_id]
        del emotional_state[user_id]
        bot.send_message(user_id, "Отчет об эмоциональных спадах отменен.\nНажмите /start для новых действий.")
    else:
        bot.send_message(user_id, "Нет активных процессов для отмены.\nНажмите /start для новых действий.")

# Убираем ReplyKeyboardRemove после завершения отчета об эмоциях, т.к. кнопки "Добавить/Завершить" теперь ReplyKeyboardMarkup
# @bot.message_handler(func=lambda message: emotional_state.get(get_user_id(message)) == EMOTIONAL_DONE)
# def emotional_report_completed(message):
#     bot.send_message(message.chat.id, "Отчет завершен.", reply_markup=types.ReplyKeyboardRemove())

if __name__ == '__main__':
    bot.polling(none_stop=True)