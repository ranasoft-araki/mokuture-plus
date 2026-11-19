#!/bin/bash
# mokuture+ 遠隔ログインの踏み台サーバーを用意する。借りたばかりの VPS(Ubuntu 24.04 以降の LTS / Debian 12 以降)で
# 管理者として 1 回動かす。やり直しても同じ状態になる。くわしくは README.md。
#
#   sudo bash setup.sh
#   sudo API_URL=https://example.com/api bash setup.sh    # API が別の場所にあるとき
#
# この踏み台がすること:
#   - OpenSSH を 443 番でも待ち受ける(外向きが 80/443 だけの会社からもつなげるように)
#   - 端末用の利用者(mokuture-tunnel): 逆向きの転送口を 1 つ開けるだけ。シェルも、ほかへの転送もできない。
#     鍵はここに置かない。つなぎに来るたびに mokuture+ の API へ「いま通してよい鍵か」を聞く
#     (運営パネルで遠隔ログインを開いている端末だけが通る)
#   - 運営用の利用者(add-operator.sh で足す): この踏み台の上の転送口へ中継してもらえるだけ。シェルは無い
#   - 見回り(1 分ごと): 開いてよい一覧に無い転送口を切る
set -euo pipefail

[ "$(id -u)" = "0" ] || { echo "管理者で動かす: sudo bash setup.sh"; exit 1; }

API_URL="${API_URL:-https://mokuture-plus-api.onrender.com/api}"
API_URL="${API_URL%/}"
SSH_PORT=443
TUNNEL_USER=mokuture-tunnel
AKC_USER=mokuture-akc
OP_GROUP=mokuture-operators
CONF=/etc/mokuture-bastion
DROPIN=/etc/ssh/sshd_config.d/50-mokuture-bastion.conf
PORT_FROM=20000     # API の TUNNEL_PORT_BASE と合わせる
PORT_TO=59999       # TUNNEL_PORT_BASE + TUNNEL_PORT_COUNT - 1

case "$API_URL" in https://*) ;; *) echo "API_URL は https:// で始める: $API_URL"; exit 1 ;; esac
case "$API_URL" in *[!A-Za-z0-9:/._-]*) echo "API_URL に使えない文字がある: $API_URL"; exit 1 ;; esac

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y openssh-server curl iproute2 unattended-upgrades

grep -Eq '^[[:space:]]*Include[[:space:]]+/etc/ssh/sshd_config\.d/' /etc/ssh/sshd_config || {
    echo "/etc/ssh/sshd_config が sshd_config.d を読み込んでいない。この OS には対応していない"; exit 1; }

# ── 利用者 ────────────────────────────────────────────────────────────────
getent group "$OP_GROUP" >/dev/null || groupadd --system "$OP_GROUP"
id "$TUNNEL_USER" >/dev/null 2>&1 || useradd --system --create-home --shell /usr/sbin/nologin "$TUNNEL_USER"
id "$AKC_USER" >/dev/null 2>&1 || useradd --system --no-create-home --shell /usr/sbin/nologin "$AKC_USER"
# パスワードでは入れない利用者にする。「!」(ロック)だと鍵でも通さない OS があるので「*」(無効)にする
usermod -p '*' "$TUNNEL_USER"
usermod -p '*' "$AKC_USER"

