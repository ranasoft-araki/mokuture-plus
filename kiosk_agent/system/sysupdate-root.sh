#!/bin/bash
# mokuture+ システム更新(管理者権限で動く側)。
#
# OTA はエージェントの利用者権限でファイルを置き換えるだけなので、OS の設定変更・
# apt のパッケージ・systemd の定義は届けられない。ここがそれを受け持つ。
#
# 管理者権限で動かすのは「署名を確かめられたもの」だけ:
#   1. 配信された SYSTEM_MANIFEST の署名を、この端末に置いた公開鍵で確かめる
#      (秘密鍵は開発機にだけある。GitHub や配信サーバーが乗っ取られても署名は作れない)
#   2. 一覧にあるファイルを管理者しか書けない場所へ写し、ハッシュが一覧と合うか確かめる
#      (確かめたあとで差し替えられないように、写しのほうを実行する)
#   3. 連番(SERIAL)が、これまでに確かめた中でいちばん新しい版より進んでいるか確かめる
#      (古い署名済みの版を再び流されない。同じ版のやり直しだけは通す)
#   4. 写した apply.sh を実行する
#
# エージェントの置き場所(AGENT_DIR)は、エージェントの利用者が好きに書き換えられる。
# そこにあるものを**管理者として開かない**(リンクの先を読まされる・終わらない読み込みで
# 止められる・大きなファイルでディスクを埋められる、を避ける)。読むのはエージェントの
# 利用者として、大きさと時間の上限つきで行い、正しさは署名とハッシュで確かめる。
#
# このファイルは /usr/local/lib/mokuture/ に置いた写しが動く(置くのは install.sh)。
# リポジトリの中のこのファイルを書き換えても、署名が無ければ端末には反映されない。
set -u
umask 022

PREFIX=""
TESTING=0
if [ "$(id -u)" != "0" ]; then
    # 試験用(tests/test_system_update.py): 管理者でない利用者が、別の場所を / の代わりにして
    # 確かめる手順だけを動かす。管理者で動くとき(本番)はこの変数を見ない。
    if [ -z "${SYSUPDATE_TEST_ROOT:-}" ]; then echo "root で動かすこと"; exit 1; fi
    PREFIX="$SYSUPDATE_TEST_ROOT"
    TESTING=1
fi
CONF="$PREFIX/etc/mokuture/sysupdate.conf"
SIGNERS="$PREFIX/etc/mokuture/allowed_signers"
STATE_DIR="$PREFIX/var/lib/mokuture"
IDENTITY=mokuture-sysupdate
NAMESPACE=mokuture-sysupdate
RETRY_AFTER_SEC=3600     # apply.sh が失敗した版をやり直すまでの間隔
MAX_BYTES=1048576        # 取り込むファイル 1 つの上限
READ_TIMEOUT=30

if [ ! -r "$CONF" ]; then echo "$CONF が無い(install.sh を実行する)"; exit 1; fi
# shellcheck disable=SC1090
. "$CONF"   # AGENT_DIR / AGENT_USER / VENV (root だけが書ける)
: "${AGENT_DIR:?}" "${AGENT_USER:?}" "${VENV:?}"
if [ "$TESTING" = "0" ]; then
    agent_uid=$(id -u "$AGENT_USER" 2>/dev/null) || { echo "利用者 $AGENT_USER がいない"; exit 1; }
    # エージェントを管理者として動かす設定では、署名の無いもの(pip が読む pyproject.toml)
    # まで管理者権限で動いてしまう。その設定では何もしない。
    if [ "$agent_uid" = "0" ]; then echo "AGENT_USER が管理者になっている。何もしない"; exit 1; fi
fi

mkdir -p "$STATE_DIR"
if command -v flock >/dev/null 2>&1; then
    exec 9>"$STATE_DIR/lock"
    flock -n 9 || exit 0   # 前の回がまだ動いている
fi
rm -rf "$STATE_DIR"/stage.*   # 前の回が途中で止められたときの残り

STAGE=$(mktemp -d "$STATE_DIR/stage.XXXXXX") || exit 1
trap 'rm -rf "$STAGE"' EXIT

write_status() {   # write_status <state> <version> <serial> <message>
    printf '{"state":"%s","version":"%s","serial":%s,"at":"%s","message":"%s"}\n' \
        "$1" "$2" "${3:-0}" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$4" > "$STATE_DIR/sysupdate.status.tmp" \
        && chmod 644 "$STATE_DIR/sysupdate.status.tmp" \
        && mv "$STATE_DIR/sysupdate.status.tmp" "$STATE_DIR/sysupdate.status"
}

# AGENT_DIR のファイルを、エージェントの利用者として・上限つきで読んで写す。
# 上限を超えた・読めなかった・時間切れは失敗。
fetch() {   # fetch <AGENT_DIR からの相対パス> <写す先>
    local src="$AGENT_DIR/$1" dst="$2" size
    if [ "$TESTING" = "1" ]; then
        timeout "$READ_TIMEOUT" head -c $((MAX_BYTES + 1)) -- "$src" > "$dst" 2>/dev/null || return 1
    else
        runuser -u "$AGENT_USER" -- timeout "$READ_TIMEOUT" head -c $((MAX_BYTES + 1)) -- "$src" \
            > "$dst" 2>/dev/null 9>&- || return 1
    fi
    size=$(stat -c %s "$dst" 2>/dev/null || echo $((MAX_BYTES + 1)))
    [ "$size" -le "$MAX_BYTES" ]
}

