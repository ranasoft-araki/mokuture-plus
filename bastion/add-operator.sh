#!/bin/bash
# 踏み台を使える運営の人を足す・鍵を差し替える・外す。踏み台で管理者として動かす。
#
#   sudo bash add-operator.sh yamada "ssh-ed25519 AAAAC3... yamada@pc"
#   sudo bash add-operator.sh --remove yamada
#
# 足した人ができるのは、踏み台の上の転送口へ中継してもらうこと(ssh -J)だけ。踏み台にシェルは無い。
# 端末に入るには、同じ公開鍵を kiosk_agent/system/operator_keys にも書いて配信する必要がある。
set -euo pipefail

[ "$(id -u)" = "0" ] || { echo "管理者で動かす: sudo bash add-operator.sh ..."; exit 1; }
CONF=/etc/mokuture-bastion
OP_GROUP=mokuture-operators
[ -d "$CONF/operators" ] || { echo "先に setup.sh を動かす"; exit 1; }

valid_name() { printf '%s' "$1" | grep -Eq '^[a-z][a-z0-9-]{1,30}$'; }
is_operator() { id -nG "$1" 2>/dev/null | tr ' ' '\n' | grep -qx "$OP_GROUP"; }

if [ "${1:-}" = "--remove" ]; then
    name="${2:-}"
    valid_name "$name" || { echo "名前は英小文字で始まる 2〜31 文字(英小文字・数字・-)"; exit 1; }
    is_operator "$name" || { echo "運営の利用者ではない: $name"; exit 1; }
    rm -f "$CONF/operators/$name"
    pkill -KILL -u "$name" 2>/dev/null || true   # つないでいる最中なら切る
    userdel "$name"
    echo "外した: $name"
    echo "端末側の鍵(kiosk_agent/system/operator_keys)からも、その人の行を消して配信する。"
    exit 0
fi

name="${1:-}"; key="${2:-}"
valid_name "$name" || { echo "名前は英小文字で始まる 2〜31 文字(英小文字・数字・-)"; exit 1; }
# 公開鍵は「種類 本体 [コメント]」。本体までを使い、前に付くオプションは受け付けない
type=$(printf '%s' "$key" | awk '{print $1}')
body=$(printf '%s' "$key" | awk '{print $2}')
case "$type" in
    ssh-ed25519|ecdsa-sha2-nistp256|ecdsa-sha2-nistp384|ecdsa-sha2-nistp521|ssh-rsa) ;;
    sk-ssh-ed25519@openssh.com|sk-ecdsa-sha2-nistp256@openssh.com) ;;
    *) echo "公開鍵(.pub の中身の 1 行)を \"\" で囲んで渡す"; exit 1 ;;
esac
printf '%s' "$body" | grep -Eq '^[A-Za-z0-9+/]+=*$' || { echo "公開鍵の形がおかしい"; exit 1; }
tmp=$(mktemp)
trap 'rm -f "$tmp"' EXIT
printf '%s %s %s\n' "$type" "$body" "$name" > "$tmp"
ssh-keygen -l -f "$tmp" >/dev/null || { echo "公開鍵として読めない"; exit 1; }

if id "$name" >/dev/null 2>&1; then
    is_operator "$name" || { echo "同じ名前の、運営ではない利用者がいる: $name"; exit 1; }
else
    useradd --no-create-home --shell /usr/sbin/nologin --gid "$OP_GROUP" "$name"
    usermod -p '*' "$name"
fi
install -o root -g root -m 644 "$tmp" "$CONF/operators/$name"
echo "足した: $name ($(ssh-keygen -l -f "$CONF/operators/$name" | awk '{print $2}'))"
echo "端末に入るには、同じ公開鍵を kiosk_agent/system/operator_keys にも書いて配信する。"
