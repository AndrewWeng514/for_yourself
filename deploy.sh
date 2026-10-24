#!/usr/bin/env bash
# 部署脚本：把代码同步到 Ubuntu → 重启服务 → 健康检查。
# 只同步运行时代码（app/ web/ server.py），不碰 data/ logs/，也不提交 git。
# git 提交在人工验证通过后另行执行（验证 = 用户在页面上确认回复「通过」）。
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

echo "[1/3] 打包代码（app/ web/ server.py）..."
tar -czf "$TARBALL" --exclude='__pycache__' --exclude='*.pyc' app web server.py

echo "[2/3] 上传到 ${HOST} ..."
scp $SSH_OPTS "$TARBALL" "${HOST}:~/dividend-code.tar.gz"

echo "[3/3] 解压并重启服务 ..."
ssh $SSH_OPTS "$HOST" "
  set -e
  cd '${REMOTE_DIR}'
  rm -rf app web server.py
  tar -xzf ~/dividend-code.tar.gz
  rm -f ~/dividend-code.tar.gz
  systemctl --user restart dividend-app.service
"

echo "=== 健康检查 ==="
ssh $SSH_OPTS "$HOST" "sleep 1; curl -s http://127.0.0.1:8000/api/health" \
  || echo "(健康检查失败，请人工查看)"
echo
echo "已同步并重启。请到 http://${DISPLAY_HOST}:8000/ 确认效果，"
echo "回复『通过』后我再提交 git。"
