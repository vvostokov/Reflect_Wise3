import os
from sqlalchemy import create_engine, Column, Integer, String, Date, Text, ForeignKey, BigInteger, DateTime, Enum as SQLAlchemyEnum, Boolean, UniqueConstraint
from sqlalchemy.orm import sessionmaker, relationship, Session, backref, Mapped, mapped_column # Добавлены Mapped и mapped_column
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.sql import func # Для server_default=func.now() 
from sqlalchemy.ext.hybrid import hybrid_property # <--- ДОБАВЛЕНО
from typing import Optional, List # <--- ИЗМЕНЕНО: Добавлен List
from datetime import datetime, date as DDate, timezone # Добавлен timezone
import enum 

# --- Настройки базы данных ---
# Используем переменную окружения DATABASE_URL для подключения к базе данных.
# Это стандартный подход для облачных хостингов типа Render.
# Если переменная окружения не установлена (например, при локальной разработке),
# используем локальную строку подключения к SQLite.
SQLALCHEMY_DATABASE_URL = os.environ.get("DATABASE_URL")

# --- Логика запасного варианта для локальной разработки (SQLite) ---
if not SQLALCHEMY_DATABASE_URL:
    # Запасной вариант для локальной разработки (SQLite)
    SQLALCHEMY_DATABASE_URL = "sqlite:///./daily_reports.db"
    print("Warning: DATABASE_URL environment variable not set. Using local SQLite database.")
# --- Конец логики запасного варианта ---


# Важно: Render автоматически преобразует строку подключения для SQLAlchemy,
# ... (остальные импорты и код)
# добавляя правильный драйвер (например, postgresql:// -> postgresql+psycopg2://)
# при использовании переменной окружения DATABASE_URL.
# Если вы не используете переменную окружения, вам может потребоваться указать драйвер явно:
# engine = create_engine(SQLALCHEMY_DATABASE_URL, pool_pre_ping=True) # Пример с явным указанием драйвера

# Создаем движок SQLAlchemy. Теперь SQLALCHEMY_DATABASE_URL не будет None локально.
engine = create_engine(SQLALCHEMY_DATABASE_URL)


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    """
    Dependency to get a database session.
    """
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# --- Модели таблиц ---
# Ваши модели остаются практически без изменений, так как SQLAlchemy абстрагирует
# ... (остальные импорты и код)
# различия между СУБД на уровне моделей.

from sqlalchemy.types import JSON # Для хранения структурированных данных
from config import Config # Импортируем Config

# ... (остальные модели User, DailyReport, Plan, EmotionalReport, Recommendation) ...
# Убедитесь, что они определены до PlanItem, если PlanItem на них ссылается,
# но в данном случае PlanItem ссылается только на User.

