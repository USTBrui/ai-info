@echo off
chcp 65001 >nul
rem ============================================================
rem  AI 资讯每日看板 · 一键刷新
rem  Author: wr
rem
rem  双击这个文件：抓一次最新资讯，然后自动打开看板网页。
rem  本文件是 GBK 编码保存的，如果中文显示乱码，用记事本打开后
rem  选择「另存为」，编码选 ANSI，再保存一次即可。
rem ============================================================
title AI 日报 - 一键刷新
cd /d "%~dp0"

rem ---- 检查 Python 装没装 ----
where python >nul 2>nul
if errorlevel 1 (
    echo.
    echo  [错误] 这台电脑上没有找到 Python。
    echo.
    echo  请先去安装：https://www.python.org/downloads/
    echo  安装的时候，一定要勾选 "Add Python to PATH" 选项！
    echo.
    pause
    exit /b 1
)

rem ---- 第一次运行时，顺手装一下辅助库（装不上也没关系）----
python -c "import requests, bs4" >nul 2>nul
if errorlevel 1 (
    echo  第一次运行，正在安装辅助库，大约 10 秒...
    python -m pip install -r requirements.txt --quiet --disable-pip-version-check
)

echo  正在抓取最新资讯，请稍等（半分钟到两分钟）...
echo.
python src\main.py

if errorlevel 1 (
    echo.
    echo  [出错了] 抓取没有成功。
    echo  可以打开「日志\抓取日志.md」看看是哪个源的问题，
    echo  也可以双击「探测数据源.bat」检查各源状态。
    echo.
    pause
    exit /b 1
)

echo.
echo  正在打开看板...
set "PAGE=%~dp0网页\index.html"
if not exist "%PAGE%" (
    echo.
    echo  [提示] 没找到网页文件：
    echo  %PAGE%
    echo  请确认「网页」文件夹还在。
    echo.
    pause
    exit /b 1
)
explorer "%PAGE%"

echo.
echo  完成！看板已经在浏览器里打开了。
echo  这个窗口会在 6 秒后自动关闭。
echo.
timeout /t 6 >nul
exit /b 0
