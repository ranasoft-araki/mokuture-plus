#!/bin/bash
# mokuture+ キオスク — サービスの停止/再開(デスクトップから1クリック)
#
#   bash scripts/kiosk-service.sh stop             # 受付サービスとブラウザを止める
#   bash scripts/kiosk-service.sh start            # 元に戻す(全画面の受付画面へ)
#   bash scripts/kiosk-service.sh status           # いま何が動いているか
#   bash scripts/kiosk-service.sh diagnose         # ブラウザを起こしているのが誰か調べる
#   bash scripts/kiosk-service.sh install-desktop  # デスクトップに停止/再開アイコンを置く
#
# **「停止したのにブラウザが戻ってくる」を無くすのがこのスクリプトの目的。**
# 端末でブラウザが勝手に立ち上がってくる経路は 3 つあり、どれも「ブラウザを閉じる /
# kill する」だけでは塞げない:
#
#   1. ブラウザ自身の systemd ユニット(mokuture-browser.service など)の Restart=always
#      → kill すると数秒で起こし直される。systemd に止めさせるのが正しい
#        (systemctl stop で止めた相手は Restart の対象外になる)。
#   2. 本体(mokuture-kiosk.service)の ExecStartPost が起動のたびにブラウザを起こす
#      → 本体は Restart=always・WatchdogSec=30 なので、ブラウザだけ先に落とすと
#        「ブラウザの heartbeat が来ない → 本体が再起動 → ブラウザが戻る」の輪に入る。
#        **必ず本体を先に止め、ブラウザを後に止める。**
#   3. デスクトップセッションの autostart(LXDE の `@chromium-browser`、`while true` で
#      起こし直すラッパー、`~/.config/autostart/*.desktop` など)
#      → 誰が起こしているか端末ごとに違う。**止めた後も見張りを残して抑える**
#        (停止中フラグ `~/.mokuture-browser-paused` がある間だけ動き、start で消える)。
#
# 見張りの pkill が「見張り自身」を巻き込まないよう、kill は必ずこのスクリプトの
# `_kill-browser` に投げる(見張りのコマンドラインにブラウザ名を出さないため)。
set -u

SELF="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"
KIOSK_UNIT="mokuture-kiosk"
VOICE_UNIT="mokuture-voice"
# 落とす対象。端末ごとに起動の仕方(URL も実行ファイル名も)が違うので、既定は
# 「デスクトップのユーザーが動かしているブラウザ全部」と広めに取る。
# 変えたいときは MOKUTURE_BROWSER_PAT で上書きする。
BROWSER_PAT="${MOKUTURE_BROWSER_PAT:-chromium|chrome|firefox|epiphany}"
# ブラウザを持っていそうな systemd ユニットの見つけ方(名前が端末ごとに違うため)。
BROWSER_UNIT_PAT="${MOKUTURE_BROWSER_UNIT_PAT:-brows|chrom|kiosk-ui}"
GUARD_TAG="MOKUTURE_BROWSER_GUARD"
# 音声サービスの可否を見る先(別プロセス・別ポート)。voice_input.yaml の server.port を
# 変えている端末は MOKUTURE_VOICE_STATUS_URL で上書きする。
VOICE_STATUS_URL="${MOKUTURE_VOICE_STATUS_URL:-http://127.0.0.1:8181/voice/status}"
VOICE_WAIT_SEC="${MOKUTURE_VOICE_WAIT_SEC:-40}"
PAUSE_AT_END=0

# デスクトップのユーザー(= ブラウザのユーザーサービスを持っている人)。sudo 経由で
# 呼ばれても root の systemd --user を見に行かないように、元のユーザーへ寄せる。
DESK_USER="${SUDO_USER:-$(id -un)}"
DESK_UID="$(id -u "$DESK_USER" 2>/dev/null || id -u)"
DESK_HOME="$(getent passwd "$DESK_USER" 2>/dev/null | cut -d: -f6)"
DESK_HOME="${DESK_HOME:-$HOME}"
FLAG="$DESK_HOME/.mokuture-browser-paused"

