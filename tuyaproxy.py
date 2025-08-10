#!/usr/bin/python3
import threading
import time

import uvicorn
from fastapi import FastAPI
import tinytuya
import yaml
from starlette.responses import JSONResponse

mode_mapping = {
    "Cooling": 0,
    "Heating": 1,
    "Auto": 2
}

work_mode_mapping = {
    "Silence": 0,
    "Smart": 1,
    "Boost": 2,
}

dps_mapping = {
    "1":  "switch",
    "2":  "mode",
    "4":  "temp_set",
    "5":  "work_mode",
    "15": "fault",
    "16": "temp_current",
    "17": "work_state",
    "25": "effluent_temp",
}

dps_scale = {
    "4": 0.1,
    "16": 0.1,
}

state_lock = threading.Lock()
state = {
    "timestamp": int(time.time()),
    "connected": 0,
    "dps": {},
    "values": {}
}

def merge_dps_and_map(incoming_dps: dict) -> None:
    state["dps"].update(incoming_dps)

    for k, v in incoming_dps.items():
        if k in dps_mapping:
            key = dps_mapping[k]
            if k in dps_scale and isinstance(v, (int, float)):
                v = v * dps_scale[k]
            if isinstance(v, bool):
                state["values"][key] = 1 if v else 0
            elif key == "mode":
                state["values"][key] = mode_mapping[v]
            elif key == "work_mode":
                state["values"][key] = work_mode_mapping[v]
            else:
                state["values"][key] = v

def update_state(connected: bool=None, data: dict=None):
    with state_lock:
        if connected is not None:
            state["connected"] = 1 if connected else 0
        if data is not None and "Err" in data:
            state["connected"] = 0
        if data is not None and "dps" in data:
            state["connected"] = 1
            merge_dps_and_map(data["dps"])
        state["timestamp"] = int(time.time())

def tuya_worker(config: dict):
    while True:
        try:
            d = tinytuya.Device(config["device_id"], config["ip_address"], config["local_key"],
                                version=config["version"])
            d.set_socketPersistent(True)

            d.status(nowait=True)
            last_rx = time.time()

            while True:
                data = d.receive()

                if data:
                    update_state(data=data)
                    last_rx = time.time()

                if time.time() - last_rx > 10:
                    d.heartbeat()

        except Exception:
            update_state(connected=False)
            time.sleep(10)
            continue


def main():
    config = yaml.safe_load(open("/etc/tuya.yaml"))

    t=threading.Thread(target=tuya_worker, args=(config,), name="tuya-worker", daemon=True)
    t.start()

    app = FastAPI(title="tuyaproxy", version="1.0")

    @app.get("/")
    def root():
        with state_lock:
            out = {
                "timestamp": state["timestamp"],
                "device_id": config["device_id"],
                "connected": state["connected"],

            }

            out.update(state["values"])

            return JSONResponse(out)

    uvicorn.run(app, host=["::1", "127.0.0.1"], port=8009)

if __name__ == "__main__":
    main()