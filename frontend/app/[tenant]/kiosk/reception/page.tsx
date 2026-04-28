"use client";
import { useEffect } from "react";
import { useRouter, useParams, useSearchParams } from "next/navigation";
import { Suspense } from "react";

function ReceptionRedirectInner() {
  const params = useParams<{ tenant: string }>();
  const router = useRouter();
  const searchParams = useSearchParams();
  useEffect(() => {
    const purpose = searchParams.get("purpose") ?? "";
    const qs = new URLSearchParams({ screen: "reception" });
    if (purpose) qs.set("purpose", purpose);
    router.replace(`/${params.tenant}/kiosk?${qs.toString()}`);
  }, [params.tenant, router, searchParams]);
  return null;
}

export default function KioskReceptionRedirect() {
  return (
    <Suspense>
      <ReceptionRedirectInner />
    </Suspense>
  );
}
