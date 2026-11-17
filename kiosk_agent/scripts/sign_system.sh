#!/bin/bash
# システム更新(kiosk_agent/system/)に署名する。開発機で動かす。
#
#   bash kiosk_agent/scripts/sign_system.sh
#
# system/apply.sh などを書き換えたら、commit の前に必ず動かす。署名した一覧
# (SYSTEM_MANIFEST と .sig)が配信され、端末は署名を確かめてから実行する。
# 署名し忘れると tests/test_system_update.py が落ちる。
#
# 秘密鍵は ~/.ssh/mokuture_sysupdate (リポジトリの外。別の場所なら SYSUPDATE_KEY)。
# この鍵を持つ人は、全端末で管理者権限の処理を動かせる。リポジトリに入れない・人に渡さない。
# 鍵が無いときだけ、このスクリプトが新しく作る(公開鍵は system/allowed_signers)。
set -euo pipefail

SYSTEM_DIR="$(cd "$(dirname "$0")/../system" && pwd)"
AGENT_DIR="$(dirname "$SYSTEM_DIR")"
KEY="${SYSUPDATE_KEY:-$HOME/.ssh/mokuture_sysupdate}"
IDENTITY=mokuture-sysupdate
NAMESPACE=mokuture-sysupdate

# 署名する(＝端末が管理者権限で信頼する)ファイル。エージェントの置き場所からの相対パス。
# system/SERIAL は必ず最後(下で書き換えるため)。
FILES=(
    system/apply.sh
    system/sysupdate-root.sh
    system/mokuture-sysupdate.service
    system/mokuture-sysupdate.timer
    system/PYPROJECT_SHA
    system/SERIAL
)

cd "$AGENT_DIR"

if [ ! -f "$KEY" ]; then
    if [ -f system/allowed_signers ]; then
        echo "秘密鍵が無い: $KEY" >&2
        echo "公開鍵(system/allowed_signers)はすでにあり、端末はその鍵の署名しか受け付けない。" >&2
        echo "鍵を置いた場所を SYSUPDATE_KEY で指定する。" >&2
        exit 1
    fi
    echo "署名用の鍵を作る: $KEY"
    mkdir -p "$(dirname "$KEY")"
    ssh-keygen -q -t ed25519 -N "" -C "$IDENTITY" -f "$KEY"
fi
if [ ! -f system/allowed_signers ]; then
    printf '%s namespaces="%s" %s\n' "$IDENTITY" "$NAMESPACE" "$(cut -d' ' -f1,2 "$KEY.pub")" > system/allowed_signers
    echo "公開鍵を書いた: system/allowed_signers"
fi

[ -f system/SERIAL ] || echo 0 > system/SERIAL
# ライブラリの一覧(pyproject.toml)そのものは署名しない(管理者権限では読ませない)が、
# 変わったら端末で入れ直す必要がある。ハッシュだけを署名の対象に入れておくと、
# pyproject.toml を変えたときに版が変わり、端末が pip をやり直す。
tr -d '\r' < pyproject.toml | sha256sum | cut -c1-64 > system/PYPROJECT_SHA
for f in "${FILES[@]}"; do
    [ -f "$f" ] || { echo "ファイルが無い: $f" >&2; exit 1; }
    # 端末(Linux)へは LF で届く。CRLF のまま署名するとハッシュが合わない
    if grep -q $'\r' "$f"; then echo "改行が CRLF になっている: $f (LF で保存する)" >&2; exit 1; fi
done

# 中身が前回の署名から変わっていたら連番を上げる(端末は連番が戻る版を受け付けない)
# 「ハッシュ  パス」(空白 2 つ)。Windows の sha256sum は「 *パス」と書くので自分で組み立てる
line() { printf '%s  %s\n' "$(sha256sum "$1" | cut -c1-64)" "$1"; }
body() { for f in "${FILES[@]}"; do [ "$f" = system/SERIAL ] || line "$f"; done; }
old_body=$(grep -v '  system/SERIAL$' system/SYSTEM_MANIFEST 2>/dev/null || true)
if [ "$(body)" != "$old_body" ]; then
    serial=$(( $(tr -cd '0-9' < system/SERIAL) + 1 ))
    echo "$serial" > system/SERIAL
    echo "連番を $serial にした"
fi

{ body; line system/SERIAL; } > system/SYSTEM_MANIFEST
rm -f system/SYSTEM_MANIFEST.sig
ssh-keygen -q -Y sign -f "$KEY" -n "$NAMESPACE" system/SYSTEM_MANIFEST
ssh-keygen -Y verify -f system/allowed_signers -I "$IDENTITY" -n "$NAMESPACE" \
    -s system/SYSTEM_MANIFEST.sig < system/SYSTEM_MANIFEST >/dev/null
echo "署名した: system/SYSTEM_MANIFEST (連番 $(cat system/SERIAL))"
