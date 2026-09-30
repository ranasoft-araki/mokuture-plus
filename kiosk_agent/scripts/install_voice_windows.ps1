# mokuture+ 声で操作する — Windows 開発機での動作試験セットアップ
#
# 【このファイルは UTF-8 BOM 付きで保存すること】
# Windows PowerShell 5.1 は BOM が無いと .ps1 をシステムの ANSI コードページ(日本語環境は
# cp932)として読むため、日本語コメントが化けて構文エラーになる。pwsh 7 は BOM 無しでも
# UTF-8 として読むので、7 でだけ確認していると気づけない。
#
#   powershell -ExecutionPolicy Bypass -File scripts\install_voice_windows.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\install_voice_windows.ps1 -NoMic
#
# 本番(Raspberry Pi)は scripts/install_voice.sh。こちらは**動作試験専用**。
#
# やること:
#   1. モデルが揃っているか確認(Git LFS のポインタのままなら教える)
#   2. マイクを使うための sounddevice と、Vosk を venv へ入れる
#   3. voice_input.yaml を雛形から作る
#
# ネットワークを使うのは 2 だけ。以後の認識は完全にオフラインで動く。

param(
    [switch]$NoMic,      # マイクを使わない(WAV での試験だけ行う)
    [switch]$Force       # 取得済みでも入れ直す
)

$ErrorActionPreference = "Stop"

function Invoke-Native {
    <#
      外部コマンドを実行する。

      $ErrorActionPreference='Stop' のままネイティブコマンドを呼ぶと、そのコマンドが
      stderr へ 1 行でも書いた時点で NativeCommandError となり、成功していても止まる
      （uv の進捗表示などが該当する）。
      ここだけ既定に戻して実行し、成否は $LASTEXITCODE で判断する。
    #>
    param([Parameter(Mandatory = $true)][scriptblock]$Command)
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try { & $Command } finally { $ErrorActionPreference = $prev }
}

$AgentDir = Split-Path -Parent $PSScriptRoot
$Venv     = Join-Path $AgentDir ".venv"
$Python   = Join-Path $Venv "Scripts\python.exe"
Write-Host "=== mokuture+ 声で操作する (Windows 動作試験) ===" -ForegroundColor Cyan
Write-Host "ディレクトリ: $AgentDir"

if (-not (Test-Path $Python)) {
    Write-Host "venv が見つかりません: $Python" -ForegroundColor Red
    Write-Host "先にキオスクエージェントの依存を入れてください (uv sync など)"
    exit 1
}

# ── 1. モデルの確認 ───────────────────────────────────────────────────────────
Write-Host ""
Write-Host "--- モデルの確認 ---"
Invoke-Native { & $Python (Join-Path $AgentDir "scripts\fetch_voice_models.py") --check }
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "モデルが揃っていません。まず次を試してください:" -ForegroundColor Yellow
    Write-Host "    git lfs pull"
    Write-Host "それでも駄目なら取得し直します:"
    Write-Host "    $Python scripts\fetch_voice_models.py"
    exit 1
}

# ── 2. マイク(sounddevice) ────────────────────────────────────────────────────
Write-Host ""
Write-Host "--- マイク ---"
if ($NoMic) {
    Write-Host "スキップしました (-NoMic)。WAV を使う試験だけ行えます。"
} else {
    Invoke-Native { & $Python -c "import sounddevice" 2>$null }
    if (($LASTEXITCODE -eq 0) -and (-not $Force)) {
        Write-Host "sounddevice は導入済み"
    } else {
        # uv があればそちら、無ければ pip
        $uv = Get-Command uv -ErrorAction SilentlyContinue
        if ($uv) {
            Invoke-Native { & uv pip install --python $Python sounddevice }
        } else {
            Invoke-Native { & $Python -m pip install sounddevice }
        }
        if ($LASTEXITCODE -ne 0) {
            Write-Host "sounddevice を入れられませんでした。WAV を使う試験だけ行えます。" -ForegroundColor Yellow
        }
    }
}

# ── 2-2. Vosk ─────────────────────────────────────────────────────────────────
# 声で操作する(画面ごとに語彙を絞って聞き分ける)。
Write-Host ""
Write-Host "--- Vosk ---"
Invoke-Native { & $Python -c "import vosk" 2>$null }
if (($LASTEXITCODE -eq 0) -and (-not $Force)) {
    Write-Host "vosk は導入済み"
} else {
    $uv = Get-Command uv -ErrorAction SilentlyContinue
    if ($uv) {
        Invoke-Native { & uv pip install --python $Python vosk }
    } else {
        Invoke-Native { & $Python -m pip install vosk }
    }
    if ($LASTEXITCODE -ne 0) {
        Write-Host "vosk を入れられませんでした。声で操作するは使えません。" -ForegroundColor Yellow
    }
}

$VoskModel = Join-Path $AgentDir "voice_models\vosk-model-small-ja-0.22"
if (Test-Path $VoskModel) {
    Write-Host "モデルは展開済み"
} else {
    Invoke-Native { & $Python (Join-Path $AgentDir "scripts\fetch_voice_models.py") --extract }
    if ($LASTEXITCODE -ne 0) {
        Write-Host "モデルを展開できませんでした。" -ForegroundColor Yellow
    }
}

# ── 3. 設定ファイル ───────────────────────────────────────────────────────────
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
Invoke-Native { & $Python (Join-Path $AgentDir "scripts\voice_selftest.py") --status }
Write-Host ""
Write-Host "試し方:"
Write-Host "  読み上げ音で試す : $Python scripts\voice_selftest.py --say `"ロッカー`" --screen top"
Write-Host "  マイクで試す     : $Python scripts\voice_selftest.py --mic --screen top"
Write-Host "  入力デバイス一覧 : $Python scripts\voice_selftest.py --devices"
Write-Host ""
Write-Host "画面から試す(手順は VOICE_COMMAND.md):"
Write-Host "  1) 音声サービス : $Python -m voice.server"
Write-Host "  2) キオスク本体 : uv run uvicorn main:app --host 0.0.0.0 --port 8080"
Write-Host "  3) ブラウザで http://localhost:8080 を開き、下部の帯の「声で操作する」を押す"
