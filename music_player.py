import usb.core
import usb.util
import sys
import hid
import asyncio, threading
from utils import decodeu, reverse_bits, get_stick_xy, decodes
import time
import traceback
from decimal import Decimal, ROUND_HALF_EVEN
import json
import pretty_midi
import datetime
import math
from controller import StickCalibrationData, VibrationData

VENDOR_ID = 0x057E 
PRODUCT_ID = 0x2069
USB_INTERFACE_NUMBER = 1

# Commands and subcommands
COMMAND_LEDS = 0x09
SUBCOMMAND_LEDS_SET_PLAYER = 0x07

COMMAND_USB = 0x03
SUBCOMMAND_REPORT_TYPE = 0x0A
SUBCOMMAND_INIT = 0x0D
SUBCOMMAND_HAPTIC = 0x0A

COMMAND_MEMORY = 0x02
SUBCOMMAND_MEMORY_READ = 0x04

COMMAND_VIBRATION = 0x0A
SUBCOMMAND_VIBRATION_PLAY_PRESET = 0x02

COMMAND_PAIR = 0x15
SUBCOMMAND_PAIR_SET_MAC = 0x01
SUBCOMMAND_PAIR_LTK1 = 0x04
SUBCOMMAND_PAIR_LTK2 = 0x02
SUBCOMMAND_PAIR_FINISH = 0x03

COMMAND_FEATURE = 0x0c
SUBCOMMAND_FEATURE_INIT = 0x02
SUBCOMMAND_FEATURE_ENABLE = 0x04

FEATURE_MOTION = 0x04
FEATUER_VIBRATION = 0x20
FEATURE_MOUSE = 0x10
FEATURE_MAGNOMETER = 0x80

# Addresses in controller memory
ADDRESS_CONTROLLER_INFO = 0x00013000
CALIBRATION_JOYSTICK_1 = 0x0130A8
CALIBRATION_JOYSTICK_2 = 0x0130E8
CALIBRATION_USER_JOYSTICK_1 = 0x1fc042
CALIBRATION_USER_JOYSTICK_2 = 0x1fc062

#Repoduce switch led patterns for up to 8 players https://en-americas-support.nintendo.com/app/answers/detail/a_id/22424
LED_PATTERN = {
    1: 0x01,
    2: 0x03,
    3: 0x07,
    4: 0x0F,
    5: 0x09,
    6: 0x05,
    7: 0x0D,
    8: 0x06,
}

print('Finding NS2 Pro Controller...')
dev = usb.core.find(idVendor=VENDOR_ID, idProduct=PRODUCT_ID)

if dev is None:
    print("Device not found")
    sys.exit(1)

print('Device found')

try:
    dev.set_configuration()
    usb.util.claim_interface(dev, USB_INTERFACE_NUMBER)
except usb.core.USBError as e:
    # リソースがビジーな場合は、すでに設定されている可能性がある
    if e.errno == 16: # Resource Busy
        print("Interface Busy")
    else:
        print(f"Failed to init device: {e}")
        sys.exit(1)

# 3. Bulk転送用のエンドポイントを検索
cfg = dev.get_active_configuration()
intf = cfg[(USB_INTERFACE_NUMBER, 0)]

# OUT (PC -> デバイス) のBulkエンドポイントを探す
ep_out = usb.util.find_descriptor(
    intf,
    custom_match=lambda e:
        usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_OUT and
        usb.util.endpoint_type(e.bmAttributes) == usb.util.ENDPOINT_TYPE_BULK
)

# IN (デバイス -> PC) のBulkエンドポイントを探す
ep_in = usb.util.find_descriptor(
    intf,
    custom_match=lambda e:
        usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_IN and
        usb.util.endpoint_type(e.bmAttributes) == usb.util.ENDPOINT_TYPE_BULK
)

def set_leds(player_number: int):
    """Set the player indicator led to the specified <player_number>"""
    if player_number > 8:
        player_number = 8

    value = LED_PATTERN[player_number]
        
    # crash if less than 4 bytes of data, even though only one byte seems significant
    data = value.to_bytes().ljust(4, b'\0')
    write_command(COMMAND_LEDS, SUBCOMMAND_LEDS_SET_PLAYER, data)

def write_command(command_id: int, subcommand_id: int, command_data = b''):
    """Generic write command method"""
    command_buffer = command_id.to_bytes() + b"\x91\x01" + subcommand_id.to_bytes() + b"\x00" + len(command_data).to_bytes() + b"\x00\x00" + command_data
    bytes_written = ep_out.write(command_buffer)
    response_buffer = dev.read(ep_in.bEndpointAddress, 32, timeout=500)
    if len(response_buffer) < 8 or response_buffer[0] != command_id or response_buffer[1] != 0x01:
        raise Exception(f"Unexpected response : {response_buffer}")
    
    return response_buffer[8:]

