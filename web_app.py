import os
import hashlib
import hmac
import urllib.parse
import time  # Для time.sleep
import markdown  # Для обработки markdown
import json  # Для работы с JSON для main_goals и task_checkin_data
import requests # Для HTTP-запросов к VK API 
from functools import wraps # Добавлен импорт timezone
from datetime import datetime, date, timedelta, timezone
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, make_response # Добавлен make_response
from sqlalchemy import desc, func as sqlalchemy_func # desc для сортировки, func для random
# Импортируем SessionLocal, engine и get_db из models.py, Boolean, HabitFrequencyType
# Убедитесь, что модели DailyReport, Plan, EmotionalReport, User, PlanItemPriority импортированы
# Добавлены импорты Recommendation, PlanItem, PlanItemStatus, PlanItemType, PlanItemPriority, Habit, DailyHabitEntry, Achievement, UserAchievement, DailySurvey
from models import Base, Plan, DailyReport, User, Recommendation, PlanItem, PlanItemStatus, PlanItemType, PlanItemPriority, SessionLocal, engine, get_db, DailySphereQuest, SphereQuestTask, Habit, DailyHabitEntry, Achievement, UserAchievement, HabitFrequencyType, DailySurvey # EmotionalReport заменен на DailySurvey
from threading import Thread
from config import Config # Добавлен импорт Config
import random # Добавлен для get_random_tasks

app = Flask(__name__)
# Применяем конфигурацию из класса Config
app.config.from_object(Config)

# --- Мок-пользователь для локальной разработки без логина ---
class MockUser:
    def __init__(self, id, first_name="Разработчик", last_name="", username="dev_user", photo_url=None, telegram_id=None, vk_id=None, created_at=None):
        self.id = id
        self.first_name = first_name
        self.last_name = last_name
        self.username = username
        self.photo_url = photo_url
        self.telegram_id = telegram_id if telegram_id else f"mock_tg_{id}"
        self.vk_id = vk_id
        self.created_at = created_at if created_at else datetime.now(timezone.utc)

# --- Настройка базы данных ---
# Движок (engine) и фабрика сессий (SessionLocal) теперь ИМПОРТИРУЮТСЯ из models.py.
# Удален повторный вызов create_engine и Session = sessionmaker(...) здесь.

# Временное создание таблиц.
# Эту строку нужно ЗАКОММЕНТИРОВАТЬ или УДАЛИТЬ после того, как таблицы будут созданы в БД на Render.
# Она создаст таблицы DailyReport, Plan, EmotionalReport, User.

Base.metadata.create_all(engine) # Убедитесь, что таблица Recommendation также создается


# Функция для получения сессии базы данных (импортируется из models.py)

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
                    # Проверяем, является ли запрос API-запросом
                    if request.accept_mimetypes.accept_json and \
                       not request.accept_mimetypes.accept_html: # Эвристика для API
                        return jsonify(error="Сессия недействительна или истекла."), 401
                    else:
                        flash('Ваша сессия истекла или недействительна. Пожалуйста, войдите снова.', 'warning')
                        return redirect(url_for('login'))
            else:
                # Проверяем, является ли запрос API-запросом
                if request.accept_mimetypes.accept_json and \
                   not request.accept_mimetypes.accept_html: # Эвристика для API
                    return jsonify(error="Требуется аутентификация."), 401
                else:
                    flash('Пожалуйста, войдите для доступа к этой странице.', 'warning')
                    return redirect(url_for('login'))
            
            return f(current_user_id, *args, **kwargs) # Pass user_id to the route
        finally:
            if db_for_check:
                db_for_check.close()
    return decorated_function

# --- Обеспечение существования пользователя по умолчанию для локальной разработки ---
# Этот блок должен выполняться один раз при старте приложения, если LOCAL_DEV_NO_LOGIN включен.
if app.config.get('LOCAL_DEV_NO_LOGIN'):
    with app.app_context(): # Гарантируем контекст приложения для доступа к app.config
        default_user_id_val = app.config.get('DEFAULT_DEV_NO_LOGIN_USER_ID', 1) # Используем более явное имя для ID
        db_startup_check = SessionLocal()
        try:
            user = db_startup_check.query(User).filter_by(id=default_user_id_val).first()
            if not user:
                print(f"LOCAL_DEV_NO_LOGIN: Default user ID {default_user_id_val} not found. Creating...")
                default_user = User(
                    id=default_user_id_val, # Устанавливаем ID явно
                    first_name="Dev",
                    last_name="User",
                    username=f"dev_user_{default_user_id_val}",
                    telegram_id=f"mock_tg_{default_user_id_val}" # Генерируем мок-ID
                )
                db_startup_check.add(default_user)
                db_startup_check.commit()
                print(f"LOCAL_DEV_NO_LOGIN: Default user ID {default_user_id_val} created.")
        except Exception as e_startup:
            db_startup_check.rollback()
            print(f"Error ensuring default dev user: {e_startup}")
        finally:
            db_startup_check.close()
# --- Константы для Квеста Развития Сфер ---
SPHERE_DEFINITIONS = {
    "Здоровье": [
        "Выпил 1,5-2 литра воды", "30 минут физической активности", "7-8 часов качественного сна",
        "Съел 2-3 порции овощей/фруктов", "Сделал разминку для глаз и спины", "5-10 минут дыхательных практик",
        "Измерил пульс/давление (если нужно)", "Избегал вредных перекусов", "Проверил осанку (3+ раза за день)",
        "Поблагодарил тело за работу"
    ],
    "Саморазвитие": [
        "Выучил 5 новых иностранных слов", "Прочитал 10+ страниц книги по развитию", "Записал 1 инсайт о своем прогрессе",
        "Практиковал новый навык 15+ минут", "Проанализировал ошибку → извлек урок", "Сделал шаг вне зоны комфорта",
        "Посмотрел образовательное видео/подкаст", "Обновил личный план развития", "Пообщался с вдохновляющим человеком",
        "Подвел итоги недели в дневнике"
    ],
    "Карьера/Труд": [
        "Выполнил 1 важную задачу из TOP-3", "Улучшил 1 рабочий процесс", "Узнал что-то новое в своей профессии",
        "Сделал полезный контакт/нетворкинг", "Подготовился к завтрашнему рабочему дню", "Отметил 3 рабочих достижения (даже мелкие)",
        "Инвестировал в профессиональный инструмент", "Оптимизировал 1 рутинную операцию", "Получил или дал обратную связь",
        "Визуализировал карьерные цели"
    ],
    "Общество/Социальная жизнь": [
        "Написал/позвонил близкому человеку", "Сделал комплимент или выразил благодарность", "Участвовал в групповой активности",
        "Помог кому-то безвозмездно", "Устроил встречу с друзьями/коллегами", "Практиковал активное слушание",
        "Поделился полезной информацией", "Поддержал чужую инициативу", "Узнал что-то новое о близких",
        "Запланировал социальное событие"
    ],
    "Интеллект": [
        "Решил логическую задачу/головоломку", "Проанализировал сложную информацию", "Записал 3 нестандартные идеи",
        "Обсудил интеллектуальную тему", "Почитал научно-популярную статью", "Поиграл в стратегическую игру",
        "Провел мозговой штурм на 10+ идей", "Изучил мнение эксперта по важному вопросу", "Сравнил разные точки зрения",
        "Тренировал критическое мышление"
    ],
    "Навыки": [ 
        "Практиковал ключевой навык 20+ минут", "Изучил новый прием/технику", "Исправил 1 ошибку в технике выполнения",
        "Сравнил свой уровень с месяц назад", "Подготовил инструменты/материалы", "Посмотрел обучающий ролик",
        "Получил обратную связь от знатока", "Экспериментировал с новым подходом", "Записал прогресс в дневнике навыков",
        "Поделился умением с другим человеком"
    ],
    "Знания": [ 
        "Прочитал 10+ страниц nonfiction", "Выучил 5+ новых терминов/фактов", "Повторил конспекты за прошлый месяц",
        "Послушал образовательный подкаст", "Сделал заметки по новой теме", "Сравнил 2 источника информации",
        "Нашел ответ на сложный вопрос", "Практиковал иностранный язык", "Обсудил новое знание с кем-то",
        "Добавил материал в \"базу знаний\""
    ],
    "Эмоциональное благополучие": [
        "Определил свои эмоции (3+ раза за день)", "Применил технику снижения стресса", "Порадовал себя маленьким удовольствием",
        "Проанализировал триггеры настроения", "Практиковал благодарность (записал 3 пункта)", "Избегал токсичных мыслей/разговоров",
        "Сделал паузу перед эмоциональной реакцией", "Насладился моментом \"здесь и сейчас\"", "Выразил чувства творчески (рисунок, текст)",
        "Провел \"эмоциональную уборку\""
    ],
    "Духовное развитие": [
        "10+ минут медитации/молитвы", "Перечитал свои ценности и миссию", "Записал 1 экзистенциальный инсайт",
        "Проанализировал уроки сложных событий", "Практиковал осознанность в рутине", "Читал вдохновляющую литературу",
        "Создал \"капсулу мудрости\" для себя", "Поразмышлял о вечных вопросах", "Сделал что-то альтруистичное",
        "Синхронизировал действия с ценностями"
    ],
    "Финансы": [
        "Зафиксировал все доходы/расходы", "Инвестировал (деньги/время в знания)", "Оптимизировал 1 статью расходов",
        "Изучил финансовые новости/тренды", "Проверил состояние накоплений", "Обновил финансовые цели",
        "Обсудил деньги с экспертом/партнером", "Автоматизировал 1 финансовый процесс", "Изучил опыт успешных инвесторов",
        "Планировал крупные покупки"
    ],
    "Отдых и развлечения": [
        "Выделил 1+ час на чистое удовольствие", "Попробовал что-то новое для развлечения", "Полностью отключился от работы",
        "Посетил новое место (даже виртуально)", "Восстановил силы через хобби", "Посмеялся/посмотрел что-то легкое",
        "Поиграл (в игры, спорт, творчество)", "Устроил цифровой детокс (2+ часа)", "Насладился искусством (кино, музыка)",
        "Планировал будущие впечатления"
    ],
    "Безопасность и комфорт": [
        "Проверил рабочее/жилое пространство", "Улучшил 1 элемент быта", "Подготовил экстренные контакты",
        "Оптимизировал домашние процессы", "Обновил страховки/гарантии", "Создал \"зону покоя\" без гаджетов",
        "Провел профилактику техники", "Запасся необходимыми средствами", "Улучшил экологию пространства",
        "Планировал долгосрочный комфорт"
    ]
}

ALL_SPHERE_TASKS = []
for sphere, tasks in SPHERE_DEFINITIONS.items():
    for task_text in tasks:
        ALL_SPHERE_TASKS.append({"sphere": sphere, "text": task_text})

MAX_REPLACEMENTS_PER_QUEST = 2
# INITIAL_QUEST_TASK_COUNT больше не используется напрямую, количество определяется сложностью

def get_random_tasks(exclude_tasks_texts=None, priority_sphere_name=None, difficulty_level='medium', num_to_return=None):
    """
    Выбирает случайные задачи, исключая уже существующие и учитывая приоритетную сферу, сложность и желаемое количество.
    """
    if exclude_tasks_texts is None:
        exclude_tasks_texts = []

    # Определяем количество задач в зависимости от сложности
    if num_to_return is None:
        if difficulty_level == 'easy':
            base_count = 5
        elif difficulty_level == 'hard':
            base_count = 9
        else: # medium или default
            base_count = 7
    else:
        base_count = num_to_return

    actual_count = base_count # Используем actual_count для дальнейшей логики, чтобы не менять слишком много

    available_tasks = [
        task for task in ALL_SPHERE_TASKS 
        if task["text"] not in exclude_tasks_texts
    ]
    if not available_tasks:
        return []

    selected_tasks = []
    
    # Если установлена приоритетная сфера, пытаемся выбрать из нее задачи
    if priority_sphere_name and priority_sphere_name in SPHERE_DEFINITIONS:
        priority_tasks_available = [
            task for task in available_tasks if task["sphere"] == priority_sphere_name
        ]
        num_priority_to_pick = 0
        if difficulty_level == 'easy': num_priority_to_pick = 2 
        elif difficulty_level == 'medium': num_priority_to_pick = 3 
        elif difficulty_level == 'hard': num_priority_to_pick = 4   
        
        picked_priority_tasks = random.sample(
            priority_tasks_available, 
            min(len(priority_tasks_available), num_priority_to_pick)
        )
        selected_tasks.extend(picked_priority_tasks)
        
        # Обновляем доступные задачи, исключая уже выбранные приоритетные
        picked_texts = {t['text'] for t in picked_priority_tasks}
        available_tasks = [task for task in available_tasks if task['text'] not in picked_texts]

    # Заполняем оставшиеся места случайными задачами
    remaining_count = actual_count - len(selected_tasks)
    if remaining_count > 0 and available_tasks:
        if len(available_tasks) <= remaining_count:
            selected_tasks.extend(available_tasks)
        else:
            selected_tasks.extend(random.sample(available_tasks, remaining_count))
            
    random.shuffle(selected_tasks) # Перемешиваем итоговый список
    return selected_tasks[:base_count] # Гарантируем, что не превысим base_count

def _get_or_create_daily_sphere_quest(db_session, user_id, target_date, force_regenerate=False, new_settings=None):
    """
    Получает или создает ежедневный квест, возможно с перегенерацией задач.
    new_settings: dict {'priority_sphere_name': str, 'difficulty_level': str}
    """
    quest = db_session.query(DailySphereQuest).filter_by(user_id=user_id, date=target_date).first()
    
    regenerate_tasks_flag = False

    if quest:
        if force_regenerate:
            regenerate_tasks_flag = True
            # Применяем новые настройки, если они переданы для перегенерации
            if new_settings:
                quest.priority_sphere_name = new_settings.get('priority_sphere_name', quest.priority_sphere_name)
                quest.difficulty_level = new_settings.get('difficulty_level', quest.difficulty_level)
    else: # Квеста нет, создаем новый
        priority_sphere = new_settings.get('priority_sphere_name') if new_settings else None # Используем None если ключ отсутствует или new_settings is None
        difficulty = new_settings.get('difficulty_level', 'medium') if new_settings else 'medium'
        
        quest = DailySphereQuest(
            user_id=user_id, 
            date=target_date, 
            replacements_used=0,
            priority_sphere_name=priority_sphere,
            difficulty_level=difficulty
        )
        db_session.add(quest)
        regenerate_tasks_flag = True # Для нового квеста всегда генерируем задачи
        
    if regenerate_tasks_flag:
        # Удаляем старые задачи, если они были (при force_regenerate для существующего квеста)
        if quest.id and not quest.tasks: # Если квест уже был в БД, но задачи пусты (маловероятно, но для полноты)
            pass # Задачи будут добавлены ниже
        elif quest.id and quest.tasks: # Если квест был и имел задачи
             for task_obj in list(quest.tasks): # list() для безопасной итерации при удалении
                db_session.delete(task_obj)
        quest.tasks = [] # Очищаем коллекцию в объекте SQLAlchemy
        quest.replacements_used = 0 # Сбрасываем счетчик замен при перегенерации
        
        # Генерируем новые задачи
        tasks_data = get_random_tasks(
            priority_sphere_name=quest.priority_sphere_name,
            difficulty_level=quest.difficulty_level
        )
        for i, task_data in enumerate(tasks_data):
            sq_task = SphereQuestTask(
                sphere_name=task_data["sphere"],
                task_text=task_data["text"],
                is_completed=False,
                display_order=i
            )
            quest.tasks.append(sq_task) # SQLAlchemy свяжет их с квестом при коммите
            
    db_session.commit()
    db_session.refresh(quest) # Обновляем объект quest, чтобы tasks были загружены/обновлены
    return quest

# --- Маршруты для Квеста Развития Сфер ---
@app.route('/sphere_quest', methods=['GET'])
@login_required_custom
def sphere_quest_page(current_user_id):
    db: SessionLocal = next(get_db())
    try:
        today = datetime.now(timezone.utc).date()
        # Получаем или создаем квест. Если настроек нет, используются дефолтные.
        quest = _get_or_create_daily_sphere_quest(db, current_user_id, today)
        
        # Убедимся, что задачи отсортированы для отображения
        sorted_tasks = sorted(quest.tasks, key=lambda t: t.display_order)
        
        return render_template('sphere_quest.html', quest=quest, tasks=sorted_tasks, 
                               max_replacements=MAX_REPLACEMENTS_PER_QUEST,
                               date_today_str=today.strftime("%d %B %Y"),
                               SPHERE_DEFINITIONS=SPHERE_DEFINITIONS) # Передаем для селектора
    except Exception as e:
        print(f"Ошибка на странице квеста развития сфер: {e}")
        flash('Произошла ошибка при загрузке квеста.', 'danger')
        return redirect(url_for('index'))
    finally:
        db.close()