# --- Добавлена модель User для аутентификации через Telegram ---
class User(Base):
    __tablename__ = 'users' # Название таблицы для пользователей

    id = Column(Integer, primary_key=True)
    telegram_id = Column(BigInteger, unique=True, nullable=True) # ID пользователя Telegram, может быть Null если вход через VK
    vk_id = Column(BigInteger, unique=True, nullable=True)       # ID пользователя VK, может быть Null если вход через Telegram
    first_name = Column(String)
    last_name = Column(String)
    username = Column(String) # Имя пользователя Telegram (опционально)
    photo_url = Column(String) # URL фото профиля (опционально)
    created_at = Column(DateTime(timezone=True), server_default=func.now()) # Дата создания пользователя    
    theme = Column(String, default='litera') # Выбранная тема оформления ('darkly', 'litera', etc.) <- ИЗМЕНЕНО НА СВЕТЛУЮ
    
    # Связи с другими таблицами
    daily_reports = relationship("DailyReport", back_populates="user", order_by="desc(DailyReport.date)")
    plans = relationship("Plan", back_populates="user", order_by="desc(Plan.date)")
    # emotional_reports = relationship("EmotionalReport", back_populates="user", order_by="desc(EmotionalReport.date)") # Закомментировано, т.к. EmotionalReport заменен
    recommendations = relationship("Recommendation", back_populates="user", order_by="desc(Recommendation.date)") # Связь с Рекомендациями
    daily_surveys = relationship("DailySurvey", back_populates="user", order_by="desc(DailySurvey.date)") # Связь с новым Дневным Опросником
    habits: Mapped[List["Habit"]] = relationship("Habit", back_populates="user", order_by="desc(Habit.created_at)", cascade="all, delete-orphan")
    daily_habit_entries: Mapped[List["DailyHabitEntry"]] = relationship("DailyHabitEntry", back_populates="user", order_by="desc(DailyHabitEntry.date)", cascade="all, delete-orphan")
    achievements: Mapped[List["UserAchievement"]] = relationship("UserAchievement", back_populates="user", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<User(id={self.id}, telegram_id={self.telegram_id}, vk_id={self.vk_id}, username='{self.username}')>"

# --- Enum типы для PlanItem ---
class PlanItemType(enum.Enum):
    MISSION = "MISSION"
    PROJECT = "PROJECT"
    GOAL = "GOAL"
    TASK = "TASK"
    SUBTASK = "SUBTASK" # <--- Перемещаем SUBTASK сюда

class PlanItemStatus(enum.Enum):
    TODO = "TODO"
    IN_PROGRESS = "IN_PROGRESS"
    # PENDING = "Ожидание" # Если нужен такой статус
    DONE = "DONE"
    ON_HOLD = "ON_HOLD"
    CANCELLED = "CANCELLED"
    # SUBTASK был ошибочно здесь, удаляем

class PlanItemPriority(enum.Enum):
    HIGH = "Высокий"
    MEDIUM = "Средний"
    LOW = "Низкий"

# --- Модель PlanItem ---
class PlanItem(Base):
    __tablename__ = "plan_items"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    parent_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("plan_items.id"), nullable=True)
    item_type: Mapped[PlanItemType] = mapped_column(SQLAlchemyEnum(PlanItemType, name="plan_item_type_enum", create_type=False), nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[Optional[PlanItemStatus]] = mapped_column(SQLAlchemyEnum(PlanItemStatus, name="plan_item_status_enum", create_type=False), nullable=True, default=PlanItemStatus.TODO)
    start_date: Mapped[Optional[DDate]] = mapped_column(Date, nullable=True)
    priority: Mapped[Optional[PlanItemPriority]] = mapped_column(SQLAlchemyEnum(PlanItemPriority, name="plan_item_priority_enum", create_type=False), nullable=True)
    spheres: Mapped[Optional[list[str]]] = mapped_column(JSON, nullable=True) # Список строк-названий сфер
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    user = relationship("User", back_populates="plan_items") # Связь с пользователем
    # Отношение "родитель-потомки" для древовидной структуры
    children = relationship("PlanItem",
                            backref=backref('parent', remote_side=[id]), # Используем backref из sqlalchemy.orm
                            cascade="all, delete-orphan"
                           )

    def to_dict(self, include_children=True):
        """Преобразует объект PlanItem в словарь, удобный для JSON и jsTree."""
        data = {
            "id": str(self.id), # jsTree ожидает строковый ID
            "parent": str(self.parent_id) if self.parent_id else "#",
            "text": self.name,
            "type": self.item_type.value if self.item_type else None,
            "original": { # Дополнительные данные
                "name": self.name,
                "description": self.description,
                "status": self.status.value if self.status else None,
                "item_type": self.item_type.value if self.item_type else None,
                "start_date": self.start_date.isoformat() if self.start_date else None, # Используем DDate
                "priority": self.priority.name if self.priority else None, 
                "spheres": self.spheres if self.spheres else [],
                # Можно добавить created_at, updated_at если нужно
            }
        }
        # Для AJAX jsTree обычно сам строит дерево по id и parent,
        # поэтому 'children' здесь не заполняем, если include_children=False (что обычно и делается для AJAX)
        # if include_children and self.children:
        #     data["children"] = [child.to_dict(include_children=True) for child in self.children]
        return data

# Определения DailyReport, Plan, EmotionalReport, Recommendation, DailySphereQuest, SphereQuestTask
# должны быть здесь, если они не были определены ранее.
# Для краткости предположим, что они уже есть выше или ниже.

class DailyReport(Base):
    __tablename__ = "daily_reports"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    date: Mapped[DDate] = mapped_column(Date, nullable=False, default=DDate.today)
    reviewed_tasks: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    evening_q1: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    evening_q2: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    evening_q3: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    evening_q4: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    evening_q5: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    evening_q6: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    user: Mapped["User"] = relationship("User", back_populates="daily_reports")

class Plan(Base):
    __tablename__ = "plans"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    date: Mapped[DDate] = mapped_column(Date, nullable=False, default=DDate.today)
    main_goals: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    morning_q2_improve_day: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    morning_q3_mindset: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    morning_q4_help_others: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    morning_q5_inspiration: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    morning_q6_health_care: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Поля для Утреннего Ритуала
    ritual_user_preferences: Mapped[Optional[str]] = mapped_column(Text, nullable=True) # Предпочтения пользователя для генерации
    ritual_part1_raw: Mapped[Optional[str]] = mapped_column(Text, nullable=True)        # Сгенерированный текст ритуала (часть 1 - до планирования)
    ritual_part2_raw: Mapped[Optional[str]] = mapped_column(Text, nullable=True)        # Сгенерированный текст ритуала (часть 2 - после планирования)
    managed_daily_tasks: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True) # Для хранения задач менеджера задач дня
    user: Mapped["User"] = relationship("User", back_populates="plans")

