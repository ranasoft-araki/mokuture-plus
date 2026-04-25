@echo off
REM deploy.bat — mokuture+ Windows用デプロイバッチ
REM ダブルクリック or コマンドプロンプトから実行
REM 使い方: deploy.bat [コミットメッセージ]

chcp 65001 > nul
setlocal

set "REPO=%~dp0"

echo ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo   mokuture+ デプロイ
echo ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

REM コミットメッセージ
if "%~1"=="" (
    for /f "tokens=1-5 delims=/ " %%a in ('date /t') do set TODAY=%%a-%%b-%%c
    for /f "tokens=1-2 delims=: " %%a in ('time /t') do set NOW=%%a:%%b
    set MSG=deploy: %TODAY% %NOW%
) else (
    set MSG=%~1
)

echo.
echo [1/3] 変更ファイルを確認
git -C "%REPO%" status --short
echo.

REM 変更があるか確認
git -C "%REPO%" status --porcelain > tmp_status.txt
for %%A in (tmp_status.txt) do if %%~zA==0 (
    echo 変更がありません。スキップします。
    del tmp_status.txt
    goto :end
)
del tmp_status.txt

echo [2/3] コミット
git -C "%REPO%" add -A
git -C "%REPO%" commit -m "%MSG%"
if errorlevel 1 (
    echo コミットに失敗しました。
    goto :error
)
echo コミット完了: %MSG%

echo.
echo [3/3] プッシュ
git -C "%REPO%" push origin master
if errorlevel 1 (
    echo プッシュに失敗しました。認証情報を確認してください。
    goto :error
)

echo.
echo ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
echo   デプロイ完了！ ビルドが開始されます。
echo.
echo   Frontend: https://mokuture-plus.netlify.app
echo   Backend:  https://mokuture-plus-api.onrender.com
echo ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
goto :end

:error
echo.
echo エラーが発生しました。上記のメッセージを確認してください。
pause
exit /b 1

:end
pause
