@echo off
chcp 65001 >nul
rem ============================================================
rem  AI 资讯每日看板 · 探测数据源
rem  Author: wr
rem  挨个试一遍配置里的源，告诉你哪些能抓、哪些失败、为什么。
rem ============================================================
title AI 日报 - 探测数据源
cd /d "%~dp0"

python src\tools\probe_sources.py --all

echo.
pause
