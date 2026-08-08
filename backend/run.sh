#!/bin/bash
# F&O Sniper Scanner - Run Commands

echo "=== F&O Sniper Scanner v3.0 ==="
echo ""

# 1. Setup
echo "[1/6] Installing dependencies..."
pip install -r requirements.txt

# 2. Database
echo "[2/6] Setting up PostgreSQL..."
# Create DB manually: createdb fno_sniper
python manage.py migrate

# 3. Seed stocks
echo "[3/6] Seeding NSE F&O stocks..."
python manage.py shell < seed_stocks.py

# 4. Create superuser (optional)
echo "[4/6] Create superuser? (y/n)"
read -r response
if [[ "$response" =~ ^([yY][eE][sS]|[yY])$ ]]; then
    python manage.py createsuperuser
fi

# 5. Start services
echo "[5/6] Starting Redis..."
redis-server --daemonize yes

echo "[6/6] Starting Celery worker + beat..."
celery -A fno_sniper worker -l info --detach
celery -A fno_sniper beat -l info --detach

echo ""
echo "=== Starting Django ASGI server ==="
echo "WebSocket: ws://localhost:8000/ws/screener/"
echo "API: http://localhost:8000/api/"
echo "Admin: http://localhost:8000/admin/"
echo ""
python -m uvicorn fno_sniper.asgi:application --host 0.0.0.0 --port 8000 --reload
