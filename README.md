# ETO.Travel MCP Server

MCP сервер для поиска туров на сайте eto.travel через Tourvisor API.

## Возможности

Сервер предоставляет следующие инструменты:

1. **load_dictionary** - загрузка справочника стран, регионов, городов отправления
2. **search_tours** - поиск туров по параметрам
3. **get_hotel_types** - получение типов отелей для страны
4. **get_hotels_by_country** - список отелей в стране
5. **find_country** - поиск страны по названию
6. **find_region** - поиск региона/курорта
7. **get_popular_countries** - список популярных направлений

## Установка локально

```bash
pip install -r requirements.txt
```

## Запуск

```bash
python mcp_server.py
```

## Деплой на Railway

1. Создай новый проект на [Railway](https://railway.app)
2. Подключи GitHub репозиторий с этим кодом
3. Railway автоматически обнаружит Dockerfile и задеплоит сервер
4. Получи URL сервера из настроек проекта

## Подключение к Cursor

Добавь в настройки MCP в Cursor (Settings → Features → MCP):

```json
{
  "mcpServers": {
    "eto-travel": {
      "command": "python",
      "args": ["/path/to/mcp_server.py"]
    }
  }
}
```

Для удаленного сервера на Railway:

```json
{
  "mcpServers": {
    "eto-travel": {
      "url": "https://your-railway-url.railway.app"
    }
  }
}
```

## Использование

После подключения к Cursor, ты можешь использовать естественный язык для поиска туров:

- "Найди туры в Египет на 7 ночей"
- "Покажи отели в Турции"
- "Какие есть популярные страны для отдыха?"
- "Найди туры в Таиланд, Пхукет с 1 марта по 15 марта"

## Примеры запросов

### 1. Загрузка справочника

```
load_dictionary
```

### 2. Поиск страны

```
find_country("Египет")
```

### 3. Поиск туров

```
search_tours(
  country_id=1,  # Египет
  date_from="01.03.2026",
  date_to="15.03.2026",
  nights_from=7,
  nights_to=10,
  adults=2
)
```

## API Endpoints

Сервер работает с следующими API:

- `tourvisor.ru/xml/listdev.php` - справочники
- `tourvisor.ru/api/v1.1/hotel-actypes/all` - типы отелей
- `search3.tourvisor.ru/modresult.php` - результаты поиска

## Структура данных

### Страны

```json
{
  "id": 1,
  "name": "Египет",
  "popular": 1,
  "directfly": 1
}
```

### Туры

```json
{
  "op": 62,
  "dt": "2026-02-13",
  "nt": 7,
  "pr": 145933,
  "hotel_id": 143644,
  "ml": 2
}
```

## Технологии

- Python 3.10
- MCP SDK
- httpx для HTTP запросов
- asyncio для асинхронности

## Лицензия

MIT