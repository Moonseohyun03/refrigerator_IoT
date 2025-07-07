# refrigerator_IoT

Ubuntu 기반 Raspberry Pi 4에서 동작하는 냉장고 제어용 IoT 하드웨어 시스템
RS485(Modbus) 통신을 통해 산업용 온도 제어기를 제어하고, 디지털 온도 센서 및 전류 센서를 통해 실시간 데이터를 수집

## 🧊 주요 기능

- RS485(Modbus) 기반 온도 제어기 통신
- 디지털 온도 센서(DS18B20) 데이터 수집
- 전류 센서(SCT-013-030A)를 통한 냉장고 전력 사용량 측정
- SQLite를 통한 로컬 데이터 저장
- 센서 상태 이상 감지 및 로그 기록

## 🛠 사용 환경

- Raspberry Pi 4B (RAM: 4GB 이상 권장)
- OS: Ubuntu 22.04 LTS (64bit)
- Python 3.10+

## 🔌 하드웨어 구성
 
| 장비               | 설명 |
|---------------- ---|------|
| Raspberry Pi 4B    | 메인 IoT 기기 |
| DS18B20            | 디지털 온도 센서 |
| SCT-013-030A       | 비접촉 AC 전류 센서 |
| FOX-MR20 (CONOTEC) | RS485 기반 산업용 온도 제어기 |
| TTL to RS485 모듈  | Modbus 통신용 |
| 16bit 4채널 ADC    | 아날로그 센서 변환용 |
