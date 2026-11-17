#!/bin/bash
# mokuture+ システム更新の中身(管理者権限で動く)。
#
# 「この端末の OS 側を、いまの版が求める状態にそろえる」手順を書く。何度動かしても
# 同じ結果になるように書くこと(すでにそうなっていれば何もしない)。
#
# ここを書き換えたら必ず署名し直す: bash kiosk_agent/scripts/sign_system.sh
# 署名が無い・合わない版は、端末の sysupdate-root.sh が実行しない。
#
# 管理者として読んでよいのは $FILES(署名を確かめた写し)だけ。$AGENT_DIR と $VENV は
# エージェントの利用者が書き換えられるので、触るときは必ずその利用者として動かす。
#
# 受け取る環境変数(sysupdate-root.sh が渡す):
#   AGENT_DIR  エージェントの置き場所      AGENT_USER  エージェントを動かす利用者
#   VENV       Python の仮想環境           STATE_DIR   /var/lib/mokuture
#   FILES      署名を確かめた写しの置き場所
set -u
: "${AGENT_DIR:?}" "${AGENT_USER:?}" "${VENV:?}" "${STATE_DIR:?}" "${FILES:?}"
export DEBIAN_FRONTEND=noninteractive

FAILED=""
step_failed() { echo "!! 失敗: $1"; FAILED="${FAILED:+$FAILED, }$1"; }
# 何かを実際に変えたときだけ、最後にエージェントへ再起動を頼む(失敗した版は 1 時間ごとに
# やり直すので、変えていないのに頼むと、直らない端末が 1 時間ごとに再起動し続ける)。
CHANGED=0

if [ "$(id -u "$AGENT_USER" 2>/dev/null)" = "0" ]; then
    echo "AGENT_USER が管理者になっている。何もしない"
    echo "agent_is_root" > "$STATE_DIR/apply.failed"
    exit 1
fi

IS_PI=0
grep -qi "raspberry pi" /proc/device-tree/model 2>/dev/null && IS_PI=1

# ── 1. この仕組み自身を新しくする(次の回から新しい版で動く) ───────────────
# いちばん先に行う。あとの手順(pip はエージェントの利用者が用意したものを動かす)が
# 終わらなくても、この仕組みの直しだけは必ず届くように。
changed_units=0
install_if_changed() {   # install_if_changed <mode> <src> <dst>  変えたら 0
    if ! cmp -s "$2" "$3"; then
        install -o root -g root -m "$1" "$2" "$3" && return 0
        step_failed self_update
    fi
    return 1
}
install -d -o root -g root -m 755 /usr/local/lib/mokuture
install_if_changed 755 "$FILES/system/sysupdate-root.sh" /usr/local/lib/mokuture/sysupdate-root.sh || true
install_if_changed 644 "$FILES/system/mokuture-sysupdate.service" /etc/systemd/system/mokuture-sysupdate.service && changed_units=1
install_if_changed 644 "$FILES/system/mokuture-sysupdate.timer" /etc/systemd/system/mokuture-sysupdate.timer && changed_units=1
if [ "$changed_units" = "1" ]; then
    systemctl daemon-reload || step_failed self_update
    systemctl enable --now mokuture-sysupdate.timer >/dev/null 2>&1 || true
fi

if [ "$IS_PI" = "1" ]; then
    # ── 2. OS のパッケージ ────────────────────────────────────────────────
    # swig / liblgpio-dev / python3-dev: GPIO と距離センサーのライブラリを組み立てるのに要る
    # i2c-tools: 配線の確認(i2cdetect)に使う
    # 1 つずつ入れる(どれか 1 つがこの OS に無くても、ほかは入るように)。
    apt_install() { timeout 900 apt-get -o DPkg::Lock::Timeout=300 install -y "$1"; }
    updated=0
    for p in swig liblgpio-dev python3-dev i2c-tools; do
        dpkg -s "$p" >/dev/null 2>&1 && continue
        echo "パッケージを入れる: $p"
        if ! apt_install "$p"; then
            if [ "$updated" = "0" ]; then timeout 600 apt-get update || true; updated=1; fi
            apt_install "$p" || { step_failed packages; continue; }
        fi
        CHANGED=1
    done

    # ── 3. I2C を有効にする(距離センサーは GPIO2=SDA / GPIO3=SCL でつなぐ) ─
    if command -v raspi-config >/dev/null 2>&1; then
        if [ "$(raspi-config nonint get_i2c 2>/dev/null)" != "0" ]; then
            echo "I2C を有効にする"
            if raspi-config nonint do_i2c 0; then CHANGED=1; else step_failed i2c; fi
        fi
    fi
    # エージェントの利用者が I2C を読めるようにする(反映はエージェントの再起動後)
    if getent group i2c >/dev/null 2>&1 && ! id -nG "$AGENT_USER" | tr ' ' '\n' | grep -qx i2c; then
        echo "$AGENT_USER を i2c グループに入れる"
        if usermod -aG i2c "$AGENT_USER"; then CHANGED=1; else step_failed i2c_group; fi
    fi
fi

# ── 4. Python のライブラリ ────────────────────────────────────────────────
# 管理者ではなくエージェントの利用者として入れる(仮想環境はその利用者のもの。
# pyproject.toml は署名の対象外なので、管理者権限では読ませない)。時間の上限つき。
as_agent() { runuser -u "$AGENT_USER" -- timeout 1200 "$@"; }
pip_as_agent() { as_agent "$VENV/bin/pip" install --quiet -e "$AGENT_DIR$1"; }   # 例: pip_as_agent "[tof]"
pip_state() { as_agent "$VENV/bin/pip" freeze 2>/dev/null | sha256sum; }
if as_agent test -x "$VENV/bin/pip"; then
    pip_before=$(pip_state)
    pip_as_agent "" || step_failed python_base
    if [ "$IS_PI" = "1" ]; then
        if ! pip_as_agent "[rpi]" || ! as_agent "$VENV/bin/python" -c "import gpiozero, lgpio"; then
            step_failed python_gpio
        fi
        if ! pip_as_agent "[tof]" \
           || ! as_agent "$VENV/bin/python" -c "import board, adafruit_vl53l0x, adafruit_vl53l1x"; then
            step_failed python_distance_sensor
        fi
    fi
    [ "$(pip_state)" = "$pip_before" ] || CHANGED=1
else
    echo "仮想環境が無い($VENV)。install.sh を一度実行する"
    step_failed no_venv
fi

# ── 5. エージェントに再起動を頼む ─────────────────────────────────────────
# ここで止めると受付の途中の来訪者を巻き込む。印だけ置き、キオスクが待機画面に
# 戻ったときにエージェントが自分で再起動する(OTA の適用と同じ流れ)。
# 印の中身は毎回変わる値。エージェントは「起動したときの中身と違うか」で見る
# (時刻で比べると、時計を持たない Pi で起動直後の時刻が戻ったときに狂う)。
if [ "$CHANGED" = "1" ]; then
    echo "$(date +%s)-$$-$RANDOM" > "$STATE_DIR/restart-requested"
    chmod 644 "$STATE_DIR/restart-requested"
    echo "エージェントに再起動を頼んだ(待機画面に戻ったときに行われる)"
fi

if [ -n "$FAILED" ]; then
    echo "$FAILED" > "$STATE_DIR/apply.failed"
    echo "終わったが失敗した手順がある: $FAILED"
    exit 1
fi
echo "すべて完了"