@app.route('/api/sphere_quest/save', methods=['POST'])
@login_required_custom
def save_sphere_quest_progress(current_user_id):
    db: SessionLocal = next(get_db())
    try:
        data = request.json
        task_updates = data.get('tasks', []) 
        quest_date_str = data.get('date', datetime.now(timezone.utc).date().isoformat())
        quest_date = date.fromisoformat(quest_date_str)

        quest = db.query(DailySphereQuest).filter_by(user_id=current_user_id, date=quest_date).first()
        if not quest:
            return jsonify({"error": "Квест не найден для этой даты."}), 404

        for update_info in task_updates:
            task_id = update_info.get('id')
            is_completed = update_info.get('completed', False)
            
            task_to_update = db.query(SphereQuestTask).filter_by(id=task_id, quest_id=quest.id).first()
            if task_to_update:
                task_to_update.is_completed = is_completed
        
        db.commit()
        return jsonify({"message": "Прогресс квеста сохранен."})
    except Exception as e:
        db.rollback()
        print(f"Ошибка сохранения прогресса квеста: {e}")
        return jsonify({"error": "Ошибка сервера при сохранении.", "details": str(e)}), 500
    finally:
        db.close()

@app.route('/api/sphere_quest/replace_task', methods=['POST'])
@login_required_custom
def replace_sphere_quest_task(current_user_id):
    db: SessionLocal = next(get_db())
    try:
        data = request.json
        task_to_replace_id = data.get('task_id')
        quest_date_str = data.get('date', datetime.now(timezone.utc).date().isoformat())
        quest_date = date.fromisoformat(quest_date_str)

        quest = db.query(DailySphereQuest).filter_by(user_id=current_user_id, date=quest_date).first()
        if not quest:
            return jsonify({"error": "Квест не найден."}), 404

        if quest.replacements_used >= MAX_REPLACEMENTS_PER_QUEST:
            return jsonify({"error": f"Лимит замен ({MAX_REPLACEMENTS_PER_QUEST}) исчерпан."}), 403

        task_to_replace = db.query(SphereQuestTask).filter_by(id=task_to_replace_id, quest_id=quest.id).first()
        if not task_to_replace:
            return jsonify({"error": "Задача для замены не найдена в текущем квесте."}), 404

        current_task_texts = [t.task_text for t in quest.tasks if t.id != task_to_replace_id] 
        new_task_data_list = get_random_tasks(
            exclude_tasks_texts=current_task_texts,
            priority_sphere_name=quest.priority_sphere_name, # Учитываем настройки квеста
            difficulty_level=quest.difficulty_level,
            num_to_return=1 # Явно указываем, что нужна одна задача
        )

        if not new_task_data_list:
            return jsonify({"error": "Не удалось подобрать новую уникальную задачу."}), 500
        
        new_task_data = new_task_data_list[0]
        original_display_order = task_to_replace.display_order
        
        db.delete(task_to_replace)
        
        new_sphere_task = SphereQuestTask(
            quest_id=quest.id,
            sphere_name=new_task_data["sphere"],
            task_text=new_task_data["text"],
            is_completed=False,
            display_order=original_display_order
        )
        db.add(new_sphere_task)
        quest.replacements_used += 1
        db.commit()
        
        updated_quest = _get_or_create_daily_sphere_quest(db, current_user_id, quest_date) # Получаем обновленный квест
        return jsonify({
            "message": "Задача заменена.",
            "quest": {
                "id": updated_quest.id,
                "date": updated_quest.date.isoformat(),
                "replacements_used": updated_quest.replacements_used,
                "tasks": [{"id": t.id, "sphere_name": t.sphere_name, "task_text": t.task_text, "is_completed": t.is_completed, "display_order": t.display_order} for t in sorted(updated_quest.tasks, key=lambda t: t.display_order)]
            }
        })

    except Exception as e:
        db.rollback()
        print(f"Ошибка замены задачи в квесте: {e}")
        return jsonify({"error": "Ошибка сервера при замене задачи.", "details": str(e)}), 500
    finally:
        db.close()

@app.route('/api/sphere_quest/update_settings', methods=['POST'])
@login_required_custom
def update_sphere_quest_settings(current_user_id):
    db: SessionLocal = next(get_db())
    try:
        data = request.json
        quest_date_str = data.get('date', date.today().isoformat())
        priority_sphere_name = data.get('priority_sphere_name') 
        difficulty_level = data.get('difficulty_level', 'medium')
        
        quest_date_obj = date.fromisoformat(quest_date_str)

        if not priority_sphere_name: # Если пустая строка, считаем как None
            priority_sphere_name = None
            
        if priority_sphere_name and priority_sphere_name not in SPHERE_DEFINITIONS:
            return jsonify({"error": "Недопустимое имя приоритетной сферы."}), 400
        if difficulty_level not in ['easy', 'medium', 'hard']:
            return jsonify({"error": "Недопустимый уровень сложности."}), 400

        settings_for_quest = {
            'priority_sphere_name': priority_sphere_name,
            'difficulty_level': difficulty_level
        }

        # Получаем или создаем квест и принудительно перегенерируем задачи с новыми настройками
        quest = _get_or_create_daily_sphere_quest(db, current_user_id, quest_date_obj, 
                                                 force_regenerate=True, new_settings=settings_for_quest)
        
        flash('Настройки квеста обновлены, задачи перегенерированы.', 'success')
        return jsonify({
            "message": "Настройки квеста обновлены и задачи перегенерированы.",
            "quest": { 
                "id": quest.id, "date": quest.date.isoformat(),
                "priority_sphere_name": quest.priority_sphere_name,
                "difficulty_level": quest.difficulty_level,
                "replacements_used": quest.replacements_used,
                "tasks_count": len(quest.tasks)
            }
        })
    except Exception as e:
        db.rollback()
        print(f"Ошибка обновления настроек квеста: {e}")
        return jsonify({"error": "Ошибка сервера при обновлении настроек квеста.", "details": str(e)}), 500
    finally:
        db.close()

# --- Функции для Telegram аутентификации ---
def check_telegram_authentication(data):
    bot_token = app.config.get('TELEGRAM_BOT_TOKEN')
    if not bot_token:
        print("Ошибка: TELEGRAM_BOT_TOKEN не установлен в конфигурации!")
        return False
    received_hash = data.get('hash')
    if not received_hash:
        return False 
    auth_data_list = []
    for key in sorted(data.keys()):
        if key != 'hash':
            auth_data_list.append(f'{key}={data[key]}')
    auth_data_string = '\n'.join(auth_data_list)
    secret_key = hashlib.sha256(bot_token.encode('utf-8')).digest()
    hmac_hash = hmac.new(secret_key, auth_data_string.encode('utf-8'), hashlib.sha256).hexdigest()
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
    for report in reversed(daily_reports): 
        prompt_segment += f"**Вечерний отчет за {report.date}:**\n"
        if report.reviewed_tasks:
            try:
                reviewed_tasks_list = json.loads(report.reviewed_tasks) if isinstance(report.reviewed_tasks, str) else report.reviewed_tasks
                if reviewed_tasks_list:
                    prompt_segment += "  Выполнение задач:\n"
                    for task_item in reviewed_tasks_list[:3]: # Первые 3 для краткости
                        prompt_segment += f"    - {task_item.get('name', 'Задача не указана')}: {task_item.get('status', 'Статус не указан')}. Комментарий: {task_item.get('comment', 'Нет')[:50]}...\n"
            except (json.JSONDecodeError, TypeError):
                prompt_segment += "  Выполнение задач: (ошибка чтения данных)\n"
        if report.evening_q1: prompt_segment += f"  1. Что получилось лучше всего: {report.evening_q1[:100]}...\n"
        if report.evening_q5: prompt_segment += f"  5. Что можно было сделать иначе: {report.evening_q5[:100]}...\n"
        prompt_segment += "---\n"
    return prompt_segment

def _format_plans_for_prompt(plans, intro_text="\n**История планов на день (Утреннее планирование, от старых к новым):**\n"):
    if not plans:
        return "Нет недавних планов.\n"
    prompt_segment = intro_text
    for plan_item in reversed(plans):
        prompt_segment += f"**Утренний план на {plan_item.date}:**\n"
        if plan_item.main_goals:
            try:
                main_goals_list = json.loads(plan_item.main_goals) if isinstance(plan_item.main_goals, str) else plan_item.main_goals
                if not isinstance(main_goals_list, list): main_goals_list = []
                prompt_segment += "  Главные задачи дня:\n"
                for goal in main_goals_list[:3]: # Первые 3 для краткости
                    prompt_segment += f"    - {goal.get('text', 'Задача не указана')}\n"
            except (json.JSONDecodeError, TypeError):
                prompt_segment += "  Главные задачи дня: (ошибка чтения данных)\n"
        if plan_item.morning_q2_improve_day: prompt_segment += f"    2. Как сделать день лучше: {plan_item.morning_q2_improve_day[:100]}...\n"
        prompt_segment += "---\n"
    return prompt_segment

def _format_daily_surveys_for_prompt(daily_surveys_history, intro_text="\n**История ежедневных опросов (от старых к новым):**\n"):
    if not daily_surveys_history:
        return "Нет недавних записей ежедневных опросов.\n"
    prompt_segment = intro_text
    for survey in reversed(daily_surveys_history):
        prompt_segment += f"**Ежедневный опрос ({survey.date}):**\n"
        if survey.q1_current_feeling:
            prompt_segment += f"  Самочувствие: {survey.q1_current_feeling[:150]}...\n"
        if survey.q2_morning_intentions_follow:
            prompt_segment += f"  Следование намерениям: {survey.q2_morning_intentions_follow[:150]}...\n"
        if survey.q3_unexpected_challenges_reaction:
            prompt_segment += f"  Реакция на вызовы: {survey.q3_unexpected_challenges_reaction[:150]}...\n"
        if survey.q4_energy_drain_gain:
            prompt_segment += f"  Энергия (утечка/приток): {survey.q4_energy_drain_gain[:150]}...\n"
        if survey.q5_small_progress:
            prompt_segment += f"  Маленький прогресс: {survey.q5_small_progress[:150]}...\n"
        if survey.q6_focus_distraction:
            prompt_segment += f"  Фокус и отвлечения: {survey.q6_focus_distraction[:150]}...\n"
        if survey.q7_action_for_better_day:
            prompt_segment += f"  Действие для улучшения дня: {survey.q7_action_for_better_day[:150]}...\n"
        prompt_segment += "---\n"
    return prompt_segment
def _format_rated_recommendations_for_prompt(rated_recommendations, intro_text="\n**Моя обратная связь на предыдущие рекомендации:**\n"):
    if not rated_recommendations:
        return "\nНет оцененных предыдущих рекомендаций для учета.\n---\n"
    prompt_segment = intro_text
    for rec in rated_recommendations:
        rating_text = "Полезно" if rec.rating == 1 else "Не полезно" if rec.rating == -1 else "Нет оценки"
        clean_text_for_prompt = rec.original_text if rec.original_text else rec.text
        prompt_segment += f"  - Совет (от {rec.date.strftime('%Y-%m-%d')}): \"{clean_text_for_prompt[:150]}...\" (Моя оценка: {rating_text})\n"
    prompt_segment += "---\n"
    return prompt_segment

def get_recommendations_from_gpt(db: SessionLocal, user_id: int):
    HISTORY_LIMIT = 3
    daily_reports = db.query(DailyReport).filter(DailyReport.user_id == user_id).order_by(desc(DailyReport.date)).limit(HISTORY_LIMIT).all()
    plans_data = db.query(Plan).filter(Plan.user_id == user_id).order_by(desc(Plan.date)).limit(HISTORY_LIMIT).all()
    daily_surveys_history = db.query(DailySurvey).filter(DailySurvey.user_id == user_id).order_by(desc(DailySurvey.date)).limit(HISTORY_LIMIT).all()
    plan_items = db.query(PlanItem).filter(PlanItem.user_id == user_id).order_by(PlanItem.item_type, desc(PlanItem.created_at)).all()
    rated_recommendations = db.query(Recommendation).filter(Recommendation.user_id == user_id, Recommendation.rating != None).order_by(desc(Recommendation.date), desc(Recommendation.id)).limit(3).all()

    prompt = "Проанализируй следующую историю моих записей и мою обратную связь на предыдущие советы. Твоя задача - дать мне две структурированные рекомендации с точки зрения психолога. Отвечай на русском языке.\n\n"
    prompt += _format_plan_items_for_prompt(plan_items)
    prompt += _format_daily_reports_for_prompt(daily_reports)
    prompt += _format_plans_for_prompt(plans_data)
    prompt += _format_daily_surveys_for_prompt(daily_surveys_history)
    prompt += _format_rated_recommendations_for_prompt(rated_recommendations)
    prompt += "\n\n**Запрос на рекомендации:**\n"
    prompt += "Исходя из всей предоставленной информации, пожалуйста, дай мне две четко разделенные рекомендации:\n\n"
    prompt += "1.  **Рекомендация для Ежедневного Благополучия:** Один конкретный, действенный совет для улучшения моего самочувствия, настроения или продуктивности на ближайшие 1-2 дня.\n\n"
    prompt += "2.  **Рекомендация для Долгосрочного Роста:** Один конкретный, действенный совет, который поможет мне эффективнее двигаться к моим долгосрочным целям или преодолеть препятствия.\n\n"
    prompt += "Формулируй рекомендации позитивно и конструктивно."

    time.sleep(1) # Уменьшено время ожидания
    try:
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
    HISTORY_LIMIT_MONTHLY = 30
    plan_items = db.query(PlanItem).filter(PlanItem.user_id == user_id).order_by(PlanItem.item_type, desc(PlanItem.created_at)).all()
    daily_reports = db.query(DailyReport).filter(DailyReport.user_id == user_id).order_by(desc(DailyReport.date)).limit(HISTORY_LIMIT_MONTHLY).all()
    plans_data = db.query(Plan).filter(Plan.user_id == user_id).order_by(desc(Plan.date)).limit(HISTORY_LIMIT_MONTHLY).all()
    daily_surveys_history = db.query(DailySurvey).filter(DailySurvey.user_id == user_id).order_by(desc(DailySurvey.date)).limit(HISTORY_LIMIT_MONTHLY).all()
    rated_recommendations = db.query(Recommendation).filter(Recommendation.user_id == user_id, Recommendation.rating != None).order_by(desc(Recommendation.date), desc(Recommendation.id)).limit(5).all()

    prompt = "Проведи глубокий стратегический анализ моих долгосрочных целей, активностей за последний месяц и моей обратной связи на предыдущие советы. Твоя роль - стратегический коуч. Предоставь структурированный ежемесячный обзор и рекомендации. Отвечай на русском языке, используя Markdown.\n\n"
    prompt += _format_plan_items_for_prompt(plan_items, missions_limit=5, projects_limit=7, goals_limit=7, tasks_limit=0, include_status=True) # Больше деталей для месяца
    prompt += _format_daily_reports_for_prompt(daily_reports, intro_text="**Обзор ежедневных отчетов (за последний месяц - ключевые моменты):**\n")
    prompt += _format_plans_for_prompt(plans_data, intro_text="\n**Обзор утренних планов (за последний месяц - ключевые моменты):**\n")
    prompt += _format_daily_surveys_for_prompt(daily_surveys_history, intro_text="\n**Обзор ежедневных опросов (за последний месяц - ключевые моменты):**\n")
    prompt += _format_rated_recommendations_for_prompt(rated_recommendations, intro_text="\n**Моя обратная связь на предыдущие рекомендации (за последнее время):**\n")
    prompt += "\n\n**Запрос на Ежемесячный Стратегический Обзор и Рекомендации:**\n"
    prompt += "Пожалуйста, предоставь структурированный ответ (используй Markdown):\n1. **Анализ Миссий и Проектов:** Насколько я продвинулся(ась) к своим миссиям? Какие проекты были успешны, какие требуют пересмотра или новых подходов? Есть ли застой?\n2. **Общие Тренды Продуктивности и Благополучия:** Какие паттерны видны в моих ежедневных записях за месяц (энергия, достижения, трудности, эмоции)?\n3. **Стратегические Рекомендации на Следующий Месяц:**\n    a. Какие 1-2 стратегические цели/проекта должны быть в приоритете?\n    b. Какие изменения в рутине или подходах могут повысить мою эффективность и удовлетворенность в долгосрочной перспективе?\n    c. Один вопрос для глубокой рефлексии о моих ценностях или долгосрочном видении.\n"
    prompt += "Будь проницательным, предлагай конкретные шаги и задавай стимулирующие вопросы.\n"
    prompt += "4. **Гипотезы для Самоисследования на Следующий Месяц:**\n"
    prompt += "    a. На основе анализа всех предоставленных данных за последний месяц, сформулируй 1-2 конкретные, проверяемые гипотезы о связях между моими действиями/подходами/эмоциями и моими результатами.\n"
    prompt += "    b. Для каждой гипотезы предложи простой способ проверки в течение следующего месяца.\n"

    time.sleep(1) # Уменьшено время ожидания
    try:
        import g4f
        response = g4f.ChatCompletion.create(
            model=g4f.models.gpt_4, 
            messages=[{"role": "user", "content": prompt}],
        )
        return response
    except Exception as e:
        print(f"Ошибка при получении ежемесячных рекомендаций от GPT: {e}")
        return f"Произошла ошибка при получении ежемесячных рекомендаций: {e}"

