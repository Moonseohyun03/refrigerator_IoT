import time
import requests
import os
import serial
import Adafruit_ADS1x15
import binascii

TEMP_API_URL = "http://203.247.202.223:9999/api/refrigerator/raspi/{check_refrigerator}?check_refrigerator=test1234"
DATA_POST_URL = "http://203.247.202.223:9999/api/temperature"
HEADERS = {"Authorization": "JWT"} # TODO: 실제 JWT 토큰으로 변경 필요

try:
    adc = Adafruit_ADS1x15.ADS1115()
    ADS1115_AVAILABLE = True
except Exception as e:
    print(f"ADS1115 초기화 오류: {e}")
    print("ADS1115 전류 측정을 건너뜁니다.")
    ADS1115_AVAILABLE = False

GAIN = 16
VOLTAGE_REF = 4.096
BIT_RESOLUTION = 32768
BURDEN_RESISTOR = 10
SENSOR_SENSITIVITY = 30.0

def read_current():
    if not ADS1115_AVAILABLE:
        return 0.0
    try:
        raw_value = adc.read_adc(0, gain=GAIN)
        voltage = (raw_value / BIT_RESOLUTION) * VOLTAGE_REF
        current = (voltage / BURDEN_RESISTOR) * SENSOR_SENSITIVITY
        return round(current, 2)
    except Exception as e:
        print(f"전류 측정 오류: {e}")
        return None

def read_temp_raw():
    base_dir = '/sys/bus/w1/devices/'
    try:
        device_folders = [d for d in os.listdir(base_dir) if d.startswith('28-')]
        if not device_folders:
            return None
        device_file = os.path.join(base_dir, device_folders[0], 'w1_slave')
    except FileNotFoundError:
        return None
    except Exception as e:
        print(f"DS18B20 경로 탐색 오류: {e}")
        return None
    try:
        with open(device_file, 'r') as f:
            return f.readlines()
    except FileNotFoundError:
        return None
    except Exception as e:
        print(f"DS18B20 파일 읽기 오류: {e}")
        return None

def read_ds18b20_temp():
    lines = read_temp_raw()
    if not lines:
        return None
    while lines[0].strip()[-3:] != 'YES':
        time.sleep(0.2)
        lines = read_temp_raw()
        if not lines:
            return None
    equals_pos = lines[1].find('t=')
    if equals_pos != -1:
        try:
            temp_string = lines[1][equals_pos + 2:]
            temp_c = float(temp_string) / 1000.0
            return round(temp_c, 2)
        except (ValueError, IndexError) as e:
            print(f"DS18B20 온도 값 파싱 오류: {e}")
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
            port='/dev/ttyUSB0', # TODO: 실제 RS485 통신 포트로 변경
            baudrate=9600,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=1
        )
        if ser.isOpen():
            print(f"RS485 포트 {ser.port} 열림")
            return ser
        else:
            print(f"RS485 포트 {ser.port} 열기 실패")
            return None
    except serial.SerialException as e:
        print(f"RS485 시리얼 통신 오류: {e}")
        return None
    except Exception as e:
        print(f"RS485 포트 초기화 중 예기치 않은 오류: {e}")
        return None

def send_modbus_command(ser, slave_id: int, function_code: int, start_address: int, data: bytes) -> bytes:
    if not ser or not ser.isOpen():
        print("RS485 포트가 열려 있지 않아 명령을 보낼 수 없습니다.")
        return b''
    packet_without_crc = bytes([slave_id, function_code]) + start_address.to_bytes(2, byteorder='big') + data
    full_packet = packet_without_crc + crc16_modbus(packet_without_crc)
    try:
        ser.write(full_packet)
        time.sleep(0.1)
        response = ser.read(15)
        return response
    except serial.SerialException as e:
        print(f"RS485 통신 중 serial 오류: {e}")
        return b''
    except Exception as e:
        print(f"RS485 명령 전송/수신 오류: {e}")
        return b''

