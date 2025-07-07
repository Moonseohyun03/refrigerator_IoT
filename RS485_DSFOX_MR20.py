from pymodbus.client import ModbusSerialClient

# RS485 설정
client = ModbusSerialClient(
    method='rtu',        # RS485 통신 방식
    port='/dev/ttyS0',   # 라즈베리파이 UART 포트
    baudrate=9600,       # DSFOX-MR20 기본 설정
    parity='N',          # 패리티 없음
    stopbits=1,          # 스톱비트 1개
    bytesize=8,          # 데이터 비트 8개
    timeout=1            # 타임아웃 설정
)

def read_temperature():
    """DSFOX-MR20에서 현재 온도 읽기"""
    if client.connect():  # RS485 연결 확인
        try:
            # 현재 온도 값 읽기 (Modbus 레지스터 주소 40001)
            result = client.read_holding_registers(address=1, count=1, unit=1)
            if not result.isError():
                temp_celsius = result.registers[0] / 10.0  # 온도값 변환
                print(f"현재 온도: {temp_celsius} ℃")
            else:
                print("데이터 읽기 오류 발생")
        except Exception as e:
            print(f"에러 발생: {e}")
        finally:
            client.close()
    else:
        print("RS485 연결 실패")

# 테스트 실행
read_temperature()
