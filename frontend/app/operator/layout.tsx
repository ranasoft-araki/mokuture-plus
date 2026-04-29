"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { getRole, getAccessToken } from "@/lib/auth";
import { OperatorShell } from "@/components/OperatorShell";
import { api } from "@/lib/api";

export default function OperatorLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [receptionUnread, setReceptionUnread] = useState(0);

  useEffect(() => {
    const role = getRole();
    const token = getAccessToken();
    if (!token || role !== "operator") {
      router.replace("/ops-console");
      return;
    }
    api.getOperatorStats(token)
      .then((s) => setReceptionUnread(s.reception_today_unread ?? 0))
      .catch(() => {});
  }, [router]);

  return <OperatorShell receptionUnread={receptionUnread}>{children}</OperatorShell>;
}
