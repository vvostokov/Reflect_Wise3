import os
from sqlalchemy import create_engine, Column, Integer, String, Date, Text, ForeignKey, BigInteger, DateTime, Enum as SQLAlchemyEnum # Добавлены BigInteger, DateTime, ForeignKey, SQLAlchemyEnum
from sqlalchemy.orm import sessionmaker, relationship, Session, backref # Добавлен backref
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.sql import func # Для server_default=func.now()
from datetime import datetime, date as DDate # Добавлен импорт datetime и date as DDate для избежания конфликта имен
import enum # Для использования Enum типов

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
# различия между СУБД на уровне моделей.

class DailyReport(Base):
    __tablename__ = "daily_reports"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    date = Column(Date, nullable=False, default=DDate.today) # Default to DDate for consistency
    
    # New structure for evening questions
    reviewed_tasks = Column(Text, nullable=True) # Stores JSON string of reviewed tasks: [{"name": "...", "status": "...", "comment": "..."}]
    evening_q1 = Column(Text, nullable=True) # Что сегодня получилось лучше всего?
    evening_q2 = Column(Text, nullable=True) # Где я сегодня вышел из зоны комфорта?
    evening_q3 = Column(Text, nullable=True) # Что я понял(а) сегодня о себе или жизни?
    evening_q4 = Column(Text, nullable=True) # Какие моменты дня принесли мне радость или умиротворение?
    evening_q5 = Column(Text, nullable=True) # Что я мог(ла) бы сделать иначе для более удачного дня?
    evening_q6 = Column(Text, nullable=True) # Кому и за что я особенно благодарен(а) сегодня?

    user = relationship("User", back_populates="daily_reports")

class Plan(Base):
    __tablename__ = "plans"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    date = Column(Date, nullable=False, default=DDate.today)
    main_goals = Column(Text, nullable=True) # Stores JSON string of tasks: [{"text": "Task 1"}, ...]
    
    # Fields for morning questions Q2-Q6
    morning_q2_improve_day = Column(Text, nullable=True)
    morning_q3_mindset = Column(Text, nullable=True)
    morning_q4_help_others = Column(Text, nullable=True)
    morning_q5_inspiration = Column(Text, nullable=True)
    morning_q6_health_care = Column(Text, nullable=True)

    user = relationship("User", back_populates="plans")

class EmotionalReport(Base):
    __tablename__ = "emotional_reports"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    date = Column(Date, nullable=False, default=DDate.today)
    situation = Column(Text, nullable=False)
    thought = Column(Text, nullable=False)
    feelings = Column(Text, nullable=False)
    impact = Column(Text, nullable=False)

    user = relationship("User", back_populates="emotional_reports")

class Recommendation(Base):
    __tablename__ = "recommendations"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    date = Column(Date, nullable=False, default=DDate.today)
    original_text = Column(Text, nullable=True) # Исходный текст от AI (Markdown или plain)
    text = Column(Text, nullable=False) # HTML-версия для отображения
    rating = Column(Integer, nullable=True) # Добавляем поле для оценки

    user = relationship("User", back_populates="recommendations")

# --- Добавлена модель User для аутентификации через Telegram ---
class User(Base):
    __tablename__ = 'users' # Название таблицы для пользователей

    id = Column(Integer, primary_key=True)
    telegram_id = Column(BigInteger, unique=True, nullable=False) # Уникальный ID пользователя Telegram
    first_name = Column(String)
    last_name = Column(String)
    username = Column(String) # Имя пользователя Telegram (опционально)
    photo_url = Column(String) # URL фото профиля (опционально)

    # Связи с другими таблицами
    daily_reports = relationship("DailyReport", back_populates="user", order_by="desc(DailyReport.date)")
    plans = relationship("Plan", back_populates="user", order_by="desc(Plan.date)")
    emotional_reports = relationship("EmotionalReport", back_populates="user", order_by="desc(EmotionalReport.date)")
    recommendations = relationship("Recommendation", back_populates="user", order_by="desc(Recommendation.date)")

    def __repr__(self):
        return f"<User(id={self.id}, telegram_id={self.telegram_id}, username='{self.username}')>"

# --- Enum типы для PlanItem ---
class PlanItemType(enum.Enum):
    MISSION = "MISSION"
    PROJECT = "PROJECT"
    GOAL = "GOAL"
    TASK = "TASK"
    SUBTASK = "SUBTASK"

class PlanItemStatus(enum.Enum):
    TODO = "TODO"
    IN_PROGRESS = "IN_PROGRESS"
    DONE = "DONE"
    ON_HOLD = "ON_HOLD"
    CANCELLED = "CANCELLED"

# --- Модель PlanItem ---
class PlanItem(Base):
    __tablename__ = "plan_items"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    parent_id = Column(Integer, ForeignKey("plan_items.id"), nullable=True) # Для иерархии
    item_type = Column(SQLAlchemyEnum(PlanItemType), nullable=False)  # Используем Enum
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    status = Column(SQLAlchemyEnum(PlanItemStatus), nullable=True, default=PlanItemStatus.TODO) # Используем Enum
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    start_date = Column(Date, nullable=True) # <--- ДОБАВЛЕНО ЭТО ПОЛЕ

    user = relationship("User", back_populates="plan_items") # Связь с пользователем
    # Отношение "родитель-потомки" для древовидной структуры
    children = relationship("PlanItem",
                            backref=backref('parent', remote_side=[id]), # Используем backref из sqlalchemy.orm
                            cascade="all, delete-orphan"
                           )

    def to_dict(self, include_children=True):
        """Преобразует объект в словарь, удобный для JSON и jsTree."""
        data = {
            "id": self.id, # jsTree использует id
            "parent": str(self.parent_id) if self.parent_id else "#", # jsTree использует 'parent', '#' для корневых
            "text": self.name, # jsTree использует 'text' для отображения имени узла
            "type": self.item_type.value if self.item_type else None, # jsTree использует 'type' для иконок и правил, передаем значение Enum
            "original": { # Дополнительные данные можно поместить в 'original' или 'data'
                "name": self.name,
                "description": self.description,
                "status": self.status.value if self.status else None, # Передаем значение Enum
                "item_type": self.item_type.value if self.item_type else None # Дублируем для удобства на клиенте, передаем значение Enum
            }
        }
        if include_children and self.children:
            # jsTree обычно сам строит иерархию на основе id и parent,
            # но если передавать сразу вложенную структуру, то это должно быть в 'children'
            # Для AJAX-загрузки jsTree обычно ожидает плоский список, где каждый элемент имеет id и parent.
            # Если ваш jsTree настроен на получение вложенных данных, то этот блок нужно активировать.
            # data["children"] = [child.to_dict(include_children=True) for child in self.children]
            pass # Для AJAX jsTree обычно сам строит дерево по id и parent
        return data


# Примечание о создании таблиц:
# Для локальной разработки с SQLite, Base.metadata.create_all(engine)
# может быть в web_app.py для удобства.
# В продакшене создание таблиц (включая новую таблицу 'users')
# обычно выполняется с помощью инструментов миграции базы данных (например, Alembic).

# Обновляем модель User для связи с PlanItem
User.plan_items = relationship("PlanItem", back_populates="user", order_by="desc(PlanItem.created_at)", cascade="all, delete-orphan")
