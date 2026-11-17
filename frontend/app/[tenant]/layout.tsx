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
  // fallback に children を置かない: 置くと代理ログインの受け取り(ProxyLoginHandler)を通らずに
  // 子が描かれ、受け取り前のトークンで通信が走りうる。
  return (
    <Suspense fallback={null}>
      <ProxyLoginHandler tenant={tenant}>
        {children}
      </ProxyLoginHandler>
    </Suspense>
  );
}
