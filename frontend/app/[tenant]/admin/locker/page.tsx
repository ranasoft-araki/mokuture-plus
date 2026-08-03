"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { useRouter } from "next/navigation";
import { AdminShell } from "@/components/AdminShell";
import { api, LockerDeviceStatus, LockerStatusItem } from "@/lib/api";
import { subscribeRealtime } from "@/lib/realtime";
import { getAccessToken, clearTokens } from "@/lib/auth";

const FONT_MONO = '"JetBrains Mono", "SF Mono", ui-monospace, Menlo, monospace';

// ─── time helpers（naive UTC を "Z" 補完して解釈） ───────────────────────────
function utcDate(value: string): Date {
  return new Date(/[Z+]/.test(value) ? value : value + "Z");
}
function formatRelative(value: string | null): string {
  if (!value) return "—";
  const diff = Date.now() - utcDate(value).getTime();
  const sec = Math.floor(diff / 1000);
  if (sec < 5) return "たった今";
  if (sec < 60) return `${sec}秒前`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}分前`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}時間前`;
  return `${Math.floor(hr / 24)}日前`;
}

// ─── Locker cell（表示専用） ────────────────────────────────────────────────
function LockerCell({ locker }: { locker: LockerStatusItem }) {
  const occupied = locker.occupied;
  const isDelivery = occupied && locker.kind === "delivery";
  return (
    <div
      style={{
        background: "#fffefb",
        border: `1px solid ${occupied ? "#e4cfa0" : "#d8d3c7"}`,
        borderRadius: 10,
        padding: "14px 14px",
        display: "flex",
        flexDirection: "column",
        gap: 8,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
        <div style={{ fontSize: 14, fontWeight: 700, color: "#1d1a15", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {locker.name}
        </div>
        {locker.door_number != null && (
          <div style={{ fontSize: 11, fontFamily: FONT_MONO, color: "#a8a198", flexShrink: 0 }}>
            #{locker.door_number}
          </div>
        )}
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
        <span
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 5,
            padding: "3px 10px",
            borderRadius: 999,
            fontSize: 11.5,
            fontWeight: 600,
            background: occupied ? "#f3e2c0" : "#dcecdd",
            color: occupied ? "#8a5a1a" : "#3a6240",
          }}
        >
          <span style={{ width: 7, height: 7, borderRadius: "50%", background: occupied ? "#c8862a" : "#4a7c4e" }} />
          {occupied ? "利用中" : "空き"}
        </span>
        {isDelivery && (
          <span
            style={{
              display: "inline-block",
              padding: "3px 8px",
              borderRadius: 999,
              fontSize: 11,
              fontWeight: 600,
              background: "#e6eef6",
              color: "#3a5a7c",
            }}
          >
            置き配
          </span>
        )}
      </div>
    </div>
  );
}

// ─── Device section ─────────────────────────────────────────────────────────
function DeviceSection({ device }: { device: LockerDeviceStatus }) {
  return (
    <div
      style={{
        background: "#fbf9f5",
        border: "1px solid #e6e2d9",
        borderRadius: 12,
        padding: 18,
        marginBottom: 16,
      }}
    >
      {/* header */}
      <div style={{ display: "flex", alignItems: "center", flexWrap: "wrap", gap: 10, marginBottom: 14 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 15, fontWeight: 700, color: "#1d1a15" }}>{device.device_name}</div>
          <div style={{ fontSize: 12, color: "#a8a198" }}>
            {device.location ?? "場所未設定"} · 更新 {formatRelative(device.updated_at)}
          </div>
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <span style={{ padding: "4px 12px", borderRadius: 999, fontSize: 12, fontWeight: 600, background: "#dcecdd", color: "#3a6240" }}>
            空き {device.available_count}
          </span>
          <span style={{ padding: "4px 12px", borderRadius: 999, fontSize: 12, fontWeight: 600, background: "#f3e2c0", color: "#8a5a1a" }}>
            利用中 {device.occupied_count}
          </span>
          <span style={{ padding: "4px 12px", borderRadius: 999, fontSize: 12, fontWeight: 600, background: "#efece5", color: "#6b6559" }}>
            全 {device.total}
          </span>
        </div>
      </div>

      {/* grid */}
      {device.lockers.length === 0 ? (
        <div style={{ fontSize: 12.5, color: "#a8a198", padding: "8px 0" }}>ロッカーがありません。</div>
      ) : (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))",
            gap: 12,
          }}
        >
          {device.lockers.map((l) => (
            <LockerCell key={l.id} locker={l} />
          ))}
        </div>
      )}
    </div>
  );
}

