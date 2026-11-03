@echo off
REM Runs WASTEX without Docker, using the embedded Kafka-compatible broker.
call "%~dp0start.bat" --embedded
