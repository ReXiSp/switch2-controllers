import vgamepad

from controller import Controller, ControllerInputData
from config import CONFIG

class VirtualController:
    player_number: int
    controllers: list[Controller]
    xb_controller: vgamepad.VX360Gamepad
    previous_buttons_left: int
    previous_buttons_right: int

    def __init__(self, player_number: int):
        self.player_number = player_number
        self.controllers = []
        self.xb_controller = vgamepad.VX360Gamepad()
        self.previous_buttons_left = 0x00000000
        self.previous_buttons_right = 0x00000000

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
