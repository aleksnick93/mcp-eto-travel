import asyncio
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    Tool,
    TextContent
)

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("eto-travel-mcp")

# Базовые URL
BASE_URL = "https://tourvisor.ru"
API_URL = "https://tourvisor.ru/api/v1.1"
SEARCH_URL = "https://search3.tourvisor.ru"
REFERRER = "https://eto.travel/search/"

# Путь к файлу справочника (можно переопределить через переменную окружения)
DICTIONARY_FILE = os.getenv("DICTIONARY_FILE", "travel-dictionary.json")


class EtoTravelMCP:
    """MCP сервер для работы с eto.travel API"""
    
    def __init__(self, dictionary_path: Optional[str] = None):
        self.server = Server("eto-travel-mcp")
        self.session: Optional[str] = None
        self.dictionary: Dict[str, Any] = {}
        self.http_client = httpx.AsyncClient(timeout=30.0)
        
        # Определяем путь к файлу справочника
        if dictionary_path:
            self.dictionary_path = Path(dictionary_path)
        else:
            # Ищем файл рядом со скриптом
            script_dir = Path(__file__).parent
            self.dictionary_path = script_dir / DICTIONARY_FILE
        
        logger.info(f"📂 Путь к справочнику: {self.dictionary_path}")
        
        # Регистрируем инструменты
        self.setup_tools()
        
    def setup_tools(self):
        """Регистрация доступных инструментов"""
        
        @self.server.list_tools()
        async def list_tools() -> List[Tool]:
            return [
                Tool(
                    name="load_dictionary",
                    description="Загрузить справочник стран, регионов, городов отправления и операторов. Вызови этот инструмент первым перед любым поиском.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "force_reload": {
                                "type": "boolean",
                                "description": "Принудительно загрузить из API вместо локального файла",
                                "default": False
                            }
                        },
                        "required": []
                    }
                ),
                Tool(
                    name="search_tours",
                    description="Поиск туров по заданным параметрам. Возвращает список доступных туров с ценами и деталями.",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "country_id": {
                                "type": "integer",
                                "description": "ID страны назначения (из справочника)"
                            },
                            "departure_id": {
                                "type": "integer",
                                "description": "ID города отправления (из справочника). По умолчанию 1 (Москва)",
                                "default": 1
                            },
                            "nights_from": {
                                "type": "integer",
                                "description": "Минимальное количество ночей",
                                "default": 7
                            },
                            "nights_to": {
                                "type": "integer",
                                "description": "Максимальное количество ночей",
                                "default": 14
                            },
                            "date_from": {
                                "type": "string",
                                "description": "Дата начала поиска в формате DD.MM.YYYY"
                            },
                            "date_to": {
                                "type": "string",
                                "description": "Дата окончания поиска в формате DD.MM.YYYY"
                            },
                            "adults": {
                                "type": "integer",
                                "description": "Количество взрослых",
                                "default": 2
                            },
                            "children": {
                                "type": "integer",
                                "description": "Количество детей",
                                "default": 0
                            },
                            "region_ids": {
                                "type": "array",
                                "items": {"type": "integer"},
                                "description": "Список ID регионов для поиска (опционально)"
                            },
                            "hotel_ids": {
                                "type": "array",
                                "items": {"type": "integer"},
                                "description": "Список ID отелей для поиска (опционально)"
                            }
                        },
                        "required": ["country_id", "date_from", "date_to"]
                    }
                ),
                Tool(
                    name="get_hotel_types",
                    description="Получить список доступных типов отелей для страны (отель, апартаменты, вилла и т.д.)",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "country_id": {
                                "type": "integer",
                                "description": "ID страны"
                            }
                        },
                        "required": ["country_id"]
                    }
                ),
                Tool(
                    name="get_hotels_by_country",
                    description="Получить список всех отелей в стране с их характеристиками (звезды, регион, рейтинг)",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "country_id": {
                                "type": "integer",
                                "description": "ID страны"
                            },
                            "departure_id": {
                                "type": "integer",
                                "description": "ID города отправления (по умолчанию 1 - Москва)",
                                "default": 1
                            }
                        },
                        "required": ["country_id"]
                    }
                ),
                Tool(
                    name="find_country",
                    description="Найти страну по названию и получить её ID и доступные направления",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Название страны для поиска (например: 'Египет', 'Турция', 'Тайланд')"
                            }
                        },
                        "required": ["query"]
                    }
                ),
                Tool(
                    name="find_region",
                    description="Найти регион/курорт по названию в конкретной стране",
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "country_id": {
                                "type": "integer",
                                "description": "ID страны"
                            },
                            "query": {
                                "type": "string",
                                "description": "Название региона/курорта"
                            }
                        },
                        "required": ["country_id", "query"]
                    }
                ),
                Tool(
                    name="get_popular_countries",
                    description="Получить список популярных стран для туризма",
                    inputSchema={
                        "type": "object",
                        "properties": {},
                        "required": []
                    }
                )
            ]
        
        @self.server.call_tool()
        async def call_tool(name: str, arguments: Any) -> List[TextContent]:
            try:
                if name == "load_dictionary":
                    force_reload = arguments.get("force_reload", False) if arguments else False
                    result = await self.load_dictionary(force_reload=force_reload)
                elif name == "search_tours":
                    result = await self.search_tours(**arguments)
                elif name == "get_hotel_types":
                    result = await self.get_hotel_types(**arguments)
                elif name == "get_hotels_by_country":
                    result = await self.get_hotels_by_country(**arguments)
                elif name == "find_country":
                    result = await self.find_country(**arguments)
                elif name == "find_region":
                    result = await self.find_region(**arguments)
                elif name == "get_popular_countries":
                    result = await self.get_popular_countries()
                else:
                    result = {"error": f"Unknown tool: {name}"}
                    
                return [TextContent(
                    type="text",
                    text=json.dumps(result, ensure_ascii=False, indent=2)
                )]
            except Exception as e:
                logger.error(f"Error in tool {name}: {str(e)}")
                return [TextContent(
                    type="text",
                    text=json.dumps({"error": str(e)}, ensure_ascii=False)
                )]
    
    async def ensure_session(self):
        """Получить session ID если его нет"""
        if not self.session:
            self.session = "0e56548e3e4ed302e692f3afc717a163324fe9526f01957108cfe5b656cbbe413ef653bcc317e817c0c4687a2b0536611942eeb3ebbe6bced2264ba434f462a787f83474aa5e2122f03b098cc16f285f024ade46527e24c1542eaa89605d5399ca6a71e337332188e0ad327a9738fa62a5e42c872dc03236bf38e1113686190d38812c51c49a21b662fe9351ad"
    
    def _load_dictionary_from_file(self) -> Optional[Dict[str, Any]]:
        """Загрузить справочник из локального файла"""
        try:
            if not self.dictionary_path.exists():
                logger.warning(f"📁 Файл справочника не найден: {self.dictionary_path}")
                return None
            
            logger.info(f"📖 Загрузка справочника из файла: {self.dictionary_path}")
            with open(self.dictionary_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            logger.info("✅ Справочник загружен из файла")
            return data
            
        except json.JSONDecodeError as e:
            logger.error(f"❌ Ошибка парсинга JSON: {e}")
            return None
        except Exception as e:
            logger.error(f"❌ Ошибка чтения файла: {e}")
            return None
    
    async def _load_dictionary_from_api(self) -> Optional[Dict[str, Any]]:
        """Загрузить справочник из API"""
        await self.ensure_session()
        
        params = {
            "type": "departure,allcountry,country,region,subregions,operator",
            "formmode": "0",
            "cndep": "1",
            "flydeparture": "1",
            "flycountry": "47",
            "format": "json",
            "referrer": REFERRER,
            "session": self.session
        }
        
        url = f"{BASE_URL}/xml/listdev.php?{urlencode(params)}"
        
        try:
            logger.info("🌐 Загрузка справочника из API...")
            response = await self.http_client.get(url)
            response.raise_for_status()
            data = response.json()
            
            logger.info("✅ Справочник загружен из API")
            
            # Сохраняем в файл для будущего использования
            try:
                with open(self.dictionary_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                logger.info(f"💾 Справочник сохранён в файл: {self.dictionary_path}")
            except Exception as e:
                logger.warning(f"⚠️ Не удалось сохранить справочник в файл: {e}")
            
            return data
            
        except Exception as e:
            logger.error(f"❌ Ошибка загрузки из API: {e}")
            return None
    
    async def load_dictionary(self, force_reload: bool = False) -> Dict[str, Any]:
        """Загрузить справочник стран, регионов и городов
        
        Args:
            force_reload: Принудительно загрузить из API вместо файла
        """
        # Если справочник уже загружен и не требуется перезагрузка
        if self.dictionary and not force_reload:
            stats = {
                "countries_count": len(self.dictionary.get("lists", {}).get("allcountry", {}).get("country", [])),
                "departures_count": len(self.dictionary.get("lists", {}).get("departures", {}).get("departure", [])),
                "regions_count": len(self.dictionary.get("lists", {}).get("regions", {}).get("region", [])),
                "loaded": True,
                "source": "cache"
            }
            return {
                "success": True,
                "message": "Справочник уже загружен (используется кэш)",
                "stats": stats
            }
        
        # Пытаемся загрузить из файла (если не требуется принудительная перезагрузка)
        if not force_reload:
            data = self._load_dictionary_from_file()
            if data:
                self.dictionary = data
                source = "file"
            else:
                # Fallback на API
                data = await self._load_dictionary_from_api()
                if data:
                    self.dictionary = data
                    source = "api"
                else:
                    return {
                        "success": False,
                        "error": "Не удалось загрузить справочник ни из файла, ни из API"
                    }
        else:
            # Принудительная загрузка из API
            data = await self._load_dictionary_from_api()
            if data:
                self.dictionary = data
                source = "api_forced"
            else:
                return {
                    "success": False,
                    "error": "Не удалось загрузить справочник из API"
                }
        
        # Подготовим статистику
        stats = {
            "countries_count": len(self.dictionary.get("lists", {}).get("allcountry", {}).get("country", [])),
            "departures_count": len(self.dictionary.get("lists", {}).get("departures", {}).get("departure", [])),
            "regions_count": len(self.dictionary.get("lists", {}).get("regions", {}).get("region", [])),
            "loaded": True,
            "source": source
        }
        
        return {
            "success": True,
            "message": f"Справочник успешно загружен из {source}",
            "stats": stats
        }
    
    async def get_hotel_types(self, country_id: int) -> Dict[str, Any]:
        """Получить типы отелей для страны"""
        await self.ensure_session()
        
        params = {
            "active": "true",
            "sortProp": "order",
            "countryId": country_id,
            "referrer": REFERRER,
            "session": self.session
        }
        
        url = f"{API_URL}/hotel-actypes/all?{urlencode(params)}"
        
        try:
            response = await self.http_client.get(url)
            response.raise_for_status()
            data = response.json()
            return {"success": True, "hotel_types": data}
        except Exception as e:
            logger.error(f"Error getting hotel types: {str(e)}")
            return {"success": False, "error": str(e)}
    
    async def get_hotels_by_country(self, country_id: int, departure_id: int = 1) -> Dict[str, Any]:
        """Получить список отелей по стране"""
        await self.ensure_session()
        
        params = {
            "type": "allhotel",
            "hotcountry": country_id,
            "format": "json",
            "referrer": REFERRER,
            "session": self.session
        }
        
        url = f"{BASE_URL}/xml/listdev.php?{urlencode(params)}"
        
        try:
            response = await self.http_client.get(url)
            response.raise_for_status()
            data = response.json()
            
            hotels = data.get("lists", {}).get("hotels", {}).get("hotel", [])
            
            return {
                "success": True,
                "hotels_count": len(hotels),
                "hotels": hotels[:100]
            }
        except Exception as e:
            logger.error(f"Error getting hotels: {str(e)}")
            return {"success": False, "error": str(e)}
    
    async def search_tours(
        self,
        country_id: int,
        date_from: str,
        date_to: str,
        departure_id: int = 1,
        nights_from: int = 7,
        nights_to: int = 14,
        adults: int = 2,
        children: int = 0,
        region_ids: Optional[List[int]] = None,
        hotel_ids: Optional[List[int]] = None
    ) -> Dict[str, Any]:
        """Поиск туров"""
        await self.ensure_session()
        
        search_params = {
            "ts_dosearch": "1",
            "s_form_mode": "0",
            "s_nights_from": nights_from,
            "s_nights_to": nights_to,
            "s_regular": "1",
            "s_j_date_from": date_from,
            "s_j_date_to": date_to,
            "s_adults": adults,
            "s_flyfrom": departure_id,
            "s_country": country_id,
            "s_currency": "0"
        }
        
        if children > 0:
            search_params["s_kids"] = children
        
        if region_ids:
            search_params["s_region_to"] = ",".join(map(str, region_ids))
        
        if hotel_ids:
            search_params["s_hotels"] = ",".join(map(str, hotel_ids))
        
        search_url = f"https://eto.travel/search/?{urlencode(search_params)}"
        
        try:
            response = await self.http_client.get(
                search_url,
                follow_redirects=True,
                headers={"User-Agent": "Mozilla/5.0"}
            )
            
            request_id = await self._extract_request_id(response.text)
            
            if not request_id:
                return {
                    "success": False,
                    "error": "Could not extract request_id",
                    "search_url": search_url
                }
            
            tours = await self._poll_search_results(request_id)
            
            return {
                "success": True,
                "request_id": request_id,
                "tours_count": len(tours),
                "tours": tours[:50],
                "search_url": search_url
            }
            
        except Exception as e:
            logger.error(f"Error searching tours: {str(e)}")
            return {"success": False, "error": str(e)}
    
    async def _extract_request_id(self, html: str) -> Optional[str]:
        """Извлечь request_id из HTML ответа"""
        pattern = r'requestid["\']?\s*[:=]\s*["\']?(\d+)'
        match = re.search(pattern, html)
        if match:
            return match.group(1)
        return None
    
    async def _poll_search_results(self, request_id: str, max_attempts: int = 10) -> List[Dict]:
        """Long polling для получения результатов поиска"""
        await self.ensure_session()
        
        all_tours = []
        last_block = 0
        
        for attempt in range(max_attempts):
            params = {
                "requestid": request_id,
                "lastblock": last_block,
                "referrer": REFERRER,
                "session": self.session
            }
            
            url = f"{SEARCH_URL}/modresult.php?{urlencode(params)}"
            
            try:
                response = await self.http_client.get(url)
                response.raise_for_status()
                data = response.json()
                
                blocks = data.get("data", {}).get("block", [])
                
                if not blocks:
                    break
                
                for block in blocks:
                    last_block = max(last_block, block.get("id", 0))
                    hotels = block.get("hotel", [])
                    
                    for hotel in hotels:
                        tours = hotel.get("tour", [])
                        for tour in tours:
                            tour["hotel_id"] = hotel.get("id")
                            tour["hotel_price"] = hotel.get("price")
                            all_tours.append(tour)
                
                if data.get("data", {}).get("final"):
                    break
                
                await asyncio.sleep(1)
                
            except Exception as e:
                logger.error(f"Error polling results: {str(e)}")
                break
        
        return all_tours
    
    async def find_country(self, query: str) -> Dict[str, Any]:
        """Найти страну по названию"""
        if not self.dictionary:
            await self.load_dictionary()
        
        countries = self.dictionary.get("lists", {}).get("allcountry", {}).get("country", [])
        query_lower = query.lower()
        
        found = [
            c for c in countries 
            if query_lower in c.get("name", "").lower()
        ]
        
        return {
            "success": True,
            "query": query,
            "found_count": len(found),
            "countries": found
        }
    
    async def find_region(self, country_id: int, query: str) -> Dict[str, Any]:
        """Найти регион в стране"""
        if not self.dictionary:
            await self.load_dictionary()
        
        regions = self.dictionary.get("lists", {}).get("regions", {}).get("region", [])
        query_lower = query.lower()
        
        found = [
            r for r in regions 
            if r.get("country") == country_id and query_lower in r.get("name", "").lower()
        ]
        
        return {
            "success": True,
            "country_id": country_id,
            "query": query,
            "found_count": len(found),
            "regions": found
        }
    
    async def get_popular_countries(self) -> Dict[str, Any]:
        """Получить популярные страны"""
        if not self.dictionary:
            await self.load_dictionary()
        
        countries = self.dictionary.get("lists", {}).get("allcountry", {}).get("country", [])
        popular = [c for c in countries if c.get("popular") == 1]
        
        return {
            "success": True,
            "popular_count": len(popular),
            "countries": popular
        }
    
    async def run(self):
        """Запуск MCP сервера"""
        async with stdio_server() as (read_stream, write_stream):
            await self.server.run(
                read_stream,
                write_stream,
                self.server.create_initialization_options()
            )


# Тестовый режим
async def test_mode():
    """Тестовый режим для проверки работоспособности без MCP клиента"""
    print("🧪 Тестовый режим MCP сервера")
    print("=" * 60)
    
    mcp = EtoTravelMCP()
    
    # Тест 1: Загрузка справочника
    print("\n1️⃣ Тест: Загрузка справочника...")
    result = await mcp.load_dictionary()
    if result.get("success"):
        print(f"✅ Успешно! Загружено:")
        print(f"   - Источник: {result['stats']['source']}")
        print(f"   - Стран: {result['stats']['countries_count']}")
        print(f"   - Городов вылета: {result['stats']['departures_count']}")
        print(f"   - Регионов: {result['stats']['regions_count']}")
    else:
        print(f"❌ Ошибка: {result.get('error')}")
    
    # Тест 2: Поиск страны
    print("\n2️⃣ Тест: Поиск страны 'Египет'...")
    result = await mcp.find_country("Египет")
    if result.get("success") and result.get("found_count") > 0:
        country = result["countries"][0]
        print(f"✅ Найдено! ID: {country['id']}, Название: {country['name']}")
    else:
        print(f"❌ Не найдено")
    
    # Тест 3: Популярные страны
    print("\n3️⃣ Тест: Получение популярных стран...")
    result = await mcp.get_popular_countries()
    if result.get("success"):
        print(f"✅ Успешно! Найдено {result['popular_count']} популярных стран:")
        for country in result["countries"][:5]:
            print(f"   - {country['name']} (ID: {country['id']})")
    else:
        print(f"❌ Ошибка")
    
    # Тест 4: Типы отелей
    print("\n4️⃣ Тест: Получение типов отелей для Египта...")
    result = await mcp.get_hotel_types(1)  # 1 = Египет
    if result.get("success"):
        print(f"✅ Успешно! Доступные типы:")
        for hotel_type in result.get("hotel_types", [])[:5]:
            print(f"   - {hotel_type['name']} (ID: {hotel_type['id']})")
    else:
        print(f"❌ Ошибка: {result.get('error')}")
    
    print("\n" + "=" * 60)
    print("✨ Все тесты завершены!")
    print("\n💡 Для запуска в MCP режиме:")
    print("   python mcp_server.py")
    print("\n💡 И подключи к Cursor через настройки MCP")
    
    await mcp.http_client.aclose()


async def main():
    """Главная функция"""
    # Проверяем режим запуска
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        # Тестовый режим
        await test_mode()
    else:
        # Обычный MCP режим
        logger.info("🚀 Запуск MCP сервера...")
        logger.info("📡 Ожидание подключения от Cursor/Claude...")
        logger.info("💡 Для тестирования используй: python mcp_server.py --test")
        
        mcp = EtoTravelMCP()
        await mcp.run()


if __name__ == "__main__":
    asyncio.run(main())