"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { getRole, getAccessToken } from "@/lib/auth";
import { OperatorShell } from "@/components/OperatorShell";

export default function OperatorLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();

  useEffect(() => {
    const role = getRole();
    const token = getAccessToken();
    if (!token || role !== "operator") {
      router.replace("/ops-console");
    }
  }, [router]);

  return <OperatorShell>{children}</OperatorShell>;
}
