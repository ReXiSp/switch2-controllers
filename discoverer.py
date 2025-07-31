"""A class used to find switch 2 controllers via Bluetooth
"""
from bleak import BleakScanner, BleakClient, BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData
from bleak.exc import BleakError
import asyncio
import logging
import bluetooth
import yaml
from utils import to_hex, convert_mac_string_to_value, decodeu
from controller import Controller, ControllerInputData, NINTENDO_VENDOR_ID, CONTROLER_NAMES, VibrationData
from virtual_controller import VirtualController
from config import CONFIG

logger = logging.getLogger(__name__)

NINTENDO_BLUETOOTH_MANUFACTURER_ID = 0x0553

class Discoverer:
    def __init__(self):
        pass

async def run():
    try:
        host_mac_value = convert_mac_string_to_value(bluetooth.read_local_bdaddr()[0])
        stop_event = asyncio.Event()
        connected_mac_addresses: list[str] = []
        virtual_controllers: list[VirtualController] = []

        def disconnected_controller(controller: Controller):
            logger.info(f"Controller disconected {controller.client.address}")
            connected_mac_addresses.remove(controller.client.address)
            for vc in virtual_controllers[:]:
                if vc.remove_controller(controller):
                    virtual_controllers.remove(vc)
                    
            logger.info(virtual_controllers)

        lock = asyncio.Lock()

        async def add_controller(device: BLEDevice, paired: bool):
            try:
                controller = await Controller.create_from_device(device)
                logger.info(f"Connected to {device.address}")
                controller.disconnected_callback = disconnected_controller
                if not paired:
                    await controller.pair()
                    logger.info(f"Paired successfully to {device.address}")

                virtual_controller = None
                await lock.acquire()
                try:
                    if CONFIG.combine_joycons:
                        # try to find an already connected joycon to combine with
                        if controller.is_joycon_left():
                            virtual_controller = next(filter(lambda vc: vc.is_single_joycon_right(), virtual_controllers), None)
                        elif controller.is_joycon_right():
                            virtual_controller = next(filter(lambda vc: vc.is_single_joycon_left(), virtual_controllers), None)

                    if virtual_controller is None:
                        virtual_controller = VirtualController(len(virtual_controllers) + 1)
                        virtual_controllers.append(virtual_controller)
                    
                    virtual_controller.add_controller(controller)
                finally:
                    lock.release()
                
                await virtual_controller.init_added_controller(controller)

                logger.info(virtual_controllers)
            except BleakError:
                logging.exception(f"Unable to initialize device {device.address}")
                connected_mac_addresses.remove(device.address)

        async def callback(device: BLEDevice, advertising_data: AdvertisementData):
            if device.address in connected_mac_addresses:
                return
            nintendo_manufacturer_data = advertising_data.manufacturer_data.get(NINTENDO_BLUETOOTH_MANUFACTURER_ID)
            if nintendo_manufacturer_data:
                vendor_id = decodeu(nintendo_manufacturer_data[3:5])
                product_id = decodeu(nintendo_manufacturer_data[5:7])
                reconnect_mac = decodeu(nintendo_manufacturer_data[10:16])
                if vendor_id == NINTENDO_VENDOR_ID and product_id in CONTROLER_NAMES:
                    logging.debug(f"Manufacturer data: {to_hex(nintendo_manufacturer_data)}")
                    if reconnect_mac == 0:
                        logging.info(f"Found pairing device {CONTROLER_NAMES[product_id]} {device.address}")
                        connected_mac_addresses.append(device.address)
                        await add_controller(device, False)
                    elif reconnect_mac == host_mac_value:
                        logging.info(f"Found already paired device {CONTROLER_NAMES[product_id]} {device.address}")
                        connected_mac_addresses.append(device.address)
                        await add_controller(device, True)

        async with BleakScanner(callback) as scanner:
            print("Presss a button on a paired controller, or hold sync button on an unpaired controller")
            await stop_event.wait()
    finally:
        for vc in virtual_controllers:
            for controller in vc.controllers:
                await controller.disconnect()

if __name__ == "__main__":
    asyncio.run(run())