def enableFeatures(feature_flags: int):
    """Enable or disable features according to <feature_flags>"""
    write_command(COMMAND_FEATURE, SUBCOMMAND_FEATURE_INIT, feature_flags.to_bytes().ljust(4, b'\0'))
    write_command(COMMAND_FEATURE, SUBCOMMAND_FEATURE_ENABLE, feature_flags.to_bytes().ljust(4, b'\0'))

if ep_out is None or ep_in is None:
    print("Endpoint not found")
    sys.exit(1)

def read_memory(length: int, address: int):
    """Returns the requested <length> bytes of data located at <address>"""
    if length > 0x4F:
        raise Exception("Maximum read size is 0x4F bytes")
    data = write_command(COMMAND_MEMORY, SUBCOMMAND_MEMORY_READ, length.to_bytes() + b'\x7e\0\0' + address.to_bytes(length=4,byteorder='little'))
    # Ensure the response is the data we requested
    if (data[0] != length or decodeu(data[4:8]) != address):
        raise Exception(f"Unexpected response from read commmand : {data}")
    return data[8:]

def read_calibration_data():
    """Returns a tuple with calibration data of left and right stick (if present)"""
    calibration_data_1 = read_memory(0x0b, CALIBRATION_USER_JOYSTICK_1)
    if (decodeu(calibration_data_1[:3]) == 0xFFFFFF):
        calibration_data_1 = read_memory(0x0b, CALIBRATION_JOYSTICK_1)
    calibration_data_2 = read_memory(0x0b, CALIBRATION_USER_JOYSTICK_2)
    if (decodeu(calibration_data_2[:3]) == 0xFFFFFF):
        calibration_data_2 = read_memory(0x0b, CALIBRATION_JOYSTICK_2)
    return StickCalibrationData(calibration_data_1), StickCalibrationData(calibration_data_2)

next_vibration_event: asyncio.Event = None
vibration_packet_id = 0
device = None

def set__vibration(vibration: VibrationData):
    global vibration_packet_id
    """Set vibration data"""
    payload = (b'\x02' + (0x50 + (vibration_packet_id & 0x0F)).to_bytes() + vibration.get_bytes()).ljust(17, b'\0')
    if device:
        # print(payload.hex(" "))
        try:
            device.write(payload)
        except Exception:
            traceback.print_exc()
    vibration_packet_id += 1
    if vibration_packet_id > 9:
        vibration_packet_id = 0

async def set_vibration(vibration: VibrationData):
    global vibration_packet_id
    """Set vibration data"""
    payload = (b'\x02' + (0x50 + (vibration_packet_id & 0x0F)).to_bytes() + vibration.get_bytes()).ljust(17, b'\0')
    if device:
        # print(payload.hex(" "))
        try:
            device.write(payload)
        except Exception:
            traceback.print_exc()
    vibration_packet_id += 1
    if vibration_packet_id > 9:
        vibration_packet_id = 0

def send_vibration(vibration: VibrationData):
    global next_vibration_event
    if next_vibration_event:
        # Notifify previous call to stop sending vibration commands
        next_vibration_event.set()
        next_vibration_event = None
    next_event = asyncio.Event()
    if vibration.lf_amp == 0 and vibration.hf_amp == 0:
        # No Need to send command repeatedly
        next_event.set()
    else:
        next_vibration_event = next_event

    async def send_vibration_task():
        # imit for how long we vibrate if we don't receive any command, just in case
        for i in range(100):
            await set_vibration(vibration)
            # await asyncio.sleep(0.02)
            if next_event.is_set():
                break

    def run_async_loop_in_thread():
        asyncio.run(send_vibration_task())
    t = threading.Thread(target=run_async_loop_in_thread)
    t.start()

A = 403.1279
B = 0.00718869

def stop_vibration():
    vib = VibrationData()
    vib.hf_amp = 0
    vib.lf_amp = 0
    send_vibration(vib)

sound =  [
    [261, 523, 1], # C5 
    [293, 493, 1], # D5 
    [329, 440, 1], # E5 
    [349, 391, 1], # F5 
    [391, 349, 1], # G5 
    [440, 329, 1], # A6 
    [493, 293, 1], # B6 
    [523, 261, 1], # C6 
]

def freq_to_code(freq):
    """周波数(Hz)からコード値を計算"""
    return int(math.log(freq / A) / B)

def midi_note_to_freq(note_number):
    """MIDIノート番号→周波数(Hz)"""
    return 440.0 * (2 ** ((note_number - 69) / 12))

