"use client";

import { useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { saveTokens } from "@/lib/auth";

export default function ProxyLoginHandler({
  tenant,
  children,
}: {
  tenant: string;
  children: React.ReactNode;
}) {
  const router = useRouter();
  const searchParams = useSearchParams();

  useEffect(() => {
    const proxyKey = searchParams.get("proxy");
    if (!proxyKey) return;

    const shortToken = localStorage.getItem(proxyKey);
    if (!shortToken) return;

    // Consume the one-time key
    localStorage.removeItem(proxyKey);

    // Install the proxy token as the active session
    saveTokens(shortToken, "", "admin", true);

    // Clean the ?proxy= param from the URL
    router.replace("/" + tenant + "/admin");
  }, [searchParams, tenant, router]);

  return <>{children}</>;
}
