"use client";

// ── 保存先の決まり ─────────────────────────────────────────────
// 通常のログイン: 「ログイン状態を保持」なら localStorage、しなければ sessionStorage。
// 代理ログイン(運営・代理店が顧客の管理画面を別タブで開く): そのタブの sessionStorage だけに置き、
//   `mk_proxy_session=1` を立てる。この印があるタブは sessionStorage しか読まない
//   (localStorage にある運営・代理店自身のログインへ切り替わらないように)。
//   代理ログインには refresh トークンが無い＝時間が来たら終わり、タブを開き直してもらう。
// 値が空文字のものは「無い」と扱う(app/page.tsx の起動ゲートも同じ扱い)。

const TOKEN_KEYS = ["mokuture_access", "mokuture_refresh", "mokuture_role", "mokuture_slug"] as const;

const PROXY_SESSION_KEY = "mk_proxy_session";
// 代理ログインのタブが終わった理由(画面の案内文を選ぶため)。"expired" | "start_failed"
const PROXY_END_KEY = "mk_proxy_end";

// 開く側 → 新しいタブへの受け渡し用の一時キー(localStorage・1回限り・短時間だけ有効)。
// 名前は固定。URL から受け取った名前のキーは読まない。
const HANDOFF_ACCESS = "mk_proxy_access";
const HANDOFF_TENANT = "mk_proxy_tenant";
const HANDOFF_EXPIRES = "mk_proxy_expires";
// 以前の版が置いていた refresh トークン(長期間有効)。見つけたら消すだけで使わない。
const LEGACY_HANDOFF_REFRESH = "mk_proxy_refresh";
const HANDOFF_TTL_MS = 60_000;

/** このタブが代理ログインのタブか。 */
export function isProxySession(): boolean {
  if (typeof window === "undefined") return false;
  try { return sessionStorage.getItem(PROXY_SESSION_KEY) === "1"; } catch { return false; }
}

function _get(k: string): string | null {
  if (typeof window === "undefined") return null;
  if (isProxySession()) return sessionStorage.getItem(k) || null;
  return sessionStorage.getItem(k) || localStorage.getItem(k) || null;
}

function _removeTabTokens() {
  TOKEN_KEYS.forEach((k) => sessionStorage.removeItem(k));
}

export function saveTokens(access: string, refresh: string, role: string | undefined, remember: boolean, slug?: string) {
  if (typeof window === "undefined") return;
  // 通常のログインをしたら、このタブの代理ログインは終わり
  if (isProxySession()) {
    _removeTabTokens();
    sessionStorage.removeItem(PROXY_SESSION_KEY);
    sessionStorage.removeItem(PROXY_END_KEY);
  }
  const store = remember ? localStorage : sessionStorage;
  store.setItem("mokuture_access", access);
  // 空の refresh トークンを「ある」ものとして保存しない
  if (refresh) store.setItem("mokuture_refresh", refresh);
  else store.removeItem("mokuture_refresh");
  if (role) store.setItem("mokuture_role", role);
  if (slug) store.setItem("mokuture_slug", slug);
}

export function getAccessToken(): string | null {
  return _get("mokuture_access");
}

export function getRefreshToken(): string | null {
  return _get("mokuture_refresh");
}

export function getRole(): string | null {
  return _get("mokuture_role");
}

export function getSlug(): string | null {
  return _get("mokuture_slug");
}

// 審査環境の閲覧専用アカウントか。アクセストークン(JWT)の ro クレームを見る。
// ログイン/refresh 時にサーバが demo1@ranasoft.co.jp 等へ ro=true を付与するため、
// 追加のAPI往復なしにトークンから同期的に判定できる（新しいトークンにも ro が引き継がれる）。
export function getReadonly(): boolean {
  const token = getAccessToken();
  if (!token) return false;
  try {
    const part = token.split(".")[1];
    if (!part) return false;
    let b64 = part.replace(/-/g, "+").replace(/_/g, "/");
    b64 += "=".repeat((4 - (b64.length % 4)) % 4);
    return JSON.parse(atob(b64)).ro === true;
  } catch {
    return false;
  }
}

export function clearTokens() {
  // 代理ログインのタブ: このタブの sessionStorage だけを消す。localStorage(運営・代理店自身の
  // ログイン)には触れない。印(mk_proxy_session)は残す＝消すと localStorage のログインを読みに行く。
  if (isProxySession()) {
    _removeTabTokens();
    return;
  }
  TOKEN_KEYS.forEach((k) => {
    localStorage.removeItem(k);
    sessionStorage.removeItem(k);
  });
  // ダッシュボードのキャッシュ即描画用データ(mk_stats_*)も消す
  // (共有端末で前ユーザーの集計値が一瞬でも残らないように)
  try {
    for (let i = localStorage.length - 1; i >= 0; i--) {
      const k = localStorage.key(i);
      if (k && k.startsWith("mk_stats_")) localStorage.removeItem(k);
    }
  } catch {}
}

/** 代理ログインの有効時間が切れたとき。このタブのトークンを消し、案内を出す状態にする。 */
export function endProxySession() {
  if (!isProxySession()) return;
  _removeTabTokens();
  sessionStorage.setItem(PROXY_END_KEY, "expired");
}

/** 代理ログインのタブで、案内を出すべき状態なら理由を返す(続けて使えるなら null)。 */
export function getProxyEndReason(): "expired" | "start_failed" | null {
  if (!isProxySession()) return null;
  if (sessionStorage.getItem("mokuture_access")) return null;
  return sessionStorage.getItem(PROXY_END_KEY) === "start_failed" ? "start_failed" : "expired";
}