ACTION="${1:-status}"
shift || true
for arg in "$@"; do
    case "$arg" in
        --pause) PAUSE_AT_END=1 ;;
        *) echo "不明な引数: $arg"; exit 2 ;;
    esac
done

as_root() { if [ "$(id -u)" = "0" ]; then "$@"; else sudo "$@"; fi; }

# systemctl --user を「デスクトップのユーザー」として実行する。
sc_user() {
    if [ "$(id -un)" = "$DESK_USER" ]; then
        XDG_RUNTIME_DIR="/run/user/$DESK_UID" systemctl --user "$@"
    else
        sudo -u "$DESK_USER" XDG_RUNTIME_DIR="/run/user/$DESK_UID" systemctl --user "$@"
    fi
}

unit_exists_system() { systemctl list-unit-files "$1.service" --no-legend 2>/dev/null | grep -q .; }

# ブラウザを持っていそうなユニットを名前で拾う(mokuture-browser とは限らないため)。
browser_units_user() {
    sc_user list-units --type=service --all --no-legend --plain 2>/dev/null \
        | awk '{print $1}' | grep -Ei "$BROWSER_UNIT_PAT" || true
}
browser_units_system() {
    systemctl list-units --type=service --all --no-legend --plain 2>/dev/null \
        | awk '{print $1}' | grep -Ei "$BROWSER_UNIT_PAT" || true
}

browser_pids() { pgrep -u "$DESK_USER" -f "$BROWSER_PAT" 2>/dev/null || true; }

# ブラウザを落とす。見張りからも呼ばれる(ここに閉じ込めておくことで、見張り自身の
# コマンドラインにブラウザ名が出ず、pkill が見張りを巻き込まない)。
do_kill_browser() {
    pkill -u "$DESK_USER" -f "$BROWSER_PAT" >/dev/null 2>&1 || true
    sleep 2
    pkill -9 -u "$DESK_USER" -f "$BROWSER_PAT" >/dev/null 2>&1 || true
}

# 音声サービスが「使える」と答えるまで待つ。モデルの読み込みで数秒〜十数秒かかるので、
# ここを待たずにブラウザを開くと受付画面から「音声で入力」が消える(latch のため復帰は
# ページ再読込まで戻らない)。マイク未接続などで永遠に available にならない端末もあるので
# 上限付き。待てなかったときは false を返すだけで、起動そのものは止めない。
wait_voice_ready() {
    command -v curl >/dev/null 2>&1 || { sleep 10; return 1; }
    i=0
    while [ "$i" -lt "$VOICE_WAIT_SEC" ]; do
        if curl -fsS --max-time 2 "$VOICE_STATUS_URL" 2>/dev/null \
            | grep -q '"available"[[:space:]]*:[[:space:]]*true'; then
            return 0
        fi
        printf '.'
        sleep 1
        i=$((i + 1))
    done
    return 1
}

guard_running() { pgrep -f "$GUARD_TAG" >/dev/null 2>&1; }

# 停止中フラグがある間だけ、復活してくるブラウザを落とし続ける見張り。
# 誰が起こしているか(ユニット・autostart・ラッパーの while ループ)に関係なく効く。
# フラグを消せば見張りは自分で終わる。再起動でも消える(通常運用に戻る)。
guard_start() {
    : > "$FLAG"
    chown "$DESK_USER" "$FLAG" 2>/dev/null || true
    guard_running && return 0
    setsid bash -c "
        # $GUARD_TAG — 停止中だけ動く見張り
        while [ -e '$FLAG' ]; do
            bash '$SELF' _kill-browser >/dev/null 2>&1
            sleep 1
        done
    " >/dev/null 2>&1 </dev/null &
}

guard_stop() {
    rm -f "$FLAG"
    pkill -f "$GUARD_TAG" >/dev/null 2>&1 || true
}