def get_weekly_recommendations_from_gpt(db: SessionLocal, user_id: int):
    HISTORY_LIMIT_WEEKLY = 7
    daily_reports = db.query(DailyReport).filter(DailyReport.user_id == user_id).order_by(desc(DailyReport.date)).limit(HISTORY_LIMIT_WEEKLY).all()
    plans_data = db.query(Plan).filter(Plan.user_id == user_id).order_by(desc(Plan.date)).limit(HISTORY_LIMIT_WEEKLY).all()
    daily_surveys_history = db.query(DailySurvey).filter(DailySurvey.user_id == user_id).order_by(desc(DailySurvey.date)).limit(HISTORY_LIMIT_WEEKLY * 2).all()
    plan_items = db.query(PlanItem).filter(PlanItem.user_id == user_id).order_by(PlanItem.item_type, desc(PlanItem.created_at)).all()
    rated_recommendations = db.query(Recommendation).filter(Recommendation.user_id == user_id, Recommendation.rating != None).order_by(desc(Recommendation.date), desc(Recommendation.id)).limit(4).all()

    prompt = "Проанализируй мои записи за последнюю неделю, мои стратегические цели и мою обратную связь на предыдущие советы. Твоя задача - выступить в роли коуча по продуктивности и благополучию и предоставить мне еженедельный обзор и рекомендации. Отвечай на русском языке, используя Markdown для форматирования.\n\n"
    prompt += _format_plan_items_for_prompt(plan_items)
    prompt += _format_daily_reports_for_prompt(daily_reports)
    prompt += _format_plans_for_prompt(plans_data)
    prompt += _format_daily_surveys_for_prompt(daily_surveys_history)
    prompt += _format_rated_recommendations_for_prompt(rated_recommendations)
    prompt += "\n\n**Запрос на Еженедельный Обзор и Рекомендации:**\n"
    prompt += "Пожалуйста, предоставь структурированный ответ (используй Markdown):\n1. **Обзор Прошедшей Недели:** Кратко об успехах, трудностях и связи эмоций с продуктивностью.\n2. **Прогресс по Стратегическим Целям:** Насколько я продвинулся(ась) к целям из Планировщика? Какие требуют внимания?\n3. **Рекомендации на Следующую Неделю:** 1-2 ключевых фокуса для долгосрочных целей, 1 совет для благополучия/энергии, 1 возможная корректировка в подходах.\n"
    prompt += "Будь конструктивным и давай действенные советы."

    time.sleep(1) # Уменьшено время ожидания
    try:
        import g4f
        response = g4f.ChatCompletion.create(
            model=g4f.models.default, 
            messages=[{"role": "user", "content": prompt}],
        )
        return response
    except Exception as e:
        print(f"Ошибка при получении еженедельных рекомендаций от GPT: {e}")
        return f"Произошла ошибка при получении еженедельных рекомендаций: {e}"

def generate_recommendations_background(app, user_id):
    with app.app_context():
        db: SessionLocal = next(get_db())
        try:
            recommendation_text = get_recommendations_from_gpt(db, user_id)
            if recommendation_text:
                new_recommendation = Recommendation(
                    user_id=user_id,
                    original_text=recommendation_text, 
                    text=markdown.markdown(recommendation_text) 
                )
                db.add(new_recommendation)
                db.commit()
                print(f"Рекомендация успешно сохранена для пользователя {user_id}")
        except Exception as e:
            print(f"Ошибка в фоновом потоке генерации рекомендаций: {e}")
        finally:
            db.close()

def generate_weekly_recommendations_background(app, user_id):
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
# --- Маршрут для новой страницы Квестов ---
@app.route('/quests')
@login_required_custom # Добавляем декоратор для проверки авторизации
def quests_page(current_user_id): # Добавляем current_user_id, т.к. login_required_custom его передает
    # Здесь можно будет передавать данные о прогрессе пользователя в квестах, если потребуется
    # user_id = session.get('user_id') # current_user_id уже доступен
    # if not current_user_id: # Эта проверка уже внутри login_required_custom
    #     pass
    return render_template('quests.html')

# --- Вспомогательная функция для карусели дат ---
def get_date_carousel_options(selected_date_iso_str=None, num_days_around=2, url_route='new_plan'): 
    days_ru = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
    months_ru_genitive = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"]
    try:
        target_selection_date = date.fromisoformat(selected_date_iso_str) if selected_date_iso_str else date.today()
    except ValueError:
        target_selection_date = date.today()
    today = date.today()
    options = []
    for i in range(-num_days_around, num_days_around + 1):
        d = target_selection_date + timedelta(days=i)
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
            'is_selected': (d == target_selection_date),
            'url': url_for(url_route, date=d.isoformat()) 
        })    
    return options

@app.route('/login')
def login():
    if 'user_id' in session:
        return redirect(url_for('index'))
    response = make_response(render_template('login.html'))
    render_domain = app.config.get('TELEGRAM_LOGIN_DOMAIN', 'reflect-wise-app.onrender.com') 
    csp_policy = f"default-src 'self'; script-src 'self' https://telegram.org; style-src 'self' 'unsafe-inline'; frame-src https://oauth.telegram.org; frame-ancestors 'self' https://oauth.telegram.org https://{render_domain};"
    response.headers['Content-Security-Policy'] = csp_policy
    return response

@app.route('/login_vk')
def login_vk():
    if 'user_id' in session:
        return redirect(url_for('index'))
    vk_app_id = app.config.get('VK_APP_ID')
    vk_redirect_uri = url_for('vk_callback', _external=True)
    vk_auth_url = (f"https://oauth.vk.com/authorize?client_id={vk_app_id}&display=page&redirect_uri={vk_redirect_uri}&scope=offline&response_type=code&v=5.199")
    return redirect(vk_auth_url)

@app.route('/vk_callback')
def vk_callback():
    code = request.args.get('code')
    if not code:
        flash('Ошибка авторизации через ВКонтакте: не получен код.', 'danger')
        return redirect(url_for('login'))
    vk_app_id = app.config.get('VK_APP_ID')
    vk_secure_key = app.config.get('VK_SECURE_KEY')
    vk_redirect_uri = url_for('vk_callback', _external=True)
    token_url = (f"https://oauth.vk.com/access_token?client_id={vk_app_id}&client_secret={vk_secure_key}&redirect_uri={vk_redirect_uri}&code={code}")
    try:
        token_response = requests.get(token_url)
        token_response.raise_for_status() 
        token_data = token_response.json()
        access_token = token_data.get('access_token')
        vk_user_id = token_data.get('user_id')
        if not access_token or not vk_user_id:
            flash('Ошибка авторизации через ВКонтакте: не удалось получить токен или ID пользователя.', 'danger')
            return redirect(url_for('login'))
        user_info_url = (f"https://api.vk.com/method/users.get?user_ids={vk_user_id}&fields=photo_100,screen_name&access_token={access_token}&v=5.199")
        user_info_response = requests.get(user_info_url)
        user_info_response.raise_for_status()
        user_info_data = user_info_response.json().get('response', [])[0]
        db: SessionLocal = next(get_db())
        try:
            user = db.query(User).filter_by(vk_id=vk_user_id).first()
            if not user:
                user = User(vk_id=vk_user_id, first_name=user_info_data.get('first_name'), last_name=user_info_data.get('last_name'), username=user_info_data.get('screen_name'), photo_url=user_info_data.get('photo_100'))
                db.add(user)
                flash('Добро пожаловать! Ваш аккаунт создан через ВКонтакте.', 'success')
            else:
                user.first_name = user_info_data.get('first_name')
                user.last_name = user_info_data.get('last_name')
                user.username = user_info_data.get('screen_name')
                user.photo_url = user_info_data.get('photo_100')
                flash(f'С возвращением через ВКонтакте, {user.first_name}!', 'info')
            db.commit()
            session['user_id'] = user.id
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

@app.route('/telegram_callback')
def telegram_callback():
    auth_data = request.args.to_dict()
    is_authenticated = check_telegram_authentication(auth_data)
    if is_authenticated:
        telegram_id = auth_data.get('id')
        first_name = auth_data.get('first_name')
        last_name = auth_data.get('last_name')
        username = auth_data.get('username')
        photo_url = auth_data.get('photo_url')
        db: SessionLocal = next(get_db())
        try:
            user = db.query(User).filter_by(telegram_id=telegram_id).first()
            if not user:
                user = User(telegram_id=telegram_id, first_name=first_name, last_name=last_name, username=username, photo_url=photo_url)
                db.add(user)
                db.commit()
                flash('Добро пожаловать! Ваш аккаунт создан.', 'success')
            else:
                user.first_name = first_name
                user.last_name = last_name
                user.username = username
                user.photo_url = photo_url
                db.commit()
                flash(f'С возвращением, {user.first_name}!', 'info')
            session['user_id'] = user.id
            session['telegram_id'] = telegram_id
            return redirect(url_for('index'))
        except Exception as e:
            print(f"Ошибка при работе с БД в telegram_callback: {e}")
            db.rollback()
            flash('Произошла ошибка при обработке вашего входа.', 'danger')
            return redirect(url_for('login'))
        finally:
            db.close()
    else:
        flash('Ошибка аутентификации через Telegram.', 'danger')
        return redirect(url_for('login'))

@app.route('/')
@login_required_custom 
def index(current_user_id): 
    db: SessionLocal = next(get_db())
    user_for_template = None 
    try:
        if app.config.get('LOCAL_DEV_NO_LOGIN'):
            dev_user_id = app.config.get('DEFAULT_DEV_USER_ID', 1)
            session['user_id'] = dev_user_id 
            user_for_template = db.query(User).filter_by(id=dev_user_id).first()
            if not user_for_template:
                user_for_template = MockUser(id=dev_user_id) 
                flash(f'Локальная разработка: Вход пропущен. Используется мок-пользователь ID {dev_user_id}. Убедитесь, что пользователь с таким ID существует в БД для полного функционала.', 'info')
            else:
                flash(f'Локальная разработка: Вход пропущен. Используется пользователь ID {dev_user_id} из БД.', 'info')
            if hasattr(user_for_template, 'telegram_id') and user_for_template.telegram_id:
                session['telegram_id'] = user_for_template.telegram_id
            elif 'telegram_id' not in session: 
                session['telegram_id'] = f"mock_tg_{dev_user_id}"
        else:
            user_for_template = db.query(User).filter_by(id=current_user_id).first()
            if not user_for_template:
                return redirect(url_for('logout')) 
        return render_template('index.html', date=date, user=user_for_template)
    except Exception as e:
        print(f"Ошибка на главной странице: {e}")
        flash('Произошла ошибка при загрузке страницы.', 'danger')
        if app.config.get('LOCAL_DEV_NO_LOGIN') and not user_for_template:
            user_for_template = MockUser(id=current_user_id, first_name="ОшибкаЗагрузки")
            return render_template('index.html', date=date, user=user_for_template)
        return "Произошла ошибка", 500
    finally:
        db.close()

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    session.pop('telegram_id', None)
    flash('Вы успешно вышли из системы.', 'info')
    return redirect(url_for('login')) 

@app.route('/report/new', methods=['GET', 'POST'])
@login_required_custom
def new_report(current_user_id):
    db: SessionLocal = next(get_db())
    try:
        # Дата для отображения страницы (из GET-параметра или сегодня)
        view_date_iso = request.args.get('date', datetime.now(timezone.utc).date().isoformat())
        view_date_obj = date.fromisoformat(view_date_iso)
        carousel_dates_for_view = get_date_carousel_options(selected_date_iso_str=view_date_iso, url_route='new_report')

        existing_report_for_view = db.query(DailyReport).filter_by(user_id=current_user_id, date=view_date_obj).first()
        if existing_report_for_view and existing_report_for_view.reviewed_tasks:
            try:
                existing_report_for_view.reviewed_tasks_list = json.loads(existing_report_for_view.reviewed_tasks)
            except (json.JSONDecodeError, TypeError):
                existing_report_for_view.reviewed_tasks_list = []

        if request.method == 'POST':
            try:
                report_date_iso_from_form = request.form.get('selected_date', datetime.now(timezone.utc).date().isoformat())
                report_date_obj_post = date.fromisoformat(report_date_iso_from_form)

                report_to_save = db.query(DailyReport).filter_by(user_id=current_user_id, date=report_date_obj_post).first()
                is_new_report = False
                if not report_to_save:
                    report_to_save = DailyReport(user_id=current_user_id, date=report_date_obj_post)
                    is_new_report = True
                
                reviewed_tasks_from_form = []
                i = 0
                while True:
                    task_name_key = f'reviewed_tasks[{i}][name]'
                    task_status_key = f'reviewed_tasks[{i}][status]'
                    task_comment_key = f'reviewed_tasks[{i}][comment]'
                    task_name = request.form.get(task_name_key)
                    if task_name is None: break
                    task_status = request.form.get(task_status_key)
                    task_comment = request.form.get(task_comment_key, "")
                    reviewed_tasks_from_form.append({"name": task_name, "status": task_status, "comment": task_comment})
                    i += 1
                report_to_save.reviewed_tasks = json.dumps(reviewed_tasks_from_form)
                report_to_save.evening_q1 = request.form.get('evening_q1')
                report_to_save.evening_q2 = request.form.get('evening_q2')
                report_to_save.evening_q3 = request.form.get('evening_q3')
                report_to_save.evening_q4 = request.form.get('evening_q4')
                report_to_save.evening_q5 = request.form.get('evening_q5')
                report_to_save.evening_q6 = request.form.get('evening_q6')

                quest_task_status_ids = request.form.getlist('quest_task_status_ids[]')
                quest_on_report_date = _get_or_create_daily_sphere_quest(db, current_user_id, report_date_obj_post)
                if quest_on_report_date and quest_on_report_date.tasks:
                    for task_in_quest in quest_on_report_date.tasks:
                        task_in_quest.is_completed = str(task_in_quest.id) in quest_task_status_ids
                
                if is_new_report: # Добавляем только если новый
                    db.add(report_to_save)
                
                db.commit()
                thread = Thread(target=generate_recommendations_background, args=(app, current_user_id))
                thread.start()
                flash('Отчет успешно сохранен!' if is_new_report else 'Отчет успешно обновлен!', 'success')
                return redirect(url_for('index'))
            except Exception as e_post:
                db.rollback()
                print(f"Ошибка при сохранении отчета: {e_post}")
                flash('Произошла ошибка при сохранении отчета.', 'danger')
                
                # Данные для перерисовки формы на дату, для которой была попытка POST
                error_render_date_iso = request.form.get('selected_date', view_date_iso) # Дата из формы POST или изначальная GET
                error_render_date_obj = date.fromisoformat(error_render_date_iso)
                carousel_dates_for_error = get_date_carousel_options(selected_date_iso_str=error_render_date_iso, url_route='new_report')
                existing_report_for_error = db.query(DailyReport).filter_by(user_id=current_user_id, date=error_render_date_obj).first()

                plan_on_error_date = db.query(Plan).filter(Plan.user_id == current_user_id, Plan.date == error_render_date_obj).first()
                goals_for_checkin_on_error = []
                if plan_on_error_date and plan_on_error_date.main_goals:
                    try: goals_for_checkin_on_error = json.loads(plan_on_error_date.main_goals)
                    except: goals_for_checkin_on_error = []
                
                quest_on_error_date = _get_or_create_daily_sphere_quest(db, current_user_id, error_render_date_obj)
                quest_tasks_for_report_on_error = []
                if quest_on_error_date and quest_on_error_date.tasks:
                    quest_tasks_for_report_on_error = [
                        {"id": qt.id, "sphere_name": qt.sphere_name, "task_text": qt.task_text, "is_completed": qt.is_completed}
                        for qt in quest_on_error_date.tasks
                    ]
                return render_template('new_report.html', report=existing_report_for_error, 
                                       morning_tasks_today=goals_for_checkin_on_error, 
                                       quest_tasks_for_report=quest_tasks_for_report_on_error, 
                                       carousel_dates=carousel_dates_for_error, selected_date_iso=error_render_date_iso)
        
        # GET request
        plan_for_selected_date = db.query(Plan).filter(Plan.user_id == current_user_id, Plan.date == view_date_obj).first()
        morning_tasks_for_form = []
        if plan_for_selected_date and plan_for_selected_date.main_goals:
            try:
                morning_tasks_for_form = json.loads(plan_for_selected_date.main_goals) 
            except (json.JSONDecodeError, TypeError):
                flash(f'Не удалось загрузить задачи из плана на {view_date_iso} для чекина.', 'warning')
                morning_tasks_for_form = []
        
        quest_for_selected_date = _get_or_create_daily_sphere_quest(db, current_user_id, view_date_obj)
        quest_tasks_for_report_form = []
        if quest_for_selected_date and quest_for_selected_date.tasks:
            quest_tasks_for_report_form = [
                {"id": qt.id, "sphere_name": qt.sphere_name, "task_text": qt.task_text, "is_completed": qt.is_completed}
                for qt in quest_for_selected_date.tasks
            ]
        return render_template('new_report.html', report=existing_report_for_view, morning_tasks_today=morning_tasks_for_form, quest_tasks_for_report=quest_tasks_for_report_form, carousel_dates=carousel_dates_for_view, selected_date_iso=view_date_iso)

    except ValueError as ve: # Ошибка парсинга даты из URL
        print(f"Ошибка парсинга даты в /report/new: {ve}")
        flash('Некорректный формат даты в URL.', 'danger')
        return redirect(url_for('index'))
    except Exception as e: # Другие ошибки при GET-запросе
        print(f"Общая ошибка в /report/new (GET): {e}")
        flash('Произошла ошибка при загрузке страницы отчета.', 'danger')
        return redirect(url_for('index'))
    finally: # Гарантированное закрытие сессии
        if db: db.close()

