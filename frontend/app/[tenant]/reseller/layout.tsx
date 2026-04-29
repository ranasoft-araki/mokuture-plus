"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { getRole, getAccessToken } from "@/lib/auth";
import { ResellerShell } from "@/components/ResellerShell";

export default function ResellerLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();

  useEffect(() => {
    const role = getRole();
    const token = getAccessToken();
    if (!token || (role !== "reseller" && role !== "operator")) {
      router.replace("/partner-portal");
    }
  }, [router]);

  return <ResellerShell>{children}</ResellerShell>;
}
