@echo off
chcp 65001 >nul
title NoteFlow
cd /d "%~dp0"
python app.py
if errorlevel 1 (
  echo.
  echo Не удалось запустить NoteFlow. Проверьте установку Python и библиотек.
  pause
)