@app.route('/plan/new', methods=['GET', 'POST'])
@login_required_custom
def new_plan(current_user_id):
    db: SessionLocal = next(get_db())
    try:
        form_date_iso = request.args.get('date', datetime.now(timezone.utc).date().isoformat())
        form_date_obj = date.fromisoformat(form_date_iso)
        carousel_dates = get_date_carousel_options(selected_date_iso_str=form_date_iso, url_route='new_plan')
        existing_plan = db.query(Plan).filter_by(user_id=current_user_id, date=form_date_obj).first()
        if existing_plan and existing_plan.main_goals:
            try:
                existing_plan.main_goals_list = json.loads(existing_plan.main_goals)
            except (json.JSONDecodeError, TypeError):
                existing_plan.main_goals_list = []
        if request.method == 'POST':
            try:
                plan_date_iso_from_form = request.form.get('selected_date', datetime.now(timezone.utc).date().isoformat())
                plan_date_obj = date.fromisoformat(plan_date_iso_from_form)
                # Список для хранения данных об основных задачах дня, выбранных пользователем
                # Каждая задача будет словарем {"text": "...", "original_item_id": ID_OR_NULL}
                plan_main_goals_data_list = []

                # 1. Обработка PlanItem, ЯВНО выбранных пользователем из списка "предложенных"
                # Эти PlanItem пользователь хочет видеть в "Главных задачах дня" утреннего плана.
                
                selected_suggested_ids = request.form.getlist('selected_suggested_task_ids[]')
                if selected_suggested_ids:
                    suggested_items_to_add = db.query(PlanItem).filter(
                        PlanItem.user_id == current_user_id,
                        PlanItem.id.in_([int(id_str) for id_str in selected_suggested_ids if id_str.isdigit()])).all()
                    for item in suggested_items_to_add:
                        plan_main_goals_data_list.append({"text": item.name, "original_item_id": item.id})
                        # Обновляем start_date для этих PlanItem, если они выбраны на сегодня
                        if item.start_date != plan_date_obj:
                            item.start_date = plan_date_obj

                # 2. Обработка задач, введенных вручную в "Главные задачи дня"
                
                manual_task_texts_from_form = request.form.getlist('manual_task_text')
                if manual_task_texts_from_form:
                    for task_text in manual_task_texts_from_form:
                        task_text_stripped = task_text.strip()
                        if task_text_stripped:
                            # Для чисто ручных задач original_item_id будет None.
                            # Автоматическое создание PlanItem для ручных задач здесь не происходит.
                            plan_main_goals_data_list.append({"text": task_text_stripped, "original_item_id": None})
                plan_to_save = db.query(Plan).filter_by(user_id=current_user_id, date=plan_date_obj).first()
                is_new_plan = False
                if not plan_to_save:
                    plan_to_save = Plan(user_id=current_user_id, date=plan_date_obj)
                    is_new_plan = True
                                # Удаляем дубликаты из plan_main_goals_data_list, если пользователь выбрал PlanItem и ввел его же текстом
                # Приоритет отдается записям с original_item_id
                unique_main_goals_dict = { (item['original_item_id'] if item['original_item_id'] else item['text']): item for item in reversed(plan_main_goals_data_list) }
                plan_to_save.main_goals = json.dumps(list(unique_main_goals_dict.values()))
                plan_to_save.morning_q2_improve_day = request.form.get('morning_q2')
                plan_to_save.morning_q3_mindset = request.form.get('morning_q3')
                plan_to_save.morning_q4_help_others = request.form.get('morning_q4')
                plan_to_save.morning_q5_inspiration = request.form.get('morning_q5')
                plan_to_save.morning_q6_health_care = request.form.get('morning_q6')
                # Сохраняем предпочтения ритуала, если они были введены в основной форме
                # (хотя основная логика сохранения предпочтений и ритуала будет в generate_morning_ritual_ai)
                plan_to_save.ritual_user_preferences = request.form.get('ritual_preferences')

                if is_new_plan:
                    db.add(plan_to_save)
                db.commit()
                thread = Thread(target=generate_recommendations_background, args=(app, current_user_id))
                thread.start()
                flash('План успешно сохранен!' if is_new_plan else 'План успешно обновлен!', 'success')
                return redirect(url_for('index'))
            except Exception as e:
                print(f"Ошибка при сохранении плана: {e}")
                db.rollback()
                flash('Произошла ошибка при сохранении плана.', 'danger')
                auto_added_tasks_error = []
                # selectable_tasks теперь только для отображения, если пользователь захочет выбрать
                # Задачи со статусом TODO или IN_PROGRESS, которые могут быть выбраны
                selectable_tasks_error = db.query(PlanItem).filter(
                    PlanItem.user_id == current_user_id,
                    PlanItem.item_type.in_([PlanItemType.TASK, PlanItemType.SUBTASK]),
                    PlanItem.status.in_([PlanItemStatus.TODO, PlanItemStatus.IN_PROGRESS])
                ).order_by(PlanItem.name).all()
                
                # form_date_obj здесь - это дата, на которую пытались сохранить план
                quest_for_plan_date_error = _get_or_create_daily_sphere_quest(db, current_user_id, plan_date_obj) # Используем plan_date_obj из POST
                quest_tasks_for_plan_error = []
                if quest_for_plan_date_error and quest_for_plan_date_error.tasks: # form_date_obj from GET
                    quest_tasks_for_plan_error = [
                        {
                            "id": qt.id, "text_display": f"[{qt.sphere_name}] {qt.task_text}", "name": qt.task_text,
                            "description": "Задача из Квеста Развития Сфер.", "sphere_name": qt.sphere_name,
                            "is_completed": qt.is_completed
                        } for qt in quest_for_plan_date_error.tasks if not qt.is_completed]

             # selected_date_iso для рендера должен быть тот, на который пытались сохранить
                return render_template('new_plan.html', plan=existing_plan, auto_added_tasks=auto_added_tasks_error, selectable_tasks=selectable_tasks_error, quest_tasks_today=quest_tasks_for_plan_error, carousel_dates=carousel_dates, selected_date_iso=plan_date_iso_from_form)
        
        # GET-запрос
        auto_added_tasks = [] # Больше не используется для авто-добавления
        # Задачи, которые пользователь может ЯВНО выбрать для добавления в "Главные задачи дня"
        # Это PlanItem со статусом TODO или IN_PROGRESS
        selectable_tasks_query = db.query(PlanItem).filter(
            PlanItem.user_id == current_user_id,
            PlanItem.item_type.in_([PlanItemType.TASK, PlanItemType.SUBTASK]),
            PlanItem.status.in_([PlanItemStatus.TODO, PlanItemStatus.IN_PROGRESS])
        ).order_by(PlanItem.name).all()
        quest_for_plan_date = _get_or_create_daily_sphere_quest(db, current_user_id, form_date_obj)
        quest_tasks_for_plan = []
        if quest_for_plan_date and quest_for_plan_date.tasks:
            quest_tasks_for_plan = [
                {
                    "id": qt.id, "text_display": f"[{qt.sphere_name}] {qt.task_text}", "name": qt.task_text,
                    "description": "Задача из Квеста Развития Сфер.", "sphere_name": qt.sphere_name,
                    "is_completed": qt.is_completed
                } for qt in quest_for_plan_date.tasks if not qt.is_completed]
        return render_template('new_plan.html', plan=existing_plan, auto_added_tasks=auto_added_tasks, selectable_tasks=selectable_tasks_query, quest_tasks_today=quest_tasks_for_plan, carousel_dates=carousel_dates, selected_date_iso=form_date_iso) # selectable_tasks_query is a list of PlanItem objects
    except Exception as e:
        print(f"Ошибка при загрузке формы плана: {e}")
        flash('Произошла ошибка при загрузке формы плана.', 'danger')
        _form_date_iso_to_render = datetime.now(timezone.utc).date().isoformat()
        _carousel_dates_to_render = []
        if 'form_date_iso' in locals() and locals()['form_date_iso']: 
            _form_date_iso_to_render = locals()['form_date_iso']
        if 'carousel_dates' in locals() and locals()['carousel_dates']: 
            _carousel_dates_to_render = locals()['carousel_dates']
        else:
            try:
                _carousel_dates_to_render = get_date_carousel_options(selected_date_iso_str=_form_date_iso_to_render, url_route='new_plan')
            except Exception as fallback_carousel_error:
                print(f"Error creating fallback carousel in new_plan error handler: {fallback_carousel_error}")
                _today = date.today()
                _carousel_dates_to_render = [{'display_text': 'Сегодня', 'iso_value': _today.isoformat(), 'is_selected': True}]
        
        _selectable_tasks_fallback = []
        _quest_tasks_fallback = []
        _plan_fallback = None
        _db_fallback = None
        try:
            _db_fallback = next(get_db())
            _form_date_obj_fallback = date.fromisoformat(_form_date_iso_to_render)
            
            if 'existing_plan' in locals() and locals()['existing_plan']:
                _plan_fallback = locals()['existing_plan']
            else:
                _plan_fallback = _db_fallback.query(Plan).filter_by(user_id=current_user_id, date=_form_date_obj_fallback).first()
                if _plan_fallback and _plan_fallback.main_goals:
                    try: _plan_fallback.main_goals_list = json.loads(_plan_fallback.main_goals)
                    except (json.JSONDecodeError, TypeError): _plan_fallback.main_goals_list = []

            _selectable_tasks_fallback = _db_fallback.query(PlanItem).filter(
                PlanItem.user_id == current_user_id,
                PlanItem.item_type.in_([PlanItemType.TASK, PlanItemType.SUBTASK]),
                PlanItem.status == PlanItemStatus.TODO
            ).order_by(PlanItem.name).all()

            _quest_for_plan_date_fallback = _get_or_create_daily_sphere_quest(_db_fallback, current_user_id, _form_date_obj_fallback)
            if _quest_for_plan_date_fallback and _quest_for_plan_date_fallback.tasks:
                _quest_tasks_fallback = [
                    {
                        "id": qt.id, "text_display": f"[{qt.sphere_name}] {qt.task_text}", "name": qt.task_text,
                        "description": "Задача из Квеста Развития Сфер.", "sphere_name": qt.sphere_name,
                        "is_completed": qt.is_completed
                    } for qt in _quest_for_plan_date_fallback.tasks if not qt.is_completed]
        except Exception as e_fallback_data:
            print(f"Error fetching fallback data for new_plan error page: {e_fallback_data}")
        finally:
            if _db_fallback:
                _db_fallback.close()
        return render_template('new_plan.html', plan=_plan_fallback, auto_added_tasks=[], selectable_tasks=_selectable_tasks_fallback, quest_tasks_today=_quest_tasks_fallback, carousel_dates=_carousel_dates_to_render, selected_date_iso=_form_date_iso_to_render)
    finally:
        db.close()

@app.route('/daily_survey/new', methods=['GET', 'POST'])
@login_required_custom
def new_daily_survey(current_user_id):
    db: SessionLocal = next(get_db())
    try:
        view_date_iso = request.args.get('date', datetime.now(timezone.utc).date().isoformat())
        view_date_obj = date.fromisoformat(view_date_iso)
        carousel_dates_for_view = get_date_carousel_options(selected_date_iso_str=view_date_iso, url_route='new_daily_survey')
        
        existing_survey_for_view = db.query(DailySurvey).filter_by(user_id=current_user_id, date=view_date_obj).first()

        if request.method == 'POST':
            try:
                survey_date_iso_from_form = request.form.get('selected_date', datetime.now(timezone.utc).date().isoformat())
                survey_date_obj_post = date.fromisoformat(survey_date_iso_from_form)

                survey_to_save = db.query(DailySurvey).filter_by(user_id=current_user_id, date=survey_date_obj_post).first()
                is_new_survey = False
                if not survey_to_save:
                    survey_to_save = DailySurvey(user_id=current_user_id, date=survey_date_obj_post)
                    is_new_survey = True

                survey_to_save.q1_current_feeling = request.form.get('q1_current_feeling')
                survey_to_save.q2_morning_intentions_follow = request.form.get('q2_morning_intentions_follow')
                survey_to_save.q3_unexpected_challenges_reaction = request.form.get('q3_unexpected_challenges_reaction')
                survey_to_save.q4_energy_drain_gain = request.form.get('q4_energy_drain_gain')
                survey_to_save.q5_small_progress = request.form.get('q5_small_progress')
                survey_to_save.q6_focus_distraction = request.form.get('q6_focus_distraction')
                survey_to_save.q7_action_for_better_day = request.form.get('q7_action_for_better_day')

                if is_new_survey: # Добавляем только если новый
                    db.add(survey_to_save)
                
                db.commit()
                thread = Thread(target=generate_recommendations_background, args=(app, current_user_id))
                thread.start()
                flash('Ежедневный опрос успешно сохранен!' if is_new_survey else 'Ежедневный опрос успешно обновлен!', 'success')
                return redirect(url_for('index'))
            except Exception as e_post:
                db.rollback()
                print(f"Ошибка при сохранении ежедневного опроса: {e_post}")
                flash('Произошла ошибка при сохранении ежедневного опроса.', 'danger')
                # Данные для перерисовки формы на дату, для которой была попытка POST
                error_render_date_iso = request.form.get('selected_date', view_date_iso)
                carousel_dates_for_error = get_date_carousel_options(selected_date_iso_str=error_render_date_iso, url_route='new_daily_survey')
                existing_survey_for_error = db.query(DailySurvey).filter_by(user_id=current_user_id, date=date.fromisoformat(error_render_date_iso)).first()
                return render_template('new_daily_survey.html', survey=existing_survey_for_error, carousel_dates=carousel_dates_for_error, selected_date_iso=error_render_date_iso)
        
        # GET запрос
        return render_template('new_daily_survey.html', survey=existing_survey_for_view, carousel_dates=carousel_dates_for_view, selected_date_iso=view_date_iso)

    except ValueError as ve: # Ошибка парсинга даты из URL
        print(f"Ошибка парсинга даты в /daily_survey/new: {ve}")
        flash('Некорректный формат даты в URL.', 'danger')
        return redirect(url_for('index'))
    except Exception as e: # Другие ошибки при GET-запросе
        print(f"Общая ошибка в /daily_survey/new (GET): {e}")
        flash('Произошла ошибка при загрузке страницы дневного опроса.', 'danger')
        return redirect(url_for('index'))
    finally: # Гарантированное закрытие сессии
        if db: db.close()

@app.route('/view/<view_date>')
@login_required_custom
def view_data(current_user_id, view_date):
    db: SessionLocal = next(get_db())
    try:
        report_db = db.query(DailyReport).filter(DailyReport.user_id == current_user_id, DailyReport.date == view_date).first()
        plan_db = db.query(Plan).filter(Plan.user_id == current_user_id, Plan.date == view_date).first()
        daily_survey_db = db.query(DailySurvey).filter(DailySurvey.user_id == current_user_id, DailySurvey.date == view_date).first() # Изменено на first(), т.к. один опрос в день
        recommendations_for_date = db.query(Recommendation).filter(Recommendation.user_id == current_user_id, Recommendation.date == view_date).order_by(desc(Recommendation.id)).all()
        plan = None
        if plan_db:
            plan = plan_db
            if plan.main_goals:
                try:
                    plan.main_goals = json.loads(plan.main_goals) 
                except (json.JSONDecodeError, TypeError): plan.main_goals = [] 
        report = None
        if report_db:
            report = report_db
            if report.reviewed_tasks:
                try:
                    if isinstance(report.reviewed_tasks, str):
                        report.reviewed_tasks = json.loads(report.reviewed_tasks) 
                    elif report.reviewed_tasks is None: 
                        report.reviewed_tasks = []
                except (json.JSONDecodeError, TypeError): report.reviewed_tasks = [] 
        return render_template('view_data.html', view_date=view_date, report=report, plan=plan, daily_survey=daily_survey_db, recommendations_for_date=recommendations_for_date)
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
            thread = Thread(target=generate_weekly_recommendations_background, args=(app, user_id_for_query))
            thread.start()
            flash('Запрос на генерацию еженедельного обзора отправлен. Он появится на странице рекомендаций через некоторое время.', 'info')
            return redirect(url_for('recommendations')) 
        except Exception as e:
            print(f"Ошибка при запуске генерации еженедельных рекомендаций: {e}")
            flash('Не удалось запустить генерацию еженедельного обзора.', 'danger')
            return redirect(url_for('recommendations'))
    return render_template('weekly_recommendations_trigger.html')

