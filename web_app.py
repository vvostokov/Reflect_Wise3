import os
import hashlib
import hmac
import urllib.parse
import time # Для time.sleep
import markdown # Для обработки markdown
import json # Для работы с JSON для main_goals и task_checkin_data
import requests # Для HTTP-запросов к VK API
from functools import wraps
from datetime import datetime, date, timedelta
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, make_response # Добавлен make_response
from sqlalchemy import desc # desc для сортировки
# Импортируем SessionLocal, engine и get_db из models.py
# Убедитесь, что модели DailyReport, Plan, EmotionalReport, User импортированы
# Добавлены импорты Recommendation, PlanItem, PlanItemStatus и PlanItemType
from models import Base, EmotionalReport, Plan, DailyReport, User, Recommendation, PlanItem, PlanItemStatus, PlanItemType, SessionLocal, engine, get_db
from threading import Thread
from config import Config # Добавлен импорт Config

app = Flask(__name__)
# Применяем конфигурацию из класса Config
app.config.from_object(Config)

# --- Мок-пользователь для локальной разработки без логина ---
class MockUser:
    def __init__(self, id, first_name="Разработчик", last_name="", username="dev_user", photo_url=None):
        self.id = id
        self.first_name = first_name
        self.last_name = last_name
        self.username = username
        self.photo_url = photo_url
        # self.telegram_id = f"mock_tg_{id}" # Раскомментируйте, если telegram_id нужен в объекте пользователя

# --- Настройка базы данных ---
# Движок (engine) и фабрика сессий (SessionLocal) теперь ИМПОРТИРУЮТСЯ из models.py.
# Удален повторный вызов create_engine и Session = sessionmaker(...) здесь.

# Временное создание таблиц ДЛЯ ПЕРВОГО РАЗВЕРТЫВАНИЯ НА RENDER!
# Эту строку нужно ЗАКОММЕНТИРОВАТЬ или УДАЛИТЬ после того, как таблицы будут созданы в БД на Render.
# Она создаст таблицы DailyReport, Plan, EmotionalReport, User.
# Base.metadata.create_all(engine) # Убедитесь, что таблица Recommendation также создается


# Функция для получения сессии базы данных (импортируется из models.py)

# --- Функции для Telegram аутентификации ---

def check_telegram_authentication(data):
    """
    Проверяет криптографическую подпись данных, полученных от виджета Telegram.
    Возвращает True, если подпись верна, иначе False.
    """
    # Получаем токен бота из конфигурации
    bot_token = app.config.get('TELEGRAM_BOT_TOKEN')
    if not bot_token:
        print("Ошибка: TELEGRAM_BOT_TOKEN не установлен в конфигурации!")
        return False

    # Извлекаем хэш из полученных данных
    received_hash = data.get('hash')
    if not received_hash:
        return False # Хэш отсутствует

    # Собираем все поля, кроме 'hash', для проверки подписи
    auth_data_list = []
    for key in sorted(data.keys()):
        if key != 'hash':
            auth_data_list.append(f'{key}={data[key]}')
    # Соединяем строки в одну строку с разделителем '\n'
    auth_data_string = '\n'.join(auth_data_list)

    # Генерируем секретный ключ для подписи (SHA256 хэш токена бота)
    secret_key = hashlib.sha256(bot_token.encode('utf-8')).digest()

    # Генерируем хэш данных с использованием секретного ключа и алгоритма HMAC-SHA256
    hmac_hash = hmac.new(secret_key, auth_data_string.encode('utf-8'), hashlib.sha256).hexdigest()

    # Сравниваем с полученным хэшем
    return hmac_hash == received_hash

# --- Функции для генерации рекомендаций (используют БД) ---

def _format_plan_items_for_prompt(plan_items, missions_limit=3, projects_limit=3, goals_limit=3, tasks_limit=5, include_status=True):
    if not plan_items:
        return "Нет данных из долгосрочного планировщика.\n---\n"
    prompt_segment = "**Мои стратегические цели и задачи (из Планировщика):**\n"
    
    missions = [pi for pi in plan_items if pi.item_type == PlanItemType.MISSION]
    projects = [pi for pi in plan_items if pi.item_type == PlanItemType.PROJECT and (not include_status or (pi.status != PlanItemStatus.DONE and pi.status != PlanItemStatus.CANCELLED))]
    goals = [pi for pi in plan_items if pi.item_type == PlanItemType.GOAL and (not include_status or (pi.status != PlanItemStatus.DONE and pi.status != PlanItemStatus.CANCELLED))]
    tasks = [pi for pi in plan_items if pi.item_type == PlanItemType.TASK and (not include_status or pi.status in (PlanItemStatus.TODO, PlanItemStatus.IN_PROGRESS))]

    if missions:
        prompt_segment += "  Миссии:\n"
        for item in missions[:missions_limit]: prompt_segment += f"    - {item.name}\n"
    if projects:
        prompt_segment += "  Активные проекты:\n"
        for item in projects[:projects_limit]: 
            prompt_segment += f"    - {item.name}"
            if include_status: prompt_segment += f" (Статус: {item.status.value if item.status else 'Не указан'})"
            prompt_segment += "\n"
    if goals:
        prompt_segment += "  Ключевые цели:\n"
        for item in goals[:goals_limit]: 
            prompt_segment += f"    - {item.name}"
            if include_status: prompt_segment += f" (Статус: {item.status.value if item.status else 'Не указан'})"
            prompt_segment += "\n"
    if tasks:
        prompt_segment += "  Задачи в фокусе:\n"
        for item in tasks[:tasks_limit]: 
            prompt_segment += f"    - {item.name}"
            if include_status: prompt_segment += f" (Статус: {item.status.value if item.status else 'Не указан'})"
            prompt_segment += "\n"
    prompt_segment += "---\n"
    return prompt_segment

def _format_daily_reports_for_prompt(daily_reports, intro_text="**История ежедневных отчетов (от старых к новым):**\n"):
    if not daily_reports:
        return "Нет недавних ежедневных отчетов.\n"
    prompt_segment = intro_text
    for report in reversed(daily_reports): # Отображаем в хронологическом порядке
        prompt_segment += f"**Вечерний отчет за {report.date}:**\n"
        if report.reviewed_tasks:
            try:
                reviewed_tasks_list = json.loads(report.reviewed_tasks) if isinstance(report.reviewed_tasks, str) else report.reviewed_tasks
                if reviewed_tasks_list:
                    prompt_segment += "  Выполнение задач:\n"
                    for task_item in reviewed_tasks_list:
                        prompt_segment += f"    - {task_item.get('name', 'Задача не указана')}: {task_item.get('status', 'Статус не указан')}. Комментарий: {task_item.get('comment', 'Нет')}\n"
            except (json.JSONDecodeError, TypeError):
                prompt_segment += "  Выполнение задач: (ошибка чтения данных)\n"
        if report.evening_q1: prompt_segment += f"  1. Что получилось лучше всего: {report.evening_q1}\n"
        # ... (add other evening_q fields) ...
        prompt_segment += "---\n"
    return prompt_segment

# Add similar helper functions: _format_plans_for_prompt, _format_emotional_reports_for_prompt, _format_rated_recommendations_for_prompt

