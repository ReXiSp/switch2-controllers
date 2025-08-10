import sys
import time
from sdl2 import *
import sdl2.ext
import ctypes

def run():
    # SDLの初期化
    if SDL_Init(SDL_INIT_GAMECONTROLLER | SDL_INIT_SENSOR) != 0:
        print(f"SDLの初期化に失敗しました: {SDL_GetError()}")
        return -1

    # ---- 複数のコントローラーを検出して開く ----
    controllers = {}
    sensor_data = {}

    num_joysticks = SDL_NumJoysticks()
    print(f"接続されているジョイスティックの数: {num_joysticks}")

    for i in range(num_joysticks):
        if SDL_IsGameController(i):
            controller_obj = SDL_GameControllerOpen(i)
            if controller_obj:
                # コントローラーのジョイスティックを取得し、インスタンスIDを得る
                joystick = SDL_GameControllerGetJoystick(controller_obj)
                instance_id = SDL_JoystickInstanceID(joystick)
                name = SDL_GameControllerName(controller_obj).decode('utf-8')
                
                # インスタンスIDをキーとしてコントローラー情報を保存
                controllers[instance_id] = {
                    'obj': controller_obj,
                    'name': name
                }
                # センサーデータを保存する領域を初期化
                sensor_data[instance_id] = {
                    'name': name,
                    'accel': [0.0, 0.0, 0.0],
                    'gyro': [0.0, 0.0, 0.0]
                }
                
                print(f"コントローラーを開きました: ID={instance_id}, Name={name}")
                
                # このコントローラーのセンサーを有効化
                SDL_GameControllerSetSensorEnabled(controller_obj, SDL_SENSOR_ACCEL, SDL_TRUE)
                SDL_GameControllerSetSensorEnabled(controller_obj, SDL_SENSOR_GYRO, SDL_TRUE)

    if not controllers:
        print("利用可能なゲームコントローラーが見つかりませんでした。")
        SDL_Quit()
        return -1

    # ---- メインループ ----
    running = True
    event = SDL_Event()
    
    print("\nセンサーの値を取得します... (Ctrl+Cで終了)")

    try:
        while running:
            # イベント処理
            while SDL_PollEvent(ctypes.byref(event)) != 0:
                if event.type == SDL_QUIT:
                    running = False
                    break
                
                if event.type == SDL_CONTROLLERBUTTONDOWN:
                    if event.cbutton.button == SDL_CONTROLLER_BUTTON_B:
                        print("Bボタンが押されたので終了します。")
                        running = False
                        break
                
                # センサー値更新イベント
                if event.type == SDL_CONTROLLERSENSORUPDATE:
                    # `which` でどのコントローラーからのイベントか識別
                    instance_id = event.csensor.which
                    
                    if instance_id in sensor_data:
                        if event.csensor.sensor == SDL_SENSOR_ACCEL:
                            # 加速度データを更新
                            sensor_data[instance_id]['accel'] = list(event.csensor.data)
                        elif event.csensor.sensor == SDL_SENSOR_GYRO:
                            # ジャイロデータを更新
                            sensor_data[instance_id]['gyro'] = list(event.csensor.data)

            # ---- 全コントローラーの情報を描画 ----
            # ANSIエスケープシーケンスで画面をクリア
            print("\033[H\033[J", end="") 

            for id, data in sensor_data.items():
                accel = data['accel']
                gyro = data['gyro']
                print(f"--- Controller ID: {id} ({data['name']}) ---")
                print(f"  Accel [X,Y,Z]: {accel[0]: >8.4f}, {accel[1]: >8.4f}, {accel[2]: >8.4f}")
                print(f"  Gyro  [X,Y,Z]: {gyro[0]: >8.4f}, {gyro[1]: >8.4f}, {gyro[2]: >8.4f}")
                print("-" * (30 + len(data['name'])))

            if not running:
                break
            
            # CPU負荷を下げるために少し待機
            SDL_Delay(16) # 約60fps相当

    except KeyboardInterrupt:
        print("\nプログラムが中断されました。")
    finally:
        # ---- クリーンアップ ----
        print("\nリソースを解放しています...")
        for controller_info in controllers.values():
            if controller_info['obj']:
                SDL_GameControllerClose(controller_info['obj'])
        SDL_Quit()

if __name__ == "__main__":
    sys.exit(run())