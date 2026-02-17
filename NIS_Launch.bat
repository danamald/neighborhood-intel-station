@echo off
title NIS Launcher
echo ============================================================
echo   NEIGHBORHOOD INTEL STATION - Launcher
echo ============================================================
echo.
echo [1/2] Starting backend server...
start "NIS Backend" /min cmd /k python C:\Users\Danie\intel_station_backend.py
echo       Waiting for backend to come online...
timeout /t 8 /noq >nul
echo [2/2] Opening dashboard...
start "" "C:\Users\Danie\neighborhood-intel-station.html"
echo.
echo Done! Backend is running minimized. 
echo Close the "NIS Backend" window to stop it.
timeout /t 3 /noq >nul
exit
