"""管理画面からのユーザー招待(メールで招待リンクを送り、本人がパスワードを決めて登録する)。

- 招待リンクは `{public_web_url}/{slug}/invite#token=<token>`。トークンは URL の `#` の後ろ
  (フラグメント)に置く＝ブラウザがサーバーへ送らないので、Netlify や Render のアクセスログに残らない。
  画面はこれを読み、公開 API へ POST の本文で渡す。
- DB にはトークンの sha256 だけを保存する。
- メールアドレスは ASCII だけの厳しい形で判定し(`STRICT_EMAIL_RE`)、画面側と同じ正規表現にそろえる。
- 送信は共有の SMTP。回数制限は来社予定 QR と同じ `mail_quota`(テナントごと1時間30通)。
"""
from __future__ import annotations

import hashlib
import re
import secrets
import unicodedata
from datetime import datetime, timedelta
from email.utils import parseaddr
from html import escape

from app.config import settings
from app.services.timeutil import format_jst, utcnow_naive

EXPIRE_DAYS = 7
# 1回の招待で受け付けるアドレスの上限(貼り付けミスで巨大な一覧を送らせない)。
# 実際に送れる数はこれより先に mail_quota で決まる。
MAX_PER_REQUEST = 100

ROLE_LABEL = {"admin": "管理者", "staff": "スタッフ"}


