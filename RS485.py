import serial
import time

# 시리얼 포트 설정
ser = serial.Serial(
    port="/dev/ttyS0",  # RS485가 연결된 포트 (ttyAMA0일 수도 있음)
    baudrate=9600,      # 장비에 맞는 속도로 설정
    parity=serial.PARITY_NONE,
    stopbits=serial.STOPBITS_ONE,
    bytesize=serial.EIGHTBITS,
    timeout=1
)

def send_data(data):
    """RS485로 데이터 전송"""
    ser.write(data)
    print(f"송신: {data}")

def receive_data():
    """RS485로 데이터 수신"""
    time.sleep(1)  # 데이터가 올 때까지 대기
    if ser.in_waiting > 0:
        received = ser.read(ser.in_waiting)
        print(f"수신: {received}")

try:
    while True:
        send_data(b'\x01\x03\x00\x00\x00\x01\x85\xDB')  # Modbus RTU 예제
        receive_data()
        time.sleep(2)
except KeyboardInterrupt:
    print("프로그램 종료")
    ser.close()
