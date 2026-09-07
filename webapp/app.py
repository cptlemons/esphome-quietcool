import os
import asyncio
import logging
import math
from typing import Dict, Any, Optional, Set
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
import aioesphomeapi

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("quietcool-web")

ESPHOME_HOST = os.getenv("ESPHOME_HOST", "192.168.50.114")
ESPHOME_PORT = int(os.getenv("ESPHOME_PORT", "6053"))
ESPHOME_API_KEY = os.getenv("ESPHOME_API_KEY", "DsAmrZ4wRjNlL9ry1fIMuGNpNveKlkwFI7E8WTgCcGA=")
WEB_PORT = int(os.getenv("WEB_PORT", "8080"))

class QuietCoolBridge:
    def __init__(self, host: str, port: int, noise_psk: str):
        self.host = host
        self.port = port
        self.noise_psk = noise_psk
        self.client: Optional[aioesphomeapi.APIClient] = None
        self.connected = False
        self.entities: Dict[str, Any] = {}
        self.key_to_name: Dict[int, str] = {}
        self.active_websockets: Set[WebSocket] = set()

        self.state: Dict[str, Any] = {
            "connected": False,
            "fan_state": False,
            "fan_speed": 1,
            "fan_speed_name": "Low",
            "supported_speeds": 3,
            "fan_state_known": False,
            "fan_confirmed_off": False,
            "controller_fault": False,
            "timer_program": "None",
            "timer_remaining_minutes": None,
            "timer_program_known": False,
            "timer_remaining_known": False,
            "confirmation_status": "idle",
            "evidence_source": "unavailable",
            "last_confirmed_state": "unknown",
            "speed_capability": "unknown",
            "remote_sender_id": "unknown",
            "wifi_signal": None,
            "battery_level": None,
            "ip_address": host,
            "uptime": 0,
        }

    async def register_websocket(self, ws: WebSocket):
        await ws.accept()
        self.active_websockets.add(ws)
        await ws.send_json(self.state)

    def unregister_websocket(self, ws: WebSocket):
        self.active_websockets.discard(ws)

    async def broadcast(self):
        if not self.active_websockets:
            return
        dead = set()
        for ws in self.active_websockets:
            try:
                await ws.send_json(self.state)
            except Exception:
                dead.add(ws)
        self.active_websockets -= dead

    def _on_state(self, state_msg: Any):
        key = getattr(state_msg, "key", None)
        name = self.key_to_name.get(key)
        if not name:
            return

        changed = False
        if name == "fan":
            new_state = bool(state_msg.state)
            new_speed = getattr(state_msg, "speed_level", 1) or 1
            speed_map = {1: "Low", 2: "Medium", 3: "High"}
            if self.state["fan_state"] != new_state or self.state["fan_speed"] != new_speed:
                self.state["fan_state"] = new_state
                self.state["fan_speed"] = new_speed
                self.state["fan_speed_name"] = speed_map.get(new_speed, "Low")
                changed = True
        elif name == "fan_timer_select":
            val = str(getattr(state_msg, "state", ""))
            if self.state["timer_program"] != val:
                self.state["timer_program"] = val
                changed = True
        elif name == "timer_remaining":
            val = getattr(state_msg, "state", None)
            val_min = int(val) if val is not None and not math.isnan(val) else None
            if self.state["timer_remaining_minutes"] != val_min:
                self.state["timer_remaining_minutes"] = val_min
                changed = True
        elif name == "fan_state_known":
            val = bool(state_msg.state)
            if self.state["fan_state_known"] != val:
                self.state["fan_state_known"] = val
                changed = True
        elif name == "fan_confirmed_off":
            val = bool(state_msg.state)
            if self.state["fan_confirmed_off"] != val:
                self.state["fan_confirmed_off"] = val
                changed = True
        elif name == "controller_fault":
            val = bool(state_msg.state)
            if self.state["controller_fault"] != val:
                self.state["controller_fault"] = val
                changed = True
        elif name == "command_status":
            val = str(getattr(state_msg, "state", ""))
            if self.state["confirmation_status"] != val:
                self.state["confirmation_status"] = val
                changed = True
        elif name == "evidence_source":
            val = str(getattr(state_msg, "state", ""))
            if self.state["evidence_source"] != val:
                self.state["evidence_source"] = val
                changed = True
        elif name == "last_confirmed":
            val = str(getattr(state_msg, "state", ""))
            if self.state["last_confirmed_state"] != val:
                self.state["last_confirmed_state"] = val
                changed = True
        elif name == "speed_capability":
            val = str(getattr(state_msg, "state", ""))
            if self.state["speed_capability"] != val:
                self.state["speed_capability"] = val
                changed = True
        elif name == "remote_sender_id":
            val = str(getattr(state_msg, "state", ""))
            if self.state["remote_sender_id"] != val:
                self.state["remote_sender_id"] = val
                changed = True
        elif name == "wifi_signal":
            val = getattr(state_msg, "state", None)
            if val is not None and not math.isnan(val):
                self.state["wifi_signal"] = int(val)
                changed = True
        elif name == "battery_level":
            val = getattr(state_msg, "state", None)
            if val is not None and not math.isnan(val):
                self.state["battery_level"] = int(val)
                changed = True
        elif name == "uptime":
            val = getattr(state_msg, "state", None)
            if val is not None and not math.isnan(val):
                self.state["uptime"] = int(val)
                changed = True

        if changed:
            asyncio.create_task(self.broadcast())

    async def run_loop(self):
        while True:
            try:
                logger.info("Connecting to ESPHome controller at %s:%s...", self.host, self.port)
                self.client = aioesphomeapi.APIClient(
                    address=self.host,
                    port=self.port,
                    password="",
                    noise_psk=self.noise_psk,
                )
                await self.client.connect(login=True)
                self.connected = True
                self.state["connected"] = True
                logger.info("Connected to ESPHome device!")

                entities, services = await self.client.list_entities_services()
                for e in entities:
                    ename = getattr(e, "name", "")
                    ekey = getattr(e, "key", 0)
                    if "QuietCool Fan" in ename:
                        self.entities["fan"] = e
                        self.key_to_name[ekey] = "fan"
                    elif ename == "Fan Timer":
                        self.entities["fan_timer_select"] = e
                        self.key_to_name[ekey] = "fan_timer_select"
                    elif ename == "Timer Remaining":
                        self.entities["timer_remaining"] = e
                        self.key_to_name[ekey] = "timer_remaining"
                    elif ename == "Fan State Known":
                        self.entities["fan_state_known"] = e
                        self.key_to_name[ekey] = "fan_state_known"
                    elif ename == "Fan Confirmed Off":
                        self.entities["fan_confirmed_off"] = e
                        self.key_to_name[ekey] = "fan_confirmed_off"
                    elif ename == "Controller Fault":
                        self.entities["controller_fault"] = e
                        self.key_to_name[ekey] = "controller_fault"
                    elif ename == "Command Confirmation Status":
                        self.entities["command_status"] = e
                        self.key_to_name[ekey] = "command_status"
                    elif ename == "Fan Evidence Source":
                        self.entities["evidence_source"] = e
                        self.key_to_name[ekey] = "evidence_source"
                    elif ename == "Last Confirmed Fan State":
                        self.entities["last_confirmed"] = e
                        self.key_to_name[ekey] = "last_confirmed"
                    elif ename == "Fan Speed Capability":
                        self.entities["speed_capability"] = e
                        self.key_to_name[ekey] = "speed_capability"
                    elif ename == "Remote Sender ID":
                        self.entities["remote_sender_id"] = e
                        self.key_to_name[ekey] = "remote_sender_id"
                    elif ename == "WiFi Signal":
                        self.entities["wifi_signal"] = e
                        self.key_to_name[ekey] = "wifi_signal"
                    elif ename == "Battery Level":
                        self.entities["battery_level"] = e
                        self.key_to_name[ekey] = "battery_level"
                    elif ename == "Uptime":
                        self.entities["uptime"] = e
                        self.key_to_name[ekey] = "uptime"
                    elif ename == "Refresh Fan State":
                        self.entities["btn_refresh"] = e
                    elif ename == "Learn Remote ID":
                        self.entities["btn_learn"] = e
                    elif ename == "Forget Remote ID":
                        self.entities["btn_forget"] = e
                    elif ename == "Restart":
                        self.entities["btn_restart"] = e

                self.client.subscribe_states(self._on_state)
                await self.broadcast()

                # Keep connected until disconnected
                while self.client.is_connected:
                    await asyncio.sleep(2)

            except Exception as ex:
                logger.warning("ESPHome connection error: %s", ex)
            finally:
                self.connected = False
                self.state["connected"] = False
                await self.broadcast()
                if self.client:
                    try:
                        await self.client.disconnect()
                    except Exception:
                        pass
                    self.client = None

            logger.info("Waiting 5s before reconnecting...")
            await asyncio.sleep(5)

    async def set_fan(self, state: bool, speed_level: Optional[int] = None):
        if not self.client or not self.connected:
            raise HTTPException(status_code=503, detail="Not connected to ESPHome controller")
        fan = self.entities.get("fan")
        if not fan:
            raise HTTPException(status_code=404, detail="Fan entity not found")
        await self.client.fan_command(key=fan.key, state=state, speed_level=speed_level)

    async def set_timer(self, duration: str):
        if not self.client or not self.connected:
            raise HTTPException(status_code=503, detail="Not connected to ESPHome controller")
        select = self.entities.get("fan_timer_select")
        if not select:
            raise HTTPException(status_code=404, detail="Timer select entity not found")
        await self.client.select_command(key=select.key, state=duration)

    async def trigger_button(self, action: str):
        if not self.client or not self.connected:
            raise HTTPException(status_code=503, detail="Not connected to ESPHome controller")
        key_map = {
            "learn": "btn_learn",
            "forget": "btn_forget",
            "refresh": "btn_refresh",
            "restart": "btn_restart",
        }
        ent_key = key_map.get(action)
        if not ent_key or ent_key not in self.entities:
            raise HTTPException(status_code=400, detail=f"Action '{action}' not recognized")
        await self.client.button_command(key=self.entities[ent_key].key)

