"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { saveTokens } from "@/lib/auth";

export default function LoginPage() {
  const router = useRouter();
  const [tab, setTab] = useState<"login" | "register">("login");
  const [form, setForm] = useState({ email: "", password: "", tenant_name: "", tenant_slug: "" });
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handle = (field: string, value: string) => setForm((f) => ({ ...f, [field]: value }));

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      let tokens;
      if (tab === "login") {
        tokens = await api.login(form.email, form.password);
      } else {
        tokens = await api.register({ tenant_name: form.tenant_name, tenant_slug: form.tenant_slug, email: form.email, password: form.password });
      }
      saveTokens(tokens.access_token, tokens.refresh_token);
      router.push(`/${tokens.tenant_slug}/admin`);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "エラーが発生しました");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#faf8f4] flex items-center justify-center p-4">
      <div className="w-full max-w-md bg-white rounded-2xl shadow-lg p-8 space-y-6">
        <div className="text-center">
          <h1 className="text-2xl font-semibold text-[#1d1a15]">mokuture+</h1>
          <p className="text-[#8a8070] text-sm mt-1">管理画面</p>
        </div>

        <div className="flex border border-[#e2ddd6] rounded-lg p-1 gap-1">
          {(["login", "register"] as const).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`flex-1 py-2 rounded-md text-sm font-medium transition-colors ${tab === t ? "bg-[#4a7c4e] text-white" : "text-[#5a5347]"}`}
            >
              {t === "login" ? "ログイン" : "新規登録"}
            </button>
          ))}
        </div>

        {error && <div className="bg-red-50 border border-red-200 rounded-lg px-4 py-3 text-red-700 text-sm">{error}</div>}

        <form onSubmit={submit} className="space-y-4">
          {tab === "register" && (
            <>
              <FormField label="テナント名（会社名など）">
                <input type="text" value={form.tenant_name} onChange={(e) => handle("tenant_name", e.target.value)} className="form-input" placeholder="磯野木工所" required />
              </FormField>
              <FormField label="テナントスラッグ（URLに使用）">
                <input type="text" value={form.tenant_slug} onChange={(e) => handle("tenant_slug", e.target.value.toLowerCase())} className="form-input" placeholder="isonoki" pattern="[a-z0-9\-]{3,64}" required />
                <p className="text-xs text-[#8a8070] mt-1">小文字・数字・ハイフンのみ 3〜64文字</p>
              </FormField>
            </>
          )}
          <FormField label="メールアドレス">
            <input type="email" value={form.email} onChange={(e) => handle("email", e.target.value)} className="form-input" required />
          </FormField>
          <FormField label="パスワード">
            <input type="password" value={form.password} onChange={(e) => handle("password", e.target.value)} className="form-input" minLength={8} required />
          </FormField>
          <button type="submit" disabled={loading} className="w-full bg-[#4a7c4e] text-white py-3 rounded-lg font-medium disabled:opacity-50">
            {loading ? "処理中…" : tab === "login" ? "ログイン" : "アカウント作成"}
          </button>
        </form>
      </div>

      <style jsx global>{`
        .form-input { width:100%; border:1px solid #e2ddd6; border-radius:8px; padding:10px 14px; font-size:14px; outline:none; }
        .form-input:focus { border-color:#4a7c4e; }
      `}</style>
    </div>
  );
}

function FormField({ label, children }: { label: string; children: React.ReactNode }) {
  return <div className="space-y-1"><label className="text-sm font-medium text-[#1d1a15]">{label}</label>{children}</div>;
}
