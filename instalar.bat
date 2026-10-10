@echo off
chcp 65001 >nul
title System ERP - Instalador
color 0A

echo ========================================
echo   System ERP - Instalacion Automatica
echo ========================================
echo.

REM Verificar si Python esta instalado
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python no esta instalado o no esta en el PATH.
    echo Descarga Python desde: https://www.python.org/downloads/
    echo Asegurate de marcar "Add Python to PATH" durante la instalacion.
    pause
    exit /b 1
)

for /f "tokens=2" %%i in ('python --version 2^>^&1') do echo [OK] Python %%i detectado.

REM Crear entorno virtual si no existe
if not exist "venv" (
    echo.
    echo [1/5] Creando entorno virtual...
    python -m venv venv
    if %errorlevel% neq 0 (
        echo [ERROR] No se pudo crear el entorno virtual.
        pause
        exit /b 1
    )
    echo [OK] Entorno virtual creado.
) else (
    echo.
    echo [1/5] Entorno virtual ya existe. Omitiendo.
)

REM Activar entorno virtual
echo.
echo [2/5] Activando entorno virtual...
call venv\Scripts\activate.bat
echo [OK] Entorno virtual activado.

REM Instalar dependencias
echo.
echo [3/5] Instalando dependencias...
pip install --upgrade pip >nul 2>&1
pip install django pillow xhtml2pdf
if %errorlevel% neq 0 (
    echo [ERROR] Fallo la instalacion de dependencias.
    pause
    exit /b 1
)
echo [OK] Dependencias instaladas correctamente.

REM Ejecutar migraciones
echo.
echo [4/5] Aplicando migraciones de base de datos...
python manage.py migrate
if %errorlevel% neq 0 (
    echo [ERROR] Fallo la aplicacion de migraciones.
    pause
    exit /b 1
)
echo [OK] Migraciones aplicadas.

REM Recopilar archivos estaticos
echo.
echo [5/5] Recopilando archivos estaticos...
python manage.py collectstatic --noinput >nul 2>&1
echo [OK] Archivos estaticos recopilados.

echo.
echo ========================================
echo   Instalacion completada con exito
echo ========================================
echo.
echo Para iniciar el servidor ejecuta: run.bat
echo.
pause
