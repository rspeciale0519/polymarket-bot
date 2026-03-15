#!/bin/bash
set -e

echo "=== PolyBot Setup ==="
echo ""

# 1. Check prerequisites
echo "[1/6] Checking prerequisites..."
command -v python3 >/dev/null 2>&1 || { echo "Python 3 required"; exit 1; }
command -v node >/dev/null 2>&1 || { echo "Node.js required"; exit 1; }
command -v docker >/dev/null 2>&1 || { echo "Docker required for PostgreSQL"; exit 1; }
echo "  OK: python3, node, docker found"

# 2. Start PostgreSQL
echo "[2/6] Starting PostgreSQL..."
docker compose up -d postgres
echo "  Waiting for database to be ready..."
sleep 3

# 3. Install Python dependencies
echo "[3/6] Installing Python dependencies..."
python3 -m pip install --user --break-system-packages -q -r engine/requirements.txt
echo "  OK"

# 4. Install dashboard dependencies
echo "[4/6] Installing dashboard dependencies..."
cd dashboard
npm install --silent
echo "  OK"

# 5. Setup environment files
echo "[5/6] Setting up environment files..."
if [ ! -f .env ]; then
  cp .env.example .env
  echo "  Created dashboard/.env from template"
else
  echo "  dashboard/.env already exists"
fi
cd ..

if [ ! -f engine/.env ]; then
  cp engine/.env.example engine/.env
  echo "  Created engine/.env from template"
else
  echo "  engine/.env already exists"
fi

# 6. Run Prisma migration
echo "[6/6] Running database migration..."
cd dashboard
npx prisma db push --accept-data-loss 2>/dev/null || npx prisma db push
echo "  OK: Database schema applied"
cd ..

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Next steps:"
echo "  1. Edit engine/.env with your Kalshi API key and Telegram tokens"
echo "  2. Edit dashboard/.env if needed (DATABASE_URL)"
echo "  3. Start the engine:    python3 -m engine.main"
echo "  4. Start the dashboard: cd dashboard && npm run dev"
echo ""
