import time
import requests
import os
import serial
import Adafruit_ADS1x15
import binascii
import logging

TEMP_API_URL = "http://bistech-db.synology.me:57166/api/refrigerator/raspi/{check_refrigerator}?check_refrigerator=test1234"
DATA_POST_URL = "http://bistech-db.synology.me:57166/api/temperature"
HEADERS = {"Authorization": "JWT"} # TODO: 실제 JWT 토큰으로 변경 필요

# 로그 설정
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s][%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

try:
    adc = Adafruit_ADS1x15.ADS1115()
    ADS1115_AVAILABLE = True
except Exception as e:
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
        return None
    try:
        with open(device_file, 'r') as f:
            return f.readlines()
    except FileNotFoundError:
        return None
    except Exception as e:
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
            return ser
        else:
            return None
    except serial.SerialException as e:
        return None
    except Exception as e:
        return None

def send_modbus_command(ser, slave_id: int, function_code: int, start_address: int, data: bytes) -> bytes:
    if not ser or not ser.isOpen():
        return b''
    packet_without_crc = bytes([slave_id, function_code]) + start_address.to_bytes(2, byteorder='big') + data
    full_packet = packet_without_crc + crc16_modbus(packet_without_crc)
    try:
        ser.write(full_packet)
        time.sleep(0.1)
        response = ser.read(15)
        return response
    except serial.SerialException as e:
        return b''
    except Exception as e:
        return b''

def set_rs485_register(ser, slave_id: int, register_address: int, value: int):
    value_bytes = value.to_bytes(2, byteorder='big')
    response = send_modbus_command(ser, slave_id, 0x06, register_address, value_bytes)

    if len(response) == 8:
        received_crc = response[-2:]
        calculated_crc = crc16_modbus(response[:-2])
        if received_crc != calculated_crc:
            return False
        else:
            expected_response_prefix = bytes([slave_id, 0x06]) + register_address.to_bytes(2, byteorder='big') + value_bytes
            if response[:-2] != expected_response_prefix:
                 return False
            return True

    elif len(response) > 0:
        return False
    else:
        return False

def read_rs485_temp(ser):
    if not ser or not ser.isOpen():
        return None
    request_packet = b'\x01\x04\x00\x64\x00\x02\x30\x14'
    try:
        ser.write(request_packet)
        response = ser.read(15)
        if len(response) < 9:
            return None

        if len(response) >= 2:
            received_crc = response[-2:]
            calculated_crc_data = response[:-2]
            calculated_crc = crc16_modbus(calculated_crc_data)
            if received_crc != calculated_crc:
                return None
        else:
             return None

        if len(response) >= 3:
            byte_count = response[2]
            if byte_count >= 2:
                temp_raw_bytes = response[3 : 3 + 2]
                if len(temp_raw_bytes) >= 2:
                    temp_value_raw = int.from_bytes(temp_raw_bytes[:2], byteorder='big')
                    temp_c = temp_value_raw / 10.0
                    return round(temp_c, 2)
                else:
                     return None
            else:
                 return None
        else:
            return None

    except serial.SerialException as e:
        return None
    except Exception as e:
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

                        if serial_port and setting_temp_value_from_api is not None:
                             slave_id = 1
                             reg_address_temp_set = 0x0002
                             try:
                                  initial_set_value_temp_scaled = int(float(setting_temp_value_from_api) * 10)
                                  if set_rs485_register(serial_port, slave_id, reg_address_temp_set, initial_set_value_temp_scaled):
                                       current_rs485_temp_setting_scaled = initial_set_value_temp_scaled
                             except (ValueError, TypeError) as e:
                                  pass
                             except Exception as e:
                                  pass
                        elif serial_port:
                             pass

                        if serial_port and heating_time_from_api is not None and heating_time_from_api != '':
                             slave_id = 1
                             reg_address_heat_time = 0x0012
                             try:
                                  initial_set_value_heat_scaled = int(float(heating_time_from_api))
                                  if set_rs485_register(serial_port, slave_id, reg_address_heat_time, initial_set_value_heat_scaled):
                                       current_rs485_heat_time_scaled = initial_set_value_heat_scaled
                             except (ValueError, TypeError) as e:
                                  pass
                             except Exception as e:
                                  pass
                        elif serial_port:
                             pass

                        if serial_port and temp_gap_api is not None and temp_gap_api != '':
                             slabe_id = 1
                             reg_temp_gap = 0x0004
                             try:
                                 initial_set_value_temp_gap = int(float(temp_gap_api))
                                 if set_rs485_register(serial_port, slave_id, reg_temp_gap, initial_set_value_temp_gap):
                                     temp_gap_scaled = initial_set_value_temp_gap
                             except (ValueError, TypeError) as e:
                                  pass
                             except Exception as e:
                                  pass
                        elif serial_port:
                            pass
                    else:
                        refrigerator_id = None
                else:
                    pass
            else:
                pass
        except requests.exceptions.RequestException as e:
            pass
        except Exception as e:
            pass

        last_api_check_time = time.time()

        while True:
            current_time = time.time()

            if current_time - last_api_check_time >= api_check_interval_seconds:
                try:
                     response = requests.get(TEMP_API_URL, headers=HEADERS, timeout=10)
                     if response.status_code == 200:
                         data = response.json().get('data')
                         if data and isinstance(data, list) and len(data) > 0:
                             found_fridge = next((item for item in data if item.get('refrigerator_number') == refrigerator_number), None)
                             if found_fridge:
                                 latest_setting_temp_from_api = found_fridge.get('setting_temp_value')
                                 latest_heating_time_from_api = found_fridge.get('defrost_term')
                                 latest_temp_gap_api = found_fridge.get('temp_gap')
                                 if latest_setting_temp_from_api is not None and latest_setting_temp_from_api != setting_temp_value_from_api:
                                     setting_temp_value_from_api = latest_setting_temp_from_api

                                     if serial_port:
                                          slave_id = 1
                                          reg_address_temp_set = 0x0002
                                          try:
                                               new_set_value_temp_scaled = int(float(setting_temp_value_from_api) * 10)
                                               if new_set_value_temp_scaled != current_rs485_temp_setting_scaled:
                                                    if set_rs485_register(serial_port, slave_id, reg_address_temp_set, new_set_value_temp_scaled):
                                                        current_rs485_temp_setting_scaled = new_set_value_temp_scaled
                                               else:
                                                    pass
                                          except (ValueError, TypeError) as e:
                                               pass
                                          except Exception as e:
                                               pass
                                     elif serial_port:
                                          pass
                                 elif latest_setting_temp_from_api is not None and latest_setting_temp_from_api == setting_temp_value_from_api:
                                      pass
                                 elif latest_setting_temp_from_api is None:
                                      pass

                                 if latest_heating_time_from_api is not None and latest_heating_time_from_api != heating_time_from_api and latest_heating_time_from_api != '':
                                     heating_time_from_api = latest_heating_time_from_api

                                     if serial_port:
                                          slave_id = 1
                                          reg_address_heat_time = 0x0012
                                          try:
                                               new_set_value_heat_scaled = int(float(heating_time_from_api))
                                               if new_set_value_heat_scaled != current_rs485_heat_time_scaled:
                                                    if set_rs485_register(serial_port, slave_id, reg_address_heat_time, new_set_value_heat_scaled):
                                                        current_rs485_heat_time_scaled = new_set_value_heat_scaled
                                               else:
                                                    pass
                                          except (ValueError, TypeError) as e:
                                               pass
                                          except Exception as e:
                                               pass
                                     elif serial_port:
                                          pass
                                 elif latest_heating_time_from_api is not None and latest_heating_time_from_api == heating_time_from_api:
                                      pass
                                 elif latest_heating_time_from_api is None or latest_heating_time_from_api == '':
                                      pass

                                 if latest_temp_gap_api is not None and latest_temp_gap_api != latest_temp_gap_api and latest_temp_gap_api != '':
                                     temp_gap_api = latest_temp_gap_api
                                     if serial_port:
                                          slave_id = 1
                                          reg_address_temp_gap = 0x0004
                                          try:
                                               new_value_temp_gap_scaled = int(float(temp_gap_api))
                                               if new_value_temp_gap_scaled != temp_gap_scaled:
                                                    if set_rs485_register(serial_port, slave_id, reg_address_temp_set, new_value_temp_gap_scaled):
                                                        temp_gap_scaled = new_value_temp_gap_scaled
                                                    else:
                                                         pass
                                               else:
                                                    pass
                                          except (ValueError, TypeError) as e:
                                              pass
                                          except Exception as e:
                                                 pass
                                     elif serial_port:
                                          pass
                                 elif latest_temp_gap_api is not None and latest_temp_gap_api == temp_gap_api:
                                       pass
                                 elif latest_temp_gap_api is None or latest_temp_gap_api == '':
                                       pass
                             else:
                                 pass
                         else:
                             pass
                     else:
                         pass
                except requests.exceptions.RequestException as e:
                     pass
                except Exception as e:
                     pass
                finally:
                     last_api_check_time = current_time

            current_value = read_current()
            ds18b20_temp = read_ds18b20_temp()

            if serial_port and serial_port.isOpen():
                rs485_temp = read_rs485_temp(serial_port)
            else:
                rs485_temp = None

            data_to_send = {
                "temperature_value": str(ds18b20_temp) if ds18b20_temp is not None else None,
                "out_temperature_value": str(rs485_temp) if rs485_temp is not None else None,
                "setting_temp_value": str(setting_temp_value_from_api) if setting_temp_value_from_api is not None else None,
                "current_value": str(current_value) if current_value is not None else None,
                "refrigerator_id": int(refrigerator_id) if refrigerator_id is not None else None
            }

            # logging으로 전송 데이터 출력
            logging.info(f'data_to_send: {data_to_send}')

            if refrigerator_id is not None:
                try:
                    response = requests.post(DATA_POST_URL, json=data_to_send, headers=HEADERS, timeout=10)
                    if response.status_code == 200 or response.status_code == 201:
                        pass
                    else:
                        pass
                except requests.exceptions.RequestException as e:
                    pass
                except Exception as e:
                     pass
            else:
                pass

            time.sleep(10)

    except KeyboardInterrupt:
        pass
    except Exception as e:
        pass
    finally:
        if serial_port and serial_port.isOpen():
            serial_port.close()

if __name__ == "__main__":
    refrigerator_number = input("냉장고번호 입력: ").strip()
    main(refrigerator_number)
