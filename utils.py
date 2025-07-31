DEADZONE = 50

def to_hex(buffer):
    return " ".join("{:02x}".format(x) for x in buffer)

def decodeu(data: bytes):
    return int.from_bytes(data, byteorder='little', signed=False)

def decodes(data: bytes):
    return int.from_bytes(data, byteorder='little', signed=True)

def convert_mac_string_to_value(mac: str):
    return int.from_bytes(bytes([int(b, 16) for b in mac.split(":")]), 'big')

def get_stick_xy(data: bytes):
    """Convert 3 bytes containing stick x y values into these values"""
    value = decodeu(data)
    x = value & 0xFFF
    y = value >> 12

    return x, y

def signed_looping_difference_16bit(a, b):
    diff = (b - a) % 65536
    return diff - 65536 if diff > 32768 else diff

def apply_calibration_to_axis(raw_value, center, max_abs, min_abs):
    signed_value = raw_value - center
    if signed_value > DEADZONE:
        return min(signed_value / max_abs, 1)
    if signed_value < -DEADZONE:
        return -min(-signed_value / min_abs, 1)
    return 0
