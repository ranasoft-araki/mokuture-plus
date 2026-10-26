"""SMTP メール送信サービス(来社予定QRのメール送信)。

webpush.py と同じ best-effort パターン: ライブラリ不在は `_AVAILABLE` フラグで握り、
送信は `(success, error_message)` タプルを返す(呼び出し側は受付/発行を止めない)。
QR画像は segno(pure-python, PIL不要)で `appt:<token>` の PNG を生成し CID インライン画像+添付にする。
"""
import io
import logging
from email.message import EmailMessage
from email.utils import formataddr

logger = logging.getLogger(__name__)

try:
    import aiosmtplib
    _AVAILABLE = True
except ImportError:
    _AVAILABLE = False
    logger.warning("aiosmtplib not installed — email disabled. Run: uv add aiosmtplib")


def build_appointment_qr_png(token: str, scale: int = 6, border: int = 3) -> bytes:
    """`appt:<token>` の QR を PNG バイト列で生成する(segno, pure-python・PIL不要)。

    キオスクの読取仕様(`appt:<token>`)と一致させる。表示用フロント(qrcode.react)と同じ値。
    """
    import segno

    buf = io.BytesIO()
    segno.make(f"appt:{token}", error="m").save(buf, kind="png", scale=scale, border=border)
    return buf.getvalue()


async def send_email(
    to: str,
    subject: str,
    html: str,
    text: str,
    *,
    host: str,
    port: int = 587,
    username: str = "",
    password: str = "",
    from_addr: str = "",
    from_name: str = "",
    starttls: bool = True,
    use_ssl: bool = False,
    inline_images: list[tuple[str, bytes, str]] | None = None,   # (cid, data, subtype)
    attachments: list[tuple[str, bytes, str, str]] | None = None,  # (filename, data, maintype, subtype)
    timeout: float = 20.0,
) -> tuple[bool, str]:
    """1通のメールを送信する。Returns (success, error_message)。best-effort(例外を握って返す)。

    inline_images の各 cid は HTML 内で `cid:<cid>` として参照する(Gmail/Outlook は data URI を
    ブロックするため、QRは CID インライン画像で埋め込む)。同じ画像を添付にも入れて保存もできるようにする。
    """
    if not _AVAILABLE:
        return False, "aiosmtplib 未インストール"
    if not host:
        return False, "SMTP が設定されていません"

    sender = from_addr or username
    if not sender:
        return False, "差出人アドレス(smtp_from / smtp_username)が未設定です"

    msg = EmailMessage()
    msg["From"] = formataddr((from_name, sender)) if from_name else sender
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text)                       # text/plain(フォールバック)
    msg.add_alternative(html, subtype="html")   # → multipart/alternative[plain, html]

    if inline_images:
        html_part = msg.get_payload()[-1]       # 直近に追加した html パート
        for cid, data, subtype in inline_images:
            # html パートを multipart/related[html, image] へ包む。HTML は `cid:<cid>` で参照。
            html_part.add_related(data, maintype="image", subtype=subtype, cid=f"<{cid}>")

    if attachments:
        for filename, data, maintype, subtype in attachments:
            msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=filename)

    try:
        await aiosmtplib.send(
            msg,
            hostname=host,
            port=port,
            username=username or None,
            password=password or None,
            start_tls=(starttls and not use_ssl),
            use_tls=use_ssl,
            timeout=timeout,
        )
        return True, ""
    except Exception as e:  # noqa: BLE001 — best-effort。認証/接続/ポリシー等を一括で握る
        error_msg = str(e)[:400]
        logger.error("email send failed to=%s… : %s", to[:40], error_msg)
        return False, error_msg