do_stop() {
    echo "=== キオスクを停止します ==="

    # 1) 本体を先に止める(ブラウザを先に落とすと watchdog が本体を再起動し、
    #    その ExecStartPost でブラウザが戻ってくる)。
    echo "--- 受付サービス($KIOSK_UNIT) ---"
    if as_root systemctl stop "$KIOSK_UNIT"; then echo "  停止しました"; else echo "  停止できませんでした"; fi

    if unit_exists_system "$VOICE_UNIT"; then
        echo "--- 音声入力($VOICE_UNIT) ---"
        if as_root systemctl stop "$VOICE_UNIT"; then echo "  停止しました"; else echo "  停止できませんでした"; fi
    fi

    # 2) ブラウザ。まず systemd に止めさせる(kill だけだと Restart=always で戻る)。
    echo "--- ブラウザ ---"
    found_unit=0
    for u in $(browser_units_user); do
        found_unit=1
        sc_user stop "$u" >/dev/null 2>&1
        echo "  停止: $u (ユーザーサービス)"
    done
    for u in $(browser_units_system); do
        found_unit=1
        as_root systemctl stop "$u" >/dev/null 2>&1
        echo "  停止: $u"
    done
    [ "$found_unit" = "0" ] && echo "  ブラウザの systemd ユニットは見つかりませんでした"

    # 3) 見張りを残す。ユニットが無い端末(セッションの autostart やラッパーの
    #    while ループ)は、ここが効かないと数秒で復活する。
    guard_start
    do_kill_browser
    if [ -n "$(browser_pids)" ]; then
        echo "  まだ残っています。見張りが落とし続けます(数秒待ってください)"
    else
        echo "  画面が空きました(再開するまで自動起動を抑止します)"
    fi

    echo ""
    echo "再開する  : bash $SELF start   (端末を再起動しても通常運用に戻ります)"
    echo "戻ってくる: bash $SELF diagnose   ← 誰が起こしているか調べて貼ってください"
}

do_start() {
    echo "=== キオスクを再開します ==="
    guard_stop

    # **起動は停止の逆順**。受付画面は起動時に一度だけ /voice/status を見て、届かなければ
    # そのページが閉じるまで「音声で入力」を出さない(kiosk.html の ensureVoiceStatus は
    # VOICE.checked で latch する)。本体を先に上げるとブラウザが数秒で開き、まだ起動中の
    # 音声サービスに間に合わず、**ボタンが消えたまま**になる。だから音声を先に上げ、
    # 応答を確かめてから本体(= ブラウザ)を起こす。
    if unit_exists_system "$VOICE_UNIT"; then
        echo "--- 音声入力($VOICE_UNIT) ---"
        if as_root systemctl start "$VOICE_UNIT"; then echo "  起動しました"; else echo "  起動できませんでした"; fi
        printf '  利用できるようになるまで待っています'
        if wait_voice_ready; then
            echo " → 準備できました"
        else
            echo " → 待ちきれませんでした"
            echo "  ※ このまま進めます。受付画面に「音声で入力」が出ない場合は次を確認:"
            echo "     systemctl status $VOICE_UNIT / curl -s $VOICE_STATUS_URL"
        fi
    fi

    echo "--- 受付サービス($KIOSK_UNIT) ---"
    # 本体の ExecStartPost がブラウザのユニットを起こし直す。
    if as_root systemctl start "$KIOSK_UNIT"; then echo "  起動しました"; else echo "  起動できませんでした"; fi

    echo "--- ブラウザ ---"
    sleep 2
    if [ -n "$(browser_pids)" ]; then
        echo "  起動しました"
    else
        for u in $(browser_units_user);   do sc_user start "$u" >/dev/null 2>&1 && echo "  起動: $u"; done
        for u in $(browser_units_system); do as_root systemctl start "$u" >/dev/null 2>&1 && echo "  起動: $u"; done
        if [ -z "$(browser_pids)" ]; then
            echo "  自動起動の抑止は解除しました。画面が戻らない場合は端末を再起動してください"
        fi
    fi
}

