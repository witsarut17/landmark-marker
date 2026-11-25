#!/bin/sh
# เปิดเซิร์ฟเวอร์ PelNav เป็น container ชื่อ pelnav (คัดลอกไฟล์นี้ไปไว้ที่ <ROOT>/run.sh)
# --restart unless-stopped = เปิดเองตอนเปิดเครื่อง และเปิดใหม่เองถ้าดับ (แทน Task Scheduler ของ Windows)
# --network host = แอปเห็น IP จริงของผู้ใช้ จึงกรองเครือข่ายภายใน (allowed_networks) ได้ถูก
set -e
R=$(cd "$(dirname "$0")" && pwd)
IMG=${PELNAV_IMAGE:-pelnav-py312}
if [ -n "$(docker ps -aq -f name=^pelnav$)" ]; then
  echo "มี container pelnav อยู่แล้ว — ถ้าจะสร้างใหม่: docker rm -f pelnav แล้วรันอีกครั้ง"
  exit 1
fi
docker run -d --name pelnav --restart unless-stopped --network host \
  --user "$(id -u):$(id -g)" -v "$R:$R" -v /etc/localtime:/etc/localtime:ro -w "$R/app" \
  --log-opt max-size=10m --log-opt max-file=5 \
  "$IMG" python -X utf8 -m server.manage --config "$R/data/config.toml" run
sleep 4
docker logs pelnav 2>&1 | tail -3
