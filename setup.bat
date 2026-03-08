@echo off
echo ============================================================
echo   Crypto Investigator — Setup
echo ============================================================
echo.

:: Check Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Python is not installed or not in PATH.
    echo Download it from https://www.python.org/downloads/
    echo IMPORTANT: Check "Add Python to PATH" during install.
    pause
    exit /b 1
)

echo [1/3] Python found:
python --version
echo.

:: Check .env exists
if not exist ".env" (
    echo ERROR: No .env file found!
    echo.
    echo What to do:
    echo   1. Find the file called ".env.example" in this folder
    echo   2. Make a copy of it
    echo   3. Rename the copy to ".env"  (just .env, no other extension)
    echo   4. Open .env in Notepad and fill in your credentials
    echo   5. Run this script again
    echo.
    echo Read README.md for detailed instructions on getting credentials.
    pause
    exit /b 1
)

echo [2/3] Installing Python packages...
echo      (this may take a minute)
echo.
pip install -r requirements.txt >nul 2>&1
if %errorlevel% neq 0 (
    echo WARNING: Some packages may have failed. Trying with --user flag...
    pip install --user -r requirements.txt
)
echo      Done.
echo.

echo [3/3] Checking connections...
echo.
python setup_check.py
echo.

if %errorlevel% equ 0 (
    echo ============================================================
    echo   Ready! To start the API server, run:
    echo.
    echo   uvicorn apps.api.main:app --reload --port 8000
    echo.
    echo   Then open http://localhost:8000/health in your browser.
    echo ============================================================
) else (
    echo ============================================================
    echo   Some connections failed. Fix them and run setup.bat again.
    echo   See README.md for help.
    echo ============================================================
)

pause