# --- EmotionalReport заменен на DailySurvey ---
# class EmotionalReport(Base):
#     __tablename__ = "emotional_reports"
#     # ... (определение полей с Mapped)
#     id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
#     user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
#     date: Mapped[DDate] = mapped_column(Date, nullable=False, default=DDate.today)
#     situation: Mapped[str] = mapped_column(Text, nullable=False)
#     thought: Mapped[str] = mapped_column(Text, nullable=False)
#     feelings: Mapped[str] = mapped_column(Text, nullable=False)
#     correction: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
#     correction_hint_used: Mapped[Optional[str]] = mapped_column(String, nullable=True)
#     new_feelings: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
#     impact: Mapped[str] = mapped_column(Text, nullable=False)
#     user: Mapped["User"] = relationship("User", back_populates="emotional_reports")

class DailySurvey(Base):
    __tablename__ = "daily_surveys"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    date: Mapped[DDate] = mapped_column(Date, nullable=False, default=DDate.today)
    q1_current_feeling: Mapped[Optional[str]] = mapped_column(Text, nullable=True) # Как я себя чувствую прямо сейчас (эмоционально и физически)?
    q2_morning_intentions_follow: Mapped[Optional[str]] = mapped_column(Text, nullable=True) # Насколько успешно я сегодня следую утренним намерениям?
    q3_unexpected_challenges_reaction: Mapped[Optional[str]] = mapped_column(Text, nullable=True) # С какими неожиданными вызовами... и как я на них отреагировал(а)?
    q4_energy_drain_gain: Mapped[Optional[str]] = mapped_column(Text, nullable=True) # Что сегодня больше всего отняло у меня энергии, а что, наоборот, добавило сил?
    q5_small_progress: Mapped[Optional[str]] = mapped_column(Text, nullable=True) # Какой небольшой, но значимый прогресс... я могу отметить?
    q6_focus_distraction: Mapped[Optional[str]] = mapped_column(Text, nullable=True) # Насколько я сегодня был(а) сфокусирован(а) на важном? Что было главным отвлечением?
    q7_action_for_better_day: Mapped[Optional[str]] = mapped_column(Text, nullable=True) # Какое одно небольшое действие я могу предпринять до конца дня...?
    user: Mapped["User"] = relationship("User", back_populates="daily_surveys")

class Recommendation(Base):
    __tablename__ = "recommendations"
    # ... (определение полей с Mapped)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    date: Mapped[DDate] = mapped_column(Date, nullable=False, default=DDate.today)
    original_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    rating: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    user: Mapped["User"] = relationship("User", back_populates="recommendations")

class DailySphereQuest(Base):
    __tablename__ = "daily_sphere_quests"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    date = Column(Date, nullable=False, default=DDate.today)
    replacements_used = Column(Integer, default=0, nullable=False)
    
    # Новые поля для настроек квеста
    # Приоритетная сфера. Null означает "смешанный" или "без приоритета".
    priority_sphere_name: Mapped[Optional[str]] = mapped_column(String, nullable=True) 
    # Уровень сложности квеста
    difficulty_level: Mapped[Optional[str]] = mapped_column(String, default='medium', nullable=True) # Например, 'easy', 'medium', 'hard'

    user = relationship("User", back_populates="sphere_quests")
    tasks = relationship("SphereQuestTask", back_populates="quest", cascade="all, delete-orphan", order_by="SphereQuestTask.display_order")

    __table_args__ = (UniqueConstraint('user_id', 'date', name='_user_date_uc_daily_sphere_quest'),)

class SphereQuestTask(Base):
    __tablename__ = "sphere_quest_tasks"

    id = Column(Integer, primary_key=True, index=True)
    quest_id = Column(Integer, ForeignKey("daily_sphere_quests.id"), nullable=False)
    sphere_name = Column(String, nullable=False)
    task_text = Column(Text, nullable=False)
    is_completed = Column(Boolean, default=False, nullable=False)
    # is_initial_task = Column(Boolean, default=True, nullable=False) # Пока не используем, но может пригодиться
    display_order = Column(Integer, nullable=False, default=0) # Для сохранения порядка отображения

    quest = relationship("DailySphereQuest", back_populates="tasks")

