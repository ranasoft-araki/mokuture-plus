"""レート制限のキー（接続元 IP）。

本番(Render)ではリクエストがロードバランサ経由で届くため、ソケットの相手は
常にプロキシで、全員が同じ IP に見える(=制限が全員で1つの枠を取り合う)。
そこで `X-Forwarded-For` から接続元を取る。

どの値を使うか: このヘッダはクライアントが自由に書けるので、**左側の値は信用しない**。
各プロキシは自分が受け取った相手の IP を右端に足していくので、**右から順に見て、
最初に現れる公開アドレス**(=手前のプロキシが実際に受け取った相手)を使う。
プライベート・ループバックの値はプロキシ同士の中継なので読み飛ばす。
公開アドレスが1つも無ければソケットの相手(従来どおり)に戻る。
`settings.trust_forwarded_for=False` にするとヘッダを見ない(プロキシの無い構成用)。
"""
from __future__ import annotations

import ipaddress

from starlette.requests import Request

from app.config import settings


def _forwarded_client(header: str) -> str | None:
    for raw in reversed(header.split(",")):
        value = raw.strip()
        if not value:
            continue
        # "1.2.3.4:5678" や "[::1]:80" の形も受ける。
        if value.startswith("[") and "]" in value:
            value = value[1:value.index("]")]
        elif value.count(":") == 1:
            value = value.split(":", 1)[0]
        try:
            ip = ipaddress.ip_address(value)
        except ValueError:
            continue
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_unspecified:
            continue
        return str(ip)
    return None


def client_ip(request: Request) -> str:
    """レート制限のキーにする接続元 IP。"""
    if settings.trust_forwarded_for:
        header = request.headers.get("x-forwarded-for")
        if header:
            found = _forwarded_client(header)
            if found:
                return found
    if request.client and request.client.host:
        return request.client.host
    return "127.0.0.1"