do_status() {
    echo "=== キオスクの状態 ==="
    printf '%-26s %s\n' "$KIOSK_UNIT" "$(systemctl is-active "$KIOSK_UNIT" 2>/dev/null || echo unknown)"
    if unit_exists_system "$VOICE_UNIT"; then
        printf '%-26s %s\n' "$VOICE_UNIT" "$(systemctl is-active "$VOICE_UNIT" 2>/dev/null || echo unknown)"
        # サービスが active でも、モデル読み込み中やマイク未接続だと available にならない。
        # 受付画面の「音声で入力」が出るかどうかはこちらで決まる。
        if command -v curl >/dev/null 2>&1; then
            if curl -fsS --max-time 2 "$VOICE_STATUS_URL" 2>/dev/null \
                | grep -q '"available"[[:space:]]*:[[:space:]]*true'; then
                printf '%-26s %s\n' "「音声で入力」" "出る(available)"
            else
                printf '%-26s %s\n' "「音声で入力」" "出ない($VOICE_STATUS_URL が available を返さない)"
            fi
        fi
    fi
    for u in $(browser_units_user); do
        printf '%-26s %s\n' "$u" "$(sc_user is-active "$u" 2>/dev/null || echo unknown) (ユーザーサービス)"
    done
    for u in $(browser_units_system); do
        printf '%-26s %s\n' "$u" "$(systemctl is-active "$u" 2>/dev/null || echo unknown)"
    done
    pids="$(browser_pids)"
    if [ -n "$pids" ]; then
        printf '%-26s %s\n' "ブラウザ(プロセス)" "起動中 pid=$(echo "$pids" | tr '\n' ' ')"
    else
        printf '%-26s %s\n' "ブラウザ(プロセス)" "いません"
    fi
    if [ -e "$FLAG" ]; then
        printf '%-26s %s\n' "自動起動の抑止" "あり($FLAG)"
        printf '%-26s %s\n' "見張り" "$(guard_running && echo 動作中 || echo 停止中)"
    fi
}

