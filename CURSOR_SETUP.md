# Настройка MCP сервера в Cursor

## Вариант 1: Локальный запуск

1. Открой Cursor Settings (Cmd/Ctrl + ,)
2. Найди раздел "Features" → "MCP"
3. Добавь конфигурацию:

```json
{
  "mcpServers": {
    "eto-travel": {
      "command": "python",
      "args": ["/полный/путь/к/mcp_server.py"],
      "env": {}
    }
  }
}
```

## Вариант 2: Через Railway (рекомендуется для 24/7)

После деплоя на Railway:

```json
{
  "mcpServers": {
    "eto-travel": {
      "transport": "sse",
      "url": "https://your-app-name.up.railway.app/sse"
    }
  }
}
```

## Проверка подключения

После добавления конфигурации перезапусти Cursor. Теперь ты можешь использовать инструменты:

1. Спроси AI: "Загрузи справочник туров"
2. Спроси: "Найди туры в Египет на 7 ночей с 1 марта"
3. Спроси: "Покажи популярные страны для отдыха"

## Отладка

Если сервер не работает:

1. Проверь логи: запусти сервер вручную
   ```bash
   python mcp_server.py
   ```

2. Убедись, что установлены зависимости:
   ```bash
   pip install -r requirements.txt
   ```

3. Проверь путь к Python:
   ```bash
   which python
   ```