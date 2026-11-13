@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

set "PY="
if exist "C:\Python312\python.exe" set "PY=C:\Python312\python.exe"
if exist "C:\Python313\python.exe" set "PY=C:\Python313\python.exe"
if exist "%LocalAppData%\Programs\Python\Python312\python.exe" set "PY=%LocalAppData%\Programs\Python\Python312\python.exe"
where python >nul 2>nul && for /f "delims=" %%I in ('where python') do (
  set "PY=%%I"
  goto :found
)
:found
if not defined PY (
  echo 未找到 Python。无法安装开机自动更新任务。
  echo 请先安装 Python 3，然后再运行本脚本。
  pause
  exit /b 1
)

set "CONFIG=%~dp0updater-config.json"
if not exist "%CONFIG%" (
  echo 缺少 updater-config.json，请先根据 updater-config.example.json 填好主页路径。
  pause
  exit /b 2
)

echo 将安装登录时自动启动的任务：BookmarkHomepageFrequentUpdate
"%PY%" "%~dp0update_frequent.py" --config "%CONFIG%" --install-task
echo.
echo 完成后，登录 Windows 会在后台更新高频访问，并在 http://127.0.0.1:8765/ 提供更顺畅的自动刷新。
echo 用 file:// 打开主页也可以：页面会尝试读取本地服务。删除记录会写入主页旁边的 hidden.json。
pause