# ── API への合言葉 ────────────────────────────────────────────────────────
install -d -o root -g root -m 755 "$CONF" "$CONF/operators"
if [ ! -s "$CONF/secret" ]; then
    ( umask 077; head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n' > "$CONF/secret" )
fi
chown root:root "$CONF/secret"; chmod 600 "$CONF/secret"
SECRET=$(cat "$CONF/secret")
# curl に渡す設定(合言葉をコマンドの引数に出さない)。読めるのは管理者と、鍵を聞きに行く係だけ
( umask 077; printf 'header = "Authorization: Bearer %s"\n' "$SECRET" > "$CONF/curl.conf" )
chown root:"$AKC_USER" "$CONF/curl.conf"; chmod 640 "$CONF/curl.conf"
printf 'API_URL=%s\nPORT_FROM=%s\nPORT_TO=%s\nTUNNEL_USER=%s\n' "$API_URL" "$PORT_FROM" "$PORT_TO" "$TUNNEL_USER" > "$CONF/env"
chown root:root "$CONF/env"; chmod 644 "$CONF/env"

# ── sshd が鍵を聞きに行くコマンド ─────────────────────────────────────────
cat > /usr/local/sbin/mokuture-authorized-keys <<'SCRIPT'
#!/bin/sh
# sshd が、端末(mokuture-tunnel)がつなぎに来るたびに動かす。いま通してよい鍵の一覧を返す。
# API に聞けなかったら何も返さない(＝誰も通さない)。
. /etc/mokuture-bastion/env
exec curl -fsS --max-time 8 -K /etc/mokuture-bastion/curl.conf "$API_URL/bastion/authorized-keys"
SCRIPT
chown root:root /usr/local/sbin/mokuture-authorized-keys
chmod 755 /usr/local/sbin/mokuture-authorized-keys

# ── 見回り(開いてよい一覧に無い転送口を切る) ──────────────────────────────
cat > /usr/local/sbin/mokuture-tunnel-reaper <<'SCRIPT'
#!/bin/bash
# 1 分ごと。運営パネルで「終了」が押された・時間切れになった端末の経路を、端末の協力を
# 待たずにこちらから切る。API に聞けなかった回は何もしない(端末側も自分の残り時間で閉じる)。
set -u
. /etc/mokuture-bastion/env
resp=$(curl -fsS --max-time 10 -K /etc/mokuture-bastion/curl.conf "$API_URL/bastion/active-ports") || exit 0
case "$resp" in '{"ports":['*']}') ;; *) exit 0 ;; esac
active=" $(printf '%s' "$resp" | grep -oE '[0-9]+' | tr '\n' ' ') "
uid=$(id -u "$TUNNEL_USER") || exit 0
ss -H -ltnp 2>/dev/null | while read -r line; do
    port=$(printf '%s\n' "$line" | awk '{print $4}' | sed 's/.*://')
    pid=$(printf '%s\n' "$line" | grep -oE 'pid=[0-9]+' | head -1 | cut -d= -f2)
    case "$port" in ''|*[!0-9]*) continue ;; esac
    [ -n "$pid" ] || continue
    [ "$port" -ge "$PORT_FROM" ] && [ "$port" -le "$PORT_TO" ] || continue
    [ "$(stat -c %u "/proc/$pid" 2>/dev/null)" = "$uid" ] || continue
    case "$active" in *" $port "*) continue ;; esac
    logger -t mokuture-bastion "転送口 $port を切る(開いてよい一覧に無い)"
    kill "$pid" 2>/dev/null || true
done
SCRIPT
chown root:root /usr/local/sbin/mokuture-tunnel-reaper
chmod 755 /usr/local/sbin/mokuture-tunnel-reaper

cat > /etc/systemd/system/mokuture-tunnel-reaper.service <<'UNIT'
[Unit]
Description=mokuture+ bastion: close tunnels that are no longer allowed
After=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/mokuture-tunnel-reaper
UNIT
cat > /etc/systemd/system/mokuture-tunnel-reaper.timer <<'UNIT'
[Unit]
Description=mokuture+ bastion: check tunnels every minute

[Timer]
OnBootSec=1min
OnUnitActiveSec=1min
AccuracySec=5s

[Install]
WantedBy=timers.target
UNIT

