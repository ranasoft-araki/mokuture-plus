@echo off
rem ============================================================
rem  Start the kiosk on this PC (voice service + kiosk agent + browser).
rem  Usage: double-click, or "kiosk-local.bat nobrowser" to skip the browser.
rem  Stop : close the two windows titled "mokuture voice" / "mokuture kiosk".
rem  Docs : CLAUDE.md "ローカル起動", kiosk_agent\VOICE_COMMAND.md section 8
rem ============================================================
chcp 65001 >nul
setlocal

rem This file works from the repo root or from the folder above it.
set "AGENT=%~dp0kiosk_agent"
if not exist "%AGENT%\main.py" set "AGENT=%~dp0mokuture\kiosk_agent"
if not exist "%AGENT%\main.py" goto no_agent

set "PY=%AGENT%\.venv\Scripts\python.exe"
if not exist "%PY%" goto no_venv
if not exist "%AGENT%\.env" goto no_env

rem --- 1) voice service (127.0.0.1:8181) ---
netstat -ano | findstr /R /C:":8181 .*LISTENING" >nul
if not errorlevel 1 goto voice_running
echo [1/3] 音声サービスを起動します - 8181
start "mokuture voice (8181)" /D "%AGENT%" cmd /k ""%PY%" -m voice.server"
goto voice_done
:voice_running
echo [1/3] 音声サービスは起動済みです - 8181
:voice_done

rem --- 2) kiosk agent (127.0.0.1:8080) ---
netstat -ano | findstr /R /C:":8080 .*LISTENING" >nul
if not errorlevel 1 goto kiosk_running
echo [2/3] キオスク本体を起動します - 8080
start "mokuture kiosk (8080)" /D "%AGENT%" cmd /k ""%PY%" -m uvicorn main:app --host 127.0.0.1 --port 8080"
goto kiosk_done
:kiosk_running
echo [2/3] キオスク本体は起動済みです - 8080
echo       設定やプログラムを変えたときは「mokuture kiosk」の窓を閉じてから、もう一度起動してください。
:kiosk_done

rem --- 3) wait for the kiosk agent, then open the browser ---
echo [3/3] キオスク本体の応答を待っています...
set /a TRIES=0
:wait_loop
curl -s -o nul --max-time 2 http://127.0.0.1:8080/
if not errorlevel 1 goto ready
set /a TRIES+=1
if %TRIES% GEQ 60 goto timed_out
ping -n 2 127.0.0.1 >nul
goto wait_loop

:ready
echo.
echo 起動しました: http://localhost:8080
echo 終了するときは「mokuture voice」「mokuture kiosk」の2つの窓を閉じてください。
if /I "%~1"=="nobrowser" goto end
start "" "http://localhost:8080"
goto end

:timed_out
echo.
echo キオスク本体が60秒たっても応答しません。「mokuture kiosk」の窓のエラーを確認してください。
goto fail

:no_agent
echo kiosk_agent フォルダが見つかりません。このファイルは mokuture フォルダか、その1つ上に置いてください。
goto fail

:no_venv
echo kiosk_agent\.venv がありません。kiosk_agent で uv sync を実行してから、もう一度起動してください。
goto fail

:no_env
echo kiosk_agent\.env がありません。.env.example をコピーして TENANT_SLUG などを設定してください。
goto fail

:fail
echo.
pause
endlocal
exit /b 1

:end
endlocal
exit /b 0
