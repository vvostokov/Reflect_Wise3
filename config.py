import os

class Config:
    """
    Класс конфигурации для Flask приложения.
    Использует переменные окружения для чувствительных данных и настроек продакшена.
    """

    # SECRET_KEY для защиты сессий Flask.
    # Читается из переменной окружения SECRET_KEY.
    # Предоставляется запасное значение для локальной разработки (НИКОГДА не используйте простое значение в продакшене!).
    SECRET_KEY = os.environ.get('SECRET_KEY', 'your_fallback_secret_key_for_local_dev_only') # <-- Убедитесь, что здесь случайная строка для локально

    # URL базы данных.
    # Читается из переменной окружения DATABASE_URL, предоставляемой Render для баз данных.
    # В локальной разработке может быть установлено вручную или через локальные переменные окружения.
    # Удален локальный путь к SQLite, так как в продакшене используется PostgreSQL.
    # SQLALCHEMY_DATABASE_URI читается в models.py, но здесь мы его тоже можем определить, если нужно
    # для других частей приложения, которые работают напрямую с app.config['SQLALCHEMY_DATABASE_URI'].
    # Теперь эта строка раскомментирована.
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL')


    # --- Настройки для Telegram Аутентификации ---

    # TELEGRAM_BOT_TOKEN - токен вашего бота Telegram, полученный от BotFather.
    # ДОЛЖЕН быть установлен как переменная окружения TELEGRAM_BOT_TOKEN на Render.
    # Локальное запасное значение оставлено для удобства, но в продакшене будет использоваться переменная окружения.
    TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "7914265696:AAFSS4QcbezoNV6O1WA60BIdBsneJUxIOzU") # <-- Замените на ваш реальный локальный токен, если нужен

    # TELEGRAM_LOGIN_DOMAIN - домен вашего сайта, который вы указали BotFather для виджета входа.
    # ДОЛЖЕН быть установлен как переменная окружения TELEGRAM_LOGIN_DOMAIN на Render.
    # Например: 'reflect-wise-app.onrender.com'
    # Для VK Redirect URI будет что-то вроде https://your_domain.com/vk_callback

    # --- Настройки для VK Аутентификации ---
    VK_APP_ID = os.environ.get("VK_APP_ID", "YOUR_VK_APP_ID_HERE") # Замените на ID вашего VK приложения
    VK_SECURE_KEY = os.environ.get("VK_SECURE_KEY", "YOUR_VK_SECURE_KEY_HERE") # Замените на защищенный ключ вашего VK приложения
    # VK_REDIRECT_URI будет сформирован автоматически в web_app.py, но его нужно указать в настройках VK приложения
    TELEGRAM_LOGIN_DOMAIN = os.environ.get('TELEGRAM_LOGIN_DOMAIN') # В продакшене Render предоставит его через env var

    # --- Настройки для VK Бота ---
    VK_BOT_TOKEN = os.environ.get("VK_BOT_TOKEN", "YOUR_VK_BOT_GROUP_TOKEN_HERE") # Токен доступа сообщества VK


    # Настройки для локальной разработки без логина
    LOCAL_DEV_NO_LOGIN = True  # Установите False, чтобы включить обычный логин
    DEFAULT_DEV_USER_ID = 1    # ID пользователя по умолчанию для режима без логина
    # --- Настройки для Telegram Webhooks (если используются) ---
    # Если вы планируете использовать вебхуки для бота, эти переменные могут понадобиться.

    # WEBHOOK_URL - полный URL для вебхука вашего бота.
    # Читается из переменной окружения WEBHOOK_URL (может быть установлен вручную на Render).
    # Запасное значение "YOUR_WEBHOOK_URL" оставлено как напоминание.
    WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "YOUR_WEBHOOK_URL")

    # WEBHOOK_PATH - путь, по которому ваше приложение будет принимать запросы вебхука.
    WEBHOOK_PATH = "/webhook" # Обычно остается статичным

    # --- Другие потенциальные настройки ---
    # Здесь можно добавить другие настройки, специфичные для вашего приложения.

# Пример использования (не в продакшене, только для локальной проверки):
# print(f"SECRET_KEY: {Config.SECRET_KEY}")
# print(f"TELEGRAM_BOT_TOKEN: {Config.TELEGRAM_BOT_TOKEN}")
# print(f"TELEGRAM_LOGIN_DOMAIN: {Config.TELEGRAM_LOGIN_DOMAIN}")
# print(f"WEBHOOK_URL: {Config.WEBHOOK_URL}")
# print(f"WEBHOOK_PATH: {Config.WEBHOOK_PATH}")
