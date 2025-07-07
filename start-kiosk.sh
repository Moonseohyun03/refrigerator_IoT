#!/bin/bash

# 첫 번째 Chromium 창: HDMI-1 (왼쪽 모니터)
chromium-browser \
  --kiosk --new-window "http://192.168.7.152:5173/kiosk/test2/NO.1-1/" \
  --window-position=0,0 \
  --user-data-dir=/tmp/profile1 &

sleep 2

# 두 번째 Chromium 창: HDMI-2 (오른쪽 모니터)
chromium-browser \
  --kiosk --new-window "http://192.168.7.152:5173/kiosk/test2/NO.1-2/" \
  --window-position=1024,0 \
  --user-data-dir=/tmp/profile2 &

