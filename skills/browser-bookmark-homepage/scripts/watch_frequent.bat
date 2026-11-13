@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

set "PY="
if exist "%LocalAppData%\Programs\Python\Python312\python.exe" set "PY=%LocalAppData%\Programs\Python\Python312\python.exe"
if exist "C:\Python312\python.exe" set "PY=C:\Python312\python.exe"
if exist "C:\Python313\python.exe" set "PY=C:\Python313\python.exe"
where py >nul 2>nul && set "PY=py -3"
where python >nul 2>nul && for /f "delims=" %%I in ('where python') do (
  set "PY=%%I"
  goto :found
)
:found
if not defined PY (
  echo 未找到 Python。请先安装 Python 3，或把 python.exe 加入 PATH。
  echo 安装后可重新运行本脚本，启动高频访问自动更新。
  pause
  exit /b 1
)

set "CONFIG=%~dp0updater-config.json"
if not exist "%CONFIG%" (
  echo 未找到 updater-config.json。请先复制一份 updater-config.example.json 并填入主页路径。
  echo 或运行： %PY% update_frequent.py --homepage "你的主页.html" --watch --serve --interval 15
  pause
  exit /b 2
)

set "NAV_UPDATER_LOG=%~dp0updater.log"
echo 正在启动高频访问自动更新（每 15 分钟，并在 127.0.0.1 提供本地服务）...
%PY% "%~dp0update_frequent.py" --config "%CONFIG%" --watch --serve --interval 15
