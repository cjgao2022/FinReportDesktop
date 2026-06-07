@echo off
chcp 65001 >nul
echo ============================================
echo  财报下载器 — 打包脚本
echo ============================================
echo.

:: 检查 Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Python，请先安装 Python 3.8+
    pause
    exit /b 1
)

:: 安装依赖
echo [1/3] 安装依赖...
pip install requests pyinstaller -q
if errorlevel 1 (
    echo [错误] 依赖安装失败
    pause
    exit /b 1
)

:: 打包
echo [2/3] 打包中（首次约需 1-2 分钟）...
pyinstaller ^
    --onefile ^
    --noconsole ^
    --name 财报下载器 ^
    --clean ^
    main.py

if errorlevel 1 (
    echo [错误] 打包失败，请查看上方错误信息
    pause
    exit /b 1
)

echo.
echo [3/3] 打包成功！
echo 可执行文件位置：dist\财报下载器.exe
echo.
pause
