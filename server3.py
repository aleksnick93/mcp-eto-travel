import asyncio
import httpx
import json
import logging
from typing import Dict, Any
from mcp.server.fastmcp import FastMCP

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("TourVisorMCP")

# Создаем сервер
mcp = FastMCP("TourVisorSearch")

# Константы
BASE_URL = "https://tourvisor.ru"
SEARCH_INIT_URL = f"{BASE_URL}/xml/list.php"
SEARCH_RESULT_URL = "https://search3.tourvisor.ru/modresult.php"
DICTIONARY_URL = f"{BASE_URL}/xml/listdev.php"

# Глобальный кэш
# Структура: {'countries': {name: id}, 'departures': {name: id}}
GLOBAL_DICT: Dict[str, Any] = {}
# Кэш отелей по странам: {country_id: {hotel_id: "Hotel Name"}}
HOTELS_CACHE: Dict[int, Dict[int, str]] = {}

async def ensure_dictionary():
    """Загружает базовый справочник (страны, города вылета)."""
    global GLOBAL_DICT
    if GLOBAL_DICT: 
        return

    logger.info("Загрузка базового справочника...")
    try:
        # Пытаемся загрузить локально
        with open('travel-dictionary.json', 'r', encoding='utf-8') as f:
            data = json.load(f)
            lists = data.get('lists', {})
            
            # Индексируем страны
            countries = {}
            for c in lists.get('countries', {}).get('country', []):
                countries[c['name'].lower()] = c['id']
            
            # Индексируем вылеты
            departures = {}
            for d in lists.get('departures', {}).get('departure', []):
                departures[d['name'].lower()] = d['id']
                
            GLOBAL_DICT = {'countries': countries, 'departures': departures}
            logger.info(f"Справочник загружен: {len(countries)} стран")
            return
    except FileNotFoundError:
        logger.warning("Файл справочника не найден! Автоматическая загрузка из сети пока не реализована в этом блоке.")
        # В реальном коде тут можно добавить fallback на httpx запрос к listdev.php

async def get_hotel_name(client: httpx.AsyncClient, country_id: int, hotel_id: int) -> str:
    """Возвращает название отеля по ID, подгружая справочник если нужно."""
    global HOTELS_CACHE
    
    # Если кэша для этой страны нет, грузим его
    if country_id not in HOTELS_CACHE:
        logger.info(f"Загрузка справочника отелей для страны ID {country_id}...")
        try:
            url = f"{DICTIONARY_URL}?type=allhotel&hotcountry={country_id}&format=json"
            resp = await client.get(url, timeout=10.0)
            data = resp.json()
            
            hotels_map = {}
            # Парсим ответ (структура из travel-hotels_example.json)
            hotel_list = data.get('lists', {}).get('hotels', {}).get('hotel', [])
            for h in hotel_list:
                hotels_map[h['id']] = h['name']
            
            HOTELS_CACHE[country_id] = hotels_map
            logger.info(f"Загружено {len(hotels_map)} отелей для страны {country_id}")
            
        except Exception as e:
            logger.error(f"Ошибка загрузки отелей: {e}")
            return f"Hotel ID {hotel_id}"

    # Ищем в кэше
    return HOTELS_CACHE[country_id].get(hotel_id, f"Hotel ID {hotel_id}")

def find_id(name: str, category: str, default: int) -> int:
    """Ищет ID в загруженном словаре."""
    if not GLOBAL_DICT: 
        return default
    mapping = GLOBAL_DICT.get(category, {})
    
    name_lower = name.lower()
    # Точное совпадение
    if name_lower in mapping:
        return mapping[name_lower]
    
    # Частичное совпадение
    for key, val in mapping.items():
        if name_lower in key:
            return val
    return default

