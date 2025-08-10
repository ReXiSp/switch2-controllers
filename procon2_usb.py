import usb.core
import usb.util
import sys
import platform
import hid
import asyncio, threading
from utils import decodeu, reverse_bits, get_stick_xy, decodes
import time
import vgamepad
import vgamepad.win.vigem_commons as vcom
from controller import ControllerInputData, StickCalibrationData, VibrationData
from virtual_controller import VirtualController
from config import CONFIG

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

async def set_vibration(vibration: VibrationData):
    global vibration_packet_id
    """Set vibration data"""
    payload = (b'\x02' + (0x50 + (vibration_packet_id & 0x0F)).to_bytes() + vibration.get_bytes()).ljust(17, b'\0')
    if device:
        # print(payload.hex(" "))
        device.write(payload)
    vibration_packet_id += 1

def vibration_callback(client, target, large_motor, small_motor, led_number, user_data):
    global next_vibration_event
    # print("Vibration : {}, {}".format(large_motor, small_motor))
    vibrationData = VibrationData()
    vibrationData.lf_amp = int(800 * large_motor / 256)
    vibrationData.hf_amp = int(800 * small_motor / 256)
    # print(vibrationData.hf_amp)
    if next_vibration_event:
        # Notifify previous call to stop sending vibration commands
        next_vibration_event.set()
        next_vibration_event = None

    next_event = asyncio.Event()
    if large_motor == 0 and small_motor == 0:
        # No Need to send command repeatedly
        next_event.set()
    else:
        next_vibration_event = next_event

    async def send_vibration_task():
        # imit for how long we vibrate if we don't receive any command, just in case
        for i in range(500):
            await set_vibration(vibrationData)
            # await asyncio.sleep(0.02)
            if next_event.is_set():
                break

    def run_async_loop_in_thread():
        asyncio.run(send_vibration_task())

    t = threading.Thread(target=run_async_loop_in_thread)
    t.start()

try:
    print("Initializing...")
    write_command(COMMAND_USB, SUBCOMMAND_INIT, bytes.fromhex("01 00 FF FF FF FF FF FF"))
    write_command(COMMAND_USB, SUBCOMMAND_REPORT_TYPE, bytes.fromhex("05 00 00 00"))
    # write_command(COMMAND_PAIR, SUBCOMMAND_PAIR_SET_MAC, bytes.fromhex("00 02 FF FF FF FF FF FF FF FF FF FF FF FF"))
    # ltk1 = bytes([0x00, 0xea, 0xbd, 0x47, 0x13, 0x89, 0x35, 0x42, 0xc6, 0x79, 0xee, 0x07, 0xf2, 0x53, 0x2c, 0x6c, 0x31])
    # write_command(COMMAND_PAIR, SUBCOMMAND_PAIR_LTK1, ltk1)
    # ltk2 = bytes([0x00, 0x40, 0xb0, 0x8a, 0x5f, 0xcd, 0x1f, 0x9b, 0x41, 0x12, 0x5c, 0xac, 0xc6, 0x3f, 0x38, 0xa0, 0x73])
    # write_command(COMMAND_PAIR, SUBCOMMAND_PAIR_LTK2, ltk2)
    # write_command(COMMAND_PAIR, SUBCOMMAND_PAIR_FINISH, b"\0")
    # write_command(COMMAND_USB, SUBCOMMAND_HAPTIC, bytes.fromhex("09 00 00 00"))
    #SET LED
    set_leds(1)
    enableFeatures(FEATURE_MOTION)
    enableFeatures(FEATUER_VIBRATION)
    print("Initialized.")
    print("Reading stick calibration data...")
    stick_calibration, second_stick_calibration = read_calibration_data()
    device = hid.device()
    device.open(VENDOR_ID, PRODUCT_ID)

    controller = vgamepad.VDS4Gamepad()
    controller.register_notification(callback_function=vibration_callback)
    print("VGamepad Init")

    report = vcom.DS4_SUB_REPORT_EX()

    print(f"Opened HID Device: {device.get_manufacturer_string()} {device.get_product_string()}")
    print("Press Ctrl+C to stop")
    device.set_nonblocking(1)
    while True:
        data = device.read(64)
        if data:
            # print(f"Raw data: {bytes(data)[0:].hex(' ')}")
            # print(f"X: {bytes(data)[0x16:0x18].hex(' ')} Y: {bytes(data)[0x1A:0x1C].hex(' ')}  Z: {bytes(data)[0x1E:0x20].hex(' ')}")
            inputData = ControllerInputData(bytes(data)[1:], stick_calibration, second_stick_calibration)
            # buttons = decodeu(data[3:6])
            buttons = inputData.buttons
            # print(buttons)
            buttonsConfig = CONFIG.procon_config

            # y, x, z = decodes(bytes(data)[0x16:0x18]), decodes(bytes(data)[0x1A:0x1C]), decodes(bytes(data)[0x1E:0x20])
            # print(f"X: {x}, Y: {y}, Z: {z}")

            report.wButtons, report.bSpecial, dpad_direction, left_trigger, right_trigger = buttonsConfig.convert_buttons(buttons)
            vcom.DS4_SET_DPAD(report, dpad_direction)
            report.bTriggerL = 255 if left_trigger else 0
            report.bTriggerR = 255 if right_trigger else 0

            report.bThumbRX = 128 + round(inputData.right_stick[0] * 127)
            report.bThumbRY = 128 + round(-inputData.right_stick[1] * 127)

            report.bThumbLX = 128 + round(inputData.left_stick[0] * 127)
            report.bThumbLY = 128 + round(-inputData.left_stick[1] * 127)
            
            # # Motion Controls 
            report.wAccelX = inputData.accelerometer[0] * 2
            report.wAccelY = inputData.accelerometer[2] * 2
            report.wAccelZ = -inputData.accelerometer[1] * 2
            report.wGyroX = inputData.gyroscope[0]
            report.wGyroY = inputData.gyroscope[2]
            report.wGyroZ = -inputData.gyroscope[1]

            ex = vcom.DS4_REPORT_EX(Report=report)
            controller.update_extended_report(ex)

except usb.core.USBError as e:
    print(f"Error while transfer: {e}")
finally:
    usb.util.release_interface(dev, USB_INTERFACE_NUMBER)
    usb.util.dispose_resources(dev)