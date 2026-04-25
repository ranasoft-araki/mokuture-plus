#!/usr/bin/env bash
# deploy.sh — mokuture+ 一括デプロイスクリプト
# 使い方: ./deploy.sh [コミットメッセージ]
# 例:     ./deploy.sh "feat: プレイリスト管理UI追加"

set -e

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_DIR"

# ─── 色定義 ─────────────────────────────────────────────────
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; CYAN='\033[0;36m'; NC='\033[0m'

echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${CYAN}  mokuture+ デプロイ                                       ${NC}"
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

# ─── 変更確認 ────────────────────────────────────────────────
echo -e "\n${YELLOW}[1/4] 変更ファイルを確認${NC}"
git status --short
echo ""

CHANGED=$(git status --porcelain)

# ─── TypeScript 型チェック ───────────────────────────────────
echo -e "${YELLOW}[2/4] TypeScript 型チェック${NC}"
if command -v npx &> /dev/null; then
  cd frontend
  if npx tsc --noEmit 2>&1; then
    echo -e "${GREEN}✓ 型チェック OK${NC}"
  else
    echo -e "${RED}✗ 型エラーがあります。デプロイを中止します。${NC}"
    exit 1
  fi
  cd ..
else
  echo -e "${YELLOW}npx が見つからないため型チェックをスキップ${NC}"
fi

# ─── コミット（変更がある場合のみ）─────────────────────────
echo -e "\n${YELLOW}[3/4] コミット & プッシュ${NC}"

if [ -n "$CHANGED" ]; then
  # コミットメッセージ（引数があれば使用、なければ自動生成）
  if [ -n "$1" ]; then
    MSG="$1"
  else
    TIMESTAMP=$(date '+%Y-%m-%d %H:%M')
    MSG="deploy: ${TIMESTAMP}"
  fi
  git add -A
  git commit -m "$MSG"
  echo -e "${GREEN}✓ コミット: ${MSG}${NC}"
else
  echo -e "${YELLOW}ローカルに新しい変更はありません。リビルドのためプッシュします。${NC}"
fi

# ─── プッシュ（変更有無に関わらず実行）─────────────────────
git push origin master
echo -e "${GREEN}✓ GitHub へプッシュ完了${NC}"

# ─── 完了 ────────────────────────────────────────────────────
echo -e "\n${YELLOW}[4/4] デプロイ状況${NC}"
echo -e "  ${CYAN}Frontend (Netlify)${NC}"
echo -e "  → https://app.netlify.com/sites/mokuture-plus/deploys"
echo -e "  → https://mokuture-plus.netlify.app"
echo ""
echo -e "  ${CYAN}Backend (Render)${NC}"
echo -e "  → https://dashboard.render.com/web/srv-d7lvfpdckfvc739dhnp0"
echo -e "  → https://mokuture-plus-api.onrender.com"
echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}  デプロイ完了！ Netlify / Render のビルドが始まります。  ${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
