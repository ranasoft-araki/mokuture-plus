"use client";
import { useEffect } from "react";
import { useRouter, useParams } from "next/navigation";

export default function KioskQRRedirect() {
  const params = useParams<{ tenant: string }>();
  const router = useRouter();
  useEffect(() => {
    router.replace(`/${params.tenant}/kiosk?screen=qr`);
  }, [params.tenant, router]);
  return null;
}
