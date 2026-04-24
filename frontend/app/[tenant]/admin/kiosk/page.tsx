"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { api, type Device } from "@/lib/api";
import { clearTokens, getAccessToken } from "@/lib/auth";

export default function AdminKioskPage() {
  const params = useParams<{ tenant: string }>();
  const router = useRouter();

  const [devices, setDevices] = useState<Device[]>([]);
  const [loading, setLoading] = useState(true);
  const [newName, setNewName] = useState("");
  const [creating, setCreating] = useState(false);
  const [newToken, setNewToken] = useState<{ name: string; token: string } | null>(null);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);

  const loadDevices = useCallback(async (token: string) => {
    try {
      setDevices(await api.listDevices(token));
    } catch {
      clearTokens();
      router.push("/login");
    } finally {
      setLoading(false);
    }
  }, [router]);

  useEffect(() => {
    const token = getAccessToken();
    if (!token) { router.push("/login"); return; }
    void loadDevices(token);
  }, [loadDevices, router]);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!newName.trim()) return;
    const token = getAccessToken();
    if (!token) { router.push("/login"); return; }
    setCreating(true);
    setError("");
    try {
      const created = await api.createDevice(token, newName.trim());
      setDevices((d) => [created, ...d]);
      setNewToken({ name: created.name, token: created.token });
      setNewName("");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "作成に失敗しました");
    } finally {
      setCreating(false);
    }
  }

  async function handleDelete(id: string, name: string) {
    if (!confirm(`「${name}」を削除すると、そのキオスク端末は使用できなくなります。続けますか？`)) return;
    const token = getAccessToken();
    if (!token) { router.push("/login"); return; }
    try {
      await api.deleteDevice(token, id);
      setDevices((d) => d.filter((dev) => dev.id !== id));
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "削除に失敗しました");
    }
  }

  async function handleCopy(token: string) {
    await navigator.clipboard.writeText(token);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  const kioskUrl = typeof window !== "undefined"
    ? `${window.location.origin}/${params.tenant}/kiosk`
    : `/${params.tenant}/kiosk`;

  return (
    <div className="min-h-screen bg-[#f5f2ed]">
      <div className="bg-white border-b border-[#e2ddd6] px-6 py-4 flex items-center gap-3">
        <button onClick={() => router.push(`/${params.tenant}/admin`)} className="text-[#8a8070] hover:text-[#1d1a15]">
          ← ダッシュボード
        </button>
        <span className="text-[#c8c0b0]">/</span>
        <span className="text-[#5a5347] font-medium">キオスク管理</span>
      </div>

      <div className="max-w-3xl mx-auto px-6 py-8 space-y-6">

        {/* Token revealed after creation */}
        {newToken && (
          <div className="bg-[#fffbe6] border border-[#f0d060] rounded-xl p-6 space-y-3">
            <p className="font-medium text-[#7a6000]">「{newToken.name}」のトークンが発行されました</p>
            <p className="text-sm text-[#7a6000]">このトークンは今後表示されません。キオスク端末のセットアップ画面に入力してください。</p>
            <div className="flex gap-2">
              <code className="flex-1 bg-white rounded-lg px-4 py-3 text-sm font-mono text-[#1d1a15] border border-[#e2ddd6] break-all">
                {newToken.token}
              </code>
              <button
                onClick={() => handleCopy(newToken.token)}
                className="shrink-0 px-4 py-2 rounded-lg bg-[#4a7c4e] text-white text-sm font-medium"
              >
                {copied ? "コピー済" : "コピー"}
              </button>
            </div>
            <p className="text-xs text-[#7a6000]">セットアップURL: <span className="font-mono">{kioskUrl}/setup</span></p>
            <button onClick={() => setNewToken(null)} className="text-xs text-[#8a8070] underline">閉じる</button>
          </div>
        )}

        {/* Add device form */}
        <div className="bg-white rounded-xl border border-[#e2ddd6] p-6">
          <h1 className="font-medium text-[#1d1a15] mb-1">キオスク端末を追加</h1>
          <p className="text-sm text-[#8a8070] mb-4">端末ごとに固有のトークンを発行します。トークンはセットアップ時に一度だけ表示されます。</p>
          <form onSubmit={handleCreate} className="flex gap-3">
            <input
              type="text"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder="例: 受付1F、ロビー端末"
              className="flex-1 border border-[#e2ddd6] rounded-lg px-4 py-2 text-sm focus:outline-none focus:border-[#4a7c4e]"
              required
            />
            <button
              type="submit"
              disabled={creating || !newName.trim()}
              className="bg-[#4a7c4e] text-white px-5 py-2 rounded-lg text-sm font-medium disabled:opacity-50"
            >
              {creating ? "発行中…" : "トークン発行"}
            </button>
          </form>
          {error && <p className="mt-3 text-sm text-red-600">{error}</p>}
        </div>

        {/* Device list */}
        <div className="bg-white rounded-xl border border-[#e2ddd6] overflow-hidden">
          <div className="px-6 py-4 border-b border-[#e2ddd6] flex items-center justify-between">
            <h2 className="font-medium text-[#1d1a15]">登録済み端末</h2>
            <span className="text-sm text-[#8a8070]">{devices.length}台</span>
          </div>

          {loading ? (
            <div className="px-6 py-8 text-center text-[#8a8070]">読み込み中…</div>
          ) : devices.length === 0 ? (
            <div className="px-6 py-8 text-center text-[#8a8070]">まだ端末が登録されていません</div>
          ) : (
            <div className="divide-y divide-[#f0ece6]">
              {devices.map((d) => (
                <div key={d.id} className="px-6 py-4 flex items-center gap-4">
                  <div className="w-10 h-10 rounded-full bg-[#e8f0e9] flex items-center justify-center shrink-0">
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#4a7c4e" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                      <rect x="2" y="3" width="20" height="14" rx="2" />
                      <line x1="8" y1="21" x2="16" y2="21" />
                      <line x1="12" y1="17" x2="12" y2="21" />
                    </svg>
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="font-medium text-[#1d1a15]">{d.name}</p>
                    <p className="text-xs text-[#8a8070] mt-0.5">
                      最終接続: {d.last_seen_at ? formatDate(d.last_seen_at) : "未接続"}
                      　発行: {formatDate(d.created_at)}
                    </p>
                  </div>
                  <button
                    onClick={() => handleDelete(d.id, d.name)}
                    className="shrink-0 px-3 py-1.5 rounded-lg text-sm text-red-600 hover:bg-red-50 border border-red-200"
                  >
                    削除
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="bg-white rounded-xl border border-[#e2ddd6] p-6 text-sm text-[#5a5347] space-y-2">
          <p className="font-medium text-[#1d1a15]">セットアップ手順</p>
          <ol className="list-decimal list-inside space-y-1 text-[#8a8070]">
            <li>上の「トークン発行」でキオスク端末の名前を入力して発行</li>
            <li>キオスク端末のブラウザで <span className="font-mono text-[#5a5347]">{kioskUrl}/setup</span> を開く</li>
            <li>表示されたトークンを入力して「設定を保存」</li>
            <li>以降は自動的にキオスク待機画面が表示される</li>
          </ol>
        </div>
      </div>
    </div>
  );
}

function formatDate(value: string) {
  if (!value) return "—";
  return new Date(value).toLocaleString("ja-JP", {
    year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit",
  });
}