# 「止めてもブラウザが戻ってくる」ときに、**誰が起こしているか**を洗い出す。
# 出力をそのまま貼れば原因が特定できるように、経路を一通り並べて出す。
do_diagnose() {
    echo "=== 診断: ブラウザを起こしているのは誰か ==="
    echo ""
    echo "--- 1. いま動いているブラウザ(pid / 親pid / コマンドライン) ---"
    hits="$(ps -eo pid,ppid,user,lstart,args 2>/dev/null | grep -Ei "$BROWSER_PAT" | grep -v grep | cut -c1-200)"
    if [ -n "$hits" ]; then echo "$hits" | sed 's/^/  /'; else echo "  いません"; fi

    echo ""
    echo "--- 2. その親は誰か(= 起こしている犯人) ---"
    for pid in $(browser_pids); do
        ppid="$(ps -o ppid= -p "$pid" 2>/dev/null | tr -d ' ')"
        [ -n "$ppid" ] || continue
        echo "  pid=$pid の親 ppid=$ppid:"
        ps -o pid,ppid,user,args -p "$ppid" 2>/dev/null | tail -n +2 | sed 's/^/    /' | cut -c1-200
        echo "    cgroup: $(cat /proc/$pid/cgroup 2>/dev/null | tail -1)"
        break
    done
    command -v pstree >/dev/null 2>&1 && {
        echo "  プロセスツリー:"
        pstree -ps "$(browser_pids | head -1)" 2>/dev/null | sed 's/^/    /' | cut -c1-200
    }

    echo ""
    echo "--- 3. systemd ユニット(ユーザー) ---"
    hits="$(sc_user list-units --type=service --all --no-legend --plain 2>/dev/null \
        | grep -Ei "$BROWSER_UNIT_PAT|mokuture")"
    if [ -n "$hits" ]; then echo "$hits" | sed 's/^/  /'; else echo "  なし(ユーザーサービスは使っていない)"; fi
    for u in $(browser_units_user); do
        echo "  --- $u の中身 ---"
        sc_user cat "$u" 2>/dev/null | sed 's/^/    /'
    done

    echo ""
    echo "--- 4. systemd ユニット(システム) ---"
    systemctl list-units --type=service --all --no-legend --plain 2>/dev/null \
        | grep -Ei "$BROWSER_UNIT_PAT|mokuture" | sed 's/^/  /' || echo "  なし"
    # 実機のユニットはリポジトリの雛形と違うことがある(手で足した ExecStartPost など)。
    echo "  --- $KIOSK_UNIT の中身(実機の実物) ---"
    systemctl cat "$KIOSK_UNIT" 2>/dev/null | grep -vE '^\s*#' | sed 's/^/    /'

    echo ""
    echo "--- 5. セッションの autostart ---"
    for f in /etc/xdg/lxsession/*/autostart "$DESK_HOME"/.config/lxsession/*/autostart \
             "$DESK_HOME"/.config/autostart/*.desktop /etc/xdg/autostart/*.desktop \
             "$DESK_HOME"/.config/wayfire.ini "$DESK_HOME"/.config/labwc/autostart \
             "$DESK_HOME"/.xsession "$DESK_HOME"/.xsessionrc "$DESK_HOME"/.profile \
             "$DESK_HOME"/.bash_profile /etc/rc.local; do
        [ -f "$f" ] || continue
        hit="$(grep -Ein "$BROWSER_PAT|kiosk" "$f" 2>/dev/null | head -5)"
        [ -n "$hit" ] && echo "  $f:" && echo "$hit" | sed 's/^/    /'
    done

    echo ""
    echo "--- 6. cron / ユーザーの systemd timer ---"
    crontab -l -u "$DESK_USER" 2>/dev/null | grep -Ei "$BROWSER_PAT|kiosk" | sed 's/^/  /' || true
    sc_user list-timers --all --no-legend 2>/dev/null | sed 's/^/  /' || true

    echo ""
    echo "--- 7. 停止中フラグと見張り ---"
    if [ -e "$FLAG" ]; then echo "  フラグ: あり($FLAG)"; else echo "  フラグ: なし"; fi
    echo "  見張り: $(guard_running && echo 動作中 || echo 停止中)"
    echo "  対象パターン: $BROWSER_PAT / ユーザー: $DESK_USER"
}

# デスクトップに「停止」「再開」のアイコンを置く。押すと端末が開いて結果が見える。
do_install_desktop() {
    desk="$(sudo -u "$DESK_USER" xdg-user-dir DESKTOP 2>/dev/null || true)"
    [ -n "${desk:-}" ] && [ -d "$desk" ] || desk="$DESK_HOME/Desktop"
    [ -d "$desk" ] || desk="$DESK_HOME/デスクトップ"
    if [ ! -d "$desk" ]; then
        echo "デスクトップのフォルダが見つかりません: $DESK_HOME/Desktop"
        exit 1
    fi

    write_entry() {  # write_entry <ファイル名> <表示名> <説明> <アクション> <アイコン>
        path="$desk/$1"
        cat > "$path" <<EOF
[Desktop Entry]
Type=Application
Name=$2
Comment=$3
Exec=bash "$SELF" $4 --pause
Icon=$5
Terminal=true
Categories=System;
EOF
        chmod +x "$path"
        chown "$DESK_USER" "$path" 2>/dev/null || true
        echo "  $path"
    }

    echo "=== デスクトップにアイコンを作ります ==="
    write_entry "mokuture-停止.desktop" "mokuture キオスク停止" \
        "受付サービスとブラウザを止めて画面を空ける" stop system-shutdown
    write_entry "mokuture-再開.desktop" "mokuture キオスク再開" \
        "受付サービスとブラウザを起動して全画面に戻す" start system-run
    echo ""
    echo "※ 初回クリック時に「実行しますか」と聞かれたら「実行する」を選んでください。"
}

case "$ACTION" in
    stop)            do_stop ;;
    start)           do_start ;;
    status)          do_status ;;
    diagnose)        do_diagnose ;;
    install-desktop) do_install_desktop ;;
    _kill-browser)   do_kill_browser ;;   # 見張りから呼ばれる内部用
    *) echo "使い方: bash $0 {stop|start|status|diagnose|install-desktop} [--pause]"; exit 2 ;;
esac

if [ "$PAUSE_AT_END" = "1" ]; then
    echo ""
    read -r -p "Enter キーで閉じます " _ || true
fi
