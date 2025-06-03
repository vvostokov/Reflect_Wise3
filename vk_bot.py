import vk_api
from vk_api.longpoll import VkLongPoll, VkEventType
from vk_api.keyboard import VkKeyboard, VkKeyboardColor
from vk_api.utils import get_random_id # Для генерации random_id
import config, json # Добавлен json для main_goals
from models import get_db, User, DailyReport, Plan # , EmotionalReport, Recommendation, PlanItem, PlanItemType, PlanItemStatus
from sqlalchemy.orm import Session
from datetime import datetime

# --- Инициализация VK API ---
try:
    vk_session = vk_api.VkApi(token=config.VK_BOT_TOKEN)
    longpoll = VkLongPoll(vk_session)
    vk = vk_session.get_api()
    print("VK Bot: Успешное подключение к VK API.")
except Exception as e:
    print(f"VK Bot: Ошибка подключения к VK API: {e}")
    exit()

# --- Хранилища данных и состояний (аналогично Telegram боту) ---
user_data_vk = {}
user_state_vk = {}

# --- Пример состояний (нужно будет расширить) ---
STATE_VK_NONE = "VK_NONE"
STATE_VK_REPORT_ENERGY_LEVEL = "VK_REPORT_ENERGY_LEVEL"
STATE_VK_REPORT_ENERGY_BOOSTERS = "VK_REPORT_ENERGY_BOOSTERS"
STATE_VK_REPORT_TOP_ACHIEVEMENT = "VK_REPORT_TOP_ACHIEVEMENT"
STATE_VK_REPORT_LESSON_LEARNED = "VK_REPORT_LESSON_LEARNED"
STATE_VK_REPORT_GRATITUDE_ITEMS = "VK_REPORT_GRATITUDE_ITEMS"
STATE_VK_REPORT_NEGATIVE_EVENTS = "VK_REPORT_NEGATIVE_EVENTS"

STATE_VK_PLAN_MAIN_GOALS = "VK_PLAN_MAIN_GOALS"
STATE_VK_PLAN_Q2_IMPROVE_DAY = "VK_PLAN_Q2_IMPROVE_DAY" # Как сделать день лучше
STATE_VK_PLAN_Q3_MINDSET = "VK_PLAN_Q3_MINDSET"         # Качество/настрой на день
STATE_VK_PLAN_Q4_HELP_OTHERS = "VK_PLAN_Q4_HELP_OTHERS"   # Кому помочь/сделать приятное
STATE_VK_PLAN_Q5_INSPIRATION = "VK_PLAN_Q5_INSPIRATION" # Вдохновение/благодарность
# STATE_VK_PLAN_Q6_HEALTH_CARE - пока пропустим для VK бота для краткости
# STATE_VK_REPORT_DONE - не явное состояние, сохранение после последнего вопроса
# ... другие состояния

# --- Вспомогательные функции ---
def get_vk_user_id(event):
    """Получает ID пользователя VK из события."""
    return event.user_id

def ensure_user_in_db(db_session: Session, vk_user_id: int, user_info=None):
    """Проверяет наличие пользователя в БД и добавляет его, если необходимо."""
    user = db_session.query(User).filter_by(vk_id=vk_user_id).first()
    if not user:
        first_name = "Пользователь"
        last_name = ""
        if user_info: # Пытаемся получить имя из VK
            try:
                vk_user_data = vk.users.get(user_ids=vk_user_id)[0]
                first_name = vk_user_data.get('first_name', 'Пользователь')
                last_name = vk_user_data.get('last_name', '')
            except Exception as e:
                print(f"VK Bot: Не удалось получить информацию о пользователе {vk_user_id}: {e}")

        user = User(vk_id=vk_user_id, first_name=first_name, last_name=last_name)
        db_session.add(user)
        db_session.commit()
        print(f"VK Bot: Новый пользователь {vk_user_id} ({first_name}) добавлен в БД.")
    return user