bridge = QuietCoolBridge(ESPHOME_HOST, ESPHOME_PORT, ESPHOME_API_KEY)

@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(bridge.run_loop())
    yield
    task.cancel()

app = FastAPI(title="QuietCool Web Controller", lifespan=lifespan)

class PowerRequest(BaseModel):
    state: bool

class SpeedRequest(BaseModel):
    speed: int

class TimerRequest(BaseModel):
    duration: str

@app.get("/api/status")
async def get_status():
    return bridge.state

@app.post("/api/fan/power")
async def set_power(req: PowerRequest):
    await bridge.set_fan(state=req.state)
    return {"status": "ok", "state": req.state}

@app.post("/api/fan/speed")
async def set_speed(req: SpeedRequest):
    if req.speed not in (1, 2, 3):
        raise HTTPException(status_code=400, detail="Speed must be 1 (Low), 2 (Med), or 3 (High)")
    await bridge.set_fan(state=True, speed_level=req.speed)
    return {"status": "ok", "speed": req.speed}

@app.post("/api/fan/timer")
async def set_timer(req: TimerRequest):
    valid = ["None", "1 hour", "2 hours", "4 hours", "8 hours", "12 hours"]
    if req.duration not in valid:
        raise HTTPException(status_code=400, detail=f"Duration must be one of {valid}")
    await bridge.set_timer(req.duration)
    return {"status": "ok", "duration": req.duration}

@app.post("/api/button/{action}")
async def trigger_button(action: str):
    await bridge.trigger_button(action)
    return {"status": "ok", "action": action}

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await bridge.register_websocket(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        bridge.unregister_websocket(ws)

static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/")
async def read_index():
    index_file = os.path.join(static_dir, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return {"message": "QuietCool Web Server is running"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=WEB_PORT, reload=False)
