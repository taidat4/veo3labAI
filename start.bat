@echo off
title UltraFlow AI - Starting...
color 0A

echo.
echo  ╔══════════════════════════════════════╗
echo  ║       UltraFlow AI Platform          ║
echo  ║   Backend (FastAPI) + Frontend (Next) ║
echo  ╚══════════════════════════════════════╝
echo.

:: Check Python
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Python not found! Install Python 3.12+
    pause
    exit /b 1
)

:: Check Node
where node >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Node.js not found! Install Node.js 20+
    pause
    exit /b 1
)

:: Install backend deps if needed
if not exist "backend\venv" (
    echo [SETUP] Creating Python virtual environment...
    cd backend
    python -m venv venv
    call venv\Scripts\activate.bat
    pip install -r requirements.txt -q
    cd ..
    echo [OK] Backend dependencies installed
) else (
    echo [OK] Backend venv found
)

:: Install frontend deps if needed
if not exist "node_modules" (
    echo [SETUP] Installing frontend dependencies...
    npm install
    echo [OK] Frontend dependencies installed
) else (
    echo [OK] Frontend node_modules found
)

echo.
echo  Starting servers...
echo  [Backend]  http://localhost:8000  (FastAPI + Swagger: /docs)
echo  [Frontend] http://localhost:3000  (UltraFlow AI)
echo.
echo  Press Ctrl+C to stop both servers.
echo.

:: Run both concurrently
npx concurrently -n "BACKEND,FRONTEND" -c "yellow,cyan" "cd backend && python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload" "npx next dev --port 3000"
