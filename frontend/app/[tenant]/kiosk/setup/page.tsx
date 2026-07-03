"use client";

import { useEffect } from "react";
import { useParams, useRouter } from "next/navigation";

// PIN セットアップは廃止。端末はキオスク画面を開くと自動登録され、管理画面での承認で起動する。
// 旧 URL（/kiosk/setup）に来た場合はキオスク画面へリダイレクトする。
export default function KioskSetupRedirect() {
  const params = useParams<{ tenant: string }>();
  const router = useRouter();

  useEffect(() => {
    router.replace(`/${params.tenant}/kiosk`);
  }, [params.tenant, router]);

  return (
    <div style={{ width: "100vw", height: "100vh", background: "#14110d", display: "flex", alignItems: "center", justifyContent: "center", color: "rgba(245,239,227,.6)", fontSize: 18, fontFamily: "Inter, 'Noto Sans JP', system-ui, sans-serif" }}>
      キオスク画面へ移動しています…
    </div>
  );
}
