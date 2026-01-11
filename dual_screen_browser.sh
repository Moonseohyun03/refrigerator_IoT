#!/bin/bash

ENV_PATH="./code/info.env"

if [ ! -f "$ENV_PATH" ]; then
  echo " env 파일을 찾을 수 없습니다: $ENV_PATH"
  exit 1
fi

set -a
source "$ENV_PATH"
set +a

# 그래픽 초기화 대기
sleep 20

# 연결된 모니터 수 확인
CONNECTED_MONITORS=$(xrandr --query | grep " connected" | wc -l)

# 디스플레이 설정
if [ "$CONNECTED_MONITORS" -ge 2 ]; then
  xrandr --output HDMI-1 --mode 1024x600 --pos 0x0 --primary
  xrandr --output HDMI-2 --mode 1024x600 --pos 1024x0 --right-of HDMI-1
else
  xrandr --output HDMI-1 --mode 1024x600 --pos 0x0 --primary
fi

sleep 2

# Chromium 공통 옵션
CHROME_OPTIONS="
  --kiosk
  --no-first-run
  --no-default-browser-check
  --disable-sync
  --disable-extensions
  --disable-translate
  --disable-infobars
  --disable-background-networking
  --disable-default-apps
  --disable-component-update
  --disable-client-side-phishing-detection
  --disable-popup-blocking
  --disable-prompt-on-repost
  --bwsi
  --noerrdialogs
  --disable-notifications
  --disable-software-rasterizer
  --use-gl=disabled
  --disable-gl-drawing-for-tests
  --disable-features=Vulkan,Translate
  --translate-ranker-model-url=
  --lang=ko
"

# URL 구성 (env 값 사용)
BASE_URL="https://bistech-db.synology.me/kiosk"

URL1="$BASE_URL/$CHECK_VALUE/$REFRIGERATOR_NUMBER"
URL2="$BASE_URL/$CHECK_VALUE/${REFRIGERATOR_NUMBER%-1}-2"

# 디버깅 로그 (문제 생기면 확인용)
echo "▶ REFRIGERATOR_NUMBER = $REFRIGERATOR_NUMBER"
echo "▶ URL1 = $URL1"
echo "▶ URL2 = $URL2"

# Chromium 실행
chromium-browser \
  --user-data-dir=/tmp/chrome_profile1 \
  $CHROME_OPTIONS \
  --window-position=0,0 \
  "$URL1" & disown

if [ "$CONNECTED_MONITORS" -ge 2 ]; then
  chromium-browser \
    --user-data-dir=/tmp/chrome_profile2 \
    $CHROME_OPTIONS \
    --window-position=1024,0 \
    "$URL2" & disown
fi