def set_rs485_register(ser, slave_id: int, register_address: int, value: int):
    value_bytes = value.to_bytes(2, byteorder='big') # TODO: 장치 매뉴얼에 따라 byteorder='little'이나 4바이트 등으로 변경 필요
    response = send_modbus_command(ser, slave_id, 0x06, register_address, value_bytes)

    if len(response) == 8:
        received_crc = response[-2:]
        calculated_crc = crc16_modbus(response[:-2])
        if received_crc != calculated_crc:
            print(f"RS485 설정 응답 CRC 불일치: 수신 {received_crc.hex()}, 계산 {calculated_crc.hex()}")
            return False
        else:
            expected_response_prefix = bytes([slave_id, 0x06]) + register_address.to_bytes(2, byteorder='big') + value_bytes
            if response[:-2] != expected_response_prefix:
                 print(f"RS485 설정 응답 내용 불일치. 예상 접두사: {expected_response_prefix.hex()}, 수신 접두사: {response[:-2].hex()}")
                 return False
            return True

    elif len(response) > 0:
        if len(response) >= 5 and response[1] == (0x06 | 0x80):
             print(f"RS485 설정 장치에서 에러 응답 수신: 에러 코드 {response[2]}")
        else:
            print(f"RS485 설정 응답 길이 오류 또는 예상치 못한 응답: {response.hex()}")
        return False
    else:
        print("RS485 설정 응답 없음 (타임아웃)")
        return False


def read_rs485_temp(ser):
    if not ser or not ser.isOpen():
        print("RS485 포트가 열려 있지 않아 온도 읽기 건너뜁니다.")
        return None
    request_packet = b'\x01\x04\x00\x64\x00\x02\x30\x14' # TODO: 장치 매뉴얼에 따라 요청 패킷 수정 필요 (주소, 레지스터 수, CRC)
    try:
        ser.write(request_packet)
        print(f"RS485 온도 요청 패킷 전송: {request_packet.hex()}")
        response = ser.read(15)
        print(f"RS485 온도 읽기 수신 응답 (raw): {response.hex()}")
        if len(response) < 9:
            print(f"RS485 응답 길이 부족. 최소 9 필요, 수신 {len(response)}. 응답: {response.hex()}")
            if len(response) >= 5 and response[1] == (0x04 | 0x80):
                 print(f"RS485 온도 읽기 장치에서 에러 응답 수신: 에러 코드 {response[2]}")
            return None

        if len(response) >= 2:
            received_crc = response[-2:]
            calculated_crc_data = response[:-2]
            calculated_crc = crc16_modbus(calculated_crc_data)
            print(f"RS485 온도 읽기 수신 CRC: {received_crc.hex()}, 계산된 CRC: {calculated_crc.hex()}")
            if received_crc != calculated_crc:
                print(f"RS485 온도 읽기 응답 CRC 불일치! 데이터 신뢰 불가.")
                return None
            else:
                 print("RS485 온도 읽기 응답 CRC 일치.")
        else:
             print("RS485 온도 읽기 응답 길이가 너무 짧아 CRC 확인 불가.")
             return None

        if len(response) >= 3:
            byte_count = response[2]
            expected_data_len = 4
            if byte_count >= 2:
                temp_raw_bytes = response[3 : 3 + 2]
                print(f"RS485 온도 읽기 추출 데이터 바이트 (response[3:5]): {temp_raw_bytes.hex()}")

                if len(temp_raw_bytes) >= 2:
                    temp_value_raw = int.from_bytes(temp_raw_bytes[:2], byteorder='big')
                    print(f"RS485 온도 읽기 Raw 정수 값 (변환 전, byteorder='big', 처음 2바이트): {temp_value_raw}")
                    temp_c = temp_value_raw / 10.0 # TODO: 실제 스케일 팩터 확인!
                    return round(temp_c, 2)
                else:
                     print(f"RS485 온도 데이터 변환에 필요한 최소 바이트(2) 부족. 수신 {len(temp_raw_bytes)}.")
                     return None
            else:
                 print(f"RS485 온도 읽기 응답 데이터 바이트 수 부족. Byte Count: {byte_count}")
                 return None
        else:
            print(f"RS485 온도 읽기 응답 길이 부족 for Byte Count: {response.hex()}")
            return None

    except serial.SerialException as e:
        print(f"RS485 시리얼 통신 오류: {e}")
        return None
    except Exception as e:
        print(f"RS485 온도 읽기 처리 중 오류 발생: {e}")
        return None

