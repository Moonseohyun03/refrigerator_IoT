import os
import glob
import time
import datetime

os.system('modprobe wl-gpio')
os.system('modprobe wl-therm')

base_dir = '/sys/bus/wl/devices/'
device_folder = glob.glob(base_dir + "28*")[0]
device_file = device_folder + '/wl_slave'

def read_temp_raw() :
    f = open(device_file, 'r')
    lines = f.readlines()
    f.close()
    return lines

def read_temp() :
    lines = read_temp_raw()
    while lines[0].strip()[-3:] != 'YES' :
        time.sleep(0.2)
        lines = read_temp_raw()
    equals_pos = lines[1].find('t=')
    if equals_pos != -1 :
        temp_string = lines[1][equals_pos+2:]
        temp_c = float(temp_string) / 1000.0
        temp_f = temp_c * 9.0 / 5.0 + 32.0
        return temp_c, temp_f

while True:
    dtime = datetime.datetime.now()
    mydate = str(dtime.date())
    mytime = str(dtime.time())
    a = read_temp()
    print(a[0])
    mylog = open('log.csv', 'a')
    mystr = mydate + "," + mytime + "," + str(a[0]) + "\n"
    print(mystr)
    mylog.write(mystr)
    mylog.close()
    time.sleep(1)