// ─── Main Page ─────────────────────────────────────────────────────────────
export default function AdminLockerPage() {
  const router = useRouter();
  const [devices, setDevices] = useState<LockerDeviceStatus[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const load = useCallback(async (silent: boolean) => {
    const token = getAccessToken();
    if (!token) { clearTokens(); router.push("/login"); return; }
    try {
      const data = await api.getLockerStatus(token);
      setDevices(data.devices);
      setError(null);
    } catch (err: unknown) {
      // 認証切れは初回のみログインへ。自動更新中のネットワーク一時失敗では画面を保持。
      if (!silent) { clearTokens(); router.push("/login"); return; }
      setError(err instanceof Error ? err.message : "取得に失敗しました");
    } finally {
      if (!silent) setLoading(false);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    load(false);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ニアリアルタイム連動: 端末がロッカーの占有状態を変えてミラーした瞬間に backend が SSE で
  // push → ロッカー状況を即再取得する。SSE が切れた稀なケースは 30秒ポーリングが拾う。
  useEffect(() => {
    if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null; }
    if (!autoRefresh) return;
    // 連続ミラー(複数端末が同時に報告する等)を300msでまとめて1回だけ取得する。
    let debounce: ReturnType<typeof setTimeout> | null = null;
    const unsub = subscribeRealtime((e) => {
      if (e.type !== "locker") return;
      if (debounce) return;
      debounce = setTimeout(() => { debounce = null; load(true); }, 300);
    });
    timerRef.current = setInterval(() => load(true), 30000); // フォールバック（SSE 断の保険）
    return () => {
      unsub();
      if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null; }
      if (debounce) clearTimeout(debounce);
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoRefresh]);

  const totalLockers = devices.reduce((n, d) => n + d.total, 0);
  const totalOccupied = devices.reduce((n, d) => n + d.occupied_count, 0);

  return (
    <AdminShell
      active="locker"
      title="ロッカー状況"
      breadcrumb="ホーム / ロッカー"
      subtitle={loading ? undefined : `${devices.length} 台 · 空き ${totalLockers - totalOccupied} / 全 ${totalLockers}`}
      actions={
        <label style={{ display: "inline-flex", alignItems: "center", gap: 8, fontSize: 13, color: "#6b6559", cursor: "pointer" }}>
          <input type="checkbox" checked={autoRefresh} onChange={(e) => setAutoRefresh(e.target.checked)} />
          自動更新
        </label>
      }
    >
      {/* Error banner (自動更新中のみ表示・非致命) */}
      {error && (
        <div
          style={{
            marginBottom: 16, padding: "10px 14px", borderRadius: 7,
            background: "#f6e0dc", border: "1px solid #a84238", color: "#a84238",
            fontSize: 13, display: "flex", alignItems: "center", gap: 8,
          }}
        >
          <span style={{ flex: 1 }}>{error}</span>
          <button onClick={() => setError(null)} style={{ background: "none", border: "none", cursor: "pointer", color: "#a84238", fontSize: 14 }}>×</button>
        </div>
      )}

      {/* 説明: ロッカーはローカル管理・ここは表示専用 */}
      <div
        style={{
          marginBottom: 18, padding: "12px 16px", borderRadius: 10,
          background: "#f4f6f2", border: "1px solid #dfe6da", color: "#4d5a48",
          fontSize: 12.5, lineHeight: 1.7,
        }}
      >
        ロッカーの施錠・解錠・暗証番号は各キオスク端末で管理されます（オフラインでも動作）。この画面は端末が報告した<strong>占有状況の表示専用</strong>です。
      </div>

      {loading ? (
        <div style={{ textAlign: "center", color: "#a8a198", fontSize: 13, padding: "60px 0" }}>
          読み込み中...
        </div>
      ) : devices.length === 0 ? (
        <div
          style={{
            background: "#fffefb", border: "1px solid #d8d3c7", borderRadius: 10,
            padding: "48px 24px", textAlign: "center", color: "#a8a198", fontSize: 13, lineHeight: 1.8,
          }}
        >
          ロッカーの状況はまだありません。<br />
          ロッカーを備えたキオスク端末が状況を送信すると、ここに端末ごとに表示されます。
        </div>
      ) : (
        <div>
          {devices.map((d) => (
            <DeviceSection key={d.device_id} device={d} />
          ))}
        </div>
      )}
    </AdminShell>
  );
}
