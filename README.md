# XEON-KING-BOT (Regenerated)

Проект перегенерирован в модульную архитектуру с сохранением экономической логики из спецификаций.

## Структура
- `src/domain/formulas` — вычислительные формулы прибыли, долей, бонусов, округления.
- `src/domain/flows` — сценарии закрытия/создания сделок.
- `src/infra/db` — DB-слой (контракты + SQL репозиторий).
- `src/bot/handlers` — обработчики команд, делегирующие в сервисы.
- `tests` — контрольные тесты формул и округления.
- `docs/traceability_map.md` — трассировка `function -> formula -> table`.

## Как запустить
Сейчас это каркас после регенерации: исполняемого bot-entrypoint (как раньше `app.py`) в репозитории нет.
Рабочий способ «запуска» на текущем этапе — прогон тестов доменной логики.

### 1) Подготовить окружение
```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip pytest
```

### 2) Запустить тесты
```bash
python -m pytest -q
```

### 3) Проверить импорт/сборку модулей
```bash
python -m compileall src
```


## Как запускать через VS Code
1. Откройте папку проекта в VS Code: `File -> Open Folder...`.
2. Откройте встроенный терминал: `Terminal -> New Terminal`.
3. Создайте окружение:
```bash
python3.11 -m venv .venv
```
4. Активируйте окружение в терминале VS Code:
```bash
source .venv/bin/activate
```
5. Установите зависимости для тестов:
```bash
python -m pip install -U pip pytest
```
6. Запустите тесты:
```bash
python -m pytest -q
```

### Запуск тестов через UI VS Code (опционально)
- Установите расширение Python (ms-python.python).
- Откройте `Testing` и нажмите `Configure Python Tests`.
- Выберите `pytest` и корневую папку `tests`.
- Запускайте тесты кнопкой `Run All Tests`.

> Важно: сейчас это регенерированный каркас без runtime entrypoint бота, поэтому в VS Code запуск сводится к тестам и проверке модулей.
