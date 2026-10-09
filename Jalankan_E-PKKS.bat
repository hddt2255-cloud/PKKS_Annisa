@echo off
title Sistem E-PKKS SDIT An Nisa 2026
cd /d "%~dp0"
echo =========================================================
echo   MEMBUKA SISTEM E-PKKS SDIT AN NISA 2026...
echo   URL: http://localhost:8001
echo =========================================================
echo.
start "" http://localhost:8001
python server.py 8001
pause
