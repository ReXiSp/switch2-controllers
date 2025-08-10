from dataclasses import dataclass
import os
import yaml
import logging
import sys

logger = logging.getLogger(__name__)

is_usb = False

SWITCH_BUTTONS = {
    "Y":     0x00000001,
    "X":     0x00000002,
    "B":     0x00000004,
    "A":     0x00000008,
    "SR_R":  0x00000010,
    "SL_R":  0x00000020,
    "R":     0x00000040,
    "ZR":    0x00000080,
    "MINUS": 0x00000100,
    "PLUS":  0x00000200,
    "R_STK": 0x00000400,
    "L_STK": 0x00000800,
    "HOME":  0x00001000,
    "CAPT":  0x00002000,
    "C":     0x00004000,
    # unused 0x00008000,
    "DOWN":  0x00010000,
    "UP":    0x00020000,
    "RIGHT": 0x00040000,
    "LEFT":  0x00080000,
    "SR_L":  0x00100000,
    "SL_L":  0x00200000,
    "L":     0x00400000,
    "ZL":    0x00800000,
    "GL":    0x02000000,
    "GR":    0x01000000,
}

SWITCH_BUTTONS_USB = {
    "Y":     0x00000004,
    "X":     0x00000008,
    "B":     0x00000001,
    "A":     0x00000002,
    "SR_R":  0x00000000,
    "SL_R":  0x00000000,
    "R":     0x00000010,
    "ZR":    0x00000020,
    "MINUS": 0x00004000,
    "PLUS":  0x00000040,
    "R_STK": 0x00000080,
    "L_STK": 0x00008000,
    "HOME":  0x00010000,
    "CAPT":  0x00020000,
    "C":     0x00100000,
    # unused 0x00008000,
    "DOWN":  0x00000100,
    "UP":    0x00000800,
    "RIGHT": 0x00000200,
    "LEFT":  0x00000400,
    "SR_L":  0x00000000,
    "SL_L":  0x00000000,
    "L":     0x00001000,
    "ZL":    0x00002000,
    "GL":    0x00800000,
    "GR":    0x00400000,
}

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

DS4_BUTTONS = {
    "START": 1 << 13,
    "TOUCHPAD": 1 << 1,
    "L_STK": 1 << 14,
    "R_STK": 1 << 15,
    "SHARE": 1 << 12,
    "LB": 1 << 8,
    "RB": 1 << 9,
    "GUIDE": 1 << 0,
    "A": 1 << 6,
    "B": 1 << 5,
    "X": 1 << 7,
    "Y": 1 << 4,
}

DS4_DPAD = [
    "DOWN", "UP", "LEFT", "RIGHT"
]

@dataclass
class ButtonConfig:
    buttons: dict[int, int]
    left_trigger: list[int]
    right_trigger: list[int]
    dpad: dict[int, str]

    def __init__(self, buttons_dict: dict[str, str], is_usb: bool = False):
        self.buttons = {}
        self.left_trigger = []
        self.right_trigger = []
        self.dpad = {}

        for k, v in buttons_dict.items():
            if k not in (is_usb and SWITCH_BUTTONS_USB or SWITCH_BUTTONS):
                raise Exception(f"Unknown switch button name in config: {k}")
            
            switch_button = (is_usb and SWITCH_BUTTONS_USB or SWITCH_BUTTONS)[k]
            if v is not None:
                if v == "LT":
                    self.left_trigger.append(switch_button)
                elif v == "RT":
                    self.right_trigger.append(switch_button)
                elif v in DS4_DPAD:
                    self.dpad[switch_button] = v
                else:
                    if v not in DS4_BUTTONS:
                        raise Exception(f"Unknown XB button name in config: {v}")
                    ds4_button = DS4_BUTTONS[v]

                    self.buttons[switch_button] = ds4_button

    def convert_buttons(self, switch_buttons: int):
        DS4_BUTTONS_ = 0x0000
        DS4_SPECIAL = 0x0000
        DS4_DPAD = []
        for switch_button, ds4_button in self.buttons.items():
            if switch_buttons & switch_button:
                if ds4_button == DS4_BUTTONS["TOUCHPAD"] or ds4_button == DS4_BUTTONS["GUIDE"]:
                    DS4_SPECIAL |= ds4_button
                else:
                    DS4_BUTTONS_ |= ds4_button

        for switch_button, dpad_key in self.dpad.items():
            if switch_buttons & switch_button:
                DS4_DPAD.append(dpad_key)

        left_trigger = any([b & switch_buttons for b in self.left_trigger])
        right_trigger = any([b & switch_buttons for b in self.right_trigger])

        dpad_value = {
            frozenset(): 0x8,
            frozenset(["UP"]): 0x0,
            frozenset(["UP", "RIGHT"]): 0x1,
            frozenset(["RIGHT"]): 0x2,
            frozenset(["DOWN", "RIGHT"]): 0x3,
            frozenset(["DOWN"]): 0x4,
            frozenset(["DOWN", "LEFT"]): 0x5,
            frozenset(["LEFT"]): 0x6,
            frozenset(["UP", "LEFT"]): 0x7,
        }.get(frozenset(d.upper() for d in DS4_DPAD), 0x8)

        return DS4_BUTTONS_, DS4_SPECIAL, dpad_value, left_trigger, right_trigger

