"use client";
import { useEffect } from "react";
import { useRouter, useParams, useSearchParams } from "next/navigation";
import { Suspense } from "react";

function CallingRedirectInner() {
  const params = useParams<{ tenant: string }>();
  const router = useRouter();
  const searchParams = useSearchParams();
  useEffect(() => {
    const qs = new URLSearchParams({ screen: "calling" });
    const name = searchParams.get("name");
    const staff = searchParams.get("staff");
    if (name) qs.set("name", name);
    if (staff) qs.set("staff", staff);
    router.replace(`/${params.tenant}/kiosk?${qs.toString()}`);
  }, [params.tenant, router, searchParams]);
  return null;
}

export default function KioskCallingRedirect() {
  return (
    <Suspense>
      <CallingRedirectInner />
    </Suspense>
  );
}
