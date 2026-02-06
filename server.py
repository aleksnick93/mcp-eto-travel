from fastmcp import FastMCP
import httpx
import re
import asyncio

# Создаем сервер
mcp = FastMCP("EtoTravel Agent")

# Заголовки как у браузера (критично для Tourvisor)
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://eto.travel/"
}

def main():
    print("Hello from mcp-eto-travel!")

def parse_tourvisor_text(text: str):
    """Парсит кастомный текстовый формат Tourvisor из modresult.php"""
    hotels = []
    # Регулярка ищет блоки отелей: ID name НАЗВАНИЕ ... stars ЦИФРА ... rating ЦИФРА
    # Мы ищем только уникальные названия, чтобы не дублировать типы комнат
    # Пример строки: 17659 name SWISSOTEL THE BOSPHORUS, desc , ... rating 4.8, pop 2540, stars 5
    
    # 1. Ищем все отели
    # Паттерн: Число (ID) + " name " + (Название до запятой) + ... "stars " + (Число)
    matches = re.findall(r'\d+\s+name\s+([^,]+),.*?stars\s+(\d+).*?rating\s+([\d\.]+)', text, re.DOTALL)
    
    seen_names = set()
    for name, stars, rating in matches:
        clean_name = name.strip()
        if clean_name not in seen_names:
            hotels.append({
                "name": clean_name,
                "stars": stars,
                "rating": rating
            })
            seen_names.add(clean_name)
    
    return hotels

@mcp.tool()
async def search_tours_eto(country_code: int = 4, nights_from: int = 7, nights_to: int = 14) -> str:
    """
    Поиск туров через скрытый API eto.travel.
    
    Args:
        country_code: ID страны (4 = Турция, 1 = Египет, 9 = ОАЭ, 56 = Таиланд)
        nights_from: Минимум ночей
        nights_to: Максимум ночей
    """
    async with httpx.AsyncClient(headers=HEADERS, timeout=30.0) as client:
        # ШАГ 1: Запуск поиска
        # Используем дату "через неделю" для примера, в реале можно добавить аргумент date
        import datetime
        start_date = (datetime.date.today() + datetime.timedelta(days=7)).strftime("%d.%m.%Y")
        
        # Минимальный payload для старта
        payload = {
            "country": country_code,
            "datefrom": start_date,
            "nightsfrom": nights_from,
            "nightsto": nights_to,
            "adults": 2,
            "departure": 1 # Москва
        }
        
        # URL может отличаться, пробуем стандартный endpoint агрегатора
        # Если не сработает прямой запрос на tourvisor, нужно использовать прокси eto.travel
        # Но по твоим логам ты бил прямо в stat.tourvisor.ru
        init_url = "https://stat.tourvisor.ru/api/v1/searches"
        
        # Трансформируем payload под формат Tourvisor (из твоего первого сообщения)
        tv_payload = {
             "adultsCount": 2,
             "countryIds": [country_code],
             "departureId": 1, # Москва
             "dateFrom": (datetime.date.today() + datetime.timedelta(days=7)).strftime("%Y-%m-%d"),
             "dateTo": (datetime.date.today() + datetime.timedelta(days=14)).strftime("%Y-%m-%d"),
             "nightsFrom": nights_from,
             "nightsTo": nights_to,
        }

        try:
            resp = await client.post(init_url, json=tv_payload)
            data = resp.json()
            
            # Получаем ID поиска
            # В ответе 201 обычно: {"result": {"requestid": 12345...}}
            request_id = data.get("result", {}).get("requestid")
            if not request_id:
                return f"Ошибка запуска поиска. Ответ: {data}"
                
            print(f"Поиск запущен ID: {request_id}. Ждем данные...")
            
            # ШАГ 2: Ждем наполнения буфера (Tourvisor медленный)
            await asyncio.sleep(8) 
            
            # ШАГ 3: Забираем сырые данные (modresult.php)
            # URL из твоего лога
            result_url = f"https://search3.tourvisor.ru/modresult.php?requestid={request_id}&referrer=https://eto.travel/"
            
            result_resp = await client.get(result_url)
            raw_text = result_resp.text
            
            # ШАГ 4: Парсим
            hotels = parse_tourvisor_text(raw_text)
            
            if not hotels:
                return "Туры не найдены (пустой ответ от провайдера). Попробуйте изменить параметры."
            
            # Формируем красивый ответ
            output = [f"Найдено {len(hotels)} отелей (Топ-15):"]
            for h in hotels[:15]:
                output.append(f"- {h['name']} {h['stars']}* (Рейтинг: {h['rating']})")
                
            return "\n".join(output)

        except Exception as e:
            return f"Критическая ошибка: {str(e)}"

# Запуск
# if __name__ == "__main__":
#     # Запускаем сервер локально с поддержкой SSE для отладки
#     # Это позволяет запускать файл просто как "python server.py"
#     mcp.run(transport="sse", port=8000)
