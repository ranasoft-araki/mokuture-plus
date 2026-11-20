# 遠隔ログインの踏み台サーバー

遠隔地の端末で問題が起きたとき、運営が自分の PC から端末(ラズパイ)へ SSH で入るための中継サーバー。
端末は顧客のネットワークの内側にあって外からは届かないので、**端末のほうから**この踏み台へ外向きにつないでもらう。

## 全体の流れ

```
運営パネル「デバイス管理」で「開く…」        端末(顧客のネットワーク内)
        │ 理由と時間を入れて開く                 │ 1 分ごとに API へ「開けと言われているか」を聞く
        ▼                                       ▼
   mokuture+ API ───────────────────────────▶ 「開け」を受け取る
        ▲                                       │ 外向きに SSH(443 番)
        │ 「この鍵を通してよいか」                ▼
   踏み台サーバー(この VPS) ◀──────────────── 逆向きの転送口を開く(踏み台の 127.0.0.1:2xxxx)
        ▲
        │ ssh -J (踏み台を経由)
   運営の PC ──────────────────────────────▶ 端末の中だけで待つ受け口(127.0.0.1:2222)へ入る
```

- 端末は普段どこにもつないでいない。開くのは運営パネルで要求した端末だけ、選んだ時間だけ。
- 終了は 3 重: 運営パネルの「終了する」／時間切れで端末が自分から閉じる／踏み台の見回りが 1 分ごとに切る。
- 鍵は 2 つに分かれている。**API が握るのは「どの端末を、いつまでつながせるか」だけ**で、端末へ入る鍵は運営それぞれの PC にしかない。API が乗っ取られても、この経路からは端末の中へ入れない。
  （端末のソフトウェア更新の配信そのものが乗っ取られた場合は別で、それはこの機能の有無に関係なく残る弱点。CLAUDE.md の「遠隔ログイン」節）

## 用意するもの

| もの | 内容 |
|---|---|
| VPS 1 台 | いちばん小さいプランでよい(メモリ 512MB〜1GB)。OS は Ubuntu の LTS(24.04 以降)か Debian 12 以降。慣れているほうでよい。固定の IP アドレス |
| ファイアウォール | 外から TCP 443 番を通す。管理用の 22 番は、できれば自分の IP アドレスからだけ通す |
| 運営の人それぞれの SSH の鍵 | 各自の PC で `ssh-keygen -t ed25519` を実行して作る。使うのは公開鍵(`~/.ssh/id_ed25519.pub`)の 1 行 |

## 手順

### 1. 踏み台を用意する(VPS で 1 回)

このフォルダの `setup.sh` と `add-operator.sh` を VPS へ写し、管理者として動かす。

```bash
scp bastion/setup.sh bastion/add-operator.sh <管理用の利用者>@<VPS>:
ssh <管理用の利用者>@<VPS>
sudo bash setup.sh
```

最後に、API へ入れる 3 つの値が表示される。

### 2. API(Render)に 3 つの環境変数を入れる

```
TUNNEL_BASTION_HOST=<踏み台のホスト名、または IP アドレス>
TUNNEL_BASTION_HOST_KEY=ssh-ed25519 AAAA...        ← setup.sh が表示した値
TUNNEL_BASTION_SECRET=...                          ← setup.sh が表示した値(合言葉。人に見せない)
```

3 つ揃うと機能が有効になり、運営パネル「デバイス管理」の「遠隔ログイン」の列が「使えません」から変わる。
揃うまでは、端末は何もつながない。

### 3. 運営の人を登録する(人ごとに 2 か所)

入るには、同じ公開鍵を **踏み台** と **端末** の両方に登録する。

**踏み台**(VPS で):

```bash
sudo bash add-operator.sh yamada "ssh-ed25519 AAAAC3... yamada@pc"
```

**端末**(開発機のリポジトリで): `kiosk_agent/system/operator_keys` に同じ 1 行を足し、署名して push する。

```bash
bash kiosk_agent/scripts/sign_system.sh
git add kiosk_agent/system && git commit && git push
```

端末は 10 分ごとに署名を確かめて取り込む。**このファイルに鍵が無いあいだは、遠隔ログインを開いても誰も端末に入れない。**

外すときは逆の手順: `sudo bash add-operator.sh --remove yamada` と、`operator_keys` からその行を消して署名・push。

### 4. 使う

