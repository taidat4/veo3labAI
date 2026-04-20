# UltraFlow AI — Video Generation Platform

> Pure HTTP architecture — Backend FastAPI + Frontend Next.js 16

## Quick Start

### Option 1: Double-click
```
start.bat
```

### Option 2: Terminal
```bash
npm run start:all
```

### Option 3: Manual
```bash
# Terminal 1 — Backend
cd backend
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# Terminal 2 — Frontend
npx next dev --port 3000
```

## URLs
| Service  | URL |
|----------|-----|
| Frontend | http://localhost:3000 |
| Backend  | http://localhost:8000 |
| API Docs | http://localhost:8000/docs |

## Default Login
- **Username:** `admin`
- **Password:** `admin123`

## Project Structure
```
Veo3-FlowSever/
├── backend/              # Python FastAPI Backend
│   ├── app/
│   │   ├── main.py       # FastAPI app entry
│   │   ├── auth.py       # JWT auth
│   │   ├── models.py     # SQLAlchemy models
│   │   ├── database.py   # DB + FakeRedis
│   │   ├── config.py     # Settings (.env)
│   │   ├── schemas.py    # Pydantic schemas
│   │   └── routes/       # API endpoints
│   ├── .env              # Backend config
│   └── requirements.txt  # Python deps
├── src/                  # Next.js Frontend
│   ├── app/              # Pages (login, dashboard, etc.)
│   ├── components/       # UI components
│   └── lib/              # API client, store, WebSocket
├── package.json          # Node deps + scripts
├── start.bat             # One-click launcher
└── .env.local            # Frontend config
```

## Tech Stack
- **Backend:** Python 3.12, FastAPI, SQLAlchemy 2.0, SQLite, JWT
- **Frontend:** Next.js 16, React 19, Zustand, TailwindCSS 4
