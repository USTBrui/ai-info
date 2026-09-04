@echo off
chcp 65001 >nul
rem ============================================================
rem  AI 资讯每日看板 · 探测网页源
rem  Author: wr
rem  想加一个没有 RSS 的厂商页面时，用它帮你找出该填什么选择器。
rem
rem  用法（在本目录打开命令行执行）：
rem    python src\tools\probe_html.py --url https://某厂商.com/changelog
rem
rem  直接双击则检查配置里已有的网页源。
rem ============================================================
title AI 日报 - 探测网页源
cd /d "%~dp0"

python src\tools\probe_html.py

echo.
pause
