#!/bin/bash

echo "🚀 Деплой MCP сервера на Railway"
echo "================================"

# Проверка Railway CLI
if ! command -v railway &> /dev/null
then
    echo "❌ Railway CLI не установлен"
    echo "Установи: npm install -g @railway/cli"
    echo "Затем: railway login"
    exit 1
fi

echo "✅ Railway CLI найден"

# Инициализация проекта
echo "📦 Инициализация Railway проекта..."
railway init

# Добавление переменных окружения
echo "🔧 Настройка переменных окружения..."
railway variables set PYTHONUNBUFFERED=1

# Деплой
echo "🚢 Деплой на Railway..."
railway up

echo ""
echo "✨ Деплой завершен!"
echo "📋 Получи URL сервера:"
echo "railway domain"
echo ""
echo "🔗 Добавь URL в настройки Cursor (см. CURSOR_SETUP.md)"