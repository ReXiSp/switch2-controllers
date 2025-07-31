from dataclasses import dataclass
import yaml
from controller import ControllerInputData
import logging

logger = logging.getLogger(__name__)

XB_BUTTONS = {
    "UP": 0x0001,
    "DOWN": 0x0002,
    "LEFT": 0x0004,
    "RIGHT": 0x0008,
    "START": 0x0010,
    "BACK": 0x0020,
    "L_STK": 0x0040,
    "R_STK": 0x0080,
    "LB": 0x0100,
    "RB": 0x0200,
    "GUIDE": 0x0400,
    "A": 0x1000,
    "B": 0x2000,
    "X": 0x4000,
    "Y": 0x8000,
}

@dataclass
class Config:
    combine_joycons: bool
    buttons: dict[int, int]
    left_trigger: list[int]
    right_trigger: list[int]

    def __init__(self, config_file_path: str):
        self.buttons = {}
        self.left_trigger = []
        self.right_trigger = []

        with open(config_file_path) as cf:
            config = yaml.safe_load(cf)

            self.combine_joycons = config["combine_joycons"]

            for k, v in config["buttons"].items():
                if k not in ControllerInputData.BUTTONS:
                    raise Exception(f"Unknown switch button name in config: {k}")
                
                switch_button = ControllerInputData.BUTTONS[k]
                if v is not None:
                    if v == "LT":
                        self.left_trigger.append(switch_button)
                    elif v == "RT":
                        self.right_trigger.append(switch_button)
                    else:
                        if v not in XB_BUTTONS:
                            raise Exception(f"Unknown XB button name in config: {v}")
                        xb_button = XB_BUTTONS[v]

                        self.buttons[switch_button] = xb_button
        
        logger.info(f"Config successfully read {self}")

    def convert_buttons(self, switch_buttons: int):
        xb_buttons = 0x0000
        for switch_button, xb_button in self.buttons.items():
            if switch_buttons & switch_button:
                xb_buttons |= xb_button

        left_trigger = any([b & switch_buttons for b in self.left_trigger])
        right_trigger = any([b & switch_buttons for b in self.right_trigger])

        return xb_buttons, left_trigger, right_trigger
    
CONFIG = Config("config.yaml")
