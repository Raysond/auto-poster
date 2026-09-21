# 🚀 Telegram Auto-Poster Bot (Google Drive & Mini App)

Автоматический Telegram-бот для публикации по расписанию случайных подборок **[набор фото + короткий текст + ссылки]** в различные каналы из Google Drive. Оснащен веб-панелью **Telegram Mini App (TMA)** для администрирования прямо внутри Telegram и **буфером на 3 поста в отложке** для защиты от обрывов интернета на сервере.

---

## 📋 Особенности и возможности

- **Умная компоновка постов:**
  - Каждый пост отправляется единым сообщением (альбом из 2–10 фото с подписью).
  - Подпись собирается динамически: `{случайный текст из texts.txt}` + `\n\n` + `{постоянная плашка ссылки}`.
  - Поддержка Telegram HTML-форматирования ссылок (`<a href="...">текст ссылки</a>`).
- **Формат Google Диска:**
  - `texts.txt`: 1 строка = 1 вариант текста. Внутренний перенос строки обозначается как `\n`.
  - Папка с фотографиями: любые форматы (jpg, png, webp). Бот запоминает использованные фото и тексты, исключая повторы, пока весь пул не исчерпан.
  - Плашка ссылки (футер): может браться из файла `footer.txt` на Диске или настраиваться индивидуально в Telegram Mini App для каждого канала.
- **Мульти-канальность:**
  - Поддержка неограниченного числа каналов.
  - Для каждого канала можно задать свою папку с фото (или одну общую), свой файл текстов, индивидуальное расписание и число фото на пост (например, 2–4).
- **🛡️ Защита от обрывов интернета на сервере (Буфер 3 поста в отложке):**
  - Бот всегда держит очередь из 3 постов вперед.
  - **Режим нативной отложки Telegram (MTProto / Telethon):** посты заранее отправляются в облачную отложку Telegram с точным временем публикации (`schedule_date`). Даже если сервер Debian полностью потеряет связь на сутки или отключится электричество — **Telegram сам опубликует посты минута в минуту!**
  - **Режим Bot API:** если аккаунт MTProto не подключен, бот держит 3 предзагруженных поста в локальном буфере SQLite, защищая от сбоев Google Drive.
- **📱 Telegram Mini App (TMA):**
  - Управление каналами без выхода из Telegram: вызовите `/admin` и нажмите кнопку.
  - Добавление и удаление каналов, настройка расписания (каждые N минут или точные часы).
  - Быстрое клонирование настроек из существующего канала при добавлении нового.
  - Интерактивный генератор превью поста с реальными фотографиями из Google Диска и отображением подписи.
  - Кнопки «Опубликовать сейчас» и «Пополнить отложку».
  - Мониторинг статуса подключения Google Drive и журнал событий.
  - Кастомные выпадающие списки (custom styled selects) и адаптивный дизайн в стиле темы Telegram.

---

## 📂 Структура проекта

```
auto-poster/
├── bot/
│   ├── handlers/          # Обработчики команд (/start, /admin, /status, /help)
│   ├── main.py            # Главная точка входа: запуск aiogram polling + FastAPI TMA
├── core/
│   ├── config.py          # Валидация .env (Pydantic Settings)
│   └── database.py        # Асинхронная база SQLite (aiosqlite)
├── services/
│   ├── google_drive.py    # Google Drive API (Service Account, стриминг фото и чтение текстов)
│   ├── post_builder.py    # Сборка случайного поста, учет использованных фото, лимит 1024 симв.
│   ├── queue_manager.py   # Контроль буфера из 3 постов в отложке
│   ├── telethon_client.py # MTProto клиент для нативной отложки Telegram
│   ├── publisher.py       # Отправка альбомов через Bot API или Telethon
│   └── scheduler.py       # Фоновый планировщик APScheduler (проверка очереди и отправка)
├── webapp/                # Telegram Mini App
│   ├── api/routes.py      # REST API для админ-панели (валидация initData)
│   └── static/            # Frontend (HTML5, CSS переменные темы Telegram, JavaScript)
├── scripts/
│   └── login_telethon.py  # Разовая интерактивная авторизация для нативной облачной отложки
├── systemd/
│   └── autoposter.service # Unit-файл службы для автозапуска на Debian 13
├── credentials/
│   └── google-service-account.json.example
├── docker-compose.yml     # Для развертывания в Docker
├── Dockerfile
├── requirements.txt
└── .env.example
```

---

## 🛠️ Настройка и запуск на Windows 11 (Разработка и тестирование)

### 1. Клонирование и виртуальное окружение
```powershell
# Перейдите в каталог проекта
cd Z:\project\auto-poster

# Создайте и активируйте venv
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Установите зависимости
pip install -r requirements.txt
```

### 2. Получение токена Telegram бота
1. Откройте `@BotFather` в Telegram.
2. Создайте бота через `/newbot`, сохраните полученный токен.
3. Добавьте бота администратором в ваш канал(ы) с правом публикации сообщений.
4. Узнайте ваш Telegram User ID (например, через бота `@userinfobot`).