# --- Обработчики команд ---
def handle_start_command(event):
    vk_user_id = get_vk_user_id(event)
    db = next(get_db())
    try:
        ensure_user_in_db(db, vk_user_id)
    finally:
        db.close()

    keyboard = VkKeyboard(one_time=False) # False - клавиатура остается после нажатия
    keyboard.add_button("Ежедневный отчет", color=VkKeyboardColor.PRIMARY)
    keyboard.add_button("План на день", color=VkKeyboardColor.PRIMARY)
    keyboard.add_line()
    keyboard.add_button("Запись эмоций", color=VkKeyboardColor.SECONDARY)
    keyboard.add_button("Рекомендации", color=VkKeyboardColor.SECONDARY)

    vk.messages.send(
        user_id=vk_user_id,
        message="Привет! Я ваш помощник Reflect Wise для ВКонтакте. Выберите действие:",
        random_id=get_random_id(),
        keyboard=keyboard.get_keyboard()
    )
    user_state_vk[vk_user_id] = STATE_VK_NONE

# --- Обработчики для Ежедневного Отчета ---
def start_vk_report(event):
    vk_user_id = get_vk_user_id(event)
    user_data_vk[vk_user_id] = {} # Очищаем старые данные, если есть
    user_state_vk[vk_user_id] = STATE_VK_REPORT_ENERGY_LEVEL
    vk.messages.send(user_id=vk_user_id, message="Начинаем ежедневный отчет. Оцените ваш уровень энергии сегодня (1-10):", random_id=get_random_id())

def handle_vk_report_energy_level(event):
    vk_user_id = get_vk_user_id(event)
    text = event.text
    if text.isdigit() and 1 <= int(text) <= 10:
        user_data_vk[vk_user_id]['energy_level'] = int(text)
        user_state_vk[vk_user_id] = STATE_VK_REPORT_ENERGY_BOOSTERS
        vk.messages.send(user_id=vk_user_id, message="Что сегодня дало вам энергию?", random_id=get_random_id())
    else:
        vk.messages.send(user_id=vk_user_id, message="Пожалуйста, введите число от 1 до 10 для уровня энергии.", random_id=get_random_id())

def handle_vk_report_energy_boosters(event):
    vk_user_id = get_vk_user_id(event)
    user_data_vk[vk_user_id]['energy_boosters'] = event.text
    user_state_vk[vk_user_id] = STATE_VK_REPORT_TOP_ACHIEVEMENT
    vk.messages.send(user_id=vk_user_id, message="Какое главное достижение дня?", random_id=get_random_id())

def handle_vk_report_top_achievement(event):
    vk_user_id = get_vk_user_id(event)
    user_data_vk[vk_user_id]['top_achievement'] = event.text
    user_state_vk[vk_user_id] = STATE_VK_REPORT_LESSON_LEARNED
    vk.messages.send(user_id=vk_user_id, message="Что вы узнали сегодня?", random_id=get_random_id())

def handle_vk_report_lesson_learned(event):
    vk_user_id = get_vk_user_id(event)
    user_data_vk[vk_user_id]['lesson_learned'] = event.text
    user_state_vk[vk_user_id] = STATE_VK_REPORT_GRATITUDE_ITEMS
    vk.messages.send(user_id=vk_user_id, message="Напишите три благодарности!", random_id=get_random_id())

def handle_vk_report_gratitude_items(event):
    vk_user_id = get_vk_user_id(event)
    user_data_vk[vk_user_id]['gratitude_items'] = event.text
    user_state_vk[vk_user_id] = STATE_VK_REPORT_NEGATIVE_EVENTS
    vk.messages.send(user_id=vk_user_id, message="Опишите три трудности или негативных события.", random_id=get_random_id())