# 招待のアドレスは ASCII だけの厳しい形にする(ログインIDとして保存し、To にもそのまま入れるため)。
# 緩い形(staff_routing._EMAIL_RE)だと「E-mail:taro@x.jp」「taro@x.jp(山田」が通り、SMTP は
# taro@x.jp へ配達するのに崩れた文字列がログインIDになり、全ユーザーでの重複確認もすり抜ける。
# 画面側(frontend/lib/inviteEmails.ts)と同じ正規表現にそろえること。
_LOCAL = r"[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+(?:\.[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+)*"
_LABEL = r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?"
STRICT_EMAIL_RE = re.compile(rf"^{_LOCAL}@{_LABEL}(?:\.{_LABEL})+$")
# 語の中からアドレスらしい部分を取り出す(「E-mail:」「まで」「（山田）」などの前後を外す)。
_EXTRACT_RE = re.compile(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+")


def normalize(addr: str) -> str:
    """全角を半角へ寄せ(NFKC)、語の中からアドレスの部分だけを取り出す。取り出せなければ元の語。

    前後の句点(文末の「.」)・引用符・かっこ・mailto: などは落ちる。"""
    s = unicodedata.normalize("NFKC", addr or "").strip()
    s = s.strip("\"'“”‘’<>()[]「」『』")
    if s.lower().startswith("mailto:"):
        s = s[7:]
    m = _EXTRACT_RE.search(s)
    if m:
        s = m.group(0).strip(".")
    return s.strip()


def is_valid(addr: str) -> bool:
    if not addr or len(addr) > 254 or not STRICT_EMAIL_RE.match(addr):
        return False
    # To ヘッダとして読み直しても同じ値になること(届く宛先＝保存するログインID)。
    return parseaddr(addr)[1] == addr


def new_token() -> tuple[str, str]:
    """(リンクに載せるトークン, DB に保存する sha256) を返す。"""
    token = secrets.token_urlsafe(32)
    return token, hash_token(token)


def hash_token(token: str) -> str:
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


def new_expiry() -> datetime:
    return utcnow_naive() + timedelta(days=EXPIRE_DAYS)


def invite_url(slug: str, token: str) -> str:
    base = (settings.public_web_url or "").rstrip("/")
    return f"{base}/{slug}/invite#token={token}"


def one_line(s: str) -> str:
    """メールのヘッダ(件名)に入れる値から改行を除く。"""
    return re.sub(r"[\r\n]+", " ", s or "").strip()


def build_email(
    *,
    tenant_name: str,
    brand_color: str,
    inviter: str,
    to: str,
    role: str,
    url: str,
    expires_at: datetime,
) -> tuple[str, str, str]:
    """(件名, テキスト本文, HTML本文)。"""
    tenant = one_line(tenant_name) or settings.app_name
    role_label = ROLE_LABEL.get(role, role)
    until = format_jst(expires_at)
    subject = f"【{tenant}】mokuture+ 管理画面への招待"

    text = "\n".join([
        f"{tenant} の mokuture+ 管理画面に招待されました。",
        "",
        "下のリンクを開いてパスワードを決めると、ログインできるようになります。",
        url,
        "",
        f"ログインID（メールアドレス）：{to}",
        f"権限：{role_label}",
        f"招待した人：{inviter}",
        f"リンクの有効期限：{until} まで（日本時間）",
        "",
        "期限が切れた場合は、招待した人に送り直しを頼んでください。",
        "心当たりのない場合は、このメールを破棄してください（何も登録されません）。",
        "",
        "※このメールは送信専用です。ご返信いただけません。",
    ])

    accent = brand_color if re.fullmatch(r"#[0-9A-Fa-f]{3,8}", brand_color or "") else "#4a7c4e"
    e_tenant = escape(tenant)
    e_url = escape(url, quote=True)
    rows = [
        ("ログインID", to),
        ("権限", role_label),
        ("招待した人", inviter),
        ("有効期限", f"{until} まで（日本時間）"),
    ]
    detail_html = "".join(
        f'<tr>'
        f'<td style="padding:6px 14px 6px 0;color:#8a8478;font-size:13px;white-space:nowrap;vertical-align:top">{escape(k)}</td>'
        f'<td style="padding:6px 0;color:#2d2a24;font-size:14px;font-weight:600;word-break:break-all">{escape(v)}</td>'
        f'</tr>'
        for k, v in rows
    )
    html = f"""\
<!DOCTYPE html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f4f1ea;font-family:'Hiragino Kaku Gothic ProN','Noto Sans JP',sans-serif">
  <div style="max-width:520px;margin:0 auto;padding:28px 16px">
    <div style="background:#fffefb;border:1px solid #e7e3d9;border-radius:16px;overflow:hidden">
      <div style="height:6px;background:{accent}"></div>
      <div style="padding:28px 30px">
        <p style="margin:0 0 4px;font-size:12px;color:#a8a198;letter-spacing:.04em">{e_tenant}</p>
        <h1 style="margin:0 0 18px;font-size:20px;color:#1d1a15">管理画面への招待</h1>
        <p style="margin:0 0 22px;font-size:14px;line-height:1.8;color:#4a463d">
          {e_tenant} の mokuture+ 管理画面に招待されました。<br>
          下のボタンからパスワードを決めると、ログインできるようになります。
        </p>
        <div style="text-align:center;margin:0 0 24px">
          <a href="{e_url}" style="display:inline-block;padding:13px 28px;background:{accent};color:#fff;text-decoration:none;border-radius:10px;font-size:15px;font-weight:700">パスワードを決めて登録する</a>
        </div>
        <table style="width:100%;border-collapse:collapse;margin:0 0 18px">{detail_html}</table>
        <p style="margin:0 0 6px;font-size:12px;line-height:1.7;color:#8a8478">
          ボタンが開けない場合は、次の URL をブラウザに貼り付けてください。
        </p>
        <p style="margin:0 0 16px;font-size:11px;color:#6b6559;font-family:monospace;word-break:break-all">{escape(url)}</p>
        <p style="margin:0;font-size:12px;line-height:1.7;color:#8a8478">
          期限が切れた場合は、招待した人に送り直しを頼んでください。<br>
          心当たりのない場合は、このメールを破棄してください（何も登録されません）。
        </p>
      </div>
      <div style="padding:14px 30px;background:#f7f5f0;border-top:1px solid #efece5">
        <p style="margin:0;font-size:11px;color:#a8a198;line-height:1.7">
          ※このメールは送信専用です。ご返信いただけません。<br>— {e_tenant}（mokuture+）
        </p>
      </div>
    </div>
  </div>
</body></html>"""
    return subject, text, html
