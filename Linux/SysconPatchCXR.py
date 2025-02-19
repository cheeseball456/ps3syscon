#!/usr/bin/python3
from binascii import unhexlify as uhx
import os
import string
import sys
import time

class PS3UART(object):

    try:
       # Check if required Python modules are installed
       import serial # pyserial
       from Crypto.Cipher import AES # pycryptodome
    except ImportError:
       print('Error: The pyserial and pycryptodome modules are required. You can install it with "pip install pyserial pycryptodome"')
       sys.exit(1)
       
    ser = serial.Serial()
    type = ''
            
    sc2tb = uhx('71f03f184c01c5ebc3f6a22a42ba9525')  # Syscon to TestBench Key    (0x130 xor 0x4578)
    tb2sc = uhx('907e730f4d4e0a0b7b75f030eb1d9d36')  # TestBench to Syscon Key    (0x130 xor 0x4588)
    value = uhx('3350BD7820345C29056A223BA220B323')  # 0x45B8
    zero  = uhx('00000000000000000000000000000000')

    auth1r_header = uhx('10100000FFFFFFFF0000000000000000')
    auth2_header  = uhx('10010000000000000000000000000000')
    
    def aes_decrypt_cbc(self, key, iv, in_data):
        return AES.new(key, AES.MODE_CBC, iv).decrypt(in_data)
    
    def aes_encrypt_cbc(self, key, iv, in_data):
        return AES.new(key, AES.MODE_CBC, iv).encrypt(in_data)

    def __init__(self, port, type):
        self.ser.port = port
        if(type == 'CXR' or type == 'SW'):
            self.ser.baudrate = 57600
        elif(type == 'CXRF'):
            self.ser.baudrate = 115200
        else:
            assert(False)
        self.type = type
        self.ser.timeout = 0.1
        self.ser.open()
        assert(self.ser.isOpen())
        self.ser.flush()
        
    def __del__(self):
        self.ser.close()
        
    def send(self, data):
        self.ser.write(data.encode('ascii'))    
                            
    def receive(self):
        return self.ser.read(self.ser.inWaiting())
        
    def command(self, com, wait = 1, verbose = False):
        if(verbose):
            print('Command: ' + com)
        
        if(self.type == 'CXR'):        
            length = len(com)
            checksum = sum(bytearray(com, 'ascii')) % 0x100
            if(length <= 10):
                self.send('C:{:02X}:{}\r\n'.format(checksum, com))
            else:
                j = 10
                self.send('C:{:02X}:{}'.format(checksum, com[0:j]))
                for i in range(length - j, 15, -15):
                    self.send(com[j:j+15])
                    j += 15
                self.send(com[j:] + '\r\n')
        elif(self.type == 'SW'):    
            length = len(com)
            if(length >= 0x40):
                if(self.command('SETCMDLONG FF FF')[0] != 0):
                    return (0xFFFFFFFF, ['Setcmdlong'])        
            checksum = sum(bytearray(com, 'ascii')) % 0x100
            self.send('{}:{:02X}\r\n'.format(com, checksum))
        else:
            self.send(com + '\r\n')
            
        time.sleep(wait)
        answer = self.receive().decode('ascii').strip()
        if(verbose):
            print('Answer: ' + answer)
        
        if(self.type == 'CXR'):
            answer = answer.split(':')
            if(len(answer) != 3):
                return (0xFFFFFFFF, ['Answer length'])
            checksum = sum(bytearray(answer[2], 'ascii')) % 0x100
            if(answer[0] != 'R' and answer[0] != 'E'):
                return (0xFFFFFFFF, ['Magic'])
            if(answer[1] != '{:02X}'.format(checksum)):
                return (0xFFFFFFFF, ['Checksum'])    
            data = answer[2].split(' ')
            if(answer[0] == 'R' and len(data) < 2 or answer[0] == 'E' and len(data) != 2):
                return (0xFFFFFFFF, ['Data length'])
            if(data[0] != 'OK' or len(data) < 2):
                return (int(data[1], 16), [])
            else:
                return (int(data[1], 16), data[2:])    
        elif(self.type == 'SW'):
            answer = answer.split('\n')
            for i in range(0, len(answer)):
                answer[i] = answer[i].replace('\n', '').rsplit(':', 1)
                if(len(answer[i]) != 2):
                    return (0xFFFFFFFF, ['Answer length'])
                checksum = sum(bytearray(answer[i][0], 'ascii')) % 0x100
                if(answer[i][1] != '{:02X}'.format(checksum)):
                    return (0xFFFFFFFF, ['Checksum'])
                answer[i][0] += '\n'
            ret = answer[-1][0].replace('\n', '').split(' ')
            if(len(ret) < 2 or len(ret[1]) != 8 and not all(c in string.hexdigits for c in ret[1])):
                return (0, [x[0] for x in answer])
            elif(len(answer) == 1):         
                return (int(ret[1], 16), ret[2:])
            else:
                return (int(ret[1], 16), [x[0] for x in answer[:-1]])
        else:
            return (0, [answer])
            
    def auth(self):
        if(self.type == 'CXR' or self.type == 'SW'):
            auth1r = self.command('AUTH1 10000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000')
            if(auth1r[0] == 0 and auth1r[1] != []):
                auth1r = uhx(auth1r[1][0])
                if(auth1r[0:0x10] == self.auth1r_header):
                    data = self.aes_decrypt_cbc(self.sc2tb, self.zero, auth1r[0x10:0x40])
                    if(data[0x8:0x10] == self.zero[0x0:0x8] and data[0x10:0x20] == self.value and data[0x20:0x30] == self.zero):
                        new_data = data[0x8:0x10] + data[0x0:0x8] + self.zero + self.zero
                        auth2_body = self.aes_encrypt_cbc(self.tb2sc, self.zero, new_data)
                        auth2r = self.command('AUTH2 ' + ''.join('{:02X}'.format(c) for c in bytearray(self.auth2_header + auth2_body)))
                        if(auth2r[0] == 0):
                            return 'Auth successful'
                        else:
                            return 'Auth failed'
                    else:
                        return 'Auth1 response body invalid'
                else:
                    return 'Auth1 response header invalid'
            else:
                return 'Auth1 response invalid'
        else:
            scopen = self.command('scopen')
            if('SC_READY' in scopen[1][0]):
                auth1r = self.command('10000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000')
                auth1r = auth1r[1][0].split('\r')[1][1:]
                if(len(auth1r) == 128):
                    auth1r = uhx(auth1r)
                    if(auth1r[0:0x10] == self.auth1r_header):
                        data = self.aes_decrypt_cbc(self.sc2tb, self.zero, auth1r[0x10:0x40])
                        if(data[0x8:0x10] == self.zero[0x0:0x8] and data[0x10:0x20] == self.value and data[0x20:0x30] == self.zero):
                            new_data = data[0x8:0x10] + data[0x0:0x8] + self.zero + self.zero
                            auth2_body = self.aes_encrypt_cbc(self.tb2sc, self.zero, new_data)
                            auth2r = self.command(''.join('{:02X}'.format(c) for c in bytearray(self.auth2_header + auth2_body)))
                            if('SC_SUCCESS' in auth2r[1][0]):
                                return 'Auth successful'
                            else:
                                return 'Auth failed'
                        else:
                            return 'Auth1 response body invalid'
                    else:
                        return 'Auth1 response header invalid'
                else:
                    return 'Auth1 response invalid'
            else:
                return 'scopen response invalid'

if(len(sys.argv) < 3):
    print(os.path.basename(__file__) + ' <serial port> <patch file>')
    sys.exit(1)
 
ps3 = PS3UART(sys.argv[1], 'CXR')
f = open(sys.argv[2], 'rb')
patch = f.read()
f.close()
print("Version: " + ps3.command("VER")[1][0])
print(ps3.auth())
patch_area_1 = 0x2800
patch_area_2 = 0x4400 # 0x7400 for CXR713, 0x4400 for CXR714
block_size = 0x40
print("First region")
for i in xrange(0, 0x400, block_size):
    print(hex(ps3.command("EEP SET " + hex(i+patch_area_1)[2:] + " " + hex(block_size)[2:] + " " + patch[i:i+block_size].encode('hex'))[0]))
 
print("") 
print("Second region")
for i in xrange(0x400, 0x1000, block_size):
    print(hex(ps3.command("EEP SET " + hex(i+patch_area_2-0x400)[2:] + " " + hex(block_size)[2:] + " " + patch[i:i+block_size].encode('hex'))[0]))