1. 運営パネル「デバイス管理」で、対象の端末の「開く…」を押し、理由と時間を入れて「遠隔ログインを開く」。
2. 状態が「接続中」になったら、表示されたコマンドを**運営用の鍵を置いた自分の PC** のターミナル(Windows なら PowerShell)で実行する。
   踏み台サーバーにログインして実行するのではない(鍵は踏み台に無い)。`-J` の利用者名は `add-operator.sh` で登録した名前で、管理用の `ubuntu` ではない。
   ```
   ssh -J yamada@<踏み台>:443 -p 2xxxx <端末の利用者名>@127.0.0.1
   ```
3. 初めてつなぐ相手には ssh が指紋を表示する(踏み台 → 端末の順)。画面に出ている指紋と同じことを確かめて `yes`。
4. 作業が終わったら「遠隔ログインを終了する」。

端末のキオスク画面(端末の中の `127.0.0.1:8080`)を自分の PC のブラウザで見たいときは、コマンドに `-L 8080:127.0.0.1:8080` を足す。

## 踏み台そのものを守る

この VPS は、開いているあいだの端末への通り道になる。世界中から 443 番が見えるので、次を済ませておく。

- **管理用のログインは鍵だけにする。** `/etc/ssh/sshd_config.d/` に `PasswordAuthentication no` と `PermitRootLogin prohibit-password`(または `no`)を書いて `sudo systemctl restart ssh`。自分の鍵で入れることを**別の窓で確かめてから**今の接続を閉じる。`setup.sh` はここを変えない(締め出しを避けるため)が、パスワードが使える設定のままだと最後に警告を出す。
- **OS の更新を自動で当てる。** `setup.sh` が `unattended-upgrades` を入れる。有効になっているかは `systemctl status unattended-upgrades`。
- **ほかの用途に使わない。** Web サーバーなどを同居させない(運営の利用者は、この VPS の `127.0.0.1` の口へ中継してもらえる)。
- **合言葉(`TUNNEL_BASTION_SECRET`)が漏れたら作り直す。** VPS で `sudo rm /etc/mokuture-bastion/secret && sudo bash setup.sh`、表示された値で Render の環境変数を入れ替える。漏れても、分かるのは「いま開いている端末の公開鍵と転送口の番号」までで、端末には入れない。

## 困ったとき

| 見えること | 確かめること |
|---|---|
| 「遠隔ログイン」の列が「使えません」 | Render の `TUNNEL_BASTION_*` の 3 つが入っているか |
| 「端末が未対応」 | その端末にシステム更新が届いているか(キオスク設定 → デバイスチェック → ソフトウェア更新の「OS の設定・部品」)。既設の端末は一度 `install.sh` が必要 |
| 「踏み台へ届かない」 | 設置先のネットワークが 443 番の SSH を通さない。この端末では遠隔ログインは使えない |
| 「接続準備中」のまま、理由に `Permission denied` | 踏み台が API に聞けていない。VPS で `sudo -u mokuture-akc /usr/local/sbin/mokuture-authorized-keys` を動かし、鍵の行が返るか |
| 「接続準備中」のまま、理由に `Host key verification failed` | `TUNNEL_BASTION_HOST_KEY` が踏み台の今の鍵と違う。VPS で `cut -d' ' -f1,2 /etc/ssh/ssh_host_ed25519_key.pub` |
| 「接続中」なのに自分の PC から入れない(踏み台で断られる) | `add-operator.sh` で登録した名前と鍵か。`ssh -v -J ...` の出力で、どちらで断られたかを見る |
| 自分の PC で `channel 0: open failed: connect failed: Connection refused` | 踏み台までは入れたが、その端末の経路が無い。遠隔ログインが閉じている(時間切れ・終了済み)か、まだ「接続中」になっていない。運営パネルで状態を確かめ、閉じていれば開き直す |
| 踏み台は通るが端末で断られる | `operator_keys` に鍵を足して署名・push したか。端末で `cat /etc/mokuture/tunnel_sshd/authorized_keys` |

記録を見る場所:

- 踏み台: `journalctl -u ssh`(誰がつないだか)、`journalctl -t mokuture-bastion`(見回りが切った転送口)
- 端末: `journalctl -u mokuture-tunnel`(常駐)、`journalctl -t sshd -t sshd-session`(誰の鍵で入ったか。OpenSSH の版で名前が違う)
- 誰が・いつ・どの端末を・何のために開けたか: 運営パネルの各端末のダイアログ下部、または API `GET /operator/tunnel/sessions`
