from pymodbus.client import ModbusSerialClient

# RS485 설정
client = ModbusSerialClient(
    method='rtu',
    port='/dev/ttyS0',  # 라즈베리파이 UART 포트
    baudrate=9600,
    parity='N',
    stopbits=1,
    bytesize=8,
    timeout=1
)

if client.connect():
    # 온도값 읽기 (레지스터 주소 40001)
    result = client.read_holding_registers(address=1, count=1, unit=1)
    if not result.isError():
        print(f"현재 온도: {result.registers[0] / 10.0} ℃")
    else:
        print("데이터 읽기 오류 발생")

    client.close()
else:
    print("RS485 연결 실패")