@app.route('/recommendations/monthly', methods=['GET', 'POST'])
@login_required_custom
def monthly_recommendations_page(user_id_for_query):
    if request.method == 'POST':
        try:
            thread = Thread(target=generate_monthly_recommendations_background, args=(app, user_id_for_query))
            thread.start()
            flash('Запрос на генерацию ежемесячного стратегического обзора отправлен. Он появится на странице рекомендаций через некоторое время.', 'info')
            return redirect(url_for('recommendations')) 
        except Exception as e:
            print(f"Ошибка при запуске генерации ежемесячных рекомендаций: {e}")
            flash('Не удалось запустить генерацию ежемесячного обзора.', 'danger')
            return redirect(url_for('recommendations'))
    return render_template('monthly_recommendations_trigger.html')

# --- Маршруты для Планировщика Миссий/Проектов/Задач ---
@app.route('/planning')
@login_required_custom
def planning_page(user_id_for_page):
    sphere_names = list(SPHERE_DEFINITIONS.keys()) 
    priority_values = {priority.name: priority.value for priority in PlanItemPriority} 
    return render_template('planning.html', user_id=user_id_for_page, sphere_names=sphere_names, priority_values=priority_values)

@app.route('/api/planning_items/selectable', methods=['GET'])
@login_required_custom 
def get_selectable_planning_items(user_id): 
    db: SessionLocal = next(get_db())
    try:
        items = db.query(PlanItem).filter(PlanItem.user_id == user_id, PlanItem.item_type.in_(['TASK', 'PROJECT', 'GOAL', 'SUBTASK'])).order_by(PlanItem.item_type, PlanItem.name).all()
        return jsonify([{"id": item.id, "text": f"{item.name} ({item.item_type.value if item.item_type else 'N/A'})"} for item in items])
    except Exception as e:
        return jsonify({"error": "Could not fetch selectable items", "details": str(e)}), 500
    finally:
        db.close()

@app.route('/api/planning_items', methods=['GET'])
@login_required_custom
def get_planning_items(current_user_id): 
    db: SessionLocal = next(get_db())
    try:
        statuses_from_request = request.args.getlist('status') 
        priority_from_request = request.args.get('priority') 
        spheres_from_request = request.args.getlist('sphere') 
        query = db.query(PlanItem).filter(PlanItem.user_id == current_user_id)
        if statuses_from_request:
            valid_status_enums = []
            for status_str in statuses_from_request:
                try:
                    status_enum = PlanItemStatus[status_str.upper()]
                    valid_status_enums.append(status_enum)
                except KeyError:
                    app.logger.warn(f"Invalid status filter value received: {status_str}")
            if valid_status_enums:
                query = query.filter(PlanItem.status.in_(valid_status_enums))
        if priority_from_request:
            try:
                priority_enum_val = PlanItemPriority[priority_from_request.upper()]
                query = query.filter(PlanItem.priority == priority_enum_val)
            except KeyError:
                app.logger.warn(f"Invalid priority filter value received: {priority_from_request}")
        if spheres_from_request:
            from sqlalchemy import or_ 
            sphere_conditions = [PlanItem.spheres.contains(sphere) for sphere in spheres_from_request if sphere in SPHERE_DEFINITIONS.keys()]
            if sphere_conditions:
                query = query.filter(or_(*sphere_conditions))
        items = query.order_by(PlanItem.item_type, PlanItem.name).all() 
        tree_data = [item.to_dict(include_children=False) for item in items] 
        return jsonify(tree_data)
    except Exception as e:
        print(f"Ошибка при получении элементов планирования: {e}")
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
        
        status_str = data.get('status', 'TODO').upper()
        status_enum = PlanItemStatus[status_str] if status_str and status_str in PlanItemStatus.__members__ else PlanItemStatus.TODO

        priority_str = data.get('priority')
        priority_enum = PlanItemPriority[priority_str.upper()] if priority_str and priority_str.upper() in PlanItemPriority.__members__ else None
        
        start_date_val = None
        if data.get('start_date') and data['start_date'].strip():
            try: start_date_val = date.fromisoformat(data['start_date'])
            except ValueError: pass 

        raw_spheres_data = data.get('spheres')
        spheres_for_item = raw_spheres_data if raw_spheres_data is not None else []
        description_for_item = data.get('description', '') # Гарантируем строку, если description не предоставлен
        
        new_item = PlanItem(
            user_id=user_id, parent_id=parent_id_int, item_type=PlanItemType[data['item_type']], 
            name=data['name'], description=description_for_item,
            status=status_enum, 
            start_date=start_date_val, 
            priority=priority_enum, 
            spheres=spheres_for_item
        )
        db.add(new_item)
        # Priority уже установлен в конструкторе, если был предоставлен
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
    from sqlalchemy.orm.attributes import flag_modified # Импортируем flag_modified
    db: SessionLocal = next(get_db())
    try:
        item = db.query(PlanItem).filter(PlanItem.id == item_id, PlanItem.user_id == user_id).first()
        if not item:
            return jsonify({"error": "Item not found"}), 404
        data = request.json # data уже содержит все поля из запроса
        if 'name' in data:
            item.name = data['name']
        if 'description' in data: # Явно проверяем наличие ключа
            new_description = data.get('description', '')
            if item.description != new_description:
                item.description = new_description

        if 'status' in data:
            status_str = data['status'].upper()
            if status_str and status_str in PlanItemStatus.__members__:
                item.status = PlanItemStatus[status_str]
            else:
                item.status = PlanItemStatus.TODO # или None, если допустимо и предпочтительно
                app.logger.warn(f"Invalid or missing status string '{data['status']}' for item {item_id}. Defaulting to TODO.")
        if 'item_type' in data:
            item_type_str = data['item_type'].upper()
            if item_type_str and item_type_str in PlanItemType.__members__:
                item.item_type = PlanItemType[item_type_str]
        if 'parent_id' in data: 
            item.parent_id = int(data['parent_id']) if data['parent_id'] and data['parent_id'] != "#" else None
        if 'start_date' in data: 
            start_date_str = data.get('start_date')
            if start_date_str and start_date_str.strip():
                try:
                    item.start_date = date.fromisoformat(start_date_str)
                except ValueError:
                    app.logger.warn(f"Invalid start_date format '{start_date_str}' for item {item_id}. Date not changed.")
            else: # Если пришла пустая строка или None, устанавливаем None
                item.start_date = None
        if 'priority' in data:
            priority_str = data.get('priority')
            if priority_str and priority_str.upper() in PlanItemPriority.__members__:
                item.priority = PlanItemPriority[priority_str.upper()]
            else: 
                item.priority = None
                app.logger.info(f"Priority for item {item_id} set to None due to invalid or missing value: '{data.get('priority')}'")
        if 'spheres' in data: 
            # Явно проверяем наличие ключа
            new_spheres_data = data.get('spheres')
            spheres_to_set = new_spheres_data if new_spheres_data is not None else []
            if item.spheres != spheres_to_set: # Проверяем, изменились ли сферы
                item.spheres = spheres_to_set
                flag_modified(item, "spheres") # Явно помечаем поле spheres как измененное
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
        db.delete(item) 
        db.commit()
        return jsonify({"message": "Item deleted successfully"}), 200
    except Exception as e:
        db.rollback()
        print(f"Ошибка при удалении элемента планирования: {e}")
        return jsonify({"error": "Could not delete item", "details": str(e)}), 500
    finally:
        db.close()

@app.route('/api/planning/generate_tree_ai', methods=['POST'])
@login_required_custom
def generate_tree_ai(user_id): 
    user_prompt = (
        "Создай пример древовидной структуры задач для проекта 'Разработка личного органайзера Reflect Wise'. "
        "Структура должна быть следующей: Миссии (1-2), для каждой Миссии создай Цели (1-2), для каждой Цели создай Проекты (1-2), и для каждого Проекта создай Задачи (2-3). "
        f"Используй следующие доступные сферы жизни: {', '.join(SPHERE_DEFINITIONS.keys())}. Для каждого элемента (миссии, цели, проекта, задачи) выбери 1-2 наиболее подходящие сферы из этого списка. "
        "Представь результат в виде JSON массива. Каждый элемент массива должен быть объектом, представляющим узел дерева. "
        "Каждый узел должен иметь следующие поля: "
        "'id' (уникальный строковый идентификатор, например 'm1', 'p1.1', 't1.1.1'), "
        "'parent' (строковый идентификатор родительского узла, или '#' для корневых узлов/миссий), "
        "'text' (название узла), "
        "'type' (строка: 'MISSION', 'GOAL', 'PROJECT', или 'TASK'), "
        "'description' (краткое описание узла, 1-2 предложения), "
        "'spheres' (JSON массив из 1-2 строк, представляющих выбранные сферы жизни из предоставленного списка). "
        "Убедись, что структура JSON корректна и готова для использования с jsTree."
        f"\nСписок доступных сфер: {list(SPHERE_DEFINITIONS.keys())}"
        "\nПример одного узла: {\"id\": \"m1\", \"parent\": \"#\", \"text\": \"Стать лучшей версией себя\", \"type\": \"MISSION\", \"description\": \"Достижение максимального личного потенциала во всех сферах жизни.\", \"spheres\": [\"Саморазвитие\", \"Духовное развитие\"]}"
        "\nПример узла цели: {\"id\": \"g1.1\", \"parent\": \"m1\", \"text\": \"Улучшить самоорганизацию\", \"type\": \"GOAL\", \"description\": \"Развить навыки планирования и управления временем для повышения продуктивности.\", \"spheres\": [\"Навыки\", \"Карьера/Труд\"]}"
        "\nПример узла проекта: {\"id\": \"p1.1.1\", \"parent\": \"g1.1\", \"text\": \"Разработать приложение для рефлексии\", \"type\": \"PROJECT\", \"description\": \"Создать мобильное приложение Reflect Wise для ежедневной рефлексии и планирования.\", \"spheres\": [\"Интеллект\", \"Навыки\"]}"
        "\nПример узла задачи: {\"id\": \"t1.1.1.1\", \"parent\": \"p1.1.1\", \"text\": \"Спроектировать базу данных\", \"type\": \"TASK\", \"description\": \"Определить структуру таблиц и связей для хранения пользовательских данных.\", \"spheres\": [\"Карьера/Труд\"]}"
        "Важно: Убедись, что поле 'parent' для каждого элемента правильно ссылается на 'id' его родительского элемента в соответствии с иерархией Миссия -> Цель -> Проект -> Задача."
        "Также важно, чтобы для каждого узла было сгенерировано поле 'description' и поле 'spheres' (массив из 1-2 строк, выбранных из списка доступных сфер)."
    )
    try:
        import g4f
        raw_response = g4f.ChatCompletion.create(model=g4f.models.default, messages=[{"role": "user", "content": user_prompt}])
        ai_tree_data = []
        json_start = raw_response.find('[')
        json_end = raw_response.rfind(']') + 1
        if json_start != -1 and json_end != -1 and json_start < json_end:
            json_string = raw_response[json_start:json_end]
            try:
                ai_tree_data = json.loads(json_string)
                if not isinstance(ai_tree_data, list) or not all(isinstance(item, dict) and 'id' in item and 'parent' in item and 'text' in item and 'type' in item for item in ai_tree_data):
                    if isinstance(ai_tree_data, dict) and 'id' in ai_tree_data : ai_tree_data = [ai_tree_data] 
                    else: raise ValueError("AI response is not a valid list of jsTree nodes.")
            except json.JSONDecodeError as e:
                print(f"Ошибка декодирования JSON ответа от AI: {json_string}. Ошибка: {e}")
                ai_tree_data = [{"id": "err_parse", "parent": "#", "text": "Ошибка парсинга ответа AI. Ответ был: " + raw_response[:200] + "...", "type": "ERROR"}]
            except ValueError as e: 
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
        for node_data in ai_tree_nodes:
            if not all(k in node_data for k in ('id', 'parent', 'text', 'type')):
                print(f"Skipping malformed node: {node_data}")
                continue
            node_start_date = None
            if node_data.get('start_date'):
                try: node_start_date = date.fromisoformat(node_data['start_date'])
                except ValueError: print(f"Warning: Invalid start_date format for node {node_data.get('id')}")
            new_item = PlanItem(
                user_id=user_id, name=node_data['text'], item_type=PlanItemType[node_data['type'].upper()],
                description=node_data.get('description'), status=PlanItemStatus[node_data.get('status', 'TODO').upper()],
                start_date=node_start_date, spheres=node_data.get('spheres', []) 
            )
            db.add(new_item)
            temp_ai_id_to_new_item_obj[node_data['id']] = new_item
        db.flush() 
        for ai_id, item_obj in temp_ai_id_to_new_item_obj.items():
            ai_id_to_db_id_map[ai_id] = item_obj.id 
            original_node_data = next((n for n in ai_tree_nodes if n['id'] == ai_id), None)
            if original_node_data:
                parent_ai_id = original_node_data.get('parent')
                if parent_ai_id and parent_ai_id != "#":
                    parent_db_id = ai_id_to_db_id_map.get(parent_ai_id)
                    if parent_db_id: item_obj.parent_id = parent_db_id
                    else: print(f"Warning: Parent AI ID '{parent_ai_id}' for item '{ai_id}' not found in map. Item will be root.")
        db.commit()
        for item_obj in temp_ai_id_to_new_item_obj.values():
            db.refresh(item_obj) 
            created_items_for_response.append(item_obj.to_dict(include_children=False))
        return jsonify(created_items_for_response), 201
    except Exception as e:
        db.rollback()
        print(f"Ошибка при сохранении AI-сгенерированного дерева: {e}")
        return jsonify({"error": "Could not save AI-generated tree", "details": str(e)}), 500
    finally:
        db.close()

@app.route('/api/planning/suggest_children_ai', methods=['POST'])
@login_required_custom
def suggest_children_ai(user_id):
    data = request.json
    parent_name = data.get("name")
    parent_type = data.get("type")
    parent_description = data.get("description", "")
    if not parent_name or not parent_type:
        return jsonify({"error": "Missing parent name or type"}), 400
    child_type_map = {"MISSION": "Проекты или Цели", "GOAL": "Проекты или Задачи", "PROJECT": "Задачи", "TASK": "Подзадачи", "SUBTASK": "Подзадачи"}
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
        raw_response = g4f.ChatCompletion.create(model=g4f.models.default, messages=[{"role": "user", "content": prompt}])
        suggested_children = json.loads(raw_response)
        return jsonify(suggested_children)
    except Exception as e:
        print(f"Ошибка при предложении дочерних элементов AI: {e}")
        return jsonify({"error": "Could not suggest children", "details": str(e)}), 500