def calculate_frequency(key):
    freq = (2**((key-69)/12))*440
    freq_int = int(Decimal(str(freq)).quantize(Decimal('1'), rounding=ROUND_HALF_EVEN))
    return freq_int

try:
    with open("config.json", "r") as f:
        conf = json.load(f)
    print("Config loaded")

    print("Initializing...")
    write_command(COMMAND_USB, SUBCOMMAND_INIT, bytes.fromhex("01 00 FF FF FF FF FF FF"))
    # write_command(COMMAND_USB, SUBCOMMAND_REPORT_TYPE, bytes.fromhex("05 00 00 00"))

    #SET LED
    enableFeatures(FEATUER_VIBRATION)
    print("Initialized.")
    device = hid.device()
    device.open(VENDOR_ID, PRODUCT_ID)

    print(f"Opened HID Device: {device.get_manufacturer_string()} {device.get_product_string()}")
    print("Press Ctrl+C to stop")
    device.set_nonblocking(1)

    playingNotes = []
    noteQueue = []
    insts = conf["instruments"]
    print(insts)
    
    try:
        print("Loading Sound...")
        for i in insts:
            inst = pretty_midi.PrettyMIDI(conf["song"]).instruments[i]
            for note in inst.notes:
                noteQueue.append([note.start, note.end, freq_to_code(calculate_frequency(note.pitch) * conf["pitch_mult"])])

        noteQueue.sort(key=lambda x: x[0])

        print("Play:")
        startTime = datetime.datetime.now()
        while len(noteQueue) > 0 or len(playingNotes) > 0:
            now = datetime.datetime.now()
            t = (now - startTime).total_seconds()

            while True:
                if len(noteQueue) <= 0 or noteQueue[0][0] > t:
                    break
                playingNotes.append(noteQueue[0])
                noteQueue.pop(0)

            # Process Queue
            if len(playingNotes) <= 0:
                # stop_vibration()
                pass

            for note in range(0, len(playingNotes), 2):
                if note + 1 >= conf["sound_count"]:
                    break

                vib = VibrationData()
                vib.lf_amp = conf["amp"]
                vib.lf_freq = playingNotes[note][2]
                vib.lf_en_tone = vib.lf_freq >= 0

                if len(playingNotes) > note + 1 and note + 1 < conf["sound_count"]:
                    vib.hf_amp = conf["amp"]
                    vib.hf_freq = playingNotes[note + 1][2]
                    vib.hf_en_tone = vib.hf_freq >= 0

                set__vibration(vib)
            
            print(playingNotes)

            data = len(playingNotes).to_bytes().ljust(4, b'\0')
            write_command(COMMAND_LEDS, SUBCOMMAND_LEDS_SET_PLAYER, data)

            if len(playingNotes) > 0:
                while True:
                    if len(playingNotes) <= 0 or playingNotes[0][1] > t:
                        break
                    playingNotes.pop(0)

            # time.sleep(0.01)

    except KeyboardInterrupt:
        print("Interrupt")
    except Exception:
        traceback.print_exc()
    finally:
        print("Finished.")
        stop_vibration()

except usb.core.USBError as e:
    print(f"Error while transfer: {e}")
finally:
    usb.util.release_interface(dev, USB_INTERFACE_NUMBER)
    usb.util.dispose_resources(dev)


# end_ms_last = 0
# for note in notes:
#     start_ms = note.start
#     end_ms = note.end
#     duration_ms = note.end - note.start
#     rest_duration_ms = start_ms - end_ms_last
#     # print(rest_duration_ms)
#     # print(note.pitch)
#     if inst.is_drum:
#         pass
#         # print("Drum Detected")
#         # output += f'["drum", {note.pitch}],["rest", {duration_ms}],'
#     else:
#         freq = calculate_frequency(note.pitch)
#         if rest_duration_ms and rest_duration_ms > 0:
#             stop_vibration()
#             print("Rest: " + str(rest_duration_ms))
#             time.sleep(rest_duration_ms)
#         # print(duration_ms)
#         vib = VibrationData()
#         vib.lf_amp = 100
#         # vib.hf_amp = 200
#         vib.lf_freq = freq_to_code(freq)
#         vib.lf_en_tone = vib.lf_freq >= 0
#         # vib.hf_freq = freq_to_code(s[1])
#         # vib.hf_en_tone = vib.hf_freq >= 0
#         # print(vib.lf_freq)
#         # vib.lf_freq = s[0]
#         # vib.hf_freq = s[0]
#         # stop_vibration()
#         # time.sleep(0.025)
#         print("Play: " + str(duration_ms))
#         send_vibration(vib)
#         time.sleep(duration_ms)
#     end_ms_last = end_ms