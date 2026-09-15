#!/bin/bash
# 公開入口 php/khojokin.php を heteml (kurage.exbridge.jp) へ FTP 配置する。
# 認証情報は aixec/.env の FTP_HOST / FTP_USER / FTP_PASS。
# バックエンドURLは khojokin_config.php（リポジトリ外）に書き出す。
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; . /home/kojima/work/aixec/.env; set +a
BACKEND="${KHOJOKIN_BACKEND_URL:-http://exbridge.ddns.net:18360}"
TMP=$(mktemp)
printf '<?php define("KHOJOKIN_BACKEND", "%s");\n' "$BACKEND" > "$TMP"
curl -sS -T php/khojokin.php "ftp://${FTP_USER}:${FTP_PASS}@${FTP_HOST}/web/kurage_exbridge_jp/khojokin.php"
curl -sS -T "$TMP" "ftp://${FTP_USER}:${FTP_PASS}@${FTP_HOST}/web/kurage_exbridge_jp/khojokin_config.php"
rm -f "$TMP"
echo "deployed: https://kurage.exbridge.jp/khojokin.php/"
curl -s -o /dev/null -w "public: %{http_code}\n" "https://kurage.exbridge.jp/khojokin.php/"
