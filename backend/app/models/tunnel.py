import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class TunnelSession(Base):
    """遠隔ログインの 1 回ぶん(運営が端末へ SSH で入るために開けた経路)。

    誰が・いつ・どの端末を・何のために開けたかの記録を兼ねる。端末やテナントを消しても
    記録は残したいので、外部キーは張らず、そのときの名前を写しておく。

    state:
      requested … 運営が要求した。端末がつなぎに来るのを待っている
      open      … 端末が踏み台へつないだ(運営が入れる)
      closing   … 終了を頼んだ(運営が押した・時間切れ)。端末が閉じたと報告するのを待っている
      closed    … 閉じた
    """
    __tablename__ = "tunnel_sessions"
    # 片づいていない遠隔ログインは、端末ごとに 1 件だけ。「開く」が同時に 2 つ届いても 2 件目は
    # 作らせない(2 件あると、終了しても古いほうが生き残って踏み台が鍵を通し続ける)。
    __table_args__ = (
        Index(
            "ix_tunnel_sessions_one_pending", "device_id", unique=True,
            sqlite_where=text("state IN ('requested', 'open', 'closing')"),
            postgresql_where=text("state IN ('requested', 'open', 'closing')"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    device_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    tenant_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    device_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    tenant_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    port: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="requested", index=True)
    requested_by_user_id: Mapped[str] = mapped_column(String(36), nullable=False)
    requested_by_email: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # 日時はすべて UTC naive
    requested_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    opened_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    close_requested_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    # 閉じた理由: operator(運営が終了を押した) / expired(時間切れ)。端末の「閉じた」が届かずに
    # 記録だけ閉じたときは、理由はそのままで error にその旨を書く
    close_reason: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    closed_by_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    # 端末が最後に報告した、つなげなかった理由(つながれば消す)
    error: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