def get_recommendations_from_gpt(db: SessionLocal, user_id: int):
    """
    Формирует промпт на основе последних записей пользователя и получает рекомендации от GPT.
    """
    HISTORY_LIMIT = 3 # Количество последних записей каждого типа для включения в промпт

    # Используем user_id из сессии для запросов к БД
    daily_reports = db.query(DailyReport).filter(DailyReport.user_id == user_id).order_by(desc(DailyReport.date)).limit(HISTORY_LIMIT).all()
    plans = db.query(Plan).filter(Plan.user_id == user_id).order_by(desc(Plan.date)).limit(HISTORY_LIMIT).all()
    emotional_reports_history = db.query(EmotionalReport).filter(EmotionalReport.user_id == user_id).order_by(desc(EmotionalReport.date)).limit(HISTORY_LIMIT).all()
    plan_items = db.query(PlanItem).filter(PlanItem.user_id == user_id).order_by(PlanItem.item_type, desc(PlanItem.created_at)).all()
    
    # Получаем последние оцененные рекомендации
    rated_recommendations = db.query(Recommendation).filter(
        Recommendation.user_id == user_id,
        Recommendation.rating != None
    ).order_by(desc(Recommendation.date), desc(Recommendation.id)).limit(3).all()

    prompt = "Проанализируй следующую историю моих записей (стратегические цели из планировщика, недавние отчеты за день, планы на день, эмоциональные события) и мою обратную связь на предыдущие советы. Твоя задача - дать мне две структурированные рекомендации с точки зрения психолога. Отвечай на русском языке.\n\n"

    prompt += _format_plan_items_for_prompt(plan_items)
    prompt += _format_daily_reports_for_prompt(daily_reports)
    # prompt += _format_plans_for_prompt(plans)
    # prompt += _format_emotional_reports_for_prompt(emotional_reports_history)
    # prompt += _format_rated_recommendations_for_prompt(rated_recommendations)

    if plans:
        prompt += "\n**История планов на день (Утреннее планирование, от старых к новым):**\n"
        for plan_item in reversed(plans): # Отображаем в хронологическом порядке
            prompt += f"**Утренний план на {plan_item.date}:**\n"
            if plan_item.main_goals:
                try:
                    # Ensure main_goals is a string before parsing
                    main_goals_list = json.loads(plan_item.main_goals) if isinstance(plan_item.main_goals, str) else plan_item.main_goals
                    if not isinstance(main_goals_list, list): # If parsing failed or it was not a list
                        main_goals_list = []
                    prompt += "  Главные задачи дня (из plan.main_goals):\n"
                    for goal in main_goals_list:
                        prompt += f"    - {goal.get('text', 'Задача не указана')}\n"
                except (json.JSONDecodeError, TypeError):
                    prompt += "  Главные задачи дня: (ошибка чтения данных)\n"
            # morning_q1_focus_tasks is no longer the primary source for Q1 tasks
            prompt += "  Утренние вопросы (настрой на день):\n"
            if plan_item.morning_q2_improve_day: prompt += f"    2. Как сделать день лучше: {plan_item.morning_q2_improve_day}\n"
            if plan_item.morning_q3_mindset: prompt += f"    3. Качество/mindset на день: {plan_item.morning_q3_mindset}\n"
            if plan_item.morning_q4_help_others: prompt += f"    4. Кому помочь/сделать приятное: {plan_item.morning_q4_help_others}\n"
            if plan_item.morning_q5_inspiration: prompt += f"    5. Вдохновение/благодарность: {plan_item.morning_q5_inspiration}\n"
            if plan_item.morning_q6_health_care: prompt += f"    6. Забота о здоровье: {plan_item.morning_q6_health_care}\n"
            prompt += "---\n"
    else:
        prompt += "Нет недавних планов.\n"

    if emotional_reports_history:
        prompt += "\n**История эмоциональных событий (от старых к новым):**\n"
        for er in reversed(emotional_reports_history): # Отображаем в хронологическом порядке
            prompt += f"**Эмоциональное событие ({er.date}):**\n"
            prompt += f"  Ситуация: {er.situation}\n"
            prompt += f"  Мысль: {er.thought}\n"
            prompt += f"  Чувства: {er.feelings}\n"
            if er.correction: prompt += f"  Коррекция: {er.correction}\n"
            if er.new_feelings: prompt += f"  Новые чувства: {er.new_feelings}\n"
            prompt += f"  Итог/Влияние: {er.impact}\n"
            prompt += "---\n"
    else:
        prompt += "Нет недавних записей об эмоциональных событиях.\n"

    if rated_recommendations:
        prompt += "\n**Моя обратная связь на предыдущие рекомендации:**\n"
        for rec in rated_recommendations:
            rating_text = "Полезно" if rec.rating == 1 else "Не полезно" if rec.rating == -1 else "Нет оценки"
            clean_text_for_prompt = rec.original_text if rec.original_text else rec.text # Предпочитаем original_text
            prompt += f"  - Совет (от {rec.date.strftime('%Y-%m-%d')}): \"{clean_text_for_prompt[:200]}...\" (Моя оценка: {rating_text})\n"
        prompt += "---\n"
    else:
        prompt += "\nНет оцененных предыдущих рекомендаций для учета.\n---\n"

    prompt += "\n\n**Запрос на рекомендации:**\n"
    prompt += "Исходя из всей предоставленной информации (мои стратегические цели, недавние записи и эмоциональные события), пожалуйста, дай мне две четко разделенные рекомендации:\n\n"
    prompt += "1.  **Рекомендация для Ежедневного Благополучия:** Один конкретный, действенный совет для улучшения моего самочувствия, настроения или продуктивности на ближайшие 1-2 дня, основанный на моих недавних отчетах, планах или эмоциональных событиях.\n\n"
    prompt += "2.  **Рекомендация для Долгосрочного Роста:** Один конкретный, действенный совет, который поможет мне эффективнее двигаться к моим долгосрочным миссиям, проектам или целям, указанным в планировщике, или поможет преодолеть препятствия на этом пути.\n\n"
    prompt += "Формулируй рекомендации позитивно и конструктивно."

    # Имитация долгой работы (можно удалить или настроить)
    time.sleep(5)
    try:
        # Используем g4f для получения ответа
        import g4f
        response = g4f.ChatCompletion.create(
            model=g4f.models.default,
            messages=[{"role": "user", "content": prompt}],
        )
        return response
    except Exception as e:
        print(f"Ошибка при получении рекомендаций от GPT: {e}")
        return f"Произошла ошибка при получении рекомендаций: {e}"

def get_monthly_recommendations_from_gpt(db: SessionLocal, user_id: int):
    """
    Формирует промпт для ежемесячного стратегического обзора и получает рекомендации от GPT.
    """
    HISTORY_LIMIT_MONTHLY = 30 # Анализируем данные за последние 30 дней

    # Для месячного обзора берем все стратегические элементы
    plan_items = db.query(PlanItem).filter(PlanItem.user_id == user_id).order_by(PlanItem.item_type, desc(PlanItem.created_at)).all()
    # Можно также взять более длительную историю отчетов, если нужно, или агрегировать их
    daily_reports = db.query(DailyReport).filter(DailyReport.user_id == user_id).order_by(desc(DailyReport.date)).limit(HISTORY_LIMIT_MONTHLY).all()
    # emotional_reports_history = db.query(EmotionalReport).filter(EmotionalReport.user_id == user_id).order_by(desc(EmotionalReport.date)).limit(HISTORY_LIMIT_MONTHLY).all()
    plans = db.query(Plan).filter(Plan.user_id == user_id).order_by(desc(Plan.date)).limit(HISTORY_LIMIT_MONTHLY).all() # Сбор утренних планов
    emotional_reports_history = db.query(EmotionalReport).filter(EmotionalReport.user_id == user_id).order_by(desc(EmotionalReport.date)).limit(HISTORY_LIMIT_MONTHLY).all() # Сбор эмоциональных отчетов

    rated_recommendations = db.query(Recommendation).filter(
        Recommendation.user_id == user_id,
        Recommendation.rating != None
    ).order_by(desc(Recommendation.date), desc(Recommendation.id)).limit(5).all() # Берем больше для месячного


    def _format_plans_for_monthly_prompt(plans_data, intro_text="**Обзор утренних планов (за последний месяц - ключевые моменты):**\n"):
        if not plans_data:
            return "Нет утренних планов за последний месяц для анализа.\n---\n"
        prompt_segment = intro_text
        for plan_item in reversed(plans_data[:5]): # Показываем 5 последних как срез
            goals_text = "Не указаны"
            if plan_item.main_goals:
                try:
                    goals_list = json.loads(plan_item.main_goals)
                    goals_text = ", ".join([g['text'] for g in goals_list[:2]]) # Первые 2 для краткости
                    if len(goals_list) > 2: goals_text += "..."
                except (json.JSONDecodeError, TypeError): pass # Игнорируем ошибки парсинга
            prompt_segment += f"  План на {plan_item.date}: Главные задачи - {goals_text}. Улучшение дня (Q2): {plan_item.morning_q2_improve_day[:60] if plan_item.morning_q2_improve_day else '-' }...\n"
        if len(plans_data) > 5: prompt_segment += "  ... и другие планы.\n"
        prompt_segment += "---\n"
        return prompt_segment

    def _format_emotional_reports_for_monthly_prompt(emotional_reports_data, intro_text="**Обзор эмоциональных событий (за последний месяц - ключевые моменты):**\n"):
        if not emotional_reports_data:
            return "Нет записей об эмоциональных событиях за последний месяц для анализа.\n---\n"
        prompt_segment = intro_text
        for er in reversed(emotional_reports_data[:5]): # Показываем 5 последних как срез
            prompt_segment += f"  Событие ({er.date}): Ситуация - {er.situation[:60] if er.situation else '-' }... Мысль: {er.thought[:60] if er.thought else '-' }... Чувства: {er.feelings[:60] if er.feelings else '-' }... Коррекция: {er.correction[:60] if er.correction else '-'}\n"
        if len(emotional_reports_data) > 5: prompt_segment += "  ... и другие эмоциональные события.\n"
        prompt_segment += "---\n"
        return prompt_segment

    prompt = "Проведи глубокий стратегический анализ моих долгосрочных целей, активностей за последний месяц и моей обратной связи на предыдущие советы. Твоя роль - стратегический коуч. Предоставь структурированный ежемесячный обзор и рекомендации. Отвечай на русском языке, используя Markdown.\n\n"


    if plan_items:
        prompt += "**Мои стратегические цели и задачи (из Планировщика - полный список):**\n"
        missions = [pi for pi in plan_items if pi.item_type == PlanItemType.MISSION]
        projects = [pi for pi in plan_items if pi.item_type == PlanItemType.PROJECT] # Все проекты, включая завершенные
        goals = [pi for pi in plan_items if pi.item_type == PlanItemType.GOAL]

        if missions: prompt += f"  Миссии: {', '.join([m.name for m in missions])}\n"
        if projects:
            prompt += "  Проекты (статус):\n"
            for p in projects[:7]: prompt += f"    - {p.name} ({p.status.value if p.status else 'Не указан'})\n" # Первые 7 для краткости
        if goals:
            prompt += "  Ключевые цели (статус):\n"
            for g in goals[:7]: prompt += f"    - {g.name} ({g.status.value if g.status else 'Не указан'})\n" # Первые 7
        prompt += "---\n"
    else:
        prompt += "Нет данных из долгосрочного планировщика.\n---\n"

    if daily_reports:
        prompt += "**Обзор ежедневных отчетов (за последний месяц - ключевые моменты):**\n"
        # Для краткости можно попросить AI самому выделить тренды или показать несколько ярких примеров
        # Здесь для примера покажем несколько последних
        for report in reversed(daily_reports[:5]): # 5 последних как срез
            prompt += f"  Отчет за {report.date}: Достижения - {report.evening_q1}, Трудности - {report.evening_q5}\n"
        if len(daily_reports) > 5: prompt += "  ... и другие отчеты.\n"
        prompt += "---\n"
    else: prompt += "Нет ежедневных отчетов за последний месяц для детального анализа.\n"

    prompt += _format_plans_for_monthly_prompt(plans)
    prompt += _format_emotional_reports_for_monthly_prompt(emotional_reports_history)

    if rated_recommendations:
        prompt += "\n**Моя обратная связь на предыдущие рекомендации (за последнее время):**\n"
        for rec in rated_recommendations:
            rating_text = "Полезно" if rec.rating == 1 else "Не полезно" if rec.rating == -1 else "Нет оценки"
            clean_text_for_prompt = rec.original_text if rec.original_text else rec.text
            prompt += f"  - Совет (от {rec.date.strftime('%Y-%m-%d')}): \"{clean_text_for_prompt[:200]}...\" (Моя оценка: {rating_text})\n"
        prompt += "---\n"
    else:
        prompt += "\nНет оцененных предыдущих рекомендаций для учета.\n---\n"

    prompt += "\n\n**Запрос на Ежемесячный Стратегический Обзор и Рекомендации:**\n"
    prompt += "Пожалуйста, предоставь структурированный ответ (используй Markdown):\n1. **Анализ Миссий и Проектов:** Насколько я продвинулся(ась) к своим миссиям? Какие проекты были успешны, какие требуют пересмотра или новых подходов? Есть ли застой?\n2. **Общие Тренды Продуктивности и Благополучия:** Какие паттерны видны в моих ежедневных отчетах за месяц (энергия, достижения, трудности)?\n3. **Стратегические Рекомендации на Следующий Месяц:**\n    a. Какие 1-2 стратегические цели/проекта должны быть в приоритете?\n    b. Какие изменения в рутине или подходах могут повысить мою эффективность и удовлетворенность в долгосрочной перспективе?\n    c. Один вопрос для глубокой рефлексии о моих ценностях или долгосрочном видении.\n"
    prompt += "Будь проницательным, предлагай конкретные шаги и задавай стимулирующие вопросы."
    prompt += "\n4. **Гипотезы для Самоисследования на Следующий Месяц:**\n"
    prompt += "    a. На основе анализа всех предоставленных данных за последний месяц (стратегические цели, ежедневные отчеты, утренние планы, эмоциональные события, обратная связь на советы), сформулируй 1-2 конкретные, проверяемые гипотезы. Гипотеза должна выявлять потенциальную связь между моими действиями/подходами/эмоциями и моими результатами (например, продуктивностью, уровнем энергии, достижением целей, эмоциональным состоянием).\n"
    prompt += "       Пример гипотезы: 'Если я последовательно выделяю время на задачу X в утреннем плане, то мои вечерние отчеты чаще показывают высокие достижения по ней и более высокий уровень энергии.' или 'Когда возникает ситуация типа Y, использование коррекции Z приводит к более быстрому восстановлению эмоционального баланса по сравнению с другими методами'.\n"
    prompt += "    b. Для каждой гипотезы предложи простой и конкретный способ, как я могу проверить её в течение следующего месяца (например, какое поведение отслеживать, на что обращать внимание в записях).\n"

    time.sleep(10) # Имитация очень долгой работы для стратегического анализа
    try:
        import g4f
        response = g4f.ChatCompletion.create(
            model=g4f.models.gpt_4, # Используем более мощную модель для стратегического анализа
            messages=[{"role": "user", "content": prompt}],
        )
        return response
    except Exception as e:
        print(f"Ошибка при получении ежемесячных рекомендаций от GPT: {e}")
        return f"Произошла ошибка при получении ежемесячных рекомендаций: {e}"