@mcp.tool()
async def search_tours(country: str, date_from: str, date_to: str, nights_from: int = 7, nights_to: int = 14, adults: int = 2, departure: str = "Москва") -> str:
    """
    Поиск туров (eto.travel / Tourvisor).
    
    Args:
        country: Страна назначения (Турция, Египет, ОАЭ...).
        date_from: Дата начала (dd.mm.yyyy).
        date_to: Дата окончания (dd.mm.yyyy).
        nights_from: Минимум ночей.
        nights_to: Максимум ночей.
        adults: Взрослых.
        departure: Город вылета.
    """
    await ensure_dictionary()
    
    country_id = find_id(country, 'countries', 47) # 47 - Египет
    departure_id = find_id(departure, 'departures', 1) # 1 - Москва
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://eto.travel/search/",
        "Origin": "https://eto.travel"
    }

    async with httpx.AsyncClient(headers=headers) as client:
        # 1. Запуск поиска
        params = {
            "ts_dosearch": 1,
            "s_flyfrom": departure_id,
            "s_country": country_id,
            "s_nights_from": nights_from,
            "s_nights_to": nights_to,
            "s_j_date_from": date_from, # Формат dd.mm.yyyy важен!
            "s_j_date_to": date_to,
            "s_adults": adults,
            "s_regular": 1,
            "format": "json"
        }
        
        try:
            logger.info(f"Инициализация поиска: {country} ({country_id}) из {departure} ({departure_id})")
            init_resp = await client.get(SEARCH_INIT_URL, params=params, timeout=15.0)
            
            # Обработка ответа инициализации
            try:
                init_data = init_resp.json()
                # requestid может быть в result.requestid или data.requestid
                request_id = init_data.get('result', {}).get('requestid') or init_data.get('data', {}).get('requestid')
                
                if not request_id:
                     return f"Ошибка API: Не удалось получить Request ID. Ответ сервера: {init_resp.text[:100]}"
            except json.JSONDecodeError:
                return f"Ошибка API: Сервер вернул не JSON. {init_resp.text[:100]}"

            logger.info(f"Поиск запущен. ID: {request_id}")

            # 2. Long Polling результатов
            tours_found = []
            last_block = 0
            max_polls = 10 # Максимум 20 секунд ожидания
            
            for i in range(max_polls):
                poll_resp = await client.get(
                    SEARCH_RESULT_URL, 
                    params={
                        "requestid": request_id,
                        "lastblock": last_block,
                        "format": "json",
                        "referrer": "https://eto.travel/search/" # Важно!
                    },
                    timeout=5.0
                )
                
                poll_data = poll_resp.json()
                data_block = poll_data.get('data', {})
                blocks = data_block.get('block', [])
                
                if blocks:
                    tours_found.extend(blocks)
                    last_block += len(blocks)
                    
                    # Если нашли достаточно (например 10), можно выходить досрочно,
                    # но лучше подождать статус finished для точности цен
                
                status = data_block.get('status', {})
                # Прогресс бар
                progress = status.get('progress', 0)
                if status.get('finished') or progress == 100:
                    break
                    
                await asyncio.sleep(1.5)

            if not tours_found:
                return "Туры не найдены по заданным параметрам."

            # 3. Формирование красивого ответа (Обогащение именами)
            # Загружаем справочник отелей лениво
            # Берем уникальные отели (часто один отель повторяется с разными типами питания)
            unique_hotels = {}
            
            for t in tours_found:
                # В структуре results.json:
                # Каждый блок - это группировка. Внутри "hotel" массив вариантов.
                # Структура: { "hotel": [ { "id": 123, "price": 50000, ... } ] }
                # Иногда ID отеля прямо в корне блока
                
                hotel_list = t.get('hotel', [])
                # Обрабатываем каждый вариант размещения
                for h in hotel_list:
                    h_id = h.get('id')
                    price = h.get('price')
                    
                    if h_id not in unique_hotels:
                        unique_hotels[h_id] = {'min_price': price, 'stars': t.get('stars', '')} # Звезды могут быть выше
                    else:
                        if price < unique_hotels[h_id]['min_price']:
                            unique_hotels[h_id]['min_price'] = price
            
            # Сортируем топ-10 самых дешевых
            sorted_hotels = sorted(unique_hotels.items(), key=lambda x: x[1]['min_price'])[:10]
            
            result_text = f"Найдено туров в {country}: {len(unique_hotels)} (показаны топ-10 лучших цен):\n"
            
            for h_id, info in sorted_hotels:
                # Асинхронно получаем имя
                name = await get_hotel_name(client, country_id, h_id)
                result_text += f"- **{name}** : от {info['min_price']} руб.\n"
                
            return result_text

        except Exception as e:
            logger.error(f"Error: {e}")
            return f"Произошла ошибка при поиске: {e}"

if __name__ == "__main__":
    mcp.run()