if ! fetch system/SYSTEM_MANIFEST "$STAGE/SYSTEM_MANIFEST" \
   || ! fetch system/SYSTEM_MANIFEST.sig "$STAGE/SYSTEM_MANIFEST.sig"; then
    echo "システム更新の一覧がまだ届いていない(または読めない)"
    exit 0
fi

VER=$(sha256sum < "$STAGE/SYSTEM_MANIFEST" | cut -c1-16)
if [ "$VER" = "$(cat "$STATE_DIR/applied.version" 2>/dev/null)" ]; then
    exit 0   # 適用済み
fi
if [ "$VER" = "$(cat "$STATE_DIR/failed.version" 2>/dev/null)" ]; then
    age=$(( $(date +%s) - $(stat -c %Y "$STATE_DIR/failed.version" 2>/dev/null || echo 0) ))
    if [ "$age" -ge 0 ] && [ "$age" -lt "$RETRY_AFTER_SEC" ]; then exit 0; fi
fi

reject() {   # 確かめられなかった。何も実行しない。次の回(10 分後)にまた確かめる
    echo "適用しない: $1"
    write_status rejected "$VER" 0 "$1"
    exit 1
}

command -v ssh-keygen >/dev/null 2>&1 || reject no_verifier
[ -r "$SIGNERS" ] || reject no_public_key
ssh-keygen -Y verify -f "$SIGNERS" -I "$IDENTITY" -n "$NAMESPACE" \
    -s "$STAGE/SYSTEM_MANIFEST.sig" < "$STAGE/SYSTEM_MANIFEST" >/dev/null 2>&1 || reject signature

# 一覧にあるファイルを、管理者しか書けない場所へ写す
mkdir "$STAGE/files"
count=0
while read -r hash rel; do
    [ -z "$hash" ] && [ -z "$rel" ] && continue
    [[ "$hash" =~ ^[0-9a-f]{64}$ ]] || reject manifest_format
    case "$rel" in
        ""|/*|*..*|*[!A-Za-z0-9._/-]*) reject manifest_path ;;
    esac
    mkdir -p "$STAGE/files/$(dirname "$rel")"
    fetch "$rel" "$STAGE/files/$rel" || reject file_missing
    count=$((count + 1))
done < "$STAGE/SYSTEM_MANIFEST"
[ "$count" -gt 0 ] || reject manifest_empty
( cd "$STAGE/files" && sha256sum --check --strict --quiet "$STAGE/SYSTEM_MANIFEST" >/dev/null 2>&1 ) || reject hash_mismatch
[ -f "$STAGE/files/system/apply.sh" ] || reject no_apply_script
[ -f "$STAGE/files/system/SERIAL" ] || reject no_serial

# 連番。これまでに確かめた中でいちばん新しい版(floor)より進んでいる版だけを通す。
# floor は「実行する前」に進める(失敗させ続けて連番を止め、古い版を流し直す手を塞ぐ)。
# 同じ連番を通すのは、floor と同じ版のやり直しのときだけ。
SERIAL=$(tr -cd '0-9' < "$STAGE/files/system/SERIAL" | head -c 9)
[ -n "$SERIAL" ] || reject no_serial
SERIAL=$((10#$SERIAL))
FLOOR=$(tr -cd '0-9' < "$STATE_DIR/floor.serial" 2>/dev/null | head -c 9)
FLOOR=$((10#${FLOOR:-0}))
if [ "$SERIAL" -gt "$FLOOR" ]; then
    echo "$SERIAL" > "$STATE_DIR/floor.serial"
    echo "$VER" > "$STATE_DIR/floor.version"
elif [ "$SERIAL" -eq "$FLOOR" ] && [ "$VER" = "$(cat "$STATE_DIR/floor.version" 2>/dev/null)" ]; then
    :   # 同じ版のやり直し
else
    reject rollback
fi

chmod -R go-w "$STAGE/files"
echo "システム更新 $VER (連番 $SERIAL) を適用する"
rm -f "$STATE_DIR/apply.failed"
set -o pipefail
# 9>&-: 排他のためのファイルを、apply.sh から先(エージェントの利用者として動く pip など)へ渡さない。
# 記録からは制御文字を落とす(pip の出力にはエージェントの利用者が好きな文字を混ぜられる)。
if AGENT_DIR="$AGENT_DIR" AGENT_USER="$AGENT_USER" VENV="$VENV" STATE_DIR="$STATE_DIR" FILES="$STAGE/files" \
        bash "$STAGE/files/system/apply.sh" 2>&1 9>&- | tr -d '\000-\010\013-\037\177' | tee "$STATE_DIR/sysupdate.log"; then
    echo "$VER" > "$STATE_DIR/applied.version"
    rm -f "$STATE_DIR/failed.version"
    write_status ok "$VER" "$SERIAL" ""
    echo "適用した"
else
    echo "$VER" > "$STATE_DIR/failed.version"
    # 失敗した手順の名前(apply.sh が書く)。英小文字・数字・_ と区切りだけ通す
    steps=$(tr -cd 'a-z0-9_, ' < "$STATE_DIR/apply.failed" 2>/dev/null | head -c 120)
    write_status failed "$VER" "$SERIAL" "${steps:-apply}"
    echo "失敗した(1 時間後にやり直す)。記録: $STATE_DIR/sysupdate.log"
    exit 1
fi
