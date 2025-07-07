#!/bin/bash

# 그래픽 초기화 대기
sleep 20

# 연결된 모니터 수 확인
CONNECTED_MONITORS=$(xrandr --query | grep " connected" | wc -l)

# 디스플레이 설정
if [ "$CONNECTED_MONITORS" -ge 2 ]; then
  # 듀얼 디스플레이 위치 설정
  xrandr --output HDMI-1 --mode 1024x600 --pos 0x0 --primary
  xrandr --output HDMI-2 --mode 1024x600 --pos 1024x0 --right-of HDMI-1
else
  # 싱글 디스플레이만 설정
  xrandr --output HDMI-1 --mode 1024x600 --pos 0x0 --primary
fi

# 디스플레이 안정화 대기
sleep 2

# Chromium 실행 공통 옵션
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
  --bwsi --noerrdialogs
  --disable-notifications
  --disable-software-rasterizer
  --use-gl=disabled
  --disable-gl-drawing-for-tests
  --disable-features=Vulkan,Translate
  --translate-ranker-model-url=
  --lang=ko
"

URL1="http://203.247.202.223:9999/kiosk/test1234/NO.1-1"
URL2="http://203.247.202.223:9999/kiosk/test1234/NO.1-2"

# 첫 번째 모니터에 Chromium 실행
chromium-browser \
  --user-data-dir=/tmp/chrome_profile1 \
  $CHROME_OPTIONS \
  --window-position=0,0 \
  "$URL1" & disown

# 두 번째 모니터에 Chromium 실행 (모니터가 2개 이상일 때만)
if [ "$CONNECTED_MONITORS" -ge 2 ]; then
  chromium-browser \
    --user-data-dir=/tmp/chrome_profile2 \
    $CHROME_OPTIONS \
    --window-position=1024,0 \
    "$URL2" & disown
fi