def handle_vk_report_negative_events_and_save(event):
    vk_user_id = get_vk_user_id(event)
    user_data_vk[vk_user_id]['negative_events'] = event.text
    
    # Сохранение отчета в БД
    db = next(get_db())
    try:
        # Убедимся, что пользователь существует в БД (на всякий случай)
        user_object = ensure_user_in_db(db, vk_user_id)
        
        report = DailyReport(
            user_id=user_object.id, # Используем ID из нашей таблицы users
            date=datetime.utcnow().date(),
            energy_level=user_data_vk[vk_user_id].get('energy_level'),
            energy_boosters=user_data_vk[vk_user_id].get('energy_boosters'),
            top_achievement=user_data_vk[vk_user_id].get('top_achievement'),
            lesson_learned=user_data_vk[vk_user_id].get('lesson_learned'),
            gratitude_items=user_data_vk[vk_user_id].get('gratitude_items'),
            negative_events=user_data_vk[vk_user_id].get('negative_events')
        )
        db.add(report)
        db.commit()
        vk.messages.send(user_id=vk_user_id, message="Ежедневный отчет сохранен! Спасибо. Напишите 'Начать', чтобы увидеть меню.", random_id=get_random_id())
    except Exception as e:
        print(f"VK Bot: Ошибка сохранения отчета для {vk_user_id}: {e}")
        vk.messages.send(user_id=vk_user_id, message=f"Произошла ошибка при сохранении отчета: {e}", random_id=get_random_id())
    finally:
        db.close()
        if vk_user_id in user_data_vk: del user_data_vk[vk_user_id] # Очистка данных
        user_state_vk[vk_user_id] = STATE_VK_NONE # Сброс состояния

# --- Обработчики для Плана на день ---
def start_vk_plan(event):
    vk_user_id = get_vk_user_id(event)
    user_data_vk[vk_user_id] = {'plan': {}} # Используем вложенный словарь для данных плана
    user_state_vk[vk_user_id] = STATE_VK_PLAN_MAIN_GOALS
    vk.messages.send(user_id=vk_user_id, message="Планируем день! Каковы ваши 1-3 главные цели/задачи на сегодня?", random_id=get_random_id())

def handle_vk_plan_main_goals(event):
    vk_user_id = get_vk_user_id(event)
    # Сохраняем как строку, потом преобразуем в JSON список объектов
    user_data_vk[vk_user_id]['plan']['main_goals_raw'] = event.text
    user_state_vk[vk_user_id] = STATE_VK_PLAN_Q2_IMPROVE_DAY
    vk.messages.send(user_id=vk_user_id, message="Как вы можете сделать сегодняшний день лучше (приятнее, продуктивнее, осмысленнее)?", random_id=get_random_id())

def handle_vk_plan_q2_improve_day(event):
    vk_user_id = get_vk_user_id(event)
    user_data_vk[vk_user_id]['plan']['morning_q2_improve_day'] = event.text
    user_state_vk[vk_user_id] = STATE_VK_PLAN_Q3_MINDSET
    vk.messages.send(user_id=vk_user_id, message="Какое качество или настрой вы хотите привнести в сегодняшний день (например, внимательность, решительность)?", random_id=get_random_id())

def handle_vk_plan_q3_mindset(event):
    vk_user_id = get_vk_user_id(event)
    user_data_vk[vk_user_id]['plan']['morning_q3_mindset'] = event.text
    user_state_vk[vk_user_id] = STATE_VK_PLAN_Q4_HELP_OTHERS
    vk.messages.send(user_id=vk_user_id, message="Кому вы могли бы сегодня помочь или сделать что-то приятное?", random_id=get_random_id())

def handle_vk_plan_q4_help_others(event):
    vk_user_id = get_vk_user_id(event)
    user_data_vk[vk_user_id]['plan']['morning_q4_help_others'] = event.text
    user_state_vk[vk_user_id] = STATE_VK_PLAN_Q5_INSPIRATION
    vk.messages.send(user_id=vk_user_id, message="Что вас сегодня вдохновляет или за что вы благодарны наперед?", random_id=get_random_id())

