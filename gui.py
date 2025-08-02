import queue
import threading
import tkinter as tk
from discoverer import start_discoverer
from virtual_controller import VirtualController

controller_frame_size = 200

background_color = "#aaaaaa"
block_color = "#404040"
player_number_bg_color = "#8B8B8B"

CONTROLLER_UPDATED_EVENT = '<<ControllersUpdated>>'

class PlayerInfoBlock:
    def __init__(self, parent):
        self.parent = parent
        self.controller_label = None
        self.player_led_label = None

        self.load_pictures()
        self.init_interface()

    def init_interface(self):
        self.main_frame = tk.Frame(self.parent, width=controller_frame_size, height=controller_frame_size + 8 + 40, bg=player_number_bg_color)
        self.main_frame.pack(padx=10, pady=10, side=tk.LEFT)
        self.main_frame.pack_propagate(False)

        self.controllers_frame = tk.Frame(self.main_frame, width=controller_frame_size, height=controller_frame_size, bg=block_color)
        self.controllers_frame.pack()
        self.controllers_frame.pack_propagate(False)

    def load_pictures(self):
        self.joycon2right = tk.PhotoImage(file="images/joycon2right.png")
        self.joycon2left = tk.PhotoImage(file="images/joycon2left.png")
        self.joycon2leftandright = tk.PhotoImage(file="images/joycon2leftandright.png")
        self.joycon2right_sideway = tk.PhotoImage(file="images/joycon2right_sideway.png")
        self.joycon2left_sideway = tk.PhotoImage(file="images/joycon2left_sideway.png")
        self.player_leds = {nb: tk.PhotoImage(file=f"images/player{nb}.png") for nb in range(1,5)}

    def clearControllerInfo(self):
        if self.controller_label is not None:
            self.controller_label.destroy()
            self.controller_label = None

        if self.player_led_label is not None:
            self.player_led_label.destroy()
            self.player_led_label = None

    def displayControllersInfo(self, virtualController : VirtualController):
        if virtualController.is_single():
            image = self.joycon2right_sideway if virtualController.is_single_joycon_right() else self.joycon2left_sideway
        else:
            image = self.joycon2leftandright

        self.controller_label = tk.Label(self.controllers_frame, image=image, bg=block_color)
        self.controller_label.pack(fill="none", expand=True)

        self.player_led_label = tk.Label(self.main_frame, image=self.player_leds[virtualController.player_number], bg=player_number_bg_color)
        self.player_led_label.pack(pady=20)

class ControllerWindow:
    def __init__(self):
        self.message_queue = queue.Queue()
        self.quit_event = threading.Event()
    
    def init_interface(self):
        self.root = tk.Tk()
        photo = tk.PhotoImage(file = 'images/icon.png')
        self.root.wm_iconphoto(False, photo)
        self.root.title("Switch2 Controllers")
        self.root.geometry("1000x600+50+50")
        self.root.config(bg=background_color, padx=10, pady=10)

        tk.Label(self.root, text="Press and hold sync button, or press a button on an already paired controller.", bg=background_color).pack()

        frame_players = tk.Frame(self.root, bg=background_color)
        frame_players.pack(pady=50, fill=tk.Y)

        self.players_info = [PlayerInfoBlock(frame_players) for i in range(4)]

    def update_controllers_from_queue(self):
        controllers_info = self.message_queue.get()

        for player_info in self.players_info:
            player_info.clearControllerInfo()

        for i, player_info in enumerate(self.players_info):
            controller_info = controllers_info[i]
            if controller_info is not None:
                player_info.displayControllersInfo(controller_info)

    def start(self):
        def update_controllers_callback_threadsafe(controllers: list[VirtualController]):
            self.message_queue.put(controllers)
            self.root.event_generate(CONTROLLER_UPDATED_EVENT)
        
        self.root.bind(CONTROLLER_UPDATED_EVENT, lambda e : self.update_controllers_from_queue())
        t = threading.Thread(target=start_discoverer, args=(update_controllers_callback_threadsafe, self.quit_event))
        t.start()

        def on_quit():
            self.quit_event.set()
            self.root.destroy()

        self.root.protocol("WM_DELETE_WINDOW", on_quit)

        self.root.mainloop()

if __name__ == "__main__":
    window = ControllerWindow()
    window.init_interface()
    window.start()