def get_weekly_recommendations_from_gpt(db: SessionLocal, user_id: int):
    """
    Формирует промпт для еженедельного обзора и получает рекомендации от GPT.
    """
    HISTORY_LIMIT_WEEKLY = 7 # Анализируем данные за последние 7 дней

    daily_reports = db.query(DailyReport).filter(DailyReport.user_id == user_id).order_by(desc(DailyReport.date)).limit(HISTORY_LIMIT_WEEKLY).all()
    plans = db.query(Plan).filter(Plan.user_id == user_id).order_by(desc(Plan.date)).limit(HISTORY_LIMIT_WEEKLY).all()
    emotional_reports_history = db.query(EmotionalReport).filter(EmotionalReport.user_id == user_id).order_by(desc(EmotionalReport.date)).limit(HISTORY_LIMIT_WEEKLY * 2).all() # Больше эмоциональных для контекста
    plan_items = db.query(PlanItem).filter(PlanItem.user_id == user_id).order_by(PlanItem.item_type, desc(PlanItem.created_at)).all()
    rated_recommendations = db.query(Recommendation).filter(
        Recommendation.user_id == user_id,
        Recommendation.rating != None
    ).order_by(desc(Recommendation.date), desc(Recommendation.id)).limit(4).all() # Для еженедельного


    prompt = "Проанализируй мои записи за последнюю неделю, мои стратегические цели и мою обратную связь на предыдущие советы. Твоя задача - выступить в роли коуча по продуктивности и благополучию и предоставить мне еженедельный обзор и рекомендации. Отвечай на русском языке, используя Markdown для форматирования.\n\n"


    if plan_items:
        prompt += "**Мои стратегические цели и задачи (из Планировщика):**\n"
        missions = [pi for pi in plan_items if pi.item_type == PlanItemType.MISSION]
        projects = [pi for pi in plan_items if pi.item_type == PlanItemType.PROJECT and pi.status != PlanItemStatus.DONE and pi.status != PlanItemStatus.CANCELLED]
        goals = [pi for pi in plan_items if pi.item_type == PlanItemType.GOAL and pi.status != PlanItemStatus.DONE and pi.status != PlanItemStatus.CANCELLED]
        # Задачи можно опустить для еженедельного обзора, если их слишком много, или показать только самые важные/недавние
        if missions: prompt += f"  Миссии: {', '.join([m.name for m in missions[:2]])}\n"
        if projects: prompt += f"  Активные проекты: {', '.join([p.name for p in projects[:3]])}\n"
        if goals: prompt += f"  Ключевые цели: {', '.join([g.name for g in goals[:3]])}\n"
        prompt += "---\n"
    else:
        prompt += "Нет данных из долгосрочного планировщика.\n---\n"

    if daily_reports:
        prompt += "**История ежедневных отчетов (за последнюю неделю, от старых к новым):**\n"
        for report in reversed(daily_reports):
            prompt += f"  Отчет за {report.date}: Основные достижения - {report.evening_q1}, Трудности - {report.evening_q5}\n"
        prompt += "---\n"
    else: prompt += "Нет ежедневных отчетов за последнюю неделю.\n"

    if plans:
        prompt += "\n**История планов на день (за последнюю неделю, от старых к новым):**\n"
        for plan_item in reversed(plans):
            goals_text = "Не указаны"
            if plan_item.main_goals:
                try: goals_text = ", ".join([g['text'] for g in json.loads(plan_item.main_goals)[:2]]) + "..." # Первые 2 для краткости
                except: pass
            prompt += f"  План на {plan_item.date}: Главные задачи - {goals_text}\n"
        prompt += "---\n"
    else: prompt += "Нет планов на день за последнюю неделю.\n"

    if emotional_reports_history:
        prompt += "\n**История эмоциональных событий (недавние):**\n"
        for er in reversed(emotional_reports_history[:5]): # Последние 5 для краткости
            prompt += f"  Событие ({er.date}): {er.situation} -> Мысль: {er.thought} -> Чувства: {er.feelings}\n"
            if er.correction: prompt += f"    Коррекция: {er.correction}\n"
        prompt += "---\n"
    else: prompt += "Нет недавних эмоциональных событий.\n"

    if rated_recommendations:
        prompt += "\n**Моя обратная связь на предыдущие рекомендации (за последнее время):**\n"
        for rec in rated_recommendations:
            rating_text = "Полезно" if rec.rating == 1 else "Не полезно" if rec.rating == -1 else "Нет оценки"
            clean_text_for_prompt = rec.original_text if rec.original_text else rec.text
            prompt += f"  - Совет (от {rec.date.strftime('%Y-%m-%d')}): \"{clean_text_for_prompt[:200]}...\" (Моя оценка: {rating_text})\n"
        prompt += "---\n"
    else:
        prompt += "\nНет оцененных предыдущих рекомендаций для учета.\n---\n"

    prompt += "\n\n**Запрос на Еженедельный Обзор и Рекомендации:**\n"
    prompt += "Пожалуйста, предоставь структурированный ответ (используй Markdown):\n1. **Обзор Прошедшей Недели:** Кратко об успехах, трудностях и связи эмоций с продуктивностью.\n2. **Прогресс по Стратегическим Целям:** Насколько я продвинулся(ась) к целям из Планировщика? Какие требуют внимания?\n3. **Рекомендации на Следующую Неделю:** 1-2 ключевых фокуса для долгосрочных целей, 1 совет для благополучия/энергии, 1 возможная корректировка в подходах.\n"
    prompt += "Будь конструктивным и давай действенные советы."

    time.sleep(7) # Имитация более долгой работы для еженедельного анализа
    try:
        import g4f
        response = g4f.ChatCompletion.create(
            model=g4f.models.default, # Можно выбрать более мощную модель для глубокого анализа
            messages=[{"role": "user", "content": prompt}],
        )
        return response
    except Exception as e:
        print(f"Ошибка при получении еженедельных рекомендаций от GPT: {e}")
        return f"Произошла ошибка при получении еженедельных рекомендаций: {e}"