@app.route('/api/planning/modify_tree_ai', methods=['POST'])
@login_required_custom
def modify_tree_ai(user_id):
    data = request.json
    user_prompt = data.get("prompt")
    if not user_prompt:
        return jsonify({"error": "Missing prompt"}), 400
    db: SessionLocal = next(get_db())
    try:
        current_items_db = db.query(PlanItem).filter(PlanItem.user_id == user_id).order_by(PlanItem.item_type, PlanItem.id).all()
        if not current_items_db:
            return jsonify({"error": "No planning items found to modify"}), 404
        current_tree_for_ai = [{"id": item.id, "parent_id": item.parent_id, "text": item.name, "type": item.item_type.value, "description": item.description, "status": item.status.value if item.status else None, "spheres": item.spheres if item.spheres else []} for item in current_items_db]
        ai_modification_prompt = (
            f"Текущая структура задач пользователя (id - это ID из базы данных):\n{json.dumps(current_tree_for_ai, indent=2, ensure_ascii=False)}\n\n"
            f"Запрос пользователя на модификацию: \"{user_prompt}\"\n\n"
            f"Доступные сферы жизни для назначения: {', '.join(SPHERE_DEFINITIONS.keys())}.\n\n"
            "Твоя задача - проанализировать текущую структуру и запрос пользователя, и предложить изменения. Придерживайся иерархии: Миссия -> Цель -> Проект -> Задача -> Подзадача. "
            "Верни JSON массив объектов, где каждый объект представляет одну операцию: 'create', 'update', 'delete'.\n"
            "Для 'create': 'item' с 'text', 'type', 'description' (опц), 'status' (опц, default TODO), 'parent_id' (ID из БД или null), 'start_date' (опц, 'YYYY-MM-DD'), 'spheres' (опц, массив строк).\n"
            "Для 'update': 'item_id' (ID из БД) и 'changes' (объект с полями для изменения: 'text', 'description', 'status', 'parent_id', 'start_date', 'spheres').\n"
            "Для 'delete': 'item_id' (ID из БД).\n"
            "Пример: [{\"operation\": \"create\", \"item\": {\"text\": \"Новая задача\", \"type\": \"TASK\", \"parent_id\": 123, \"spheres\": [\"Карьера/Труд\"]}}, {\"operation\": \"update\", \"item_id\": 456, \"changes\": {\"status\": \"DONE\"}}]\n"
            "Если не можешь выполнить или неясно, верни пустой массив []."
        )
        import g4f 
        operations = [] 
        mock_ai_response_message = "AI обработал запрос."
        try:
            raw_ai_response = g4f.ChatCompletion.create(model=g4f.models.default, messages=[{"role": "user", "content": ai_modification_prompt}])
            try:
                json_string = raw_ai_response.strip()
                try: operations = json.loads(json_string)
                except json.JSONDecodeError:
                    if "```json" in json_string: json_string = json_string.split("```json", 1)[1].split("```", 1)[0].strip()
                    elif "```" in json_string: json_string = json_string.split("```", 1)[1].split("```", 1)[0].strip()
                    operations = json.loads(json_string)
                if not isinstance(operations, list): raise ValueError("AI response is not a list of operations.")
            except (json.JSONDecodeError, ValueError, IndexError) as e:
                print(f"Error parsing AI response for modification: {e}. Response was: {raw_ai_response}")
                return jsonify({"error": "AI response parsing error", "details": str(e), "raw_response": raw_ai_response}), 500
            processed_info = []
            applied_changes = False
            if not operations: mock_ai_response_message = "AI проанализировал ваш запрос, но не предложил конкретных изменений, или запрос был неясен."
            for op in operations:
                op_type = op.get("operation")
                if op_type == "create":
                    item_data = op.get("item", {}); text = item_data.get('text'); item_type_str = item_data.get('type'); parent_id = item_data.get('parent_id'); start_date_str = item_data.get('start_date')
                    if not text or not item_type_str: processed_info.append(f"AI ОШИБКА CREATE: Отсутствует text или type. Данные: {item_data}"); continue
                    try: item_type_enum = PlanItemType[item_type_str.upper()]
                    except KeyError: processed_info.append(f"AI ОШИБКА CREATE: Неверный item_type '{item_type_str}'."); continue
                    actual_parent_id = None
                    if parent_id:
                        parent_item = db.query(PlanItem).filter(PlanItem.id == parent_id, PlanItem.user_id == user_id).first()
                        if not parent_item: processed_info.append(f"AI ПРЕДУПРЕЖДЕНИЕ CREATE: Родительский элемент с ID {parent_id} не найден. Элемент будет создан как корневой.")
                        else: actual_parent_id = parent_id
                    actual_start_date = None
                    if start_date_str:
                        try: actual_start_date = date.fromisoformat(start_date_str.strip())
                        except ValueError: processed_info.append(f"AI ПРЕДУПРЕЖДЕНИЕ CREATE: Неверный формат start_date '{start_date_str}'. Дата не будет установлена.")
                    ai_spheres = item_data.get('spheres', []); valid_spheres = []
                    if isinstance(ai_spheres, list):
                        for s_name in ai_spheres:
                            if isinstance(s_name, str) and s_name in SPHERE_DEFINITIONS: valid_spheres.append(s_name)
                            else: processed_info.append(f"AI ПРЕДУПРЕЖДЕНИЕ CREATE: Неверная сфера '{s_name}' для элемента '{text}'. Сфера проигнорирована.")
                    else: processed_info.append(f"AI ПРЕДУПРЕЖДЕНИЕ CREATE: Поле 'spheres' для элемента '{text}' не является списком. Сферы проигнорированы.")
                    new_pi = PlanItem(user_id=user_id, name=text, item_type=item_type_enum, description=item_data.get('description', ''), status=PlanItemStatus[item_data.get('status', 'TODO').upper()], parent_id=actual_parent_id, start_date=actual_start_date, spheres=valid_spheres)
                    db.add(new_pi); applied_changes = True; processed_info.append(f"AI ПРИМЕНЕНО: СОЗДАН элемент '{text}' типа '{item_type_str}' (родитель: {actual_parent_id if actual_parent_id else 'корень'})")
                elif op_type == "update":
                    item_id_to_update = op.get("item_id"); changes = op.get("changes", {})
                    if not item_id_to_update or not changes: processed_info.append(f"AI ОШИБКА UPDATE: Отсутствует item_id или changes. Данные: {op}"); continue
                    target_item = db.query(PlanItem).filter(PlanItem.id == item_id_to_update, PlanItem.user_id == user_id).first()
                    if not target_item: processed_info.append(f"AI ОШИБКА UPDATE: Элемент с ID {item_id_to_update} не найден."); continue
                    for key, value in changes.items():
                        if key == "parent_id":
                            actual_parent_id_update = None
                            if value: 
                                parent_check = db.query(PlanItem).filter(PlanItem.id == value, PlanItem.user_id == user_id).first()
                                if not parent_check: processed_info.append(f"AI ПРЕДУПРЕЖДЕНИЕ UPDATE: Новый родитель с ID {value} для элемента {item_id_to_update} не найден. parent_id не изменен."); continue 
                                else: actual_parent_id_update = value
                            setattr(target_item, key, actual_parent_id_update)
                        elif key == "status":
                            try: setattr(target_item, key, PlanItemStatus[value.upper()])
                            except KeyError: processed_info.append(f"AI ПРЕДУПРЕЖДЕНИЕ UPDATE: Неверный status '{value}' для элемента {item_id_to_update}.")
                        elif key == "start_date":
                            if value is None: setattr(target_item, key, None)
                            else:
                                try: setattr(target_item, key, date.fromisoformat(str(value).strip()))
                                except ValueError: processed_info.append(f"AI ПРЕДУПРЕЖДЕНИЕ UPDATE: Неверный формат start_date '{value}' для элемента {item_id_to_update}. Дата не изменена."); continue 
                        elif key == "spheres": 
                            valid_spheres_update = []
                            if isinstance(value, list):
                                for s_name in value:
                                    if isinstance(s_name, str) and s_name in SPHERE_DEFINITIONS: valid_spheres_update.append(s_name)
                                    else: processed_info.append(f"AI ПРЕДУПРЕЖДЕНИЕ UPDATE: Неверная сфера '{s_name}' для элемента ID {item_id_to_update}. Сфера проигнорирована.")
                                setattr(target_item, key, valid_spheres_update)
                            else: processed_info.append(f"AI ПРЕДУПРЕЖДЕНИЕ UPDATE: Поле 'spheres' для элемента ID {item_id_to_update} не является списком. Сферы не изменены.")
                        elif hasattr(target_item, key): setattr(target_item, key, value)
                        else: processed_info.append(f"AI ПРЕДУПРЕЖДЕНИЕ UPDATE: Неверное поле '{key}' для обновления элемента {item_id_to_update}.")
                    applied_changes = True; processed_info.append(f"AI ПРИМЕНЕНО: ОБНОВЛЕН элемент ID {item_id_to_update} с изменениями: {changes}")
                elif op_type == "delete":
                    item_id_to_delete = op.get("item_id")
                    target_item_to_delete = db.query(PlanItem).filter(PlanItem.id == item_id_to_delete, PlanItem.user_id == user_id).first()
                    if target_item_to_delete: db.delete(target_item_to_delete); applied_changes = True; processed_info.append(f"AI ПРИМЕНЕНО: УДАЛЕН элемент ID {item_id_to_delete} ('{target_item_to_delete.name}')")
                    else: processed_info.append(f"AI ОШИБКА DELETE: Элемент с ID {item_id_to_delete} не найден.")
                else: processed_info.append(f"AI предлагает: НЕИЗВЕСТНАЯ операция {op}")
            if operations: 
                if applied_changes: db.commit(); mock_ai_response_message = "AI обработал ваш запрос. Изменения применены. Детали:\n" + "\n".join(processed_info)
                else: mock_ai_response_message = "AI обработал ваш запрос, но изменения не были применены. Детали:\n" + "\n".join(processed_info)
        except Exception as ai_call_exception:
            print(f"Error calling AI for modification: {ai_call_exception}")
            return jsonify({"error": "AI call failed", "details": str(ai_call_exception)}), 500
        refreshed_items_db = db.query(PlanItem).filter(PlanItem.user_id == user_id).order_by(PlanItem.item_type, PlanItem.id).all()
        return jsonify({"message": mock_ai_response_message, "prompt_received": user_prompt, "ai_operations_parsed": operations, "modified_tree_data": [item.to_dict(include_children=False) for item in refreshed_items_db]}), 200
    except Exception as e:
        db.rollback()
        print(f"Ошибка при модификации дерева AI: {e}")
        return jsonify({"error": "Could not modify tree with AI", "details": str(e)}), 500
    finally:
        db.close()

# --- Эндпоинт для импорта ветки дерева ---
@app.route('/api/planning/import_branch', methods=['POST'])
@login_required_custom
def import_planning_branch(user_id):
    db: SessionLocal = next(get_db())
    try:
        data = request.json
        branch_data = data.get('branch_data') # Ожидается объект или массив объектов
        parent_db_id_str = data.get('parent_id') # ID родителя в БД, может быть null

        parent_db_id = int(parent_db_id_str) if parent_db_id_str else None

        if not branch_data:
            return jsonify({"error": "No branch data provided"}), 400

        created_items_response = []

        def create_items_recursive(items_to_create, current_parent_id):
            for item_data in (items_to_create if isinstance(items_to_create, list) else [items_to_create]):
                new_item = PlanItem(
                    user_id=user_id,
                    name=item_data.get('name', 'Без названия'),
                    item_type=PlanItemType[item_data.get('type', 'TASK').upper()],
                    description=item_data.get('description'),
                    status=PlanItemStatus[item_data.get('status', 'TODO').upper()],
                    priority=PlanItemPriority[item_data['priority'].upper()] if item_data.get('priority') and item_data['priority'] in PlanItemPriority.__members__ else None,
                    spheres=item_data.get('spheres', []),
                    parent_id=current_parent_id
                )
                db.add(new_item)
                db.flush() # Получаем ID для нового элемента
                created_items_response.append(new_item.to_dict(include_children=False))
                if item_data.get('children'):
                    create_items_recursive(item_data['children'], new_item.id)

        create_items_recursive(branch_data, parent_db_id)
        db.commit()
        return jsonify({"message": "Branch imported successfully", "imported_items": created_items_response}), 201
    except Exception as e:
        db.rollback()
        print(f"Ошибка при импорте ветки: {e}")
        return jsonify({"error": "Could not import branch", "details": str(e)}), 500
    finally:
        db.close()

# --- Маршруты и логика для Трекера Привычек ---
def recalculate_habit_streak(db: SessionLocal, habit: Habit):
    entries = db.query(DailyHabitEntry).filter(DailyHabitEntry.habit_id == habit.id).order_by(desc(DailyHabitEntry.date)).all()
    if not entries: habit.formation_streak = 0; habit.last_completed_date = None; return
    last_known_completed_entry_date = None
    for entry in entries: 
        if entry.is_completed: last_known_completed_entry_date = entry.date; break 
    habit.last_completed_date = last_known_completed_entry_date
    if last_known_completed_entry_date is None: habit.formation_streak = 0
    else:
        streak_count = 0; expected_date = last_known_completed_entry_date
        entries_by_date = {entry.date: entry for entry in entries}
        while True:
            current_day_entry = entries_by_date.get(expected_date)
            if current_day_entry and current_day_entry.is_completed: streak_count += 1; expected_date -= timedelta(days=1)
            else: break 
        habit.formation_streak = streak_count

@app.route('/habits', methods=['GET'])
@login_required_custom
def habits_page(current_user_id):
    db: SessionLocal = next(get_db())
    try:
        selected_date_str = request.args.get('date', datetime.now(timezone.utc).date().isoformat())
        selected_date_obj = date.fromisoformat(selected_date_str)
        carousel_dates = get_date_carousel_options(selected_date_iso_str=selected_date_str, num_days_around=3)
        user_active_habits = db.query(Habit).filter(Habit.user_id == current_user_id, Habit.is_active == True).order_by(Habit.created_at).all()
        daily_entries_for_display = []
        for habit_obj in user_active_habits:
            daily_entry = db.query(DailyHabitEntry).filter(DailyHabitEntry.habit_id == habit_obj.id, DailyHabitEntry.date == selected_date_obj).first()
            if not daily_entry:
                # Логика создания DailyHabitEntry должна учитывать расписание привычки
                # Пока что оставляем как есть, но это место для доработки
                # Если привычка не должна быть активна сегодня по расписанию, запись не создаем
                is_due_today = True # ЗАГЛУШКА - здесь должна быть проверка расписания
                if habit_obj.frequency_type == HabitFrequencyType.WEEKLY:
                    if habit_obj.days_of_week is None or selected_date_obj.weekday() not in habit_obj.days_of_week:
                        is_due_today = False
                elif habit_obj.frequency_type == HabitFrequencyType.MONTHLY:
                    if habit_obj.days_of_month is None or selected_date_obj.day not in habit_obj.days_of_month:
                        is_due_today = False
                
                if is_due_today:
                    daily_entry = DailyHabitEntry(habit_id=habit_obj.id, user_id=current_user_id, date=selected_date_obj, is_completed=False)
                    db.add(daily_entry); db.commit(); db.refresh(daily_entry)
                else:
                    # Если привычка не запланирована на сегодня, не добавляем ее в список для отображения активных
                    continue 
            
            if daily_entry: # Убедимся, что daily_entry существует (оно может быть None, если is_due_today было False)
                daily_entries_for_display.append({"entry_id": daily_entry.id, "habit_id": habit_obj.id, "habit_name": habit_obj.name, "habit_description": habit_obj.description, "is_completed": daily_entry.is_completed, "notes": daily_entry.notes, "streak": habit_obj.formation_streak, "target": habit_obj.formation_target_days, "frequency_type": habit_obj.frequency_type.value, "days_of_week": habit_obj.days_of_week, "days_of_month": habit_obj.days_of_month })
        formed_habits = db.query(Habit).filter(Habit.user_id == current_user_id, Habit.is_active == False, Habit.formation_streak >= Habit.formation_target_days).order_by(desc(Habit.updated_at)).limit(10).all()
        return render_template('habits.html', daily_habits=daily_entries_for_display, formed_habits=formed_habits, selected_date_iso=selected_date_str, selected_date_obj=selected_date_obj, carousel_dates=carousel_dates, default_formation_days=14)
    except Exception as e:
        db.rollback(); print(f"Error on habits page: {e}"); flash(f"Ошибка загрузки страницы привычек: {e}", "danger"); return redirect(url_for('index'))
    finally: db.close()