@dataclass
class MouseButtonConfig:
    left_button: int
    middle_button: int
    right_button: int

    def __init__(self, buttons_dict: dict[str, str]):
        self.left_button = SWITCH_BUTTONS[buttons_dict["left_button"]]
        self.middle_button = SWITCH_BUTTONS[buttons_dict["middle_button"]]
        self.right_button = SWITCH_BUTTONS[buttons_dict["right_button"]]

@dataclass
class MouseConfig:
    enabled: bool
    sensitivity: float
    scroll_sensitivity: float
    joycon_l_buttons: MouseButtonConfig
    joycon_r_buttons: MouseButtonConfig

    def __init__(self, config_dict: dict[str, str]):
        self.enabled = config_dict["enabled"]
        self.sensitivity = config_dict["sensitivity"]
        self.scroll_sensitivity = config_dict["scroll_sensitivity"]
        buttons_config = config_dict["buttons"]
        self.joycon_l_buttons = MouseButtonConfig(buttons_config["left_joycon"])
        self.joycon_r_buttons = MouseButtonConfig(buttons_config["right_joycon"])


@dataclass
class Config:
    combine_joycons: bool
    motion_controls: bool
    deadzone: int
    dual_joycons_config: ButtonConfig
    single_joycon_l_config: ButtonConfig
    single_joycon_r_config: ButtonConfig
    procon_config: ButtonConfig
    mouse_config: MouseConfig

    def __init__(self, config_file_path: str, is_usb: bool = False):

        with open(config_file_path) as cf:
            config = yaml.safe_load(cf)

            self.combine_joycons = config["combine_joycons"]
            self.deadzone = config["deadzone"]
            self.motion_controls = config["motion_controls"]

            buttons_config = config["buttons"]

            self.dual_joycons_config = ButtonConfig(buttons_config["dual_joycons"], is_usb)
            self.single_joycon_l_config = ButtonConfig(buttons_config["single_joycon_l"], is_usb)
            self.single_joycon_r_config = ButtonConfig(buttons_config["single_joycon_r"], is_usb)
            self.procon_config = ButtonConfig(buttons_config["procon"], is_usb)

            self.mouse_config = MouseConfig(config["mouse"])

        logger.info(f"Config successfully read {self}")

def get_resource(resource_path: str, resource_name = "resources"):
    # PyInstallerでonefile化された場合
    if getattr(sys, 'frozen', False):
        # 実行ファイルのあるディレクトリを取得
        base_path = os.path.dirname(sys.executable)
    # 通常のPythonスクリプトとして実行された場合
    else:
        # スクリプトのあるディレクトリを取得
        base_path = os.path.dirname(__file__)

    return os.path.join(base_path, resource_name, resource_path)
    
CONFIG = Config(get_resource("config.yaml", "."), is_usb)