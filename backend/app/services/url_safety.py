"""外へ送る URL(Webhook)と Web Push の送信先を確かめる。

管理画面で登録された URL へは、サーバーが自分から HTTP リクエストを送る。送信先が
サーバーの内側(自分自身・同じネットワークの機器・クラウドのメタデータ等)を指して
いると、外からは届かない場所へサーバーが代わりにリクエストを送ることになる。
そこで「公開されたインターネット上の https の宛先」だけを受け付ける。

確かめるのは2回: 保存するとき(400 で画面に理由を出す)と、送る直前(DNS の答えは
後から変わりうるので、その時点でもう一度見る。駄目なら送らず失敗として扱う)。
"""
from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket
from urllib.parse import urlsplit

from app.config import settings

logger = logging.getLogger(__name__)


class UnsafeUrlError(ValueError):
    """送信先として使えない URL。メッセージはそのまま画面に出せる日本語。"""


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """公開インターネット上の宛先でなければ True。"""
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        ip = mapped
    return (
        ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
        or not ip.is_global
    )


def _resolve(host: str, port: int) -> list[str]:
    """名前解決して IP アドレスの一覧を返す(同期。スレッドで呼ぶ)。

    テストではこの関数を差し替えて、外の DNS を引かずに判定だけを確かめる。"""
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return [info[4][0] for info in infos]


async def validate_public_url(url: str) -> None:
    """外へ送ってよい URL か確かめる。駄目なら `UnsafeUrlError`(日本語の理由つき)。

    - https のみ(開発時 `settings.debug` のときだけ http も可)
    - ホスト名が必要。IP アドレスを直接書いた URL は受け付けない
    - 名前解決した結果が1つでも内側のアドレス(ループバック・プライベート・
      リンクローカル・予約済み・マルチキャスト)なら受け付けない
    """
    raw = (url or "").strip()
    try:
        parts = urlsplit(raw)
    except ValueError:
        raise UnsafeUrlError("URL の形式が正しくありません")
    scheme = (parts.scheme or "").lower()
    allowed = {"https", "http"} if settings.debug else {"https"}
    if scheme not in allowed:
        raise UnsafeUrlError("URL は https:// で始めてください")
    host = (parts.hostname or "").strip().rstrip(".").lower()
    if not host:
        raise UnsafeUrlError("URL にホスト名がありません")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise UnsafeUrlError("IP アドレスを直接指定した URL は使えません。ホスト名で指定してください")
    if host == "localhost" or host.endswith(".localhost"):
        raise UnsafeUrlError("この URL は送信先に使えません")
    try:
        port = parts.port or (443 if scheme == "https" else 80)
    except ValueError:
        raise UnsafeUrlError("URL のポート番号が正しくありません")

    try:
        addresses = await asyncio.to_thread(_resolve, host, port)
    except (OSError, UnicodeError):
        raise UnsafeUrlError("URL のホスト名を確認できませんでした。URL をご確認ください")
    if not addresses:
        raise UnsafeUrlError("URL のホスト名を確認できませんでした。URL をご確認ください")
    for addr in addresses:
        try:
            ip = ipaddress.ip_address(addr.split("%", 1)[0])
        except ValueError:
            raise UnsafeUrlError("この URL は送信先に使えません")
        if _is_blocked_ip(ip):
            raise UnsafeUrlError("社内ネットワークなど外から届かない宛先の URL は使えません")


async def is_public_url(url: str) -> bool:
    """送る直前の確認用。駄目なら False(理由はログにだけ残す。URL そのものは出さない)。"""
    try:
        await validate_public_url(url)
        return True
    except UnsafeUrlError as e:
        logger.warning("outbound url rejected before send: %s", e)
        return False


# ── Web Push の送信先 ─────────────────────────────────────────────────────────
# ブラウザが発行する購読の送信先は、各ブラウザの配信サービスのものだけ。
# それ以外のホストは購読として受け付けない(サーバーから任意の宛先へ送らせないため)。
_PUSH_EXACT_HOSTS = {
    "fcm.googleapis.com",               # Chrome / Edge(Chromium) / Android ほか
    "updates.push.services.mozilla.com",  # Firefox
}
_PUSH_HOST_SUFFIXES = (
    "push.apple.com",                   # Safari / iOS(web.push.apple.com 等)
    "notify.windows.com",               # Windows(WNS)
    "push.services.mozilla.com",        # Firefox の配信ホスト
)


def is_allowed_push_endpoint(endpoint: str) -> bool:
    """Web Push の購読先として受け付けるか(https かつ既知の配信サービスのホスト)。"""
    try:
        parts = urlsplit((endpoint or "").strip())
    except ValueError:
        return False
    if (parts.scheme or "").lower() != "https":
        return False
    host = (parts.hostname or "").rstrip(".").lower()
    if not host:
        return False
    if host in _PUSH_EXACT_HOSTS:
        return True
    return any(host.endswith("." + suffix) for suffix in _PUSH_HOST_SUFFIXES)