# ── sshd の設定 ───────────────────────────────────────────────────────────
# いま待ち受けている番号は残す(管理用の 22 番など)。そこへ 443 番を足す。
ports=$( { sshd -T 2>/dev/null | awk '$1=="port"{print $2}'; echo "$SSH_PORT"; } | sort -un )
backup=""
if [ -f "$DROPIN" ]; then backup=$(mktemp); cp -p "$DROPIN" "$backup"; fi
{
    echo "# mokuture+ 遠隔ログインの踏み台。bastion/setup.sh が書く(手で直さない。直すなら setup.sh を)"
    for p in $ports; do echo "Port $p"; done
    cat <<CONF

# 端末: 逆向きの転送口を開けるだけ。鍵はここに置かず、つなぎに来るたびに API へ聞く
Match User $TUNNEL_USER
    AuthorizedKeysFile none
    AuthorizedKeysCommand /usr/local/sbin/mokuture-authorized-keys
    AuthorizedKeysCommandUser $AKC_USER
    PasswordAuthentication no
    KbdInteractiveAuthentication no
    AllowTcpForwarding remote
    AllowStreamLocalForwarding no
    GatewayPorts no
    PermitTunnel no
    PermitTTY no
    X11Forwarding no
    AllowAgentForwarding no
    ForceCommand /usr/sbin/nologin
    ClientAliveInterval 30
    ClientAliveCountMax 3

# 運営: この踏み台の上の転送口へ中継してもらえるだけ(ssh -J)。鍵は add-operator.sh が置く
Match Group $OP_GROUP
    AuthorizedKeysFile $CONF/operators/%u
    PasswordAuthentication no
    KbdInteractiveAuthentication no
    AllowTcpForwarding local
    PermitOpen 127.0.0.1:*
    AllowStreamLocalForwarding no
    PermitTunnel no
    PermitTTY no
    X11Forwarding no
    AllowAgentForwarding no
    ForceCommand /usr/sbin/nologin
CONF
} > "$DROPIN"
chmod 644 "$DROPIN"
if ! sshd -t; then
    echo "sshd が設定を受け付けない。元に戻す"
    if [ -n "$backup" ]; then cp -p "$backup" "$DROPIN"; else rm -f "$DROPIN"; fi
    exit 1
fi
[ -z "$backup" ] || rm -f "$backup"

systemctl daemon-reload
# Ubuntu は待ち受けを ssh.socket が持つ(番号は sshd の設定から作られるので、変えたら作り直す)。
# ssh.service が動いたままだと ssh.socket は起動し直せないので、先に止める
# (入っている最中の接続は切れない。接続ごとに別のプロセスが受け持っている)。
# Debian は ssh.service だけ。
if systemctl is-enabled ssh.socket >/dev/null 2>&1 || systemctl is-active ssh.socket >/dev/null 2>&1; then
    systemctl stop ssh.service || true
    systemctl restart ssh.socket
else
    systemctl restart ssh.service
fi
systemctl enable --now mokuture-tunnel-reaper.timer >/dev/null

# ── 確かめと、次にすること ────────────────────────────────────────────────
echo
# いったん変数に受ける(pipefail の下で grep -q が先に終わると、前のコマンドが止められて失敗扱いになる)
listening=$(ss -H -ltn | awk '{print $4}')
effective=$(sshd -T 2>/dev/null || true)
if ! printf '%s\n' "$listening" | grep -q ":$SSH_PORT\$"; then
    echo "!!! $SSH_PORT 番で待ち受けていない。journalctl -u ssh を確かめる !!!"
fi
if printf '%s\n' "$effective" | grep -qi '^passwordauthentication yes'; then
    echo "!!! この踏み台は、管理用のログインにパスワードが使える設定のままになっている。"
    echo "    443 番は世界中から見えるので、鍵でのログインだけにする(README.md の「踏み台そのものを守る」)。"
    echo
fi
HOST_KEY=$(cut -d' ' -f1,2 /etc/ssh/ssh_host_ed25519_key.pub)
cat <<DONE
=== 踏み台の用意ができた ===

1. mokuture+ の API(Render)の環境変数に、次の 3 つを入れる:

   TUNNEL_BASTION_HOST=<この踏み台のホスト名、または IP アドレス>
   TUNNEL_BASTION_HOST_KEY=$HOST_KEY
   TUNNEL_BASTION_SECRET=$SECRET

   (TUNNEL_BASTION_SECRET は合言葉。人に見せない・チャットに貼らない)

2. 運営の人を足す(その人の PC の公開鍵で):

   sudo bash add-operator.sh <名前> "<ssh-ed25519 AAAA... の 1 行>"

3. 事業者の管理画面(ファイアウォール)で、外から $SSH_PORT 番(TCP)へ届くようにする。
DONE
