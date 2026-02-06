import asyncio
import httpx
import re
import uvicorn
import datetime
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.routing import Route

# Импорты чистого MCP SDK
from mcp.server.lowlevel import Server
from mcp.server.sse import SseServerTransport
from mcp.types import Tool, TextContent, EmbeddedResource, ImageContent

# Инициализация сервера
server = Server("eto-travel-agent")

# Заголовки для Tourvisor
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://eto.travel/"
}

# --- Логика парсинга (без изменений) ---
def parse_tourvisor_text(text: str):
    hotels = []
    matches = re.findall(r'\d+\s+name\s+([^,]+),.*?stars\s+(\d+).*?rating\s+([\d\.]+)', text, re.DOTALL)
    seen_names = set()
    for name, stars, rating in matches:
        clean_name = name.strip()
        if clean_name not in seen_names:
            hotels.append({"name": clean_name, "stars": stars, "rating": rating})
            seen_names.add(clean_name)
    return hotels

# --- Регистрация инструментов ---

#https://tourvisor.ru/xml/listdev.php?type=departure,allcountry,country,region,subregions,operator&formmode=0&cndep=1&flydeparture=1&flycountry=47&format=json&referrer=https%3A%2F%2Feto.travel%2Fsearch%2F&session=0e56548e3e4ed302e692f3afc717a163324fe9526f01957108cfe5b656cbbe413ef653bcc317e817c0c4687a2b0536611942eeb3ebbe6bced2264ba434f462a787f83474aa5e2122f03b098cc16f285f024ade46527e24c1542eaa89605d5399ca6a71e337332188e0ad327a9738fa62a5e42c872dc03236bf38e1113686190d38812c51c49a21b662fe9351ad
#

@server.list_tools()
async def handle_list_tools():
    return [
        Tool(
            name="search_tours_eto",
            description="Поиск туров на сайте eto.travel (Турция, Египет и др.)",
            inputSchema={
                "type": "object",
                "properties": {
                    "country_code": {"type": "integer", "description": "ID страны (4=Турция, 1=Египет, 9=ОАЭ)", "default": 4},
                    "nights_from": {"type": "integer", "description": "Минимум ночей", "default": 7},
                    "nights_to": {"type": "integer", "description": "Максимум ночей", "default": 14}
                },
                "required": ["country_code"]
            }
        )
    ]

@server.call_tool()
async def handle_call_tool(name: str, arguments: dict | None) -> list[TextContent | ImageContent | EmbeddedResource]:
    if name != "search_tours_eto":
        raise ValueError(f"Unknown tool: {name}")

    if not arguments:
        arguments = {}

    country_code = arguments.get("country_code", 4)
    nights_from = arguments.get("nights_from", 7)
    nights_to = arguments.get("nights_to", 14)

    # --- Бизнес-логика поиска (перенесена из FastMCP версии) ---
    async with httpx.AsyncClient(headers=HEADERS, timeout=30.0) as client:
        start_date = (datetime.date.today() + datetime.timedelta(days=7)).strftime("%Y-%m-%d")
        end_date = (datetime.date.today() + datetime.timedelta(days=14)).strftime("%Y-%m-%d")
        
        tv_payload = {
             "adultsCount": 2,
             "countryIds": [country_code],
             "departureId": 1, 
             "dateFrom": start_date,
             "dateTo": end_date,
             "nightsFrom": nights_from,
             "nightsTo": nights_to,
        }

        try:
            # 1. Запуск
            print(f"Запускаем поиск для страны {country_code}...")
            resp = await client.post("https://stat.tourvisor.ru/api/v1/searches", json=tv_payload)
            data = resp.json()
            
            request_id = data.get("result", {}).get("requestid")
            if not request_id:
                return [TextContent(type="text", text=f"Ошибка запуска API: {data}")]
            
            print(f"Поиск ID: {request_id}. Ждем 8 сек...")
            await asyncio.sleep(8) # Ждем наполнения
            
            # 2. Получение результатов
            result_url = f"https://search3.tourvisor.ru/modresult.php?requestid={request_id}&referrer=https://eto.travel/"
            result_resp = await client.get(result_url)
            
            # 3. Парсинг
            hotels = parse_tourvisor_text(result_resp.text)
            
            if not hotels:
                 return [TextContent(type="text", text="Туры не найдены (пустой ответ).")]
            
            # Формирование ответа
            output = [f"Найдено {len(hotels)} отелей (Топ-15):"]
            for h in hotels[:15]:
                output.append(f"- {h['name']} {h['stars']}* (Рейтинг: {h['rating']})")
            
            return [TextContent(type="text", text="\n".join(output))]

        except Exception as e:
            return [TextContent(type="text", text=f"Ошибка выполнения: {str(e)}")]

# --- Настройка SSE сервера (Starlette + CORS) ---

# Глобальный транспорт
transport = SseServerTransport("/messages")

async def sse_endpoint(request):
    """Эндпоинт для подключения по SSE (GET)"""
    async with transport.connect_sse(request.scope, request.receive, request._send) as streams:
        read_stream, write_stream = streams
        # Запускаем сервер с этим потоком
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options()
        )

async def messages_endpoint(request):
    """Эндпоинт для отправки сообщений (POST)"""
    await transport.handle_post_message(request.scope, request.receive, request._send)

if __name__ == "__main__":
    middleware = [
        Middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
        )
    ]

    app = Starlette(
        routes=[
            Route("/sse", endpoint=sse_endpoint, methods=["GET"]),
            Route("/messages", endpoint=messages_endpoint, methods=["POST"]),
        ],
        middleware=middleware
    )

    uvicorn.run(app)