/** 開く側: 新しいタブへ渡す一時キーを書く(短時間だけ有効)。 */
export function writeProxyHandoff(access: string, tenantSlug: string) {
  localStorage.setItem(HANDOFF_ACCESS, access);
  localStorage.setItem(HANDOFF_TENANT, tenantSlug);
  localStorage.setItem(HANDOFF_EXPIRES, String(Date.now() + HANDOFF_TTL_MS));
}

export const PROXY_POPUP_BLOCKED =
  "新しいタブを開けませんでした。ブラウザでこのサイトのポップアップを許可してから、もう一度「代理ログイン」を押してください。";

/**
 * 開く側: 代理ログイン用の空のタブを開く。ボタンを押した処理の中で、await より前に呼ぶこと
 * (通信の後に開くとポップアップとして止められる)。開けなければ null。
 */
export function openProxyTab(): Window | null {
  const w = window.open("", "_blank");
  if (!w || w.closed) return null;
  try {
    w.document.title = "代理ログイン";
    w.document.body.textContent = "代理ログインの準備をしています…";
  } catch {}
  return w;
}

/** 一時キーを消す(開く側の失敗時・受け取り後)。 */
export function clearProxyHandoff() {
  [HANDOFF_ACCESS, HANDOFF_TENANT, HANDOFF_EXPIRES, LEGACY_HANDOFF_REFRESH].forEach((k) => {
    try { localStorage.removeItem(k); } catch {}
  });
}

/** 期限切れ・期限の無い(以前の版の)一時キーを消す。代理ログイン以外の画面表示でも呼んでよい。 */
export function purgeStaleProxyHandoff() {
  try {
    localStorage.removeItem(LEGACY_HANDOFF_REFRESH);
    if (!localStorage.getItem(HANDOFF_ACCESS)) return;
    const exp = Number(localStorage.getItem(HANDOFF_EXPIRES) || "0");
    if (!exp || Date.now() > exp) clearProxyHandoff();
  } catch {}
}

/**
 * 受け取る側(新しいタブ): 一時キーを1回だけ使って、このタブを代理ログインのタブにする。
 * window.open で開いたタブには開いた側の sessionStorage が写っているので、最初にそれを消す。
 * 一時キーが無い・期限切れ・別テナント宛のときは、トークン無しの代理タブ(＝案内表示)にする。
 */
export function consumeProxyHandoff(tenantSlug: string): "installed" | "failed" {
  // StrictMode などで2回呼ばれても、受け取り済みのセッションを壊さない
  if (isProxySession() && sessionStorage.getItem("mokuture_access")
      && sessionStorage.getItem("mokuture_slug") === tenantSlug) {
    return "installed";
  }
  const access = localStorage.getItem(HANDOFF_ACCESS);
  const forTenant = localStorage.getItem(HANDOFF_TENANT);
  const exp = Number(localStorage.getItem(HANDOFF_EXPIRES) || "0");
  const valid = !!access && forTenant === tenantSlug && !!exp && Date.now() <= exp;
  // 別テナント宛の有効なキーは、そちらのタブのために残す(期限が来れば消える)
  if (valid || !access || !exp || Date.now() > exp) clearProxyHandoff();

  _removeTabTokens();
  sessionStorage.setItem(PROXY_SESSION_KEY, "1");
  if (!valid || !access) {
    sessionStorage.setItem(PROXY_END_KEY, "start_failed");
    return "failed";
  }
  sessionStorage.removeItem(PROXY_END_KEY);
  sessionStorage.setItem("mokuture_access", access);
  sessionStorage.setItem("mokuture_role", "admin");
  sessionStorage.setItem("mokuture_slug", tenantSlug);
  return "installed";
}

// トークンの入れ替え(refresh・パスワード変更後)。いまのセッションと同じ保存先に書く。
export function refreshSaveTokens(access: string, refresh: string) {
  if (typeof window === "undefined") return;
  if (isProxySession()) {
    // 代理ログインのタブは refresh トークンを持たない(長期間のログインにしない)
    sessionStorage.setItem("mokuture_access", access);
    return;
  }
  const store = sessionStorage.getItem("mokuture_access") ? sessionStorage : localStorage;
  store.setItem("mokuture_access", access);
  if (refresh) store.setItem("mokuture_refresh", refresh);
}

export function getLogoutUrl(): string {
  const role = getRole();
  if (role === "operator") return "/ops-console";
  if (role === "reseller") return "/partner-portal";
  return "/login";
}

// ログイン済みセッションがある場合に「開いたら中へ」自動遷移する先を返す。
// slug が無い（本機能導入前の旧セッション等）場合は null=遷移せずログイン画面を表示。
// 代理ログインのタブは refresh トークンを持たないので常に null(ログイン画面)。
// app/page.tsx の起動ゲートと分岐を揃えること。
export function getHomeUrl(): string | null {
  if (typeof window === "undefined") return null;
  if (!getRefreshToken()) return null;
  const role = getRole();
  const slug = getSlug();
  if (role === "operator") return "/operator";
  if (role === "reseller") return slug ? `/${slug}/reseller` : null;
  return slug ? `/${slug}/admin` : null;
}

// ログインIDのみ端末に記憶する（パスワードは保存しない）。ログアウトでは消さない。
export function rememberLoginId(key: string, id: string) {
  if (typeof window === "undefined") return;
  if (id) localStorage.setItem(`mokuture_saved_id_${key}`, id);
}

export function getSavedLoginId(key: string): string {
  if (typeof window === "undefined") return "";
  return localStorage.getItem(`mokuture_saved_id_${key}`) ?? "";
}