### 3. Настройка Google Cloud Service Account
1. Перейдите в [Google Cloud Console](https://console.cloud.google.com/).
2. Создайте новый проект (или выберите существующий).
3. Перейдите в раздел **APIs & Services > Library** и включите **Google Drive API**.
4. Перейдите в **APIs & Services > Credentials** -> **Create Credentials** -> **Service Account**.
5. Задайте имя (например, `auto-poster-bot`) и нажмите **Done**.
6. Откройте созданный сервисный аккаунт -> вкладка **Keys** -> **Add Key** -> **Create new key** -> **JSON**.
7. Сохраните скачанный файл в папку проекта:
   `credentials/google-service-account.json`
8. **ВАЖНО:** Скопируйте email сервисного аккаунта (например, `auto-poster@project.iam.gserviceaccount.com`). 
   Откройте на Google Диске вашу папку с фотографиями, нажмите **Поделиться** и добавьте этот email с правами **Читатель** (Viewer).

### 4. Подготовка файлов на Google Диске
- **Папка с фото:** загрузите в расшаренную папку фотографии (jpg, png, webp). Скопируйте ID папки из адресной строки браузера (символы после `folders/`).
- **Файл `texts.txt`:** создайте текстовый файл, где каждая строка — отдельный вариант текста. Для переноса строки внутри одного текста пишите `\n`:
  ```text
  Утренний дайджест событий! 🔥\nСобрали для вас самое интересное за ночь.
  Аналитика рынка за неделю 📊\nПодборка ключевых изменений.
  Короткая фраза дня 🌙
  ```
  Скопируйте ID файла из ссылки общего доступа.

### 5. Конфигурация `.env`
Скопируйте `.env.example` в `.env`:
```powershell
cp .env.example .env
```
Заполните параметры:
```ini
BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz
ADMIN_IDS=123456789
GOOGLE_SERVICE_ACCOUNT_FILE=credentials/google-service-account.json
WEBAPP_PORT=8080
WEBAPP_URL=http://localhost:8080
```
*(Для работы Telegram Mini App внутри мобильного Telegram нужен валидный HTTPS. Во время локальной разработки используйте туннель: `cloudflared tunnel --url http://localhost:8080` или `ngrok http 8080` и укажите полученный https-адрес в `WEBAPP_URL`).*

### 6. [Опционально] Настройка нативной облачной отложки (Telethon MTProto)
Если вы хотите 100% защиту от отключения сервера:
1. Зайдите на [my.telegram.org](https://my.telegram.org) -> **API development tools**.
2. Скопируйте `App api_id` и `App api_hash` в `.env`:
   ```ini
   TELEGRAM_API_ID=1234567
   TELEGRAM_API_HASH=abcdef1234567890abcdef1234567890
   ```
3. Выполните разовый вход в терминале:
   ```powershell
   python -m scripts.login_telethon
   ```
   Введите номер телефона и код из Telegram. Сессия сохранится локально в `data/admin_session.session`.

### 7. Запуск проекта
```powershell
python -m bot.main
```
Откройте бота в Telegram, введите `/admin` и управляйте публикациями через Mini App!

---

## 🐧 Развертывание и эксплуатация на Debian 13

### Вариант 1: Через системную службу systemd (Рекомендуется)

1. **Подготовка системы:**
   ```bash
   sudo apt update && sudo apt install -y python3 python3-venv python3-pip git
   ```

2. **Копирование проекта:**
   ```bash
   sudo mkdir -p /opt/auto-poster
   sudo chown -R $USER:$USER /opt/auto-poster
   # Склонируйте репозиторий или скопируйте файлы в /opt/auto-poster
   cd /opt/auto-poster
   ```

3. **Создание venv и установка зависимостей:**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install --upgrade pip
   pip install -r requirements.txt
   ```

4. **Копирование ключей и .env:**
   - Поместите `credentials/google-service-account.json`.
   - Заполните `.env` (укажите реальный домен или внешний IP с HTTPS).
   - Если используется Telethon, скопируйте файл сессии `data/admin_session.session` или запустите `python3 -m scripts.login_telethon`.

5. **Установка systemd unit:**
   ```bash
   sudo cp systemd/autoposter.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable autoposter
   sudo systemctl start autoposter
   ```

6. **Проверка статуса и логов:**
   ```bash
   sudo systemctl status autoposter
   sudo journalctl -u autoposter -f
   ```

---

### Вариант 2: Запуск в Docker / Docker Compose

```bash
docker compose up -d --build
```
Просмотр логов:
```bash
docker compose logs -f
```

---

## 🧪 Запуск автоматических тестов

```bash
pytest -v
```
Тесты проверяют парсинг строк `texts.txt`, сборку подписей, лимит длины подписи, транзакции базы данных SQLite и работу REST API панели управления.

---

## 🤖 Разработка

Проект спроектирован и реализован при помощи AI-ассистента **Antigravity** (Google DeepMind).