@app.route('/api/habits', methods=['POST'])
@login_required_custom
def create_habit(current_user_id):
    db: SessionLocal = next(get_db())
    data = request.json
    name = data.get('name')
    description = data.get('description')
    formation_target_days_str = data.get('formation_target_days')
    frequency_type_str = data.get('frequency_type', 'DAILY').upper()
    days_of_week_data = data.get('days_of_week') # Ожидается список чисел [0-6]
    days_of_month_data = data.get('days_of_month') # Ожидается список чисел [1-31]


    if not name or not name.strip():
        return jsonify({"error": "Название привычки обязательно и не может быть пустым."}), 400

    if formation_target_days_str is None or str(formation_target_days_str).strip() == '':
        formation_target_days = 14 # Значение по умолчанию, если не указано или пусто
    else:
        try:
            formation_target_days = int(formation_target_days_str)
        except ValueError:
            return jsonify({"error": "Цель формирования (в днях) должна быть целым числом."}), 400
    
    if not (7 <= formation_target_days <= 365):
        return jsonify({"error": "Цель формирования должна быть между 7 и 365 днями (включительно)."}), 400

    try:
        frequency_type = HabitFrequencyType[frequency_type_str]
    except KeyError:
        return jsonify({"error": "Недопустимый тип частоты."}), 400

    valid_days_of_week = None
    if frequency_type == HabitFrequencyType.WEEKLY:
        if not isinstance(days_of_week_data, list) or not all(isinstance(d, int) and 0 <= d <= 6 for d in days_of_week_data):
            return jsonify({"error": "Для еженедельной привычки 'days_of_week' должен быть списком чисел от 0 до 6."}), 400
        if not days_of_week_data: # Должен быть выбран хотя бы один день
             return jsonify({"error": "Для еженедельной привычки должен быть выбран хотя бы один день недели."}), 400
        valid_days_of_week = sorted(list(set(days_of_week_data))) # Убираем дубликаты и сортируем

    valid_days_of_month = None
    if frequency_type == HabitFrequencyType.MONTHLY:
        if not isinstance(days_of_month_data, list) or not all(isinstance(d, int) and 1 <= d <= 31 for d in days_of_month_data):
            return jsonify({"error": "Для ежемесячной привычки 'days_of_month' должен быть списком чисел от 1 до 31."}), 400
        if not days_of_month_data: # Должен быть выбран хотя бы один день
            return jsonify({"error": "Для ежемесячной привычки должен быть выбран хотя бы один день месяца."}), 400
        valid_days_of_month = sorted(list(set(days_of_month_data)))

    try:
        new_habit = Habit(
            user_id=current_user_id, 
            name=name, 
            description=description, 
            formation_target_days=formation_target_days,
            frequency_type=frequency_type,
            days_of_week=valid_days_of_week,
            days_of_month=valid_days_of_month
        )
        db.add(new_habit); db.commit(); db.refresh(new_habit)
        
        # Создаем запись на сегодня, только если привычка должна быть выполнена сегодня
        today_date = datetime.now(timezone.utc).date()
        today_entry = db.query(DailyHabitEntry).filter(DailyHabitEntry.habit_id == new_habit.id, DailyHabitEntry.date == today_date).first()
        if not today_entry:
            # Проверка, должна ли привычка быть активна сегодня (упрощенная, полная логика в habits_page)
            is_due_today_for_new = True
            if new_habit.frequency_type == HabitFrequencyType.WEEKLY and (new_habit.days_of_week is None or today_date.weekday() not in new_habit.days_of_week):
                is_due_today_for_new = False
            elif new_habit.frequency_type == HabitFrequencyType.MONTHLY and (new_habit.days_of_month is None or today_date.day not in new_habit.days_of_month):
                is_due_today_for_new = False
            
            if is_due_today_for_new:
                today_entry = DailyHabitEntry(habit_id=new_habit.id, user_id=current_user_id, date=today_date, is_completed=False)
                db.add(today_entry); db.commit()

        flash(f"Привычка '{new_habit.name}' добавлена.", "success")
        return jsonify({"message": "Привычка создана", "habit": {"id": new_habit.id, "name": new_habit.name, "description": new_habit.description, "is_active": new_habit.is_active, "formation_streak": new_habit.formation_streak, "formation_target_days": new_habit.formation_target_days, "frequency_type": new_habit.frequency_type.value, "days_of_week": new_habit.days_of_week, "days_of_month": new_habit.days_of_month}}), 201
    except Exception as e:
        db.rollback(); print(f"Error creating habit: {e}"); return jsonify({"error": "Ошибка сервера при создании привычки", "details": str(e)}), 500
    finally: db.close()

@app.route('/api/habits/<int:habit_id>', methods=['PUT'])
@login_required_custom
def update_habit(current_user_id, habit_id):
    db: SessionLocal = next(get_db())
    try:
        habit_to_update = db.query(Habit).filter(Habit.id == habit_id, Habit.user_id == current_user_id).first()
        if not habit_to_update:
            return jsonify({"error": "Привычка не найдена или у вас нет прав на её редактирование"}), 404

        data = request.json
        new_name = data.get('name', habit_to_update.name).strip()
        new_description = data.get('description', habit_to_update.description)
        new_target_days_str = data.get('formation_target_days', str(habit_to_update.formation_target_days))
        frequency_type_str = data.get('frequency_type', habit_to_update.frequency_type.value).upper()
        days_of_week_data = data.get('days_of_week') # Может быть None, если не меняется или тип DAILY/MONTHLY
        days_of_month_data = data.get('days_of_month') # Может быть None


        if not new_name:
            return jsonify({"error": "Название привычки не может быть пустым."}), 400
        
        try:
            new_target_days = int(new_target_days_str)
            if not (7 <= new_target_days <= 365):
                return jsonify({"error": "Цель формирования должна быть между 7 и 365 днями."}), 400
        except ValueError:
            return jsonify({"error": "Цель формирования (в днях) должна быть целым числом."}), 400

        try:
            new_frequency_type = HabitFrequencyType[frequency_type_str]
        except KeyError:
            return jsonify({"error": "Недопустимый тип частоты."}), 400

        valid_days_of_week = habit_to_update.days_of_week
        if new_frequency_type == HabitFrequencyType.WEEKLY:
            if days_of_week_data is not None: # Обновляем, только если передано
                if not isinstance(days_of_week_data, list) or not all(isinstance(d, int) and 0 <= d <= 6 for d in days_of_week_data):
                    return jsonify({"error": "Для еженедельной привычки 'days_of_week' должен быть списком чисел от 0 до 6."}), 400
                if not days_of_week_data:
                     return jsonify({"error": "Для еженедельной привычки должен быть выбран хотя бы один день недели."}), 400
                valid_days_of_week = sorted(list(set(days_of_week_data)))
        elif days_of_week_data is None and new_frequency_type == HabitFrequencyType.WEEKLY and habit_to_update.days_of_week is None: # Если тип WEEKLY, а дни не заданы
            return jsonify({"error": "Для еженедельной привычки должны быть указаны дни недели."}), 400
        else: # Для DAILY или MONTHLY, или если не обновляется
            valid_days_of_week = None if new_frequency_type != HabitFrequencyType.WEEKLY else habit_to_update.days_of_week

        valid_days_of_month = habit_to_update.days_of_month
        if new_frequency_type == HabitFrequencyType.MONTHLY:
            if days_of_month_data is not None:
                if not isinstance(days_of_month_data, list) or not all(isinstance(d, int) and 1 <= d <= 31 for d in days_of_month_data):
                    return jsonify({"error": "Для ежемесячной привычки 'days_of_month' должен быть списком чисел от 1 до 31."}), 400
                if not days_of_month_data:
                    return jsonify({"error": "Для ежемесячной привычки должен быть выбран хотя бы один день месяца."}), 400
                valid_days_of_month = sorted(list(set(days_of_month_data)))
        elif days_of_month_data is None and new_frequency_type == HabitFrequencyType.MONTHLY and habit_to_update.days_of_month is None:
            return jsonify({"error": "Для ежемесячной привычки должны быть указаны дни месяца."}), 400
        else:
            valid_days_of_month = None if new_frequency_type != HabitFrequencyType.MONTHLY else habit_to_update.days_of_month

        habit_to_update.name = new_name
        habit_to_update.description = new_description
        habit_to_update.formation_target_days = new_target_days
        habit_to_update.frequency_type = new_frequency_type
        habit_to_update.days_of_week = valid_days_of_week
        habit_to_update.days_of_month = valid_days_of_month

        # Если привычка была сформирована, но цель изменилась так, что она больше не сформирована, делаем ее активной
        if not habit_to_update.is_active and habit_to_update.formation_streak < new_target_days:
            habit_to_update.is_active = True
        # Если привычка активна, но теперь по новой цели она сформирована
        elif habit_to_update.is_active and habit_to_update.formation_streak >= new_target_days:
             habit_to_update.is_active = False

        db.commit(); db.refresh(habit_to_update)
        return jsonify({"message": "Привычка обновлена", "habit": {"id": habit_to_update.id, "name": habit_to_update.name, "description": habit_to_update.description, "is_active": habit_to_update.is_active, "formation_streak": habit_to_update.formation_streak, "formation_target_days": habit_to_update.formation_target_days, "frequency_type": habit_to_update.frequency_type.value, "days_of_week": habit_to_update.days_of_week, "days_of_month": habit_to_update.days_of_month}}), 200
    except Exception as e:
        db.rollback(); print(f"Error updating habit: {e}"); return jsonify({"error": "Ошибка сервера при обновлении привычки", "details": str(e)}), 500
    finally: db.close()

@app.route('/api/daily_habit_entries/<int:entry_id>', methods=['PUT'])
@login_required_custom
def update_daily_habit_entry(current_user_id, entry_id):
    db: SessionLocal = next(get_db())
    try:
        data = request.json; is_completed = data.get('is_completed'); notes = data.get('notes')
        if is_completed is None: return jsonify({"error": "Missing 'is_completed' field"}), 400
        entry = db.query(DailyHabitEntry).filter(DailyHabitEntry.id == entry_id, DailyHabitEntry.user_id == current_user_id).first()
        if not entry: return jsonify({"error": "Запись о привычке не найдена"}), 404
        entry.is_completed = bool(is_completed)
        if notes is not None: entry.notes = notes
        db.flush() 
        habit = db.query(Habit).filter(Habit.id == entry.habit_id).first()
        if not habit: db.rollback(); return jsonify({"error": "Связанная привычка не найдена"}), 500
        was_active_before_update = habit.is_active
        recalculate_habit_streak(db, habit)
        if habit.formation_streak >= habit.formation_target_days:
            if was_active_before_update: habit.is_active = False; flash(f"Поздравляем! Привычка '{habit.name}' успешно сформирована.", "success")
        db.commit(); db.refresh(habit); db.refresh(entry)
        return jsonify({"message": "Статус привычки обновлен", "entry": {"id": entry.id, "is_completed": entry.is_completed, "notes": entry.notes, "date": entry.date.isoformat()}, "habit_streak": habit.formation_streak, "habit_last_completed": habit.last_completed_date.isoformat() if habit.last_completed_date else None, "habit_is_active": habit.is_active, "habit_name": habit.name, "habit_target": habit.formation_target_days})
    except Exception as e:
        db.rollback(); print(f"Error updating daily habit entry: {e}"); return jsonify({"error": "Ошибка сервера при обновлении привычки", "details": str(e)}), 500
    finally: db.close()

@app.route('/api/habits/<int:habit_id>', methods=['DELETE'])
@login_required_custom
def delete_habit(current_user_id, habit_id):
    db: SessionLocal = next(get_db())
    try:
        habit_to_delete = db.query(Habit).filter(Habit.id == habit_id, Habit.user_id == current_user_id).first()
        if not habit_to_delete: return jsonify({"error": "Привычка не найдена или у вас нет прав на её удаление"}), 404
        db.delete(habit_to_delete); db.commit()
        flash(f"Привычка '{habit_to_delete.name}' и все связанные с ней записи удалены.", "info")
        return jsonify({"message": "Привычка удалена"}), 200
    except Exception as e:
        db.rollback(); print(f"Error deleting habit: {e}"); return jsonify({"error": "Ошибка сервера при удалении привычки", "details": str(e)}), 500
    finally: db.close()

# --- Маршрут-заглушка для страницы профиля ---
@app.route('/profile')
@login_required_custom
def profile_page(current_user_id):
    db: SessionLocal = next(get_db())
    try:
        user = db.query(User).filter_by(id=current_user_id).first()
        if not user:
            flash("Пользователь не найден.", "danger")
            return redirect(url_for('logout'))
        
        user_achievements_earned = db.query(UserAchievement).filter_by(user_id=current_user_id).order_by(desc(UserAchievement.earned_at)).all()
        
        # Доступные темы (можно вынести в конфигурацию или определить здесь)
        available_themes = {
            'litera': 'Litera (Светлая)',
            'darkly': 'Darkly (Темная)',
            'cerulean': 'Cerulean (Голубая)',
            'cosmo': 'Cosmo (Космос)',
            'flatly': 'Flatly (Плоская)',
            'journal': 'Journal (Журнал)',
            'lumen': 'Lumen (Светящаяся)',
            'lux': 'Lux (Люкс)',
            'materia': 'Materia (Материальная)',
            'minty': 'Minty (Мятная)',
            'pulse': 'Pulse (Пульс)',
            'sandstone': 'Sandstone (Песчаник)',
            'simplex': 'Simplex (Простая)',
            'sketchy': 'Sketchy (Эскиз)',
            'slate': 'Slate (Сланец)',
            'solar': 'Solar (Солнечная)',
            'spacelab': 'Spacelab (Космолаб)',
            'superhero': 'Superhero (Супергерой)',
            'united': 'United (Объединенная)',
            'yeti': 'Yeti (Йети)'
        }
        return render_template('profile.html', user=user, achievements=user_achievements_earned, available_themes=available_themes)
    except Exception as e:
        print(f"Ошибка на странице профиля: {e}")
        flash("Ошибка загрузки профиля.", "danger")
        return redirect(url_for('index'))
    finally:
        db.close()

@app.route('/profile/update_theme', methods=['POST'])
@login_required_custom
def update_theme(current_user_id):
    db: SessionLocal = next(get_db())
    try:
        new_theme = request.form.get('theme')
        user = db.query(User).filter_by(id=current_user_id).first()
        if not user:
            flash("Пользователь не найден.", "danger")
            return redirect(url_for('logout'))
        
        # Здесь можно добавить проверку, что new_theme одна из доступных, если нужно
        user.theme = new_theme
        db.commit()
        session['user_theme'] = new_theme # Обновляем тему в сессии для немедленного применения
        flash("Тема оформления обновлена.", "success")
    except Exception as e:
        db.rollback()
        print(f"Ошибка обновления темы: {e}")
        flash("Не удалось обновить тему.", "danger")
    finally:
        db.close()
    return redirect(url_for('profile_page'))

# --- Маршрут для Утреннего Ритуала ---
@app.route('/morning_ritual', methods=['GET', 'POST'])
@login_required_custom
def morning_ritual_page(current_user_id):
    db: SessionLocal = next(get_db())
    form_date_iso = request.args.get('date', datetime.now(timezone.utc).date().isoformat())
    form_date_obj = date.fromisoformat(form_date_iso)
    carousel_dates = get_date_carousel_options(selected_date_iso_str=form_date_iso, url_route='morning_ritual_page')

    try:
        existing_plan = db.query(Plan).filter_by(user_id=current_user_id, date=form_date_obj).first()
        if not existing_plan:
            existing_plan = Plan(user_id=current_user_id, date=form_date_obj) # Создаем объект, если его нет, для передачи в шаблон

        if request.method == 'POST':
            try:
                plan_date_iso_from_form = request.form.get('selected_date', datetime.now(timezone.utc).date().isoformat())
                plan_date_obj = date.fromisoformat(plan_date_iso_from_form)
                
                plan_to_save = db.query(Plan).filter_by(user_id=current_user_id, date=plan_date_obj).first()
                is_new_plan_entry = False
                if not plan_to_save:
                    plan_to_save = Plan(user_id=current_user_id, date=plan_date_obj)
                    # is_new_plan_entry = True # Флаг для возможной ачивки, если бы план сохранялся здесь
                    db.add(plan_to_save)

                plan_to_save.ritual_user_preferences = request.form.get('ritual_preferences')

                db.commit()
                # Логика ачивки за первый план здесь неактуальна, т.к. сам план (задачи, вопросы) здесь не сохраняется

                flash('Предпочтения для утреннего ритуала сохранены!', 'success')
                return redirect(url_for('morning_ritual_page', date=plan_date_obj.isoformat())) 
            except Exception as e:
                db.rollback()
                print(f"Ошибка при сохранении предпочтений ритуала: {e}")
                flash('Произошла ошибка при сохранении предпочтений ритуала.', 'danger')
                # При ошибке POST, отображаем страницу с текущим existing_plan для поля ritual_preferences
                return render_template('morning_ritual.html', plan=existing_plan, carousel_dates=carousel_dates, selected_date_iso=form_date_iso)

        # GET-запрос: отображаем страницу с existing_plan (для ritual_preferences и отображения сгенерированного ритуала)
        # и каруселью дат.
        return render_template('morning_ritual.html', plan=existing_plan, carousel_dates=carousel_dates, selected_date_iso=form_date_iso)
    except Exception as e:
        print(f"Ошибка при загрузке страницы утреннего ритуала: {e}")
        flash('Произошла ошибка при загрузке страницы утреннего ритуала.', 'danger')
        # В случае общей ошибки при GET-запросе, пытаемся отобразить страницу с тем, что есть
        _plan_for_error = existing_plan if 'existing_plan' in locals() and existing_plan else Plan(user_id=current_user_id, date=form_date_obj)
        _carousel_dates_to_render = carousel_dates if 'carousel_dates' in locals() and carousel_dates else get_date_carousel_options(selected_date_iso_str=form_date_iso, url_route='morning_ritual_page')
        
        return render_template('morning_ritual.html', plan=_plan_for_error, carousel_dates=_carousel_dates_to_render, selected_date_iso=form_date_iso)
    finally:
        db.close()

