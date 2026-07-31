"""氏名の敬称ユーティリティ。

フロント `lib/honorific.ts`(withHonorific/hasHonorific)と同一規則。
既に敬称(様/さま/さん)で終わる名前(デモの来訪者名「審査員様」、法人名+様、"お客様" 等)
には「様」を重ねず、それ以外の氏名には「様」を付ける。キオスク/管理画面/メール/通知
すべてで訪問者名の敬称表示をこの規則に統一する。
"""

_HONORIFICS = ("様", "さま", "さん")


def has_honorific(name: str | None) -> bool:
    """名前が既に敬称(様/さま/さん)で終わっているか。"""
    return (name or "").strip().endswith(_HONORIFICS)


def with_honorific(name: str | None) -> str:
    """氏名に「様」を付ける。既に敬称で終わる名前には重ねない。空文字はそのまま返す。"""
    n = (name or "").strip()
    if not n:
        return n
    return n if n.endswith(_HONORIFICS) else f"{n} 様"
