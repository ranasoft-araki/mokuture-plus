"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import KioskFlow from "./KioskFlow";

export default function KioskPage() {
  const params = useParams<{ tenant: string }>();
  const router = useRouter();
  const [token, setToken] = useState<string | null>(null);

  useEffect(() => {
    const stored = localStorage.getItem("mokuture_kiosk_token");
    if (!stored) {
      router.replace(`/${params.tenant}/kiosk/setup`);
    } else {
      setToken(stored);
    }
  }, [params.tenant, router]);

  if (!token) return null;

  return <KioskFlow kioskToken={token} />;
}