# --- API ЭНДПОИНТ для генерации ритуала ---
@app.route('/api/morning_ritual/generate_ai', methods=['POST'])
@login_required_custom
def generate_morning_ritual_ai(current_user_id):
    db: SessionLocal = next(get_db())
    try:
        data = request.json
        plan_date_str = data.get('date')
        user_preferences = data.get('preferences', '')

        if not plan_date_str:
            return jsonify({"error": "Дата плана не указана."}), 400
        
        plan_date_obj = date.fromisoformat(plan_date_str)

        plan_entry = db.query(Plan).filter_by(user_id=current_user_id, date=plan_date_obj).first()
        if not plan_entry:
            plan_entry = Plan(user_id=current_user_id, date=plan_date_obj)
            db.add(plan_entry)

        plan_entry.ritual_user_preferences = user_preferences

        prompt = (
            "Создай персонализированный утренний ритуал, разделенный на две части. "
            "Часть 1: действия ДО заполнения дневника/плана (например, пробуждение, вода, короткая разминка/дыхание). "
            "Часть 2: действия ПОСЛЕ заполнения дневника/плана (например, здоровый завтрак, зарядка энергией). "
            "Не включай в ритуал пункты 'заполнение дневника', 'планирование дня' или 'расстановка приоритетов', так как пользователь делает это между частями ритуала. "
            "Учти следующие предпочтения и ограничения пользователя: "
            f"'{user_preferences if user_preferences else 'Общие рекомендации, если предпочтений нет.'}'\n\n"
            "Представь результат в формате JSON с двумя ключами: 'ritual_part1' и 'ritual_part2', где значение каждого ключа - это текстовое описание соответствующей части ритуала. "
            "Пример: {\"ritual_part1\": \"1. Пробуждение в 7:00, сразу встать.\\n2. Выпить стакан теплой воды с лимоном.\\n3. 5 минут дыхательной гимнастики.\", \"ritual_part2\": \"1. Приготовить и съесть овсянку с ягодами.\\n2. 10 минут послушать вдохновляющую музыку.\"}"
        )

        import g4f
        raw_response_text = g4f.ChatCompletion.create(
            model=g4f.models.default,
            messages=[{"role": "user", "content": prompt}],
        )

        try:
            # Очистка от markdown-оберток, если они есть
            json_string_ritual = str(raw_response_text).strip()
            if json_string_ritual.startswith("```json"):
                json_string_ritual = json_string_ritual[len("```json"):].strip()
            if json_string_ritual.endswith("```"):
                json_string_ritual = json_string_ritual[:-len("```")].strip()
            
            ritual_data = json.loads(json_string_ritual)
            part1 = ritual_data.get("ritual_part1", "Не удалось сгенерировать часть 1.")
            part2 = ritual_data.get("ritual_part2", "Не удалось сгенерировать часть 2.")
        except (json.JSONDecodeError, TypeError):
            part1 = "Ошибка: AI вернул некорректный формат для части 1. Ответ: " + str(raw_response_text)[:200] + "..."
            part2 = "Ошибка: AI вернул некорректный формат для части 2."
            print(f"Ошибка декодирования JSON для ритуала: {raw_response_text}")

        plan_entry.ritual_part1_raw = part1
        plan_entry.ritual_part2_raw = part2
        db.commit()
        return jsonify({"ritual_part1": part1, "ritual_part2": part2, "message": "Ритуал сгенерирован и сохранен."})
    except Exception as e:
        db.rollback()
        print(f"Ошибка генерации утреннего ритуала AI: {e}")
        return jsonify({"error": "Ошибка сервера при генерации ритуала.", "details": str(e)}), 500
    finally:
        db.close()

# --- Вспомогательная функция для структуры задач дня ---
def _to_daily_task_dto(text, source, source_id=None, status='todo', comment='', is_excluded=False, description='', priority=None, spheres=None, original_item_id=None):
    """Создает стандартизированный объект задачи для страницы daily_tasks_manager."""
    # Генерируем ID: стабильный, если есть source_id, иначе временный на основе времени/случайности
    task_internal_id = f"{source}_{source_id}" if source_id else f"{source}_{int(time.time())}_{random.randint(1000,9999)}"
    return {
        "id": task_internal_id, # Уникальный ID для задачи в рамках списка на день
        "text": text,
        "source": source, # 'planner', 'quest', 'habit', 'manual'
        "source_id": source_id, # ID оригинального объекта в БД (SphereQuestTask.id, DailyHabitEntry.id и т.д.)
        "original_item_id": original_item_id, # Для задач из PlanItem, их ID
        "status": status, # 'todo', 'done'
        "comment": comment,
        "is_excluded": is_excluded, # Если пользователь скрыл задачу на день
        "description": description,
        "priority": priority.value if hasattr(priority, 'value') else priority, # значение Enum или строка
        "spheres": spheres or []
    }

# --- Маршрут для Менеджера Задач Дня ---
@app.route('/daily_tasks_manager', methods=['GET', 'POST'])
@login_required_custom
def daily_tasks_manager(current_user_id):
    db: SessionLocal = next(get_db())
    try:
        selected_date_iso = request.args.get('date', datetime.now(timezone.utc).date().isoformat())
        target_date = date.fromisoformat(selected_date_iso)
        carousel_dates = get_date_carousel_options(selected_date_iso_str=selected_date_iso, url_route='daily_tasks_manager')

        plan_obj = db.query(Plan).filter(Plan.user_id == current_user_id, Plan.date == target_date).first()

        if request.method == 'POST':
            tasks_data_json = request.form.get('tasks_data')
            if not tasks_data_json:
                flash("Нет данных о задачах для сохранения.", "warning")
                return redirect(url_for('daily_tasks_manager', date=selected_date_iso))

            if not plan_obj:
                plan_obj = Plan(user_id=current_user_id, date=target_date)
                db.add(plan_obj)
            
            plan_obj.managed_daily_tasks = tasks_data_json # Сохраняем весь JSON как есть

            # Синхронизация статусов с оригинальными источниками
            try:
                parsed_tasks = json.loads(tasks_data_json)
                for task_dto in parsed_tasks:
                    source = task_dto.get('source')
                    source_id = task_dto.get('source_id') # Это ID оригинальной записи (SphereQuestTask, DailyHabitEntry)
                    status_done = task_dto.get('status') == 'done'
                    status_partial = task_dto.get('status') == 'partial' # Учитываем частичное выполнение
                    comment = task_dto.get('comment', '')
                    is_excluded = task_dto.get('is_excluded', False)

                    if is_excluded: # Если задача исключена, не обновляем ее статус в источнике
                        continue

                    if source == 'quest' and source_id:
                        sq_task = db.query(SphereQuestTask).filter(SphereQuestTask.id == source_id).join(DailySphereQuest).filter(DailySphereQuest.user_id == current_user_id).first()
                        if sq_task:
                            sq_task.is_completed = status_done
                    elif source == 'habit' and source_id: # source_id это DailyHabitEntry.id
                        dhe = db.query(DailyHabitEntry).filter(DailyHabitEntry.id == source_id, DailyHabitEntry.user_id == current_user_id).first()
                        if dhe:
                            dhe.is_completed = status_done
                            dhe.notes = comment
                            db.flush() 
                            parent_habit = db.query(Habit).filter(Habit.id == dhe.habit_id).first()
                            if parent_habit:
                                recalculate_habit_streak(db, parent_habit)
                                if parent_habit.formation_streak >= parent_habit.formation_target_days and parent_habit.is_active:
                                    parent_habit.is_active = False
                    elif source == 'plan_item':
                        # Используем 'original_item_id' или 'source_id' для идентификации PlanItem
                        plan_item_id_to_sync = task_dto.get('original_item_id') or task_dto.get('source_id')
                        if not plan_item_id_to_sync: continue # Не можем синхронизировать без ID

                        pi_to_update = db.query(PlanItem).filter(PlanItem.id == plan_item_id_to_sync, PlanItem.user_id == current_user_id).first()
                        if pi_to_update:
                            if status_done:
                                pi_to_update.status = PlanItemStatus.DONE
                            elif status_partial:
                                pi_to_update.status = PlanItemStatus.IN_PROGRESS # Или другой статус для частичного
                            else:
                                if pi_to_update.status == PlanItemStatus.DONE: # Меняем только если был DONE
                                    pi_to_update.status = PlanItemStatus.TODO 
                            # Комментарии для PlanItem пока не синхронизируем из этого интерфейса
            
                    # Добавить синхронизацию для PlanItem, если 'original_item_id' используется
            except json.JSONDecodeError:
                flash("Ошибка обработки данных задач.", "danger")
            
            db.commit()
            flash("Задачи на день успешно сохранены!", "success")
            return redirect(url_for('daily_tasks_manager', date=selected_date_iso))

        # GET-запрос
        tasks_for_page = []
        tasks_from_storage = [] # <--- Инициализируем здесь
        if plan_obj and plan_obj.managed_daily_tasks:
            try:
                # Загружаем существующие задачи; они могут содержать измененные пользователем статусы/комментарии
                tasks_from_storage = json.loads(plan_obj.managed_daily_tasks)
                # Базовая проверка, что это список словарей
                if not (isinstance(tasks_from_storage, list) and all(isinstance(t, dict) for t in tasks_from_storage)):
                    tasks_from_storage = [] # Неверный формат, считаем пустым
            except (json.JSONDecodeError, TypeError):
                tasks_from_storage = [] # Ошибка парсинга, для слияния будем считать пустым
        
                # else: # Если нет plan_obj или managed_daily_tasks, tasks_from_storage остается пустым списком
            # tasks_from_storage = [] # Нет сохраненных задач (это условие уже покрыто инициализацией выше)
 

            # Всегда компилируем задачи из источников, чтобы отразить последнее состояние
        compiled_source_tasks = []
        # Задачи из утреннего планировщика (Plan.main_goals)
        if plan_obj and plan_obj.main_goals: # Используем plan_obj, который уже мог быть загружен
            try:
                morning_goals_list = json.loads(plan_obj.main_goals) # Теперь это список словарей
                if isinstance(morning_goals_list, list):
                    for goal_item_data in morning_goals_list: # goal_item_data это {"text": "...", "original_item_id": ID_OR_NULL}
                        if isinstance(goal_item_data, dict) and goal_item_data.get('text'):
                            text = goal_item_data.get('text')
                            original_id = goal_item_data.get('original_item_id')

                            if original_id:
                                # Задача из PlanItem, ЯВНО добавленная в утренний план
                                plan_item_obj = db.query(PlanItem).filter(PlanItem.id == original_id, PlanItem.user_id == current_user_id).first()
                                if plan_item_obj:
                                    compiled_source_tasks.append(
                                        _to_daily_task_dto(
                                            text=plan_item_obj.name,
                                            source='plan_item', 
                                            source_id=plan_item_obj.id, # source_id для plan_item это ID самого PlanItem
                                            original_item_id=plan_item_obj.id,
                                            status='done' if plan_item_obj.status == PlanItemStatus.DONE else 'todo',
                                            description=plan_item_obj.description or "Из стратегического плана (выбрано утром)",
                                            priority=plan_item_obj.priority,
                                            spheres=plan_item_obj.spheres
                                        )
                                    )
                                else: # PlanItem не найден (удален?)
                                    compiled_source_tasks.append(
                                        _to_daily_task_dto(text=text, source='planner_orphan', description="Из утреннего плана (исходник не найден)")
                                    )
                            else:
                                # Задача, введенная вручную в утренний план
                                compiled_source_tasks.append(
                                    _to_daily_task_dto(text=text, source='planner_manual', description="Из утреннего плана (ручной ввод)")
                                )
            except (json.JSONDecodeError, TypeError):
                pass # Игнорируем ошибки в main_goals

        # Задачи из стратегического планировщика (PlanItem), которые актуальны (TODO/IN_PROGRESS)
        # и должны появиться в менеджере задач дня, даже если не были ЯВНО выбраны в утреннем плане.
        from sqlalchemy import or_
        relevant_plan_items = db.query(PlanItem).filter(
            PlanItem.user_id == current_user_id,
            PlanItem.item_type.in_([PlanItemType.TASK, PlanItemType.SUBTASK]),
            PlanItem.status.in_([PlanItemStatus.TODO, PlanItemStatus.IN_PROGRESS]),
            or_(PlanItem.start_date == target_date, (PlanItem.start_date < target_date), PlanItem.start_date == None) # Начало сегодня, просрочено или без даты
        ).all()

        for pi in relevant_plan_items:
            # DTO id будет "plan_item_" + pi.id. Если этот PlanItem уже был обработан из main_goals,
            # final_tasks_map (ниже) обработает дублирование, отдав приоритет версии из main_goals (если она есть),
            # а затем версии из tasks_from_storage (если она есть).
            compiled_source_tasks.append(
                _to_daily_task_dto(
                    text=pi.name, source='plan_item', source_id=pi.id, original_item_id=pi.id,
                    status='todo', # т.к. мы запрашиваем только TODO/IN_PROGRESS (статус DONE будет из хранилища, если задача уже выполнена)
                    description=pi.description or "Из стратегического плана",
                    priority=pi.priority, spheres=pi.spheres
                )
            )
                
        # Задачи из Квеста Развития Сфер
        quest = _get_or_create_daily_sphere_quest(db, current_user_id, target_date)
        if quest and quest.tasks:
            for qt in quest.tasks:
                compiled_source_tasks.append(
                    _to_daily_task_dto(text=qt.task_text, source='quest', source_id=qt.id, status='done' if qt.is_completed else 'todo', description=f"Квест: {qt.sphere_name}", spheres=[qt.sphere_name])
                )
        
        # Задачи из Трекера Привычек
        active_habits = db.query(Habit).filter(Habit.user_id == current_user_id, Habit.is_active == True).all()
        for habit_obj in active_habits:
            is_due_today = False
            if habit_obj.frequency_type == HabitFrequencyType.DAILY: is_due_today = True
            elif habit_obj.frequency_type == HabitFrequencyType.WEEKLY and habit_obj.days_of_week and target_date.weekday() in habit_obj.days_of_week: is_due_today = True
            elif habit_obj.frequency_type == HabitFrequencyType.MONTHLY and habit_obj.days_of_month and target_date.day in habit_obj.days_of_month: is_due_today = True
            
            if is_due_today:
                entry = db.query(DailyHabitEntry).filter(DailyHabitEntry.habit_id == habit_obj.id, DailyHabitEntry.date == target_date).first()
                if not entry:
                    entry = DailyHabitEntry(habit_id=habit_obj.id, user_id=current_user_id, date=target_date, is_completed=False)
                    db.add(entry); db.flush() 
                
                compiled_source_tasks.append(
                    _to_daily_task_dto(text=habit_obj.name, source='habit', source_id=entry.id, status='done' if entry.is_completed else 'todo', comment=entry.notes or '', description=habit_obj.description or "Привычка")
                )
        
        # Объединяем задачи: начинаем с задач из источников, затем "накладываем" задачи из хранилища
        # Это гарантирует, что новые задачи из источников будут добавлены, а существующие сохранят свое состояние из хранилища.
        final_tasks_map = {task['id']: task for task in compiled_source_tasks if isinstance(task, dict) and 'id' in task}
        for stored_task in tasks_from_storage:
            if isinstance(stored_task, dict) and 'id' in stored_task:
                # Если задача из хранилища совпадает по ID с скомпилированной, версия из хранилища (с ее статусом/комментарием) имеет приоритет.
                # Если это вручную добавленная задача из хранилища, она также будет включена.
                final_tasks_map[stored_task['id']] = stored_task
        
        tasks_for_page = list(final_tasks_map.values())

        # Обновляем managed_daily_tasks в БД, если это первая загрузка за день,
        # или если объединенный список отличается от того, что было сохранено (например, добавлены новые задачи из источников)
        # Простая проверка: если tasks_from_storage был пуст, или если содержимое изменилось.
        # Используем sort_keys=True для консистентного сравнения JSON строк
        current_managed_tasks_json = json.dumps(tasks_for_page, sort_keys=True)
        stored_managed_tasks_json = json.dumps(tasks_from_storage, sort_keys=True) if tasks_from_storage else None

        if not stored_managed_tasks_json or current_managed_tasks_json != stored_managed_tasks_json:
            if not plan_obj: # Если запись Plan для этого дня еще не существовала
                
                plan_obj = Plan(user_id=current_user_id, date=target_date) # Исправлен отступ
                db.add(plan_obj) # Добавляем в сессию
            plan_obj.managed_daily_tasks = current_managed_tasks_json # Сохраняем актуальный JSON
            db.commit()

        return render_template('daily_tasks_manager.html', tasks=tasks_for_page, selected_date_iso=selected_date_iso, carousel_dates=carousel_dates)
    except ValueError: # Ошибка парсинга даты
        flash("Некорректный формат даты.", "danger")
        return redirect(url_for('index'))
    except Exception as e:
        db.rollback()
        print(f"Ошибка на странице менеджера задач дня: {e}")
        flash(f"Произошла ошибка: {e}", "danger")
        return redirect(url_for('index'))
    finally:
        db.close()

if __name__ == '__main__':
    app.run(debug=True)
