from models import Base, engine

Base.metadata.drop_all(engine) # Удалит ВСЕ таблицы
Base.metadata.create_all(engine) # Создаст таблицы на основе ваших моделей
print("Все таблицы удалены и созданы заново.")