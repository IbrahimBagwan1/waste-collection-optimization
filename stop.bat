@echo off
REM Stops the Kafka containers (the Python server stops with Ctrl+C in its window).
cd /d "%~dp0"
docker compose down
