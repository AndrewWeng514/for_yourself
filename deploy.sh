#!/usr/bin/env bash
# 部署脚本：把代码同步到 Ubuntu → 备份旧代码 → 重启 → 健康检查 → 失败回滚。
# 只同步运行时代码（app/ web/ server.py），不碰 data/ logs/，也不提交 git。
#
# 目标机配置放在 deploy.local（不入库），内容形如：
#   HOST="wenghuawei@192.168.31.54"
#   REMOTE_DIR="/home/wenghuawei/文档/dividend-app"
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCAL_CONF="$DIR/deploy.local"

if [ -f "$LOCAL_CONF" ]; then
  # shellcheck disable=SC1090
  source "$LOCAL_CONF"
fi
: "${HOST:?请在 deploy.local 中配置 HOST=user@ip}"
: "${REMOTE_DIR:?请在 deploy.local 中配置 REMOTE_DIR=/home/user/项目目录}"

TARBALL="/tmp/dividend-code.tar.gz"
SSH_OPTS="-o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15"
DISPLAY_HOST="${HOST#*@}"

cd "$DIR"

echo "[1/4] 打包代码（app/ web/ server.py）..."
tar -czf "$TARBALL" --exclude='__pycache__' --exclude='*.pyc' app web server.py

echo "[2/4] 上传到 ${HOST} ..."
scp $SSH_OPTS "$TARBALL" "${HOST}:~/dividend-code.tar.gz"

echo "[3/4] 备份旧代码、解压并重启 ..."
ssh $SSH_OPTS "$HOST" "REMOTE_DIR='$REMOTE_DIR' bash -s" <<'REMOTE'
set -euo pipefail
cd "$REMOTE_DIR"

STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP_DIR="$REMOTE_DIR/.deploy-backups"
BACKUP="$BACKUP_DIR/code-$STAMP.tgz"
NEW_DIR="$REMOTE_DIR/.deploy-new-$STAMP"

mkdir -p "$BACKUP_DIR"
if [ -e app ] || [ -e web ] || [ -e server.py ]; then
  tar -czf "$BACKUP" app web server.py 2>/dev/null || true
fi

mkdir -p "$NEW_DIR"
tar -xzf "$HOME/dividend-code.tar.gz" -C "$NEW_DIR"

rollback() {
  echo "[rollback] 健康检查失败，恢复 $BACKUP"
  rm -rf app web server.py
  if [ -f "$BACKUP" ]; then
    tar -xzf "$BACKUP"
  fi
  systemctl --user restart dividend-app.service || true
  sleep 2
  curl -fsS http://127.0.0.1:8000/api/health || true
  exit 1
}

rm -rf app web server.py
cp -a "$NEW_DIR"/app "$NEW_DIR"/web "$NEW_DIR"/server.py .
rm -rf "$NEW_DIR" "$HOME/dividend-code.tar.gz"

if ! systemctl --user restart dividend-app.service; then
  rollback
fi

healthy=0
for _ in $(seq 1 20); do
  sleep 1
  if curl -fsS http://127.0.0.1:8000/api/health 2>/dev/null | grep -q '"ok": true'; then
    healthy=1
    break
  fi
done
if [ "$healthy" != "1" ]; then
  rollback
fi

# 只保留最近 10 份代码备份
ls -1t "$BACKUP_DIR"/code-*.tgz 2>/dev/null | tail -n +11 | xargs -r rm -f
echo "[deploy] ok, backup=$BACKUP"
REMOTE

echo "[4/4] 健康检查 ..."
ssh $SSH_OPTS "$HOST" "curl -fsS http://127.0.0.1:8000/api/health"
echo
echo "已同步并重启。请到 http://${DISPLAY_HOST}:8000/ 确认效果，"
echo "回复『通过』后我再提交 git。"
