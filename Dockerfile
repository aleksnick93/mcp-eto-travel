FROM python:3.10-slim

WORKDIR /app

# Копируем зависимости
COPY requirements.txt .

# Устанавливаем зависимости
RUN pip install --no-cache-dir -r requirements.txt

# Копируем код сервера
COPY mcp_server.py .

# Запускаем сервер
CMD ["python", "mcp_server.py"]