class Habit(Base):
    __tablename__ = "habits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    formation_streak: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_completed_date: Mapped[Optional[DDate]] = mapped_column(Date, nullable=True)
    formation_target_days: Mapped[int] = mapped_column(Integer, default=14, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user: Mapped["User"] = relationship(back_populates="habits")
    daily_entries: Mapped[List["DailyHabitEntry"]] = relationship(back_populates="habit", cascade="all, delete-orphan", order_by="desc(DailyHabitEntry.date)")

    @hybrid_property
    def is_formed(self):
        return not self.is_active and self.formation_streak >= self.formation_target_days

    def __repr__(self):
        return f"<Habit(id={self.id}, name='{self.name}', user_id={self.user_id}, active={self.is_active}, streak={self.formation_streak})>"

class DailyHabitEntry(Base):
    __tablename__ = "daily_habit_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    habit_id: Mapped[int] = mapped_column(Integer, ForeignKey("habits.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    date: Mapped[DDate] = mapped_column(Date, nullable=False)
    is_completed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    habit: Mapped["Habit"] = relationship(back_populates="daily_entries")
    user: Mapped["User"] = relationship(back_populates="daily_habit_entries")

    __table_args__ = (UniqueConstraint('habit_id', 'date', name='_habit_date_uc'),)

    def __repr__(self):
        return f"<DailyHabitEntry(id={self.id}, habit_id={self.habit_id}, date='{self.date}', completed={self.is_completed})>"

# --- Модели для системы достижений ---
class Achievement(Base):
    __tablename__ = "achievements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False) # Название достижения, напр. "Первый отчет"
    description: Mapped[str] = mapped_column(Text, nullable=False) # Описание, напр. "Вы успешно заполнили свой первый ежедневный отчет!"
    icon_class: Mapped[Optional[str]] = mapped_column(String(100), nullable=True) # CSS класс для иконки (напр., из FontAwesome)
    trigger_event: Mapped[Optional[str]] = mapped_column(String(100), nullable=True) # Событие, которое триггерит достижение (для программной логики)

    user_achievements: Mapped[List["UserAchievement"]] = relationship(back_populates="achievement")

    def __repr__(self):
        return f"<Achievement(id={self.id}, name='{self.name}')>"

class UserAchievement(Base):
    __tablename__ = "user_achievements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    achievement_id: Mapped[int] = mapped_column(Integer, ForeignKey("achievements.id"), nullable=False)
    earned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship(back_populates="achievements")
    achievement: Mapped["Achievement"] = relationship(back_populates="user_achievements")

    __table_args__ = (UniqueConstraint('user_id', 'achievement_id', name='_user_achievement_uc'),)

    def __repr__(self):
        return f"<UserAchievement(user_id={self.user_id}, achievement_id={self.achievement_id}, earned_at='{self.earned_at}')>"

# --- Enum для частоты привычек ---
class HabitFrequencyType(enum.Enum):
    DAILY = "DAILY"     # Каждый день (текущее поведение)
    WEEKLY = "WEEKLY"   # Определенные дни недели
    MONTHLY = "MONTHLY" # Определенные числа месяца

# Примечание о создании таблиц:
# Для локальной разработки с SQLite, Base.metadata.create_all(engine)
# может быть в web_app.py для удобства.
# В продакшене создание таблиц (включая новую таблицу 'users')
# обычно выполняется с помощью инструментов миграции базы данных (например, Alembic).
# Обновляем модель User для связи с PlanItem
User.plan_items = relationship("PlanItem", back_populates="user", order_by="desc(PlanItem.created_at)", cascade="all, delete-orphan")
# Обновляем модель User для связи с DailySphereQuest
User.sphere_quests = relationship("DailySphereQuest", back_populates="user", order_by="desc(DailySphereQuest.date)")

# --- Обновление модели Habit для поддержки частоты ---
Habit.frequency_type = mapped_column(SQLAlchemyEnum(HabitFrequencyType, name="habit_frequency_type_enum", create_type=False), default=HabitFrequencyType.DAILY, nullable=False)
# Список целых чисел [0, 1, ..., 6] для Пн, Вт, ..., Вс
Habit.days_of_week = mapped_column(JSON, nullable=True) # Mapped[Optional[List[int]]]
# Список целых чисел [1, 2, ..., 31] для дней месяца
Habit.days_of_month = mapped_column(JSON, nullable=True) # Mapped[Optional[List[int]]]
