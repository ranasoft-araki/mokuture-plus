// 起動ゲート（/）: ログイン状態を hydration 前にインライン script で同期判定し、
// ログイン済みなら /login を素通りして直接ダッシュボードへ location.replace する。
// 従来は / → 307 → /login をフル起動(React hydrate)してから useEffect で初めて
// リダイレクト判定していたため、ログイン画面のフル起動(スマホで数秒)がまるごと無駄だった。
// このゲートは React を一切 hydrate せず（script が即 replace で離脱する）、
// アプリの「二重起動」を解消する。判定ロジックは lib/auth.ts の getHomeUrl と一致させること。
//
// 静的HTMLとして配信（Netlify CDN 即応答・SW でも cache-first）。

export const dynamic = "force-static";

// getHomeUrl(lib/auth.ts) と同じ分岐を素の JS で再現する。
const GATE = `(function(){try{
var ss=window.sessionStorage,ls=window.localStorage;
var g=function(k){return ss.getItem(k)||ls.getItem(k);};
var refresh=g('mokuture_refresh'),role=g('mokuture_role'),slug=g('mokuture_slug');
var dest='/login';
if(refresh){
  if(role==='operator')dest='/operator';
  else if(role==='reseller')dest=slug?('/'+slug+'/reseller'):'/login';
  else if(slug)dest='/'+slug+'/admin';
}
location.replace(dest);
}catch(e){location.replace('/login');}})();`;

export default function Home() {
  return (
    <>
      <script dangerouslySetInnerHTML={{ __html: GATE }} />
      {/* replace が走るまでの一瞬だけ見える背景（ダッシュボードの下地色と揃える） */}
      <div style={{ width: "100vw", height: "100vh", background: "#faf8f4" }} />
    </>
  );
}
