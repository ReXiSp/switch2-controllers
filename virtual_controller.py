import vgamepad
import asyncio
import threading

from controller import Controller, ControllerInputData, VibrationData
from config import CONFIG

class VirtualController:
    player_number: int
    controllers: list[Controller]
    xb_controller: vgamepad.VX360Gamepad
    previous_buttons_left: int
    previous_buttons_right: int
    next_vibration_event: asyncio.Event

    def __init__(self, player_number: int):
        self.player_number = player_number
        self.controllers = []
        self.xb_controller = vgamepad.VX360Gamepad()
        self.previous_buttons_left = 0x00000000
        self.previous_buttons_right = 0x00000000
        self.next_vibration_event = None

        def vibration_callback(client, target, large_motor, small_motor, led_number, user_data):
                print("Vibration : {}, {}".format(large_motor, small_motor))
                vibrationData = VibrationData()
                vibrationData.lf_amp = int(800 * large_motor / 256)
                vibrationData.hf_amp = int(800 * small_motor / 256)

                if self.next_vibration_event:
                    # Notifify previous call to stop sending vibration commands
                    self.next_vibration_event.set()
                    self.next_vibration_event = None

                next_event = asyncio.Event()
                if large_motor == 0 and small_motor == 0:
                    # No Need to send command repeatedly
                    next_event.set()
                else:
                    self.next_vibration_event = next_event

                async def send_vibration_task():
                    while True:
                        if len(self.controllers) == 1:
                            await self.controllers[0].set_vibration(vibrationData)
                        elif len(self.controllers) == 2:
                            await asyncio.gather(self.controllers[0].set_vibration(vibrationData), self.controllers[1].set_vibration(vibrationData))
                        await asyncio.sleep(0.02)
                        if next_event.is_set():
                            break

                def run_async_loop_in_thread():
                    asyncio.run(send_vibration_task())

                t = threading.Thread(target=run_async_loop_in_thread)
                t.start()

        self.xb_controller.register_notification(callback_function=vibration_callback)

    def __repr__(self):
        return f"Player {self.player_number} {self.controllers}"

    async def add_controller(self, controller: Controller):
        if len(self.controllers) > 1:
            raise Exception("Cannot add more than 2 controller on a virtual controller")
        
        if len(self.controllers) != 0:
            # Ensure we only combine left and right joycons together
            existing_controller = self.controllers[0]
            if not (existing_controller.is_joycon_left() and controller.is_joycon_right() or
                    existing_controller.is_joycon_right() and controller.is_joycon_left):
                raise Exception("Can only combine left and right joycons")
        
        await controller.set_leds(self.player_number)

        def input_report_callback(inputData: ControllerInputData, controller: Controller):
            # In case of 2 joycons, we need to merge the left and right buttons input
            buttons = inputData.buttons
            if len(self.controllers) == 2:
                if controller.is_joycon_left():
                    buttons |= self.previous_buttons_right
                    self.previous_buttons_left = inputData.buttons
                elif controller.is_joycon_right():
                    buttons |= self.previous_buttons_left
                    self.previous_buttons_right = inputData.buttons

            self.xb_controller.report.wButtons, left_trigger, right_trigger = CONFIG.convert_buttons(buttons)
            self.xb_controller.left_trigger(255 if left_trigger else 0)
            self.xb_controller.right_trigger(255 if right_trigger else 0)
            if not controller.is_joycon_left():
                self.xb_controller.right_joystick_float(inputData.right_stick[0], inputData.right_stick[1])
            
            if not controller.is_joycon_right():
                self.xb_controller.left_joystick_float(inputData.left_stick[0], inputData.left_stick[1])

            self.xb_controller.update()

        await controller.set_input_report_callback(input_report_callback)

        self.controllers.append(controller)

    def remove_controller(self, controller: Controller):
        """Returns True if this was the last controller
        """
        if controller in self.controllers:
            self.controllers.remove(controller)

            if len(self.controllers) == 0:
                del self.xb_controller
                return True

    def is_single_joycon_right(self):
        return len(self.controllers) == 1 and self.controllers[0].is_joycon_right()

    def is_single_joycon_left(self):
        return len(self.controllers) == 1 and self.controllers[0].is_joycon_left()
