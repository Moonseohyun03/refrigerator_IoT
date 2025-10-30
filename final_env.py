import os
import time
import requests
import serial
import Adafruit_ADS1x15
import logging
from typing import Optional, Any, Dict
from dotenv import load_dotenv

# ==============================================================================
# 0. 로깅 설정
# ==============================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("refrigerator.log"),
        logging.StreamHandler()
    ]
)

# ==============================================================================
# 1. 환경 변수 관리
# ==============================================================================
ENV_PATH = "info.env"

def ensure_env():
    load_dotenv(ENV_PATH)

    refrigerator_number = os.getenv("REFRIGERATOR_NUMBER")
    check_value = os.getenv("CHECK_VALUE")

    if not refrigerator_number or not check_value:
        logging.info("첫 실행입니다. 냉장고 번호와 관리자 ID를 입력해주세요.")
        refrigerator_number = input("냉장고 번호 입력: ").strip()
        check_value = input("관리자 ID 입력: ").strip()

        with open(ENV_PATH, "w") as f:
            f.write(f"REFRIGERATOR_NUMBER={refrigerator_number}\n")
            f.write(f"CHECK_VALUE={check_value}\n")

        logging.info(".env 파일을 생성했습니다. 다음 실행부터는 자동으로 불러옵니다.")

    return refrigerator_number, check_value

# ==============================================================================
# 2. 상수 및 전역 변수
# ==============================================================================
TEMP_API_BASE_URL = "http://bistech-db.synology.me:57166/api/refrigerator/raspi"
DATA_POST_URL = "http://bistech-db.synology.me:57166/api/temperature"
HEADERS = {"Authorization": "JWT"}  # 필요 시 토큰 추가

SLAVE_ID = 1
REG_ADDR_TEMP_SET = 0x0002
REG_ADDR_TEMP_GAP = 0x0004
REG_ADDR_HEAT_TIME = 0x0012

GAIN = 16
VOLTAGE_REF = 4.096
BIT_RESOLUTION = 32768
BURDEN_RESISTOR = 10
SENSOR_SENSITIVITY = 30.0
ADS1115_AVAILABLE = False

try:
    adc = Adafruit_ADS1x15.ADS1115()
    ADS1115_AVAILABLE = True
except Exception as e:
    logging.error(f"ADS1115 초기화 오류: {e}")
    ADS1115_AVAILABLE = False

# ==============================================================================
# 3. 센서/RS485 헬퍼 함수
# ==============================================================================
def read_current():
    if not ADS1115_AVAILABLE:
        return 0.0
    try:
        raw_value = adc.read_adc(0, gain=GAIN)
        voltage = (raw_value / BIT_RESOLUTION) * VOLTAGE_REF
        current = (voltage / BURDEN_RESISTOR) * SENSOR_SENSITIVITY
        return round(current, 2)
    except Exception as e:
        logging.error(f"전류 측정 오류: {e}")
        return None

def read_temp_raw():
    base_dir = '/sys/bus/w1/devices/'
    try:
        device_folders = [d for d in os.listdir(base_dir) if d.startswith('28-')]
        if not device_folders:
            return None
        device_file = os.path.join(base_dir, device_folders[0], 'w1_slave')
    except Exception:
        return None
    try:
        with open(device_file, 'r') as f:
            return f.readlines()
    except Exception:
        return None

def read_ds18b20_temp():
    lines = read_temp_raw()
    if not lines:
        return None
    while lines and lines[0].strip()[-3:] != 'YES':
        time.sleep(0.2)
        lines = read_temp_raw()
        if not lines:
            return None
    if lines and len(lines) > 1:
        equals_pos = lines[1].find('t=')
        if equals_pos != -1:
            try:
                temp_string = lines[1][equals_pos + 2:]
                temp_c = float(temp_string) / 1000.0
                return round(temp_c, 2)
            except Exception as e:
                logging.error(f"DS18B20 파싱 오류: {e}")
                return None
    return None

def crc16_modbus(data: bytes) -> bytes:
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            if crc & 0x0001:
                crc >>= 1
                crc ^= 0xA001
            else:
                crc >>= 1
    return crc.to_bytes(2, byteorder='little')

