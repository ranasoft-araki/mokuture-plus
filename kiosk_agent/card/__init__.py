"""名刺認識（QR無し来訪者の受付フォーム自動入力）。

キオスク端末内で完結する。外部 OCR / 生成 AI / 外部 API は一切呼ばない。
ブラウザ(getUserMedia)が取得したフレームを HTTP で受け取り、検出→自動撮影判定→
台形補正→OCR→項目抽出までを Python 側で行い、結果を JSON で返す。

画像・抽出結果はいずれもディスクに書かない（プロセスメモリ上のセッションのみ）。
セッションは確定 / キャンセル / タイムアウトのいずれかで必ず破棄される。

依存(opencv / onnxruntime など)は任意。未導入の端末では `card.api` の import が
cv2 の不在で失敗するので、`main.py` 側が try/except で受けてルーターを登録しない
（= `/card/*` が生えない）。キオスク画面は起動時に `GET /card/status` を叩き、
404 や available=False なら「名刺で入力」を描画しない。

依存が入っていてモデルだけ無い場合は import に成功し、`GET /card/status` が
available=False と理由（どのモデルが無いか）を返す。
"""
