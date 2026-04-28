"use client";
import { useEffect } from "react";
import { useRouter, useParams } from "next/navigation";

export default function KioskTopRedirect() {
  const params = useParams<{ tenant: string }>();
  const router = useRouter();
  useEffect(() => {
    router.replace(`/${params.tenant}/kiosk`);
  }, [params.tenant, router]);
  return null;
}
