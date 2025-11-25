#!/usr/bin/env python3
"""
MCP Server для работы с данными Росреестра
Получение координат и информации об объектах недвижимости по кадастровому номеру
"""

import json
import os
import sys
from typing import Optional
import requests

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

# Конфигурация API (установите через переменные окружения в .mcp.json)
API_URL = os.environ.get('ROSREESTR_API_URL', 'https://rosreestr2coord.yoltash.ru')
API_TOKEN = os.environ.get('ROSREESTR_API_TOKEN', '')  # Обязательно укажите токен!

# Проверка геолокации IP
RU_IP_CHECK_URL = 'https://ipapi.co/json/'


def is_russian_ip() -> bool:
    """Проверяет, является ли текущий IP российским"""
    try:
        response = requests.get(RU_IP_CHECK_URL, timeout=5)
        data = response.json()
        country = data.get('country_code', '').upper()
        return country == 'RU'
    except Exception:
        return False


def get_area_via_api(cadastral_number: str, area_type: int = 1) -> dict:
    """Получает данные через API"""
    if not API_TOKEN:
        return {'error': 'ROSREESTR_API_TOKEN not configured'}
    
    try:
        response = requests.get(
            f"{API_URL}/api/cadastral/{cadastral_number}",
            params={'area_type': area_type},
            headers={
                'Authorization': f'Bearer {API_TOKEN}'
            },
            timeout=60
        )
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        return {'error': str(e)}


def get_area_direct(cadastral_number: str, area_type: int = 1) -> dict:
    """Получает данные напрямую через rosreestr2coord (только из РФ)"""
    try:
        from rosreestr2coord.parser import Area

        area = Area(
            code=cadastral_number,
            area_type=area_type,
            with_log=False,
            timeout=30
        )

        if area.feature:
            return {
                'success': True,
                'data': {
                    'features': [area.feature]
                }
            }
        else:
            return {'error': 'No data found for this cadastral number'}

    except ImportError:
        return {'error': 'rosreestr2coord not installed'}
    except Exception as e:
        return {'error': str(e)}


def get_area(cadastral_number: str, area_type: int = 1, force_api: bool = False) -> dict:
    """
    Получает данные об объекте.
    Автоматически определяет, использовать API или прямой запрос.
    """
    use_api = force_api or not is_russian_ip()

    if use_api:
        return get_area_via_api(cadastral_number, area_type)
    else:
        return get_area_direct(cadastral_number, area_type)


# Создаём MCP сервер
server = Server("rosreestr")


@server.list_tools()
async def list_tools():
    """Список доступных инструментов"""
    return [
        Tool(
            name="get_cadastral_coordinates",
            description="Получить координаты и информацию об объекте недвижимости по кадастровому номеру. "
                       "Возвращает GeoJSON геометрию, адрес, площадь, стоимость и другие данные.",
            inputSchema={
                "type": "object",
                "properties": {
                    "cadastral_number": {
                        "type": "string",
                        "description": "Кадастровый номер (например: 12:05:0101001:1)"
                    },
                    "area_type": {
                        "type": "integer",
                        "description": "Тип объекта: 1-Недвижимость (ЗУ, ОКС), 2-Кадастровое деление, "
                                      "4-Адм.деление, 5-Зоны, 7-Терр.зоны, 15-Комплексы. По умолчанию: 1",
                        "default": 1
                    }
                },
                "required": ["cadastral_number"]
            }
        ),
        Tool(
            name="batch_get_cadastral_coordinates",
            description="Пакетное получение данных для нескольких кадастровых номеров",
            inputSchema={
                "type": "object",
                "properties": {
                    "cadastral_numbers": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Список кадастровых номеров"
                    },
                    "area_type": {
                        "type": "integer",
                        "description": "Тип объекта (см. get_cadastral_coordinates)",
                        "default": 1
                    }
                },
                "required": ["cadastral_numbers"]
            }
        ),
        Tool(
            name="check_ip_location",
            description="Проверить текущую геолокацию IP адреса (для диагностики)",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        )
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict):
    """Обработчик вызовов инструментов"""

    if name == "get_cadastral_coordinates":
        cadastral_number = arguments.get("cadastral_number", "")
        area_type = arguments.get("area_type", 1)

        if not cadastral_number:
            return [TextContent(
                type="text",
                text=json.dumps({"error": "cadastral_number is required"}, ensure_ascii=False)
            )]

        result = get_area(cadastral_number, area_type)

        return [TextContent(
            type="text",
            text=json.dumps(result, ensure_ascii=False, indent=2)
        )]

    elif name == "batch_get_cadastral_coordinates":
        cadastral_numbers = arguments.get("cadastral_numbers", [])
        area_type = arguments.get("area_type", 1)

        if not cadastral_numbers:
            return [TextContent(
                type="text",
                text=json.dumps({"error": "cadastral_numbers array is required"}, ensure_ascii=False)
            )]

        results = []
        for cn in cadastral_numbers:
            response = get_area(cn, area_type)
            results.append(response)

        features = []
        for r in results:
            if r.get('success') and r.get('geojson'):
                features.append(r['geojson'])

        result = {
            "total": len(cadastral_numbers),
            "success_count": sum(1 for r in results if r.get('success')),
            "results": results,
            "geojson": {
                "type": "FeatureCollection",
                "features": features
            }
        }

        return [TextContent(
            type="text",
            text=json.dumps(result, ensure_ascii=False, indent=2)
        )]

    elif name == "check_ip_location":
        try:
            response = requests.get(RU_IP_CHECK_URL, timeout=5)
            data = response.json()
            is_ru = data.get('country_code', '').upper() == 'RU'

            result = {
                "ip": data.get('ip'),
                "country": data.get('country_name'),
                "country_code": data.get('country_code'),
                "city": data.get('city'),
                "is_russian": is_ru,
                "will_use_api": not is_ru
            }
        except Exception as e:
            result = {"error": str(e)}

        return [TextContent(
            type="text",
            text=json.dumps(result, ensure_ascii=False, indent=2)
        )]

    else:
        return [TextContent(
            type="text",
            text=json.dumps({"error": f"Unknown tool: {name}"}, ensure_ascii=False)
        )]


async def main():
    """Запуск сервера"""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options()
        )


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
