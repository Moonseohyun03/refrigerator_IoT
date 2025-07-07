import time
import Adafruit_ADS1x15

# ADS1115 초기화
adc = Adafruit_ADS1x15.ADS1115()
GAIN = 1  # ADC 증폭 설정

# 센서 파라미터
VOLTAGE_REF = 4.096  # ADS1115 기준 전압 (Gain 설정에 따라 다름)
BIT_RESOLUTION = 32768  # 16비트 해상도 (2^15)
BURDEN_RESISTOR = 10  # Burden 저항 값 (옴)
SENSOR_SENSITIVITY = 30.0  # SCT-013-030의 감도 (30A -> 1V 출력)

def read_current():
    """SCT-013-030 센서에서 전류 값을 측정"""
    raw_value = adc.read_adc(0, gain=GAIN)  # A0 채널에서 데이터 읽기
    voltage = (raw_value / BIT_RESOLUTION) * VOLTAGE_REF  # ADC 값을 전압으로 변환
    current = (voltage / BURDEN_RESISTOR) * SENSOR_SENSITIVITY  # 전류 값 계산
    return round(current, 2)  # 소수점 2자리까지 표시

try:
    while True:
        current_value = read_current()
        print(f"측정된 전류: {current_value} A")
        time.sleep(1)
except KeyboardInterrupt:
    print("프로그램 종료")
