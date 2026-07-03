"use client";

import { useEffect, useRef, useState } from "react";
import { useParams } from "next/navigation";
import { api } from "@/lib/api";
import KioskFlow from "./KioskFlow";

const TOKEN_KEY = "mokuture_kiosk_token";
const NAME_KEY = "mokuture_kiosk_name";
const HWID_KEY = "mokuture_kiosk_hwid";

type Phase = "loading" | "pending" | "ready" | "error";

// Web キオスク端末の安定ID（承認待ちの重複登録を防ぐ）。ブラウザに一度だけ保存する。
function getHardwareId(): string {
  let id = localStorage.getItem(HWID_KEY);
  if (!id) {
    id = "web-" + (crypto?.randomUUID?.() ?? Math.random().toString(36).slice(2) + Date.now().toString(36));
    localStorage.setItem(HWID_KEY, id);
  }
  return id;
}

export default function KioskPage() {
  const params = useParams<{ tenant: string }>();
  const [phase, setPhase] = useState<Phase>("loading");
  const [token, setToken] = useState<string | null>(null);
  const [deviceName, setDeviceName] = useState<string>("");
  const [errorMsg, setErrorMsg] = useState<string>("");
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    const slug = params.tenant;
    let cancelled = false;

    // トークンを確保（無ければ自己登録）し、承認状態を判定する。
    async function boot() {
      let t = localStorage.getItem(TOKEN_KEY);
      let status = "active";
      let name = localStorage.getItem(NAME_KEY) ?? "";
      let tokenInvalidated = false; // 承認前に端末が削除された等でトークンが無効化されたか

      try {
        if (!t) {
          const reg = await api.registerKioskDevice({
            tenant_slug: slug,
            hardware_id: getHardwareId(),
          });
          t = reg.device_token;
          status = reg.status;
          name = reg.device_name;
          localStorage.setItem(TOKEN_KEY, t);
          localStorage.setItem(NAME_KEY, name);
        } else {
          const s = await api.getKioskStatus(t).catch((e) => {
            if (e instanceof Error && e.message === "Invalid kiosk token") {
              localStorage.removeItem(TOKEN_KEY);
              localStorage.removeItem(NAME_KEY);
              tokenInvalidated = true;
            }
            throw e;
          });
          status = s.status;
          name = s.device_name || name;
          localStorage.setItem(NAME_KEY, name);
        }
      } catch (e) {
        // トークンが無効化された場合のみ再登録からやり直す（数秒待ってバックオフ）。
        // 初回登録失敗（ネットワーク不通・500・429 等）はエラー画面を表示し、無限リトライを避ける。
        if (tokenInvalidated) {
          if (!cancelled) setTimeout(() => { if (!cancelled) void boot(); }, 3000);
          return;
        }
        if (!cancelled) {
          setErrorMsg(e instanceof Error ? e.message : "端末の登録に失敗しました");
          setPhase("error");
        }
        return;
      }

      if (cancelled) return;
      setToken(t);
      setDeviceName(name);

      if (status === "pending") {
        setPhase("pending");
        startPending(t!);
      } else {
        setPhase("ready");
      }
    }

    // 承認待ちポーリング: active になったら受付画面へ切り替える。
    function startPending(t: string) {
      if (pollRef.current) clearInterval(pollRef.current);
      pollRef.current = setInterval(async () => {
        try {
          const s = await api.getKioskStatus(t);
          if (cancelled) return;
          if (s.device_name) { setDeviceName(s.device_name); localStorage.setItem(NAME_KEY, s.device_name); }
          if (s.status !== "pending") {
            if (pollRef.current) clearInterval(pollRef.current);
            setPhase("ready");
          }
        } catch { /* keep polling */ }
      }, 4000);
    }

    void boot();
    return () => {
      cancelled = true;
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [params.tenant]);

  if (phase === "ready" && token) return <KioskFlow kioskToken={token} />;
  if (phase === "pending") return <PendingScreen deviceName={deviceName} />;
  if (phase === "error") return <ErrorScreen message={errorMsg} />;
  return <FullScreen>読み込み中…</FullScreen>;
}

function FullScreen({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ width: "100vw", height: "100vh", background: "#14110d", display: "flex", alignItems: "center", justifyContent: "center", color: "rgba(245,239,227,.6)", fontSize: 20, fontFamily: "Inter, 'Noto Sans JP', system-ui, sans-serif" }}>
      {children}
    </div>
  );
}

function PendingScreen({ deviceName }: { deviceName: string }) {
  return (
    <div style={{ width: "100vw", height: "100vh", background: "#14110d", display: "flex", alignItems: "center", justifyContent: "center", fontFamily: "Inter, 'Noto Sans JP', system-ui, sans-serif" }}>
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 32, textAlign: "center", padding: "0 40px", maxWidth: 640 }}>
        <p style={{ color: "#f5efe3", fontSize: 22, fontWeight: 300, letterSpacing: 6 }}>mokuture+</p>
        <div style={{ width: 72, height: 72, borderRadius: "50%", border: "3px solid rgba(122,180,120,.35)", borderTopColor: "#7ab478", animation: "mk-spin 1.1s linear infinite" }} />
        <div>
          <p style={{ color: "#faf8f4", fontSize: 30, fontWeight: 600, letterSpacing: 1 }}>承認待ちです</p>
          <p style={{ color: "rgba(245,239,227,.65)", fontSize: 16, marginTop: 14, lineHeight: 1.7 }}>
            管理画面の「キオスク端末」でこの端末を承認すると、<br />自動的に受付画面が表示されます。
          </p>
        </div>
        <div style={{ padding: "12px 24px", background: "rgba(255,255,255,.05)", border: "1px solid rgba(255,255,255,.12)", borderRadius: 12 }}>
          <span style={{ color: "rgba(245,239,227,.5)", fontSize: 13, letterSpacing: 1 }}>端末名</span>
          <span style={{ color: "#faf8f4", fontSize: 16, fontWeight: 600, marginLeft: 12 }}>{deviceName || "この端末"}</span>
        </div>
      </div>
      <style>{`@keyframes mk-spin{to{transform:rotate(360deg)}}`}</style>
    </div>
  );
}

function ErrorScreen({ message }: { message: string }) {
  return (
    <div style={{ width: "100vw", height: "100vh", background: "#14110d", display: "flex", alignItems: "center", justifyContent: "center", fontFamily: "Inter, 'Noto Sans JP', system-ui, sans-serif" }}>
      <div style={{ textAlign: "center", maxWidth: 560, padding: "0 40px", lineHeight: 1.7 }}>
        <p style={{ color: "#f2a6a6", fontSize: 22, fontWeight: 600 }}>端末の登録に失敗しました</p>
        <p style={{ color: "rgba(245,239,227,.6)", fontSize: 15, marginTop: 12 }}>{message}</p>
        <button
          onClick={() => location.reload()}
          style={{ marginTop: 28, padding: "12px 28px", borderRadius: 10, border: "none", background: "#4a7c4e", color: "#fffefb", fontSize: 15, fontWeight: 600, cursor: "pointer" }}
        >
          再試行
        </button>
      </div>
    </div>
  );
}