def generate_recommendations_background(app, user_id):
    """
    Генерирует рекомендации в фоновом потоке для конкретного пользователя.
    """
    with app.app_context():
        db: SessionLocal = next(get_db())
        try:
            recommendation_text = get_recommendations_from_gpt(db, user_id)
            if recommendation_text:
                # Сохраняем рекомендацию в БД
                new_recommendation = Recommendation(
                    user_id=user_id,
                    original_text=recommendation_text, # Сохраняем исходный текст
                    text=markdown.markdown(recommendation_text) # Сохраняем HTML-версию
                )
                db.add(new_recommendation)
                db.commit()
                print(f"Рекомендация успешно сохранена для пользователя {user_id}")
        except Exception as e:
            print(f"Ошибка в фоновом потоке генерации рекомендаций: {e}")
        finally:
            db.close()

def generate_weekly_recommendations_background(app, user_id):
    """
    Генерирует ЕЖЕНЕДЕЛЬНЫЕ рекомендации в фоновом потоке.
    """
    with app.app_context():
        db: SessionLocal = next(get_db())
        try:
            recommendation_text = get_weekly_recommendations_from_gpt(db, user_id)
            if recommendation_text:
                new_recommendation = Recommendation(
                    user_id=user_id,
                    original_text=recommendation_text,
                    text=markdown.markdown(recommendation_text)
                )
                db.add(new_recommendation)
                db.commit()
                print(f"Еженедельная рекомендация успешно сохранена для пользователя {user_id}")
        except Exception as e:
            print(f"Ошибка в фоновом потоке генерации еженедельных рекомендаций: {e}")
        finally:
            db.close()

def generate_monthly_recommendations_background(app, user_id):
    """
    Генерирует ЕЖЕМЕСЯЧНЫЕ стратегические рекомендации в фоновом потоке.
    """
    with app.app_context():
        db: SessionLocal = next(get_db())
        try:
            recommendation_text = get_monthly_recommendations_from_gpt(db, user_id)
            if recommendation_text:
                new_recommendation = Recommendation(
                    user_id=user_id,
                    original_text=recommendation_text,
                    text=markdown.markdown(recommendation_text)
                )
                db.add(new_recommendation)
                db.commit()
                print(f"Ежемесячная стратегическая рекомендация успешно сохранена для пользователя {user_id}")
        except Exception as e:
            print(f"Ошибка в фоновом потоке генерации ежемесячных рекомендаций: {e}")
        finally:
            db.close()

# --- Маршруты Flask ---

# --- Вспомогательная функция для карусели дат ---
def get_date_carousel_options(selected_date_iso_str=None, num_days_around=2):
    """
    Генерирует список дат для карусели.
    selected_date_iso_str: дата, которая должна быть выбрана по умолчанию (ISO формат 'YYYY-MM-DD').
    num_days_around: количество дней до и после выбранной даты для отображения.
    """
    days_ru = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    months_ru_genitive = [
        "января", "февраля", "марта", "апреля", "мая", "июня",
        "июля", "августа", "сентября", "октября", "ноября", "декабря"
    ]

    try:
        target_selection_date = date.fromisoformat(selected_date_iso_str) if selected_date_iso_str else date.today()
    except ValueError:
        target_selection_date = date.today()

    today = date.today()
    options = []

    for i in range(-num_days_around, num_days_around + 1):
        d = target_selection_date + timedelta(days=i) # Даты генерируются относительно target_selection_date
        
        display_text_parts = []
        if d == today: display_text_parts.append("Сегодня")
        elif d == today - timedelta(days=1): display_text_parts.append("Вчера")
        elif d == today + timedelta(days=1): display_text_parts.append("Завтра")
        
        day_name_ru = days_ru[d.weekday()]
        month_name_ru = months_ru_genitive[d.month - 1]
        date_str_part = f"{day_name_ru}, {d.day} {month_name_ru}"
        
        display_text_parts.append(f"({date_str_part})" if display_text_parts else date_str_part)

        options.append({
            'display_text': " ".join(display_text_parts),
            'iso_value': d.isoformat(),
            'is_selected': (d == target_selection_date) # Выбранной будет именно target_selection_date
        })
    return options

