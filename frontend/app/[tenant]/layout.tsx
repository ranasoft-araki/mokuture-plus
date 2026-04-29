import { Suspense } from "react";
import ProxyLoginHandler from "./ProxyLoginHandler";

// キオスク静的ビルド時に使用するテナントスラッグを指定する。
// KIOSK_TENANT_SLUG 未設定の場合は空配列を返し、Netlify 側は SSR で動的処理する。
export async function generateStaticParams() {
  const slug = process.env.KIOSK_TENANT_SLUG;
  return slug ? [{ tenant: slug }] : [];
}

export default async function TenantLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ tenant: string }>;
}) {
  const { tenant } = await params;
  return (
    <Suspense fallback={<>{children}</>}>
      <ProxyLoginHandler tenant={tenant}>
        {children}
      </ProxyLoginHandler>
    </Suspense>
  );
}
