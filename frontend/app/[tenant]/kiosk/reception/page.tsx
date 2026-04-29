"use client";
import { useEffect } from "react";
import { useParams, useRouter } from "next/navigation";

// KioskFlow manages all screen state — sub-routes redirect to the main kiosk page.
export default function KioskSubPage() {
  const params = useParams<{ tenant: string }>();
  const router = useRouter();
  useEffect(() => {
    router.replace(`/${params.tenant}/kiosk`);
  }, [params.tenant, router]);
  return null;
}
