"""ログインせずに受付へ返事できるリンク（メール・Teams の通知用）。

Slack のボタンやプッシュ通知のボタンは、受付ごとに発行した署名トークン
(`auth.create_decision_token`・2時間)でログイン無しに返事できる。メールと Teams には
押すと mokuture の API を直接叩けるボタンが無い(Teams の Webhook 投稿はリンクしか開けない)ので、
同じトークンを持たせたリンクで画面 `/{slug}/respond` を開かせ、そこで押してもらう。

- **トークンは URL の `#` の後ろに置く**(招待メールと同じ)。ブラウザはこの部分をサーバーへ
  送らないので、Netlify/Render のアクセスログにトークンが残らない。
- **リンクを開いただけでは返事にならない**。メールや Teams のセキュリティ機能
  (Microsoft Defender の Safe Links など)は、リンクが安全かを確かめるために中身を勝手に開く。
  開いただけで確定する作りだと、担当者が押していないのに「受付」になってしまうので、
  画面は読み取りだけをして、確定は画面のボタンを押したときだけ行う。
"""
from __future__ import annotations

from urllib.parse import urlencode

from app.config import settings
from app.services.auth import create_decision_token

# 返事をした経路として `reception_logs.decided_via` に残す語。
LINK_VIAS = ("email", "teams")


def respond_url(slug: str, token: str, *, via: str, decision: str | None = None) -> str:
    """返事用の画面の URL。`decision` を渡すと、その返事を選んだ状態で開く(押すのは画面で1回)。"""
    params = {"token": token, "via": via}
    if decision:
        params["d"] = decision
    base = settings.public_web_url.rstrip("/")
    return f"{base}/{slug}/respond#{urlencode(params)}"


def admin_reception_url(slug: str, log_id: str) -> str:
    """管理画面の受付ログ(該当受付の対応画面を開く)。ログインが要る。"""
    return f"{settings.public_web_url.rstrip('/')}/{slug}/admin/reception?respond={log_id}"


def button_links(slug: str, token: str, log, *, via: str) -> list[tuple[str, str]]:
    """[(ボタンの文字, URL)] を受付の種類に合った選択肢で返す(予約・配達は お断り なし)。
    選択肢は Slack・プッシュ通知と同じ `reception.decision_actions`。"""
    from app.api.reception import decision_actions  # 遅延 import で循環参照を避ける

    return [
        (a["title"], respond_url(slug, token, via=via, decision=a["action"]))
        for a in decision_actions(log)
    ]


def new_token(log_id: str, tenant_id: str, *, actor_name: str = "") -> str:
    """返事用のトークン。担当者ごとの宛先へ送るときは `actor_name` にその担当者名を入れる
    (返事のあとの「〇〇さんが対応しました」に出る)。共通の宛先では空＝「担当者」になる。"""
    return create_decision_token(log_id, tenant_id, actor_name=(actor_name or "").strip() or None)
