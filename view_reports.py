from models import get_db, DailyReport
from sqlalchemy.orm import Session

def main():
    try:
        db = next(get_db())
        reports = db.query(DailyReport).all()
        if reports:
            print("Все сохраненные отчеты:")
            for report in reports:
                print(f"ID: {report.id}, User ID: {report.user_id}, Дата: {report.date}")
                print(f"  Уровень энергии: {report.energy_level}")
                print(f"  Топ-3 дела: {report.top_3_tasks}")
                # Выведите другие поля по мере необходимости
                print("---")
        else:
            print("В базе данных нет сохраненных отчетов.")
    except Exception as e:
        print(f"Произошла ошибка при чтении базы данных: {e}")
    finally:
        if 'db' in locals():
            db.close()

if __name__ == "__main__":
    main()