def handle_vk_plan_q5_inspiration_and_save(event):
    vk_user_id = get_vk_user_id(event)
    user_data_vk[vk_user_id]['plan']['morning_q5_inspiration'] = event.text

    # Сохранение плана в БД
    db = next(get_db())
    try:
        user_object = ensure_user_in_db(db, vk_user_id)
        plan_details = user_data_vk[vk_user_id]['plan']

        raw_main_goals = plan_details.get('main_goals_raw', '')
        if raw_main_goals:
            goal_texts = [goal.strip() for goal in raw_main_goals.replace(',', '\n').split('\n') if goal.strip()]
            main_goals_json = json.dumps([{"text": goal} for goal in goal_texts])
        else:
            main_goals_json = json.dumps([])

        new_plan = Plan(
            user_id=user_object.id,
            date=datetime.utcnow().date(),
            main_goals=main_goals_json,
            morning_q2_improve_day=plan_details.get('morning_q2_improve_day'),
            morning_q3_mindset=plan_details.get('morning_q3_mindset'),
            morning_q4_help_others=plan_details.get('morning_q4_help_others'),
            morning_q5_inspiration=plan_details.get('morning_q5_inspiration')
            # morning_q6_health_care не собираем в VK боте
        )
        db.add(new_plan)
        db.commit()
        vk.messages.send(user_id=vk_user_id, message="План на день сохранен! Удачи! Напишите 'Начать', чтобы увидеть меню.", random_id=get_random_id())
    except Exception as e:
        print(f"VK Bot: Ошибка сохранения плана для {vk_user_id}: {e}")
        vk.messages.send(user_id=vk_user_id, message=f"Произошла ошибка при сохранении плана: {e}", random_id=get_random_id())
    finally:
        db.close()
        if vk_user_id in user_data_vk: del user_data_vk[vk_user_id] # Очистка данных
        user_state_vk[vk_user_id] = STATE_VK_NONE # Сброс состояния
# --- Основной цикл обработки событий ---
def main_vk_bot():
    print("VK Bot: Запуск основного цикла...")
    for event in longpoll.listen():
        if event.type == VkEventType.MESSAGE_NEW and event.to_me:
            vk_user_id = get_vk_user_id(event)
            text = event.text.lower()
            current_state = user_state_vk.get(vk_user_id, STATE_VK_NONE)

            print(f"VK Bot: Получено сообщение от {vk_user_id}: '{event.text}', состояние: {current_state}")

            if text == "начать" or text == "/start_vk": # Команда "Начать" для VK
                handle_start_command(event)
            elif text == "ежедневный отчет":
                start_vk_report(event)
            elif current_state == STATE_VK_REPORT_ENERGY_LEVEL:
                handle_vk_report_energy_level(event)
            elif current_state == STATE_VK_REPORT_ENERGY_BOOSTERS:
                handle_vk_report_energy_boosters(event)
            elif current_state == STATE_VK_REPORT_TOP_ACHIEVEMENT:
                handle_vk_report_top_achievement(event)
            elif current_state == STATE_VK_REPORT_LESSON_LEARNED:
                handle_vk_report_lesson_learned(event)
            elif current_state == STATE_VK_REPORT_GRATITUDE_ITEMS:
                handle_vk_report_gratitude_items(event)
            elif current_state == STATE_VK_REPORT_NEGATIVE_EVENTS:
                handle_vk_report_negative_events_and_save(event)
            
            elif text == "план на день":
                start_vk_plan(event)
            elif current_state == STATE_VK_PLAN_MAIN_GOALS:
                handle_vk_plan_main_goals(event)
            elif current_state == STATE_VK_PLAN_Q2_IMPROVE_DAY:
                handle_vk_plan_q2_improve_day(event)
            elif current_state == STATE_VK_PLAN_Q3_MINDSET:
                handle_vk_plan_q3_mindset(event)
            elif current_state == STATE_VK_PLAN_Q4_HELP_OTHERS:
                handle_vk_plan_q4_help_others(event)
            elif current_state == STATE_VK_PLAN_Q5_INSPIRATION:
                handle_vk_plan_q5_inspiration_and_save(event)
            # Добавить обработку других кнопок и состояний (План, Эмоции, Рекомендации)
            else:
                # Если нет активного состояния и команда не распознана, предлагаем начать
                if current_state == STATE_VK_NONE:
                    vk.messages.send(user_id=vk_user_id, message=f"Неизвестная команда: '{event.text}'. Напишите 'Начать', чтобы увидеть меню.", random_id=get_random_id())
                # Если есть активное состояние, но текст не соответствует ожидаемому вводу, можно ничего не делать или попросить повторить

if __name__ == '__main__':
    print("VK Bot: Запуск...")
    main_vk_bot()