def main(refrigerator_number = "NO.1-1"):
    serial_port = None
    refrigerator_id = None
    setting_temp_value_from_api = None
    current_rs485_temp_setting_scaled = None
    temp_gap_api = None
    temp_gap_scaled = None
    heating_time_from_api = None
    current_rs485_heat_time_scaled = None

    api_check_interval_seconds = 300
    last_api_check_time = 0

    try:
        serial_port = open_rs485_serial()
        if not serial_port:
            print("RS485 포트 열기 실패. RS485 관련 기능은 작동하지 않습니다.")

        print(f"프로그램 시작 시 API에서 초기 설정 정보 가져오는 중: {TEMP_API_URL}")
        try:
            response = requests.get(TEMP_API_URL, headers=HEADERS, timeout=10)
            if response.status_code == 200:
                data = response.json().get('data')
                if data and isinstance(data, list) and len(data) > 0:
                
                    found_fridge = next((item for item in data if item.get('refrigerator_number') == refrigerator_number), None)
                    if found_fridge:
                        refrigerator_id = found_fridge.get("refrigerator_id")
                        setting_temp_value_from_api = found_fridge.get('setting_temp_value')
                        temp_gap_api = found_fridge.get('temp_gap') 
                        heating_time_from_api = found_fridge.get('defrost_time')

                        print(f"API에서 초기 냉장고 ID({refrigerator_id}), 온도 설정({setting_temp_value_from_api}), 히팅 시간({heating_time_from_api}) 확인")

                        if serial_port and setting_temp_value_from_api is not None:
                             print("\n초기 API 값으로 RS485 장치 온도 설정 시작...")
                             slave_id = 1
                             reg_address_temp_set = 0x0002
                             try:
                                  initial_set_value_temp_scaled = int(float(setting_temp_value_from_api) * 10) # TODO: 장치 매뉴얼에 따라 변환 방식 수정!
                                  print(f"-> 초기 API 온도 값 ({setting_temp_value_from_api}) 스케일링 ({initial_set_value_temp_scaled})으로 주소 0x{reg_address_temp_set:04X} 쓰기 시도")
                                  if set_rs485_register(serial_port, slave_id, reg_address_temp_set, initial_set_value_temp_scaled):
                                       print(f"-> 초기 온도 설정 성공: 주소 0x{reg_address_temp_set:04X}, 값 {initial_set_value_temp_scaled}")
                                       current_rs485_temp_setting_scaled = initial_set_value_temp_scaled
                                  else:
                                       print(f"-> 초기 온도 설정 실패: 주소 0x{reg_address_temp_set:04X}, 값 {initial_set_value_temp_scaled}. current_rs485_temp_setting_scaled는 이전 값 유지.")

                             except (ValueError, TypeError) as e:
                                  print(f"API에서 받아온 초기 설정 온도 값 '{setting_temp_value_from_api}' 변환 오류: {e}")
                                  print("초기 API 값으로 온도 설정을 건너뜁니다.")
                             except Exception as e:
                                  print(f"RS485 장치 초기 온도 설정 중 오류 발생: {e}")
                        elif serial_port:
                             print("API에서 초기 설정 온도 값을 가져오지 못하여 초기 RS485 온도 설정을 건너뜁니다.")

                        # --- 수정된 부분: API에서 받아온 초기 히팅 시간 값이 None이 아니고 빈 문자열도 아닐 때만 설정 시도 ---
                        if serial_port and heating_time_from_api is not None and heating_time_from_api != '':
                             print("\n초기 API 값으로 RS485 장치 히팅 시간 설정 시작...")
                             slave_id = 1
                             reg_address_heat_time = 0x0012 # TODO: 실제 히팅 시간 레지스터 주소
                             try:
                                  # API에서 받아온 값을 장치에 보낼 형식(정수)으로 변환
                                  # TODO: 장치 매뉴얼에 따라 변환 방식(스케일링 등) 수정 필요!
                                  initial_set_value_heat_scaled = int(float(heating_time_from_api)) # 이 줄에서 오류 났었음!

                                  print(f"-> 초기 API 히팅 시간 값 ({heating_time_from_api}) 스케일링 ({initial_set_value_heat_scaled})으로 주소 0x{reg_address_heat_time:04X} 쓰기 시도")
                                  if set_rs485_register(serial_port, slave_id, reg_address_heat_time, initial_set_value_heat_scaled):
                                       print(f"-> 초기 히팅 시간 설정 성공: 주소 0x{reg_address_heat_time:04X}, 값 {initial_set_value_heat_scaled}")
                                       current_rs485_heat_time_scaled = initial_set_value_heat_scaled
                                  else:
                                       print(f"-> 초기 히팅 시간 설정 실패: 주소 0x{reg_address_heat_time:04X}, 값 {initial_set_value_heat_scaled}. current_rs485_heat_time_scaled는 이전 값 유지.")

                             except (ValueError, TypeError) as e:
                                  print(f"API에서 받아온 초기 히팅 시간 값 '{heating_time_from_api}' 변환 오류: {e}")
                                  print("초기 API 값으로 히팅 시간 설정을 건너뜁니다.")
                             except Exception as e:
                                  print(f"RS485 장치 초기 히팅 시간 설정 중 오류 발생: {e}")
                        # --- 수정된 부분: 값이 None이거나 빈 문자열일 때 건너뛴다고 출력 ---
                        elif serial_port:
                             print(f"API에서 초기 히팅 시간 값을 가져오지 못했거나 값이 유효하지 않아 초기 RS485 히팅 시간 설정을 건너뜁니다. 값: '{heating_time_from_api}'")
                        # --- 초기 히팅 시간 설정 끝 ---

                        if serial_port and temp_gap_api is not None and temp_gap_api != '':
                             print("\n온도 편차 api값으로 설정")
                             slabe_id = 1
                             reg_temp_gap = 0x0004
                             try:
                                 initial_set_value_temp_gap = int(float(temp_gap_api))
                                 print(f"->초기 API 온도편차 값({temp_gap_api}) 스케일링 ({initial_set_value_temp_gap})으로 주소 0x{reg_temp_gap:04X}쓰기 시도")
                                 if set_rs485_register(serial_port, slave_id, reg_temp_gap, initial_set_value_temp_gap):
                                     print(f"->초기 온도편차 설정 성공: 주소 0x{reg_temp_gap:04X}, 값 {initial_set_value_temp_gap}")
                                     temp_gap_scaled = initial_set_value_temp_gap
                                 else:
                                     print(f"->초기 온도편차 설정 실패: 주소 0x{reg_temp_gap:04X}, 값 {initial_set_value_temp_gap}")
                             except (ValueError, TypeError) as e:
                                  print(f"API에서 받아온 초기 온도 편차 값 '{temp_gap_api}' 변환 오류:{e}")
                                  print(f"초기 API 값으로 온도 편차 설정을 건너뜁니다.")
                             except Exception as e:
                                  print(f"RS485 장치 초기 온도 편차 설정 중 오류 발생: {e}")
                        elif serial_port:
                            print(f"API에서 초기 온도 편차 값을 가져오지 못했거나 값이 유효하지 않아 설정을 건너뜁니다. 값: '{temp_gap_api}'")

                    else:
                        print(f"API 응답에서 냉장고 번호 '{refrigerator_number}'를 찾을 수 없습니다. 데이터 전송 불가.")
                        refrigerator_id = None
                else:
                    print("API 응답에 유효한 'data' 리스트가 없거나 비어 있습니다. API 설정값 및 냉장고 ID 가져오기 실패.")
            else:
                print(f"프로그램 시작 시 API 요청 실패: 상태 코드 {response.status_code}. 응답 내용: {response.text[:200]}...")
        except requests.exceptions.RequestException as e:
            print(f"프로그램 시작 시 API 요청 중 오류 발생: {e}")
        except Exception as e:
            print(f"프로그램 시작 시 API 응답 처리 중 오류 발생: {e}")

        if refrigerator_id is None:
             print("데이터 전송을 위한 냉장고 ID를 얻지 못했습니다. 데이터 전송 기능은 작동하지 않습니다.")

        print("\n센서 데이터 측정, API 설정 확인 및 전송 루프 시작...")
        last_api_check_time = time.time()

        while True:
            current_time = time.time()

            if current_time - last_api_check_time >= api_check_interval_seconds:
                print(f"\nAPI에서 최신 설정 정보 확인 중 (주기: {api_check_interval_seconds}초)...")
                try:
                     response = requests.get(TEMP_API_URL, headers=HEADERS, timeout=10)
                     if response.status_code == 200:
                         data = response.json().get('data')
                         if data and isinstance(data, list) and len(data) > 0:
                             found_fridge = next((item for item in data if item.get('refrigerator_number') == refrigerator_number), None)
                             if found_fridge:
                                 latest_setting_temp_from_api = found_fridge.get('setting_temp_value')
                                 latest_heating_time_from_api = found_fridge.get('defrost_term') # API 히팅 시간 값을 'deFrost_term' 키로 가져옴
                                 latest_temp_gap_api = found_fridge.get('temp_gap')
                                 print(f"-> API에서 최신 온도 설정 확인: {latest_setting_temp_from_api}")
                                 print(f"-> API에서 최신 히팅 시간 확인: {latest_heating_time_from_api}")
                                 print(f"-> API에서 최신 온도 편차 확인: {latest_temp_gap_api}")
                                 if latest_setting_temp_from_api is not None and latest_setting_temp_from_api != setting_temp_value_from_api:
                                     print(f"--> 온도 설정 변경 감지: 이전 '{setting_temp_value_from_api}' -> 최신 '{latest_setting_temp_from_api}'")
                                     setting_temp_value_from_api = latest_setting_temp_from_api

                                     if serial_port:
                                          slave_id = 1
                                          reg_address_temp_set = 0x0002
                                          try:
                                               new_set_value_temp_scaled = int(float(setting_temp_value_from_api) * 10) # TODO: 장치 매뉴얼에 맞게 수정!
                                               if new_set_value_temp_scaled != current_rs485_temp_setting_scaled:
                                                    print(f"--> 스케일링된 새 온도 설정 값 ({new_set_value_temp_scaled})으로 주소 0x{reg_address_temp_set:04X} 쓰기 시도")
                                                    if set_rs485_register(serial_port, slave_id, reg_address_temp_set, new_set_value_temp_scaled):
                                                        print(f"--> 온도 설정 성공: 주소 0x{reg_address_temp_set:04X}, 값 {new_set_value_temp_scaled}")
                                                        current_rs485_temp_setting_scaled = new_set_value_temp_scaled
                                                    else:
                                                        print(f"--> 온도 설정 실패: 주소 0x{reg_address_temp_set:04X}, 값 {new_set_value_temp_scaled}. current_rs485_temp_setting_scaled는 이전 값 유지.")
                                               else:
                                                    print(f"--> 변환된 온도 설정 값 ({new_set_value_temp_scaled})이 현재 장치 설정값과 동일하여 설정을 건너뜁니다.")
                                          except (ValueError, TypeError) as e:
                                               print(f"API에서 받아온 최신 설정 온도 값 '{setting_temp_value_from_api}' 변환 오류: {e}")
                                               print("최신 API 값으로 온도 설정을 건너뜁니다.")
                                          except Exception as e:
                                               print(f"RS485 장치 온도 설정 중 오류 발생: {e}")
                                     elif serial_port:
                                          print("RS485 시리얼 포트가 열려있지 않아 최신 API 값으로 온도 설정을 건너뜁니다.")
                                 elif latest_setting_temp_from_api is not None and latest_setting_temp_from_api == setting_temp_value_from_api:
                                      print(f"-> API 온도 설정 값은 이전과 동일 ({setting_temp_value_from_api}).")
                                 elif latest_setting_temp_from_api is None:
                                      print("-> API에서 유효한 온도 설정 값을 받지 못했습니다 (None).")

                                 # --- 수정된 부분: API에서 받아온 최신 히팅 시간 값이 None이 아니고 빈 문자열도 아닐 때만 설정 시도 ---
                                 if latest_heating_time_from_api is not None and latest_heating_time_from_api != heating_time_from_api and latest_heating_time_from_api != '':
                                     print(f"--> 히팅 시간 설정 변경 감지: 이전 '{heating_time_from_api}' -> 최신 '{latest_heating_time_from_api}'")
                                     heating_time_from_api = latest_heating_time_from_api

                                     if serial_port:
                                          slave_id = 1
                                          reg_address_heat_time = 0x0012 # TODO: 실제 히팅 시간 레지스터 주소
                                          try:
                                               # API 값 변환 및 스케일링 (TODO: 장치 매뉴얼에 따라 변환 방식(스케일링 등) 수정 필요!)
                                               new_set_value_heat_scaled = int(float(heating_time_from_api)) # 이 줄에서 오류 났었음!
                                               if new_set_value_heat_scaled != current_rs485_heat_time_scaled:
                                                    print(f"--> 스케일링된 새 히팅 시간 설정 값 ({new_set_value_heat_scaled})으로 주소 0x{reg_address_heat_time:04X} 쓰기 시도")
                                                    if set_rs485_register(serial_port, slave_id, reg_address_heat_time, new_set_value_heat_scaled):
                                                        print(f"--> 히팅 시간 설정 성공: 주소 0x{reg_address_heat_time:04X}, 값 {new_set_value_heat_scaled}")
                                                        current_rs485_heat_time_scaled = new_set_value_heat_scaled
                                                    else:
                                                        print(f"--> 히팅 시간 설정 실패: 주소 0x{reg_address_heat_time:04X}, 값 {new_set_value_heat_scaled}. current_rs485_heat_time_scaled는 이전 값 유지.")
                                               else:
                                                    print(f"--> 변환된 히팅 시간 설정 값 ({new_set_value_heat_scaled})이 현재 장치 설정값과 동일하여 설정을 건너뜁니다.")
                                          except (ValueError, TypeError) as e:
                                               print(f"API에서 받아온 최신 히팅 시간 값 '{heating_time_from_api}' 변환 오류: {e}")
                                               print("최신 API 값으로 히팅 시간 설정을 건너뜁니다.")
                                          except Exception as e:
                                               print(f"RS485 장치 히팅 시간 설정 중 오류 발생: {e}")
                                     elif serial_port:
                                          print("RS485 시리얼 포트가 열려있지 않아 최신 API 값으로 히팅 시간 설정을 건너뜁니다.")
                                 # --- 수정된 부분: 값이 None이거나 빈 문자열일 때 건너뛴다고 출력 ---
                                 elif latest_heating_time_from_api is not None and latest_heating_time_from_api == heating_time_from_api:
                                      print(f"-> API 히팅 시간 값은 이전과 동일 ({heating_time_from_api}).")
                                 elif latest_heating_time_from_api is None or latest_heating_time_from_api == '':
                                      print(f"-> API에서 유효한 히팅 시간 값을 받지 못했습니다 (None 또는 빈 문자열 ''). 값: '{latest_heating_time_from_api}'")
                                 # --- 히팅 시간 설정 변경 감지 끝 ---
                                 if latest_temp_gap_api is not None and latest_temp_gap_api != latest_temp_gap_api and latest_temp_gap_api != '':
                                     print(f"-->온도 편차 변경 감지: 이전 '{temp_gap_api}' -> 최신 '{latest_temp_gap_api}'")
                                     temp_gap_api = latest_temp_gap_api
                                     if serial_port:
                                          slave_id = 1
                                          reg_address_temp_gap = 0x0004
                                          try:
                                               new_value_temp_gap_scaled = int(float(temp_gap_api))
                                               if new_value_temp_gap_scaled != temp_gap_scaled:
                                                    print(f"--> 스케일링 된 새 온도 편차 값({new_value_temp_gap_scaled})으로 쓰기 시도")
                                                    if set_rs485_register(serial_port, slave_id, reg_address_temp_set, new_value_temp_gap_scaled):
                                                        print(f"-->온도 편차 설정 성공 값{new_value_temp_gap_scaled}")
                                                        temp_gap_scaled = new_value_temp_gap_scaled
                                                    else:
                                                         print(f"--> 온도 편차 설정 실패 이전 값 유지")
                                               else:
                                                    print(f"--> 변환된 온도 편차 설정 값 ({new_value_temp_gap_scaled}이 현재 설정값과 동일하여 건너뜁니다.)")
                                          except (ValueError, TypeError) as e:
                                              print(f"변환 오류{e}")
                                              print(f"최신 값으로 온도편차 설정을 건너뜁니다.")
                                          except Exception as e:
                                                 print(f"rs485 온도 편차 설정 중 오류 발생: {e}")
                                     elif serial_port:
                                          print("RS485 시리얼 포트가 열려있지 않아 온도편차 설정을 건너뜁니다.")
                                 elif latest_temp_gap_api is not None and latest_temp_gap_api == temp_gap_api:
                                       print(f"-> API 온도편차 갑은 이전과 동일")
                                 elif latest_temp_gap_api is None or latest_temp_gap_api == '':
                                       print(f"-> API에서 유효한 값을 받지 못했습니다")
                             else:
                                 print(f"API 응답에서 냉장고 번호 '{refrigerator_number}'를 찾을 수 없습니다.")
                         else:
                             print("API 응답에 유효한 'data' 리스트가 없거나 비어 있습니다. API 설정값 및 냉장고 ID 가져오기 실패.")
                     else:
                         print(f"API 주기 확인 요청 실패: 상태 코드 {response.status_code}. 응답 내용: {response.text[:200]}...")
                except requests.exceptions.RequestException as e:
                     print(f"API 주기 확인 요청 중 오류 발생: {e}")
                except Exception as e:
                     print(f"API 주기 확인 응답 처리 중 오류 발생: {e}")
                finally:
                     last_api_check_time = current_time

            print("-" * 20)
            current_value = read_current()
            print(f"측정된 전류: {current_value} A" if current_value is not None else "전류 측정 실패")

            ds18b20_temp = read_ds18b20_temp()
            print(f"DS18B20 온도: {ds18b20_temp} °C" if ds18b20_temp is not None else "DS18B20 온도 측정 실패")

            if serial_port and serial_port.isOpen():
                rs485_temp = read_rs485_temp(serial_port)
                print(f"RS485 온도: {rs485_temp} °C" if rs485_temp is not None else "RS485 온도 측정 실패")
            else:
                rs485_temp = None
                print("RS485 포트 문제로 RS485 온도 측정 건너옴")

            data_to_send = {
                "temperature_value": str(ds18b20_temp) if ds18b20_temp is not None else None,
                "out_temperature_value": str(rs485_temp) if rs485_temp is not None else None,
                "setting_temp_value": str(setting_temp_value_from_api) if setting_temp_value_from_api is not None else None,
                "current_value": str(current_value) if current_value is not None else None,
                "refrigerator_id": int(refrigerator_id) if refrigerator_id is not None else None
            }
            print(f"전송할 데이터: {data_to_send}")

            if refrigerator_id is not None:
                try:
                    print(f"데이터를 {DATA_POST_URL} 로 전송 시도...")
                    response = requests.post(DATA_POST_URL, json=data_to_send, headers=HEADERS, timeout=10)
                    if response.status_code == 200 or response.status_code == 201:
                        print("데이터 전송 성공!")
                    else:
                        print(f"데이터 전송 실패: 상태 코드 {response.status_code}. 응답 내용: {response.text[:200]}...")
                except requests.exceptions.RequestException as e:
                    print(f"데이터 전송 중 오류 발생: {e}")
                except Exception as e:
                     print(f"데이터 전송 처리 중 오류 발생: {e}")
            else:
                print("냉장고 ID가 없어 데이터 전송을 건너뜁니다.")

            time.sleep(10)

    except KeyboardInterrupt:
        print("\n프로그램을 종료합니다.")
    except Exception as e:
        print(f"\n프로그램 실행 중 예기치 않은 오류 발생: {e}")
    finally:
        if serial_port and serial_port.isOpen():
            serial_port.close()
            print("RS485 포트 닫힘")

if __name__ == "__main__":
    refrigerator_number = input("냉장고번호 입력: ").strip()
    main(refrigerator_number)
