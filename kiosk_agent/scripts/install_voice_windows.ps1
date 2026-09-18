# mokuture+ 音声入力 — Windows 開発機での動作試験セットアップ
#
#   powershell -ExecutionPolicy Bypass -File scripts\install_voice_windows.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\install_voice_windows.ps1 -NoMic
#
# 本番(Raspberry Pi)は scripts/install_voice.sh。こちらは**動作試験専用**で、
# Pi 上でビルドする代わりに上流の配布バイナリ(同じ v1.9.3)を展開する。
#
# やること:
#   1. モデルが揃っているか確認(Git LFS のポインタのままなら教える)
#   2. whisper.cpp の Windows x64 バイナリを取得して vendor\ へ展開(SHA-256 照合)
#   3. マイクを使うための sounddevice を venv へ入れる
#   4. voice_input.yaml を雛形から作る
#
# ネットワークを使うのは 2 と 3 だけ。以後の認識は完全にオフラインで動く。

param(
    [switch]$NoMic,      # マイクを使わない(WAV での試験だけ行う)
    [switch]$Force       # 取得済みでも入れ直す
)

$ErrorActionPreference = "Stop"

$AgentDir = Split-Path -Parent $PSScriptRoot
$Venv     = Join-Path $AgentDir ".venv"
$Python   = Join-Path $Venv "Scripts\python.exe"
$VendorDir = Join-Path $AgentDir "vendor"
$WhisperDir = Join-Path $VendorDir "whisper.cpp-win-x64"
$WhisperExe = Join-Path $WhisperDir "Release\whisper-cli.exe"

# 上流の配布バイナリ。タグ b4938 は v1.9.3 と同じソースから作られたもの
# (vendor\whisper.cpp-1.9.3.tar.gz と版が揃う)。
$ZipUrl  = "https://github.com/ggml-org/whisper.cpp/releases/download/b4938/whisper-bin-x64.zip"
$ZipSha  = "c2a4b60edb11f7e11a9191ffb50929535527d4d91c9903dbe3e554583bbbc63d"
$ZipSize = 8361840

Write-Host "=== mokuture+ 音声入力 (Windows 動作試験) ===" -ForegroundColor Cyan
Write-Host "ディレクトリ: $AgentDir"

if (-not (Test-Path $Python)) {
    Write-Host "venv が見つかりません: $Python" -ForegroundColor Red
    Write-Host "先にキオスクエージェントの依存を入れてください (uv sync など)"
    exit 1
}

# ── 1. モデルの確認 ───────────────────────────────────────────────────────────
Write-Host ""
Write-Host "--- モデルの確認 ---"
& $Python (Join-Path $AgentDir "scripts\fetch_voice_models.py") --check
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "モデルが揃っていません。まず次を試してください:" -ForegroundColor Yellow
    Write-Host "    git lfs pull"
    Write-Host "それでも駄目なら取得し直します:"
    Write-Host "    $Python scripts\fetch_voice_models.py"
    exit 1
}

# ── 2. whisper.cpp の Windows バイナリ ────────────────────────────────────────
Write-Host ""
Write-Host "--- whisper.cpp (Windows x64) ---"
if ((Test-Path $WhisperExe) -and (-not $Force)) {
    Write-Host "取得済み: $WhisperExe"
} else {
    $zip = Join-Path $env:TEMP "whisper-bin-x64.zip"
    Write-Host "取得中: $ZipUrl"
    # 進捗バーを切ると Invoke-WebRequest が体感で10倍ほど速くなる
    $oldProgress = $ProgressPreference
    $ProgressPreference = "SilentlyContinue"
    try {
        Invoke-WebRequest -Uri $ZipUrl -OutFile $zip -UseBasicParsing
    } finally {
        $ProgressPreference = $oldProgress
    }

    $actual = (Get-FileHash -Path $zip -Algorithm SHA256).Hash.ToLower()
    if ($actual -ne $ZipSha) {
        Remove-Item $zip -Force -ErrorAction SilentlyContinue
        Write-Host "SHA-256 が一致しません。壊れたファイルは残しません。" -ForegroundColor Red
        Write-Host "  期待: $ZipSha"
        Write-Host "  実際: $actual"
        exit 1
    }
    $size = (Get-Item $zip).Length
    if ($size -ne $ZipSize) { Write-Host "  (サイズ $size / 想定 $ZipSize)" }

    if (Test-Path $WhisperDir) { Remove-Item $WhisperDir -Recurse -Force }
    New-Item -ItemType Directory -Force -Path $WhisperDir | Out-Null
    Expand-Archive -Path $zip -DestinationPath $WhisperDir -Force
    Remove-Item $zip -Force -ErrorAction SilentlyContinue
    Write-Host "展開しました: $WhisperDir"
}

if (-not (Test-Path $WhisperExe)) {
    Write-Host "whisper-cli.exe が見つかりません。展開に失敗しています。" -ForegroundColor Red
    exit 1
}
& $WhisperExe --version 2>&1 | Select-Object -Last 1 | ForEach-Object { Write-Host "OK: $_" }

# ── 3. マイク(sounddevice) ────────────────────────────────────────────────────
Write-Host ""
Write-Host "--- マイク ---"
if ($NoMic) {
    Write-Host "スキップしました (-NoMic)。WAV を使う試験だけ行えます。"
} else {
    $hasSd = & $Python -c "import importlib.util,sys; sys.exit(0 if importlib.util.find_spec('sounddevice') else 1)"
    if ($LASTEXITCODE -eq 0 -and (-not $Force)) {
        Write-Host "sounddevice は導入済み"
    } else {
        # uv があればそちら、無ければ pip
        $uv = Get-Command uv -ErrorAction SilentlyContinue
        if ($uv) {
            & uv pip install --python $Python sounddevice
        } else {
            & $Python -m pip install sounddevice
        }
        if ($LASTEXITCODE -ne 0) {
            Write-Host "sounddevice を入れられませんでした。WAV を使う試験だけ行えます。" -ForegroundColor Yellow
        }
    }
}

# ── 4. 設定ファイル ───────────────────────────────────────────────────────────
Write-Host ""
Write-Host "--- 設定 ---"
$yaml = Join-Path $AgentDir "voice_input.yaml"
if (-not (Test-Path $yaml)) {
    Copy-Item (Join-Path $AgentDir "voice_input.yaml.example") $yaml
    Write-Host "作成しました: $yaml"
} else {
    Write-Host "既にあります: $yaml"
}

# ── 仕上げ ────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "=== 完了 ===" -ForegroundColor Cyan
Write-Host ""
& $Python (Join-Path $AgentDir "scripts\voice_selftest.py") --status
Write-Host ""
Write-Host "試し方:"
Write-Host "  読み上げ音で1往復 : $Python scripts\voice_selftest.py --say `"株式会社ラナソフトです`" --show-text"
Write-Host "  マイクで1往復     : $Python scripts\voice_selftest.py --mic --show-text"
Write-Host "  入力デバイス一覧  : $Python scripts\voice_selftest.py --devices"
Write-Host ""
Write-Host "画面から試す:"
Write-Host "  1) 音声サービス   : $Python -m voice.server"
Write-Host "  2) キオスク本体   : uv run uvicorn main:app --host 0.0.0.0 --port 8080"
Write-Host "  3) ブラウザで http://localhost:8080 を開き、受付フォームの「音声で入力」"
