# XEON-KING-BOT (Regenerated)

Проект перегенерирован в модульную архитектуру с сохранением экономической логики из спецификаций.

## Структура
- `src/domain/formulas` — вычислительные формулы прибыли, долей, бонусов, округления.
- `src/domain/flows` — сценарии закрытия/создания сделок.
- `src/infra/db` — DB-слой (контракты + SQL репозиторий).
- `src/bot/handlers` — обработчики команд, делегирующие в сервисы.
- `src/bot/runtime` — исполняемый runtime для Telegram (polling, меню, команды).
- `tests` — контрольные тесты формул и округления.
- `docs/traceability_map.md` — трассировка `function -> formula -> table`.

## Полноценный запуск бота в Telegram

### 1) Подготовка
```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -r requirements.txt
```

### 2) Настройка окружения
```bash
cp .env.example .env
```

Заполните в `.env`:
- `BOT_TOKEN` — токен от BotFather.
- `ADMIN_IDS` — список tg_id админов через запятую (опционально).

### 3) Запуск
Вариант A (рекомендуется, без PYTHONPATH):
```bash
python run_bot.py
```

Вариант B (скрипт):
```bash
./scripts/run_bot.sh
```

Вариант C (entrypoint из `pyproject`):
```bash
xeon-king-bot
```


Если запускаете из Windows CMD/PowerShell и видите `ModuleNotFoundError: No module named 'bot'`,
используйте `python run_bot.py` (этот файл теперь сам добавляет `src` в `sys.path`).

## Запуск через VS Code
1. Откройте проект (`File -> Open Folder`).
2. Откройте терминал (`Terminal -> New Terminal`).
3. Выполните шаги из раздела выше (venv, install, `.env`, запуск).
4. Для тестов можно использовать панель `Testing` и `pytest`.

## Проверки
```bash
python -m pytest -q
python -m compileall src
```
