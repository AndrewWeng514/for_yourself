#!/usr/bin/env bash
# 备份个人门户：日记目录 + SQLite 数据库（不含 AI Key）。
#
# 默认：
#   日记：~/文档/portal-diary
#   数据库：~/文档/dividend-app/data/app.db
#   备份：~/portal-backups
#
# 可用环境变量覆盖：
#   PORTAL_DIARY_DIR / PORTAL_DB / PORTAL_BACKUP_DIR / PORTAL_BACKUP_KEEP_DAYS
set -euo pipefail

DIARY_DIR="${PORTAL_DIARY_DIR:-$HOME/文档/portal-diary}"
DB_FILE="${PORTAL_DB:-$HOME/文档/dividend-app/data/app.db}"
DEST="${PORTAL_BACKUP_DIR:-$HOME/portal-backups}"
KEEP_DAYS="${PORTAL_BACKUP_KEEP_DAYS:-14}"

mkdir -p "$DEST"
STAMP="$(date +%Y%m%d-%H%M%S)"
OUT="$DEST/portal-$STAMP.tgz"

if [ ! -d "$DIARY_DIR" ]; then
  echo "日记目录不存在：$DIARY_DIR" >&2
  exit 2
fi

args=(-czf "$OUT" -C "$(dirname "$DIARY_DIR")" "$(basename "$DIARY_DIR")")
if [ -f "$DB_FILE" ]; then
  args+=(-C "$(dirname "$DB_FILE")" "$(basename "$DB_FILE")")
fi

tar "${args[@]}"
chmod 600 "$OUT"

# 只保留最近 N 天
find "$DEST" -maxdepth 1 -type f -name 'portal-*.tgz' -mtime +"$KEEP_DAYS" -delete

echo "备份完成：$OUT"
du -h "$OUT" | awk '{print "大小：" $1}'