# --- Custom Decorator for Login ---
def login_required_custom(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        current_user_id = None
        db_for_check = None
        try:
            if app.config.get('LOCAL_DEV_NO_LOGIN'):
                current_user_id = app.config.get('DEFAULT_DEV_USER_ID', 1)
                if session.get('user_id') != current_user_id:
                    session['user_id'] = current_user_id
                # For API routes, we might not need to flash, just return error
                # For page routes, flashing is fine.
            elif 'user_id' in session:
                current_user_id = session['user_id']
                db_for_check = next(get_db())
                user = db_for_check.query(User).filter_by(id=current_user_id).first()
                if not user:
                    session.pop('user_id', None)
                    session.pop('telegram_id', None)
                    flash('Ваша сессия истекла или недействительна. Пожалуйста, войдите снова.', 'warning')
                    return redirect(url_for('login'))
            else:
                flash('Пожалуйста, войдите для доступа к этой странице.', 'warning')
                return redirect(url_for('login'))
            
            return f(current_user_id, *args, **kwargs) # Pass user_id to the route
        finally:
            if db_for_check:
                db_for_check.close()
    return decorated_function


# Маршрут для страницы входа с виджетом Telegram
@app.route('/login')
def login():
    # Если пользователь уже авторизован, перенаправляем на главную
    if 'user_id' in session:
        return redirect(url_for('index'))

    # Иначе отображаем страницу входа login.html
    response = make_response(render_template('login.html'))

    # --- Устанавливаем CSP заголовок для Render ---
    # Используйте домен вашего приложения на Render вместо localhost.local
    # Например: https://reflect-wise-app.onrender.com
    # Разрешаем загрузку скриптов с telegram.org
    # Разрешаем встраивание (фреймы) с oauth.telegram.org
    # Разрешаем, чтобы нашу страницу встраивали (frame-ancestors) с домена Render И oauth.telegram.org
    # Разрешаем инлайн-стили ('unsafe-inline') для style-src
    # Убедитесь, что TELEGRAM_LOGIN_DOMAIN установлен в переменных окружения Render
    render_domain = app.config.get('TELEGRAM_LOGIN_DOMAIN', 'reflect-wise-app.onrender.com') # Используем домен из конфига или запасной
    csp_policy = f"default-src 'self'; script-src 'self' https://telegram.org; style-src 'self' 'unsafe-inline'; frame-src https://oauth.telegram.org; frame-ancestors 'self' https://oauth.telegram.org https://{render_domain};" # <-- ИЗМЕНЕНО ЗДЕСЬ

    response.headers['Content-Security-Policy'] = csp_policy
    # --- КОНЕЦ УСТАНОВКИ CSP ---

    return response

# Маршрут для инициации входа через VK
@app.route('/login_vk')
def login_vk():
    if 'user_id' in session:
        return redirect(url_for('index'))

    vk_app_id = app.config.get('VK_APP_ID')
    # Важно: VK_REDIRECT_URI должен точно совпадать с тем, что указан в настройках вашего VK приложения
    vk_redirect_uri = url_for('vk_callback', _external=True)
    
    # Формируем URL для авторизации VK
    # display=page - тип окна авторизации
    # scope=offline,email - запрашиваемые права доступа (offline для долгоживущего токена, email - если нужен)
    #   проверьте документацию VK API для актуальных scope
    # response_type=code - тип ответа (код авторизации)
    # v=5.131 - версия API VK
    vk_auth_url = (
        f"https://oauth.vk.com/authorize?client_id={vk_app_id}"
        f"&display=page&redirect_uri={vk_redirect_uri}"
        f"&scope=offline&response_type=code&v=5.199" # Используйте актуальную версию API
    )
    return redirect(vk_auth_url)

# Маршрут для обработки callback от VK
@app.route('/vk_callback')
def vk_callback():
    code = request.args.get('code')
    if not code:
        flash('Ошибка авторизации через ВКонтакте: не получен код.', 'danger')
        return redirect(url_for('login'))

    vk_app_id = app.config.get('VK_APP_ID')
    vk_secure_key = app.config.get('VK_SECURE_KEY')
    vk_redirect_uri = url_for('vk_callback', _external=True)

    # Обмен кода на access_token
    token_url = (
        f"https://oauth.vk.com/access_token?client_id={vk_app_id}"
        f"&client_secret={vk_secure_key}&redirect_uri={vk_redirect_uri}&code={code}"
    )
    try:
        token_response = requests.get(token_url)
        token_response.raise_for_status() # Проверка на HTTP ошибки
        token_data = token_response.json()

        access_token = token_data.get('access_token')
        vk_user_id = token_data.get('user_id')
        # email = token_data.get('email') # Если запрашивали и VK вернул

        if not access_token or not vk_user_id:
            flash('Ошибка авторизации через ВКонтакте: не удалось получить токен или ID пользователя.', 'danger')
            return redirect(url_for('login'))

        # Получение информации о пользователе VK
        # fields=photo_100 - запрашиваем URL фотографии размером 100px
        user_info_url = (
            f"https://api.vk.com/method/users.get?user_ids={vk_user_id}"
            f"&fields=photo_100,screen_name&access_token={access_token}&v=5.199"
        )
        user_info_response = requests.get(user_info_url)
        user_info_response.raise_for_status()
        user_info_data = user_info_response.json().get('response', [])[0]

        db: SessionLocal = next(get_db())
        try:
            user = db.query(User).filter_by(vk_id=vk_user_id).first()
            if not user:
                user = User(
                    vk_id=vk_user_id,
                    first_name=user_info_data.get('first_name'),
                    last_name=user_info_data.get('last_name'),
                    username=user_info_data.get('screen_name'), # или другое поле, если нужно
                    photo_url=user_info_data.get('photo_100')
                )
                db.add(user)
                flash('Добро пожаловать! Ваш аккаунт создан через ВКонтакте.', 'success')
            else:
                # Обновляем данные, если пользователь уже существует
                user.first_name = user_info_data.get('first_name')
                user.last_name = user_info_data.get('last_name')
                user.username = user_info_data.get('screen_name')
                user.photo_url = user_info_data.get('photo_100')
                flash(f'С возвращением через ВКонтакте, {user.first_name}!', 'info')
            
            db.commit()
            session['user_id'] = user.id
            # session['vk_id'] = vk_user_id # Можно сохранить и vk_id в сессии
            return redirect(url_for('index'))
        except Exception as e_db:
            db.rollback()
            print(f"Ошибка работы с БД при VK callback: {e_db}")
            flash('Произошла ошибка на сервере при обработке вашего входа через ВКонтакте.', 'danger')
            return redirect(url_for('login'))
        finally:
            db.close()

    except requests.exceptions.RequestException as e_req:
        print(f"Ошибка запроса к VK API: {e_req}")
        flash('Произошла ошибка при связи с сервером ВКонтакте.', 'danger')
        return redirect(url_for('login'))
    except Exception as e_general:
        print(f"Общая ошибка при VK callback: {e_general}")
        flash('Произошла неизвестная ошибка при входе через ВКонтакте.', 'danger')
        return redirect(url_for('login'))

# Маршрут для обработки данных от виджета Telegram
@app.route('/telegram_callback')
def telegram_callback():
    # Получаем данные пользователя из параметров запроса
    auth_data = request.args.to_dict()

    # Проверяем подпись данных
    is_authenticated = check_telegram_authentication(auth_data)

    if is_authenticated:
        # Подпись верна, данные подлинные
        telegram_id = auth_data.get('id')
        first_name = auth_data.get('first_name')
        last_name = auth_data.get('last_name')
        username = auth_data.get('username')
        photo_url = auth_data.get('photo_url') # URL фото профиля

        db: SessionLocal = next(get_db())
        try:
            # Ищем пользователя в базе данных по telegram_id
            user = db.query(User).filter_by(telegram_id=telegram_id).first()

            if not user:
                # Если пользователя нет, создаем нового
                user = User(
                    telegram_id=telegram_id,
                    first_name=first_name,
                    last_name=last_name,
                    username=username,
                    photo_url=photo_url
                )
                db.add(user)
                db.commit()
                flash('Добро пожаловать! Ваш аккаунт создан.', 'success')
            else:
                # Если пользователь найден, можно обновить его данные (имя, фото и т.д.)
                user.first_name = first_name
                user.last_name = last_name
                user.username = username
                user.photo_url = photo_url
                db.commit()
                flash(f'С возвращением, {user.first_name}!', 'info')

            # Устанавливаем ID пользователя в сессию Flask
            session['user_id'] = user.id
            session['telegram_id'] = telegram_id # Можно сохранить и telegram_id в сессии

            # Перенаправляем пользователя на главную страницу
            return redirect(url_for('index'))
        except Exception as e:
            # Логируем ошибку при работе с БД
            print(f"Ошибка при работе с БД в telegram_callback: {e}")
            db.rollback() # Откатываем изменения в случае ошибки
            flash('Произошла ошибка при обработке вашего входа.', 'danger')
            return redirect(url_for('login'))
        finally:
            db.close()

    else:
        # Подпись неверна, данные поддельные
        flash('Ошибка аутентификации через Telegram.', 'danger')
        return redirect(url_for('login')) # Перенаправляем обратно на страницу входа

# Маршрут для главной страницы
@app.route('/')
@login_required_custom # Apply the decorator
def index(current_user_id): # Receives current_user_id from decorator
    db: SessionLocal = next(get_db())
    try:
        if app.config.get('LOCAL_DEV_NO_LOGIN'):
            dev_user_id = app.config.get('DEFAULT_DEV_USER_ID', 1)
            session['user_id'] = dev_user_id  # Устанавливаем user_id в сессию

            user_for_template = db.query(User).filter_by(id=dev_user_id).first()
            if not user_for_template:
                user_for_template = MockUser(id=dev_user_id) # Use current_user_id from decorator
                flash(f'Локальная разработка: Вход пропущен. Используется мок-пользователь ID {dev_user_id}. Убедитесь, что пользователь с таким ID существует в БД для полного функционала.', 'info')
            else:
                flash(f'Локальная разработка: Вход пропущен. Используется пользователь ID {dev_user_id} из БД.', 'info')
            
            if hasattr(user_for_template, 'telegram_id') and user_for_template.telegram_id:
                session['telegram_id'] = user_for_template.telegram_id
            elif 'telegram_id' not in session: # Если у мок-пользователя нет, ставим заглушку
                session['telegram_id'] = f"mock_tg_{dev_user_id}"
        else:
            user_for_template = db.query(User).filter_by(id=current_user_id).first()
            if not user_for_template:
                # This case should be caught by the decorator, but as a fallback:
                return redirect(url_for('logout')) # Log out if user not found

        return render_template('index.html', date=date, user=user_for_template)
    except Exception as e:
        print(f"Ошибка на главной странице: {e}")
        flash('Произошла ошибка при загрузке страницы.', 'danger')
        # В режиме разработки без логина, если произошла ошибка, все равно пытаемся отрендерить страницу с мок-пользователем
        if app.config.get('LOCAL_DEV_NO_LOGIN') and not user_for_template:
            user_for_template = MockUser(id=current_user_id, first_name="ОшибкаЗагрузки")
            return render_template('index.html', date=date, user=user_for_template)
        return "Произошла ошибка", 500
    finally:
        db.close()

# Маршрут для выхода
@app.route('/logout')
def logout():
    # Удаляем user_id и telegram_id из сессии
    session.pop('user_id', None)
    session.pop('telegram_id', None)
    flash('Вы успешно вышли из системы.', 'info')
    return redirect(url_for('login')) # Перенаправляем на страницу входа

# --- Другие маршруты вашего приложения (например, для отчетов, планов и т.д.) ---
# Убедитесь, что эти маршруты также проверяют session['user_id']
# перед предоставлением доступа к защищенным данным или функциям.

@app.route('/report/new', methods=['GET', 'POST'])
@login_required_custom
def new_report(current_user_id):
    db: SessionLocal = next(get_db())
    
    # Определяем дату для формы (из GET параметра или сегодня)
    form_date_iso = request.args.get('date', datetime.utcnow().date().isoformat())
    form_date_obj = date.fromisoformat(form_date_iso)
    carousel_dates = get_date_carousel_options(selected_date_iso_str=form_date_iso)

    if request.method == 'POST':
        try:
            reviewed_tasks_from_form = [] # Собираем данные для task_checkin_data
            i = 0
            while True:
                task_name_key = f'reviewed_tasks[{i}][name]'
                task_status_key = f'reviewed_tasks[{i}][status]'
                task_comment_key = f'reviewed_tasks[{i}][comment]'
                
                task_name = request.form.get(task_name_key)
                if task_name is None: # No more tasks
                    break
                
                task_status = request.form.get(task_status_key)
                task_comment = request.form.get(task_comment_key, "") # Default to empty string if not present
                
                reviewed_tasks_from_form.append({
                    "name": task_name,
                    "status": task_status,
                    "comment": task_comment
                })
                i += 1

            # Получаем дату из формы (скрытое поле, обновляемое каруселью)
            report_date_iso_from_form = request.form.get('selected_date', datetime.utcnow().date().isoformat())
            report_date_obj = date.fromisoformat(report_date_iso_from_form)

            new_report_entry = DailyReport(
                user_id=current_user_id, 
                date=report_date_obj, # Используем дату из карусели
                reviewed_tasks=json.dumps(reviewed_tasks_from_form), # Save as JSON string
                evening_q1=request.form.get('evening_q1'),
                evening_q2=request.form.get('evening_q2'),
                evening_q3=request.form.get('evening_q3'),
                evening_q4=request.form.get('evening_q4'),
                evening_q5=request.form.get('evening_q5'),
                evening_q6=request.form.get('evening_q6')
            )
            db.add(new_report_entry)
            db.commit()
            
            thread = Thread(target=generate_recommendations_background, args=(app, current_user_id))
            thread.start()

            flash('Отчет успешно сохранен!', 'success')
            return redirect(url_for('index'))
        except Exception as e:
            print(f"Ошибка при сохранении отчета: {e}")
            db.rollback()
            flash('Произошла ошибка при сохранении отчета.', 'danger')
            # Re-fetch tasks for the form for the *originally selected date* in case of error
            plan_on_error_date = db.query(Plan).filter(Plan.user_id == current_user_id, Plan.date == form_date_obj).first()
            goals_for_checkin_on_error = []
            if plan_on_error_date and plan_on_error_date.main_goals:
                try:
                    goals_for_checkin_on_error = json.loads(plan_on_error_date.main_goals)
                except (json.JSONDecodeError, TypeError):
                    goals_for_checkin_on_error = [] # Handle error if JSON is malformed
            return render_template('new_report.html', 
                                   morning_tasks_today=goals_for_checkin_on_error, 
                                   carousel_dates=carousel_dates, 
                                   selected_date_iso=form_date_iso)
        finally:
            db.close()

    # GET request: Fetch tasks from the plan for the selected date
    plan_for_selected_date = db.query(Plan).filter(Plan.user_id == current_user_id, Plan.date == form_date_obj).first()
    morning_tasks_for_form = []
    if plan_for_selected_date and plan_for_selected_date.main_goals:
        try:
            morning_tasks_for_form = json.loads(plan_for_selected_date.main_goals) # Parse JSON string
        except (json.JSONDecodeError, TypeError):
            flash(f'Не удалось загрузить задачи из плана на {form_date_iso} для чекина.', 'warning')
            morning_tasks_for_form = []
    db.close()
    return render_template('new_report.html', 
                           morning_tasks_today=morning_tasks_for_form, 
                           carousel_dates=carousel_dates, 
                           selected_date_iso=form_date_iso)

@app.route('/plan/new', methods=['GET', 'POST'])
@login_required_custom
def new_plan(current_user_id):
    db: SessionLocal = next(get_db())
    try:
        # Определяем дату для формы (из GET параметра или сегодня)
        form_date_iso = request.args.get('date', datetime.utcnow().date().isoformat())
        form_date_obj = date.fromisoformat(form_date_iso)
        carousel_dates = get_date_carousel_options(selected_date_iso_str=form_date_iso)

        if request.method == 'POST':
            try:
                # Получаем дату из формы (скрытое поле, обновляемое каруселью)
                plan_date_iso_from_form = request.form.get('selected_date', datetime.utcnow().date().isoformat())
                plan_date_obj = date.fromisoformat(plan_date_iso_from_form)

                all_task_names_for_main_goals = [] 
                known_task_names_from_selections = set() 

                # 1. Автоматическое добавление задач ОТКЛЮЧЕНО.
                # actually_auto_added_tasks будет пустым списком.
                # Никакие задачи не добавляются в all_task_names_for_main_goals на этом шаге.
                # Если задача выбрана из списка или введена вручную, ее start_date будет обновлена.


                # 2. Задачи, выбранные из предложенных (без даты)
                selected_suggested_ids = request.form.getlist('selected_suggested_task_ids[]')
                if selected_suggested_ids:
                    suggested_items_to_add = db.query(PlanItem).filter(
                        PlanItem.user_id == current_user_id,
                        PlanItem.id.in_([int(id_str) for id_str in selected_suggested_ids if id_str.isdigit()]),
                        PlanItem.item_type.in_([PlanItemType.TASK, PlanItemType.SUBTASK]) # Убедимся, что это задачи/подзадачи
                    ).all()
                    for item in suggested_items_to_add:
                        all_task_names_for_main_goals.append(item.name)
                        known_task_names_from_selections.add(item.name)
                        # Устанавливаем/обновляем дату начала для выбранных задач
                        item.start_date = plan_date_obj 

                # 4. Задачи, введенные вручную
                manual_task_texts_from_form = request.form.getlist('manual_task_text')
                if manual_task_texts_from_form:
                    for task_text in manual_task_texts_from_form:
                        task_text_stripped = task_text.strip()
                        if task_text_stripped:
                            if task_text_stripped not in known_task_names_from_selections:
                                new_manual_pi = PlanItem(
                                    user_id=current_user_id,
                                    name=task_text_stripped,
                                    item_type=PlanItemType.TASK, 
                                    status=PlanItemStatus.TODO,
                                    start_date=plan_date_obj, # Устанавливаем дату начала
                                    description="Задача на день из утреннего планирования (ручной ввод)."
                                )
                                db.add(new_manual_pi)
                            all_task_names_for_main_goals.append(task_text_stripped)

                seen = set()
                final_main_goals_texts = [x for x in all_task_names_for_main_goals if not (x in seen or seen.add(x))]
                plan_main_goals_data = [{'text': name} for name in final_main_goals_texts]

                new_plan_entry = Plan(
                    user_id=current_user_id, 
                    date=plan_date_obj, # Используем дату из карусели
                    main_goals=json.dumps(plan_main_goals_data),
                    morning_q2_improve_day=request.form.get('morning_q2'),
                    morning_q3_mindset=request.form.get('morning_q3'),
                    morning_q4_help_others=request.form.get('morning_q4'),
                    morning_q5_inspiration=request.form.get('morning_q5'),
                    morning_q6_health_care=request.form.get('morning_q6')
                )
                db.add(new_plan_entry)
                db.commit()

                thread = Thread(target=generate_recommendations_background, args=(app, current_user_id))
                thread.start()

                flash('План успешно сохранен!', 'success')
                return redirect(url_for('index'))
            except Exception as e:
                print(f"Ошибка при сохранении плана: {e}")
                db.rollback()
                flash('Произошла ошибка при сохранении плана.', 'danger')
                # Re-fetch data for the form for the *originally selected date*
                
                # Автоматически добавленные задачи теперь всегда пустой список
                auto_added_tasks_error = []
                auto_added_error_ids = set() # Соответственно, ID тоже нет


                # Query for selectable tasks on error
                from sqlalchemy import or_, and_
                potential_selectable_tasks_error_query = db.query(PlanItem).filter(
                    PlanItem.user_id == current_user_id,
                    PlanItem.item_type.in_([PlanItemType.TASK, PlanItemType.SUBTASK]),
                    PlanItem.status == PlanItemStatus.TODO # Показываем только задачи "К выполнению"
                    # or_(PlanItem.status.is_(None), PlanItem.status.notin_([PlanItemStatus.DONE, PlanItemStatus.CANCELLED])) # Старая логика
                ) # Фильтр .notin_(auto_added_error_ids) не нужен, т.к. auto_added_error_ids пуст

                selectable_tasks_error = potential_selectable_tasks_error_query.order_by(PlanItem.name).all()
                
                return render_template('new_plan.html', 
                                       auto_added_tasks=auto_added_tasks_error, 
                                       selectable_tasks=selectable_tasks_error, 
                                       carousel_dates=carousel_dates, 
                                       selected_date_iso=form_date_iso)

        # GET request:
        # 1. Автоматически добавленные задачи - теперь всегда пустой список
        auto_added_tasks = []
        auto_added_task_ids = set() # Соответственно, ID тоже нет

        # 2. Задачи для выбора из Планировщика (все активные задачи и подзадачи)
        from sqlalchemy import or_, and_
        selectable_tasks_query = db.query(PlanItem).filter(
            PlanItem.user_id == current_user_id,
            PlanItem.item_type.in_([PlanItemType.TASK, PlanItemType.SUBTASK]),
            PlanItem.status == PlanItemStatus.TODO # Показываем только задачи "К выполнению"
            # or_(PlanItem.status.is_(None), PlanItem.status.notin_([PlanItemStatus.DONE, PlanItemStatus.CANCELLED])) # Старая логика
        ) # Фильтр .notin_(auto_added_task_ids) не нужен, т.к. auto_added_task_ids пуст

        selectable_tasks = selectable_tasks_query.order_by(PlanItem.name).all()
        
        return render_template('new_plan.html', auto_added_tasks=auto_added_tasks, selectable_tasks=selectable_tasks, carousel_dates=carousel_dates, selected_date_iso=form_date_iso)
    
    except Exception as e:
        print(f"Ошибка при загрузке формы плана: {e}")
        flash('Произошла ошибка при загрузке формы плана.', 'danger')
        
        _form_date_iso_to_render = datetime.utcnow().date().isoformat()
        _carousel_dates_to_render = []

        # Check if form_date_iso was defined in the try block before the error
        if 'form_date_iso' in locals() and locals()['form_date_iso']: # Check existence and non-emptiness
            _form_date_iso_to_render = locals()['form_date_iso']
        
        # Check if carousel_dates was defined in the try block before the error
        if 'carousel_dates' in locals() and locals()['carousel_dates']: # Check existence and non-emptiness
            _carousel_dates_to_render = locals()['carousel_dates']
        else:
            # If carousel_dates failed to initialize (e.g., due to an error in get_date_carousel_options)
            # provide a minimal default. This assumes get_date_carousel_options might fail.
            try:
                # This relies on timedelta being imported globally (which should be the case).
                _carousel_dates_to_render = get_date_carousel_options(selected_date_iso_str=_form_date_iso_to_render)
            except Exception as fallback_carousel_error:
                print(f"Error creating fallback carousel in new_plan error handler: {fallback_carousel_error}")
                _today = date.today()
                _carousel_dates_to_render = [{'display_text': 'Сегодня', 'iso_value': _today.isoformat(), 'is_selected': True}]

        return render_template('new_plan.html', 
                               auto_added_tasks=[], 
                               selectable_tasks=[], 
                               carousel_dates=_carousel_dates_to_render, 
                               selected_date_iso=_form_date_iso_to_render)
    finally:
        db.close()

@app.route('/emotional_report/new', methods=['GET', 'POST'])
@login_required_custom
def new_emotional_report(current_user_id):
    db: SessionLocal = next(get_db())

    form_date_iso = request.args.get('date', datetime.utcnow().date().isoformat())
    # form_date_obj = date.fromisoformat(form_date_iso) # Не используется в GET для этой формы
    carousel_dates = get_date_carousel_options(selected_date_iso_str=form_date_iso)

    if request.method == 'POST':
        try:
            report_date_iso_from_form = request.form.get('selected_date', datetime.utcnow().date().isoformat())
            report_date_obj = date.fromisoformat(report_date_iso_from_form)

            situation = request.form['situation']
            thought = request.form['thought']
            feelings = request.form['feelings']
            correction = request.form.get('correction')
            new_feelings = request.form.get('new_feelings')
            impact = request.form['impact']
            # correction_hint_used не собирается из веб-формы напрямую, будет None
            new_emotional_report_entry = EmotionalReport(user_id=current_user_id, 
                                                   date=datetime.utcnow().date(), # Используем UTC дату
                                                   situation=situation, thought=thought, feelings=feelings,
                                                   correction=correction,
                                                   new_feelings=new_feelings,
                                                   impact=impact)
            db.add(new_emotional_report_entry)
            db.commit()

            # Запускаем генерацию рекомендаций в фоне
            # (после сохранения эмоционального отчета)
            
            thread = Thread(target=generate_recommendations_background, args=(app, current_user_id))
            thread.start()

            flash('Эмоциональный отчет успешно сохранен!', 'success')
            return redirect(url_for('index'))
        except Exception as e:
            print(f"Ошибка при сохранении эмоционального отчета: {e}")
            db.rollback()
            flash('Произошла ошибка при сохранении эмоционального отчета.', 'danger')
            return render_template('new_emotional_report.html', carousel_dates=carousel_dates, selected_date_iso=form_date_iso)
        finally:
            db.close()

    return render_template('new_emotional_report.html', carousel_dates=carousel_dates, selected_date_iso=form_date_iso)


@app.route('/view/<view_date>')
@login_required_custom
def view_data(current_user_id, view_date):
    db: SessionLocal = next(get_db())
    try:
        # Убедитесь, что модели DailyReport, Plan, EmotionalReport импортированы из models.py
        report_db = db.query(DailyReport).filter(DailyReport.user_id == current_user_id, DailyReport.date == view_date).first()
        plan_db = db.query(Plan).filter(Plan.user_id == current_user_id, Plan.date == view_date).first()
        emotional_reports = db.query(EmotionalReport).filter(EmotionalReport.user_id == current_user_id, EmotionalReport.date == view_date).all()
        recommendations_for_date = db.query(Recommendation).filter(Recommendation.user_id == current_user_id, Recommendation.date == view_date).order_by(desc(Recommendation.id)).all()

        plan = None
        if plan_db:
            plan = plan_db
            if plan.main_goals:
                try:
                    plan.main_goals = json.loads(plan.main_goals) # Parse JSON for template
                except (json.JSONDecodeError, TypeError): plan.main_goals = [] # Handle error
        
        report = None
        if report_db:
            report = report_db
            if report.reviewed_tasks:
                try:
                    # Проверяем, что reviewed_tasks это строка, перед json.loads
                    if isinstance(report.reviewed_tasks, str):
                        report.reviewed_tasks = json.loads(report.reviewed_tasks) 
                    elif report.reviewed_tasks is None: # Если None, делаем пустым списком
                        report.reviewed_tasks = []
                    # Если это уже список (например, после предыдущей обработки), оставляем как есть
                    report.reviewed_tasks = json.loads(report.reviewed_tasks) # Parse JSON for template
                except (json.JSONDecodeError, TypeError): report.reviewed_tasks = [] # Handle error

        return render_template('view_data.html', view_date=view_date, report=report, plan=plan, emotional_reports=emotional_reports, recommendations_for_date=recommendations_for_date)
    except Exception as e:
            print(f"Ошибка при просмотре данных: {e}")
            flash('Произошла ошибка при загрузке данных.', 'danger')
            return redirect(url_for('index'))
    finally:
        db.close()


@app.route('/recommendations')
@login_required_custom
def recommendations(user_id_for_query):

    db: SessionLocal = next(get_db())
    try:
        user_recommendations = db.query(Recommendation).filter(Recommendation.user_id == user_id_for_query).order_by(desc(Recommendation.date), desc(Recommendation.id)).all()
        return render_template('recommendations.html', recommendations_list=user_recommendations)
    except Exception as e:
        print(f"Ошибка при загрузке рекомендаций: {e}")
        flash('Не удалось загрузить рекомендации.', 'danger')
        return redirect(url_for('index'))
    finally:
        db.close()

@app.route('/recommendations/weekly', methods=['GET', 'POST'])
@login_required_custom
def weekly_recommendations_page(user_id_for_query):

    if request.method == 'POST':
        try:
            # Запускаем генерацию еженедельных рекомендаций в фоне
            
            thread = Thread(target=generate_weekly_recommendations_background, args=(app, user_id_for_query))
            thread.start()
            flash('Запрос на генерацию еженедельного обзора отправлен. Он появится на странице рекомендаций через некоторое время.', 'info')
            return redirect(url_for('recommendations')) # Перенаправляем на общую страницу рекомендаций
        except Exception as e:
            print(f"Ошибка при запуске генерации еженедельных рекомендаций: {e}")
            flash('Не удалось запустить генерацию еженедельного обзора.', 'danger')
            return redirect(url_for('recommendations'))

    # Для GET запроса просто отображаем страницу с кнопкой
    # Можно также передать информацию о том, когда была последняя генерация, если это нужно
    return render_template('weekly_recommendations_trigger.html')




# --- Маршруты для Планировщика Миссий/Проектов/Задач ---

@app.route('/planning')
@login_required_custom
def planning_page(user_id_for_page):
    return render_template('planning.html', user_id=user_id_for_page)

@app.route('/api/planning_items/selectable', methods=['GET'])
@login_required_custom # Note: Decorator flashes and redirects for non-API. For API, might want different behavior.
def get_selectable_planning_items(user_id): # User ID from decorator
    # If decorator redirects, this code won't run.
    # For pure API, decorator might need adjustment to return 401/403 instead of redirect.
    # For now, assuming this is called from an authenticated web page context.
    db: SessionLocal = next(get_db())
    try:
        items = db.query(PlanItem).filter(PlanItem.user_id == user_id, PlanItem.item_type.in_(['TASK', 'PROJECT', 'GOAL', 'SUBTASK'])).order_by(PlanItem.item_type, PlanItem.name).all()
        return jsonify([{"id": item.id, "text": f"{item.name} ({item.item_type.value if item.item_type else 'N/A'})"} for item in items])
    except Exception as e:
        return jsonify({"error": "Could not fetch selectable items", "details": str(e)}), 500
    finally:
        db.close()

@app.route('/api/planning_items', methods=['GET'])
def get_planning_items():
    user_id = None
    if app.config.get('LOCAL_DEV_NO_LOGIN'):
        user_id = app.config.get('DEFAULT_DEV_USER_ID', 1)
    elif 'user_id' in session:
        user_id = session['user_id']
    else:
        return jsonify({"error": "Unauthorized"}), 401

    db: SessionLocal = next(get_db())
    try:
        statuses_from_request = request.args.getlist('status') # Получаем список статусов из GET-параметров

        # jsTree ожидает плоский список элементов, где каждый имеет id и parent
        # Метод to_dict() в PlanItem должен это учитывать
        query = db.query(PlanItem).filter(PlanItem.user_id == user_id)

        if statuses_from_request:
            valid_status_enums = []
            for status_str in statuses_from_request:
                try:
                    # Преобразуем строковое значение статуса в соответствующий Enum член
                    status_enum = PlanItemStatus[status_str.upper()]
                    valid_status_enums.append(status_enum)
                except KeyError:
                    # Игнорируем невалидные значения статусов, можно добавить логирование
                    app.logger.warn(f"Invalid status filter value received: {status_str}")
            
            if valid_status_enums:
                query = query.filter(PlanItem.status.in_(valid_status_enums))

        items = query.order_by(PlanItem.item_type, PlanItem.name).all() # Сортировка для лучшего отображения
        # Преобразуем в формат, подходящий для jsTree
        # jsTree сам построит иерархию на основе 'id' и 'parent' полей
        tree_data = [item.to_dict(include_children=False) for item in items] # include_children=False для плоского списка
        return jsonify(tree_data)
    except Exception as e:
        print(f"Ошибка при получении элементов планирования: {e}")
        db.rollback()
        return jsonify({"error": "Could not fetch items", "details": str(e)}), 500
    finally:
        db.close()

@app.route('/api/planning_items', methods=['POST'])
@login_required_custom 
def create_planning_item(user_id):

    data = request.json
    if not data or not data.get('name') or not data.get('item_type'):
        return jsonify({"error": "Missing name or item_type"}), 400

    db: SessionLocal = next(get_db())
    try:
        parent_id_str = data.get('parent_id')
        parent_id_int = int(parent_id_str) if parent_id_str and parent_id_str != "#" else None

        new_item = PlanItem(
            user_id=user_id,
            parent_id=parent_id_int,
            item_type=data['item_type'],
            name=data['name'],
            description=data.get('description'),
            status=data.get('status', 'TODO'),
            start_date=date.fromisoformat(data['start_date']) if data.get('start_date') else None # Обработка start_date
        )
        db.add(new_item)
        db.commit()
        db.refresh(new_item)
        return jsonify(new_item.to_dict(include_children=False)), 201
    except Exception as e:
        db.rollback()
        print(f"Ошибка при создании элемента планирования: {e}")
        return jsonify({"error": "Could not create item", "details": str(e)}), 500
    finally:
        db.close()

@app.route('/api/planning_items/<int:item_id>', methods=['PUT'])
@login_required_custom
def update_planning_item(user_id, item_id):

    db: SessionLocal = next(get_db())
    try:
        item = db.query(PlanItem).filter(PlanItem.id == item_id, PlanItem.user_id == user_id).first()
        if not item:
            return jsonify({"error": "Item not found"}), 404

        data = request.json
        if 'name' in data: item.name = data['name']
        if 'description' in data: item.description = data['description']
        if 'status' in data: item.status = data['status']
        if 'item_type' in data: item.item_type = data['item_type'] # Обычно тип не меняют, но возможно
        if 'parent_id' in data: # Для DND (перемещения узлов)
            item.parent_id = int(data['parent_id']) if data['parent_id'] and data['parent_id'] != "#" else None
        if 'start_date' in data: # Обновление даты начала
            item.start_date = date.fromisoformat(data['start_date']) if data.get('start_date') else None

        db.commit()
        db.refresh(item)
        return jsonify(item.to_dict(include_children=False))
    except Exception as e:
        db.rollback()
        print(f"Ошибка при обновлении элемента планирования: {e}")
        return jsonify({"error": "Could not update item", "details": str(e)}), 500
    finally:
        db.close()

@app.route('/api/planning_items/<int:item_id>', methods=['DELETE'])
@login_required_custom
def delete_planning_item(user_id, item_id):

    db: SessionLocal = next(get_db())
    try:
        item = db.query(PlanItem).filter(PlanItem.id == item_id, PlanItem.user_id == user_id).first()
        if not item:
            return jsonify({"error": "Item not found"}), 404

        db.delete(item) # SQLAlchemy обработает каскадное удаление, если настроено
        db.commit()
        return jsonify({"message": "Item deleted successfully"}), 200
    except Exception as e:
        db.rollback()
        print(f"Ошибка при удалении элемента планирования: {e}")
        return jsonify({"error": "Could not delete item", "details": str(e)}), 500
    finally:
        db.close()

@app.route('/api/planning/generate_tree_ai', methods=['POST'])
@login_required_custom # user_id is passed but not strictly used by current AI prompt
def generate_tree_ai(user_id): 

    # data = request.json # Если будете передавать промпт с клиента
    # user_prompt_from_client = data.get("prompt", "...")

    user_prompt = (
        "Создай пример древовидной структуры задач для проекта 'Разработка личного органайзера Reflect Wise'. "
        "Включи миссии (1-2), проекты (2-3 для каждой миссии) и задачи (3-5 для каждого проекта). "
        "Представь результат в виде JSON массива. Каждый элемент массива должен быть объектом, представляющим узел дерева. "
        "Каждый узел должен иметь следующие поля: "
        "'id' (уникальный строковый идентификатор, например 'm1', 'p1.1', 't1.1.1'), "
        "'parent' (строковый идентификатор родительского узла, или '#' для корневых узлов/миссий), "
        "'text' (название узла), "
        "'type' (строка: 'MISSION', 'PROJECT', или 'TASK'). "
        "Убедись, что структура JSON корректна и готова для использования с jsTree."
        "\nПример одного узла: {\"id\": \"m1\", \"parent\": \"#\", \"text\": \"Стать лучшей версией себя\", \"type\": \"MISSION\"}"
        "\nПример дочернего узла: {\"id\": \"p1.1\", \"parent\": \"m1\", \"text\": \"Разработать приложение для рефлексии\", \"type\": \"PROJECT\"}"
    )

    try:
        import g4f
        import json

        raw_response = g4f.ChatCompletion.create(
            model=g4f.models.default, # или g4f.models.gpt_4
            messages=[{"role": "user", "content": user_prompt}],
        )

        ai_tree_data = []
        # Попытка извлечь JSON из ответа g4f
        # Ищем начало '[' и конец ']' JSON массива
        json_start = raw_response.find('[')
        json_end = raw_response.rfind(']') + 1

        if json_start != -1 and json_end != -1 and json_start < json_end:
            json_string = raw_response[json_start:json_end]
            try:
                ai_tree_data = json.loads(json_string)
                # Простая валидация структуры для jsTree
                if not isinstance(ai_tree_data, list) or not all(
                    isinstance(item, dict) and 'id' in item and 'parent' in item and 'text' in item and 'type' in item
                    for item in ai_tree_data
                ):
                    print(f"AI response parsed as JSON, but not in expected jsTree format: {json_string}")
                    # Можно попытаться обернуть, если это один объект, но промпт просит массив
                    if isinstance(ai_tree_data, dict) and 'id' in ai_tree_data : # Если это один объект, а не массив
                         ai_tree_data = [ai_tree_data] # Оборачиваем в список
                    else: # Если формат все равно не тот
                         raise ValueError("AI response is not a valid list of jsTree nodes.")
            except json.JSONDecodeError as e:
                print(f"Ошибка декодирования JSON ответа от AI: {json_string}. Ошибка: {e}")
                ai_tree_data = [{"id": "err_parse", "parent": "#", "text": "Ошибка парсинга ответа AI. Ответ был: " + raw_response[:200] + "...", "type": "ERROR"}]
            except ValueError as e: # Наша кастомная ошибка валидации
                 ai_tree_data = [{"id": "err_format", "parent": "#", "text": str(e) + " Ответ: " + raw_response[:200] + "...", "type": "ERROR"}]
        else:
            print(f"Не удалось найти JSON массив в ответе AI: {raw_response}")
            ai_tree_data = [{"id": "err_no_json", "parent": "#", "text": "AI не вернул ожидаемый JSON массив. Ответ: " + raw_response[:200] + "...", "type": "ERROR"}]

        return jsonify(ai_tree_data)
    except Exception as e:
        print(f"Ошибка при генерации дерева AI: {e}")
        return jsonify([{"id": "err_general", "parent": "#", "text": f"Ошибка генерации AI дерева: {str(e)}", "type": "ERROR"}]), 500

@app.route('/api/planning/save_ai_tree', methods=['POST'])
@login_required_custom
def save_ai_tree(user_id):

    request_data = request.json
    ai_tree_nodes = request_data.get("tree_data")

    if not isinstance(ai_tree_nodes, list):
        return jsonify({"error": "Invalid input: tree_data must be a list"}), 400

    db: SessionLocal = next(get_db())
    ai_id_to_db_id_map = {}
    created_items_for_response = []
    temp_ai_id_to_new_item_obj = {}

    try:
        # First pass: Create PlanItem objects from AI data, add to session, but don't set parent_id yet.
        # This allows us to handle nodes even if they appear before their parents in the AI's list.
        for node_data in ai_tree_nodes:
            if not all(k in node_data for k in ('id', 'parent', 'text', 'type')):
                # Skip malformed nodes or return an error
                print(f"Skipping malformed node: {node_data}")
                continue

            node_start_date = None
            if node_data.get('start_date'):
                try:
                    node_start_date = date.fromisoformat(node_data['start_date'])
                except ValueError:
                    print(f"Warning: Invalid start_date format for node {node_data.get('id')}")
                    # Keep node_start_date as None

            new_item = PlanItem(
                user_id=user_id,
                name=node_data['text'],
                item_type=node_data['type'],
                description=node_data.get('description'), # Optional
                status=node_data.get('status', 'TODO'),   # Optional, default
                start_date=node_start_date                # Optional
                # parent_id will be set after all items have DB IDs
            )
            db.add(new_item)
            temp_ai_id_to_new_item_obj[node_data['id']] = new_item

        db.flush() # Assign database IDs to all newly added items

        # Second pass: Now that all items have DB IDs, set their parent_id
        for ai_id, item_obj in temp_ai_id_to_new_item_obj.items():
            ai_id_to_db_id_map[ai_id] = item_obj.id # Map AI's string ID to new DB integer ID

            original_node_data = next((n for n in ai_tree_nodes if n['id'] == ai_id), None)
            if original_node_data:
                parent_ai_id = original_node_data.get('parent')
                if parent_ai_id and parent_ai_id != "#":
                    parent_db_id = ai_id_to_db_id_map.get(parent_ai_id)
                    if parent_db_id:
                        item_obj.parent_id = parent_db_id
                    else:
                        print(f"Warning: Parent AI ID '{parent_ai_id}' for item '{ai_id}' not found in map. Item will be root.")

        db.commit() # Commit all changes, including parent_id updates

        for item_obj in temp_ai_id_to_new_item_obj.values():
            db.refresh(item_obj) # Ensure all relationships are loaded for the response
            created_items_for_response.append(item_obj.to_dict(include_children=False))

        return jsonify(created_items_for_response), 201
    except Exception as e:
        db.rollback()
        print(f"Ошибка при сохранении AI-сгенерированного дерева: {e}")
        return jsonify({"error": "Could not save AI-generated tree", "details": str(e)}), 500
    finally:
        db.close()

@app.route('/api/planning/suggest_children_ai', methods=['POST'])
@login_required_custom # user_id is passed but not strictly used by current AI prompt
def suggest_children_ai(user_id):

    data = request.json
    parent_name = data.get("name")
    parent_type = data.get("type")
    parent_description = data.get("description", "")

    if not parent_name or not parent_type:
        return jsonify({"error": "Missing parent name or type"}), 400

    child_type_map = {
        "MISSION": "Проекты или Цели",
        "GOAL": "Проекты или Задачи",
        "PROJECT": "Задачи",
        "TASK": "Подзадачи",
        "SUBTASK": "Подзадачи" # Для подзадач тоже могут быть подзадачи
    }
    suggested_child_type_description = child_type_map.get(parent_type, "элементы")

    prompt = (
        f"Для существующего элемента '{parent_name}' (тип: {parent_type}), "
        f"с описанием: '{parent_description if parent_description else 'Нет описания'}', "
        f"предложи 2-3 дочерних элемента типа '{suggested_child_type_description}'. "
        "Верни результат в виде JSON массива объектов. Каждый объект должен иметь поля 'text' (название предлагаемого элемента) и 'type' (предлагаемый тип: GOAL, PROJECT, TASK, SUBTASK, в зависимости от родителя). "
        "Например: [{\"text\": \"Название подзадачи 1\", \"type\": \"TASK\"}, {\"text\": \"Название подзадачи 2\", \"type\": \"TASK\"}]"
    )

    try:
        import g4f
        import json
        raw_response = g4f.ChatCompletion.create(
            model=g4f.models.default,
            messages=[{"role": "user", "content": prompt}],
        )
        # Простой парсинг JSON из ответа
        suggested_children = json.loads(raw_response)
        return jsonify(suggested_children)
    except Exception as e:
        print(f"Ошибка при предложении дочерних элементов AI: {e}")
        return jsonify({"error": "Could not suggest children", "details": str(e)}), 500

# Удалена функция add_security_headers

if __name__ == '__main__':
    app.run(debug=True)