def open_rs485_serial():
    try:
        ser = serial.Serial(
            port='/dev/ttyUSB0',
            baudrate=9600,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=1
        )
        if ser.isOpen():
            logging.info(f"RS485 포트 {ser.port} 열림")
            return ser
    except Exception as e:
        logging.error(f"RS485 포트 오류: {e}")
    return None

def read_rs485_temp(ser):
    if not ser or not ser.isOpen():
        return None
    request_packet = b'\x01\x04\x00\x64\x00\x02\x30\x14'
    try:
        ser.write(request_packet)
        response = ser.read(15)
        if len(response) < 9:
            return None
        received_crc = response[-2:]
        calculated_crc = crc16_modbus(response[:-2])
        if received_crc != calculated_crc:
            logging.warning("RS485 CRC 불일치")
            return None
        temp_value_raw = int.from_bytes(response[3:5], byteorder='big')
        return round(temp_value_raw / 10.0, 2)
    except Exception as e:
        logging.error(f"RS485 읽기 오류: {e}")
        return None

# ==============================================================================
# 4. API 설정 동기화
# ==============================================================================
def update_refrigerator_settings(serial_port, refrigerator_number, check_value, settings):
    temp_api_url_full = f"{TEMP_API_BASE_URL}/{refrigerator_number}?check_refrigerator={check_value}"
    try:
        response = requests.get(temp_api_url_full, headers=HEADERS, timeout=10)
        if response.status_code != 200:
            logging.warning(f"API 요청 실패: {response.status_code}")
            return
        data = response.json().get('data')
        if not data:
            return
        found_fridge = next((item for item in data if item.get('refrigerator_number') == refrigerator_number), None)
        if not found_fridge:
            settings['refrigerator_id'] = None
            return
        settings['refrigerator_id'] = found_fridge.get("refrigerator_id")
        settings['setting_temp_value_from_api'] = found_fridge.get('setting_temp_value')
        settings['temp_gap_api'] = found_fridge.get('temp_gap')
        settings['heating_time_from_api'] = found_fridge.get('defrost_time')
        logging.info(f"API 설정 동기화 완료: {settings}")
    except Exception as e:
        logging.error(f"API 통신 오류: {e}")

# ==============================================================================
# 5. 메인 루프
# ==============================================================================
def main(refrigerator_number: str, check_value: str):
    settings = {
        'refrigerator_id': None,
        'setting_temp_value_from_api': None,
        'temp_gap_api': None,
        'heating_time_from_api': None,
    }

    api_check_interval_seconds = 300
    last_api_check_time = 0

    serial_port = open_rs485_serial()
    update_refrigerator_settings(serial_port, refrigerator_number, check_value, settings)

    while True:
        current_value = read_current()
        ds18b20_temp = read_ds18b20_temp()
        rs485_temp = read_rs485_temp(serial_port)

        data_to_send = {
            "temperature_value": str(ds18b20_temp) if ds18b20_temp else None,
            "out_temperature_value": str(rs485_temp) if rs485_temp else None,
            "setting_temp_value": str(settings['setting_temp_value_from_api']) if settings['setting_temp_value_from_api'] else None,
            "current_value": str(current_value) if current_value else None,
            "refrigerator_id": int(settings['refrigerator_id']) if settings['refrigerator_id'] else None
        }

        logging.info(f"전송할 데이터: {data_to_send}")

        if settings['refrigerator_id']:
            try:
                response = requests.post(DATA_POST_URL, json=data_to_send, headers=HEADERS, timeout=10)
                if response.status_code in [200, 201]:
                    logging.info("데이터 업로드 성공")
                else:
                    logging.warning(f"업로드 실패: {response.status_code}")
            except Exception as e:
                logging.error(f"데이터 업로드 오류: {e}")

        # 설정값 재확인 주기
        now = time.time()
        if now - last_api_check_time >= api_check_interval_seconds:
            update_refrigerator_settings(serial_port, refrigerator_number, check_value, settings)
            last_api_check_time = now

        time.sleep(10)

# ==============================================================================
# 6. 실행부
# ==============================================================================
if __name__ == "__main__":
    refrigerator_number, check_value = ensure_env()
    try:
        main(refrigerator_number, check_value)
    except KeyboardInterrupt:
        logging.info("사용자에 의해 프로그램이 종료되었습니다.")
    except Exception as e:
        logging.critical(f"예상치 못한 오류 발생: {e}")
