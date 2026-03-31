@echo off
echo =========================================
echo   简历制作系统 - 简化环境检查
echo =========================================
echo.

echo 1. 检查 Node.js...
node --version
if errorlevel 1 echo [错误] Node.js 未安装

echo.
echo 2. 检查 npm...
call npm --version
if errorlevel 1 echo [错误] npm 未安装

echo.
echo 3. 检查项目目录...
if exist backend (
    echo [成功] backend 目录存在
) else (
    echo [错误] backend 目录不存在
)

if exist frontend (
    echo [成功] frontend 目录存在
) else (
    echo [错误] frontend 目录不存在
)

echo.
echo 4. 检查端口...
netstat -ano | findstr ":3001" >nul && echo [警告] 端口3001被占用 || echo [正常] 端口3001可用
netstat -ano | findstr ":8080" >nul && echo [警告] 端口8080被占用 || echo [正常] 端口8080可用

echo.
echo =========================================
echo 检查完成！
pause