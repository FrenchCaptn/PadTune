"""Liaison Bluetooth LE avec la manette (bleak) + manette simulée pour le mode démo."""
from __future__ import annotations

import asyncio
import copy
import logging
import random
from dataclasses import dataclass

import flexi_protocol as fp
from i18n import tr

log = logging.getLogger("flexi")


@dataclass
class FoundDevice:
    name: str
    address: str
    rssi: int
    has_service: bool

    def label(self) -> str:
        star = "★ " if self.has_service else ""
        return f"{star}{self.name or tr('(sans nom)')}  [{self.address}]  {self.rssi} dBm"


class LinkError(Exception):
    pass


# nom -> (commande de lecture, commande d'écriture, classe)
BLOCKS = {
    "sticks": (fp.CMD_READ_STICKS, fp.CMD_WRITE_STICKS, fp.SticksConfig),
    "triggers": (fp.CMD_READ_TRIGGERS, fp.CMD_WRITE_TRIGGERS, fp.TriggersConfig),
    "motors": (fp.CMD_READ_MOTORS, fp.CMD_WRITE_MOTORS, fp.MotorsConfig),
}
ALL_BLOCKS = [*BLOCKS, "remap", "lights", "macros"]
BLOCK_CLASSES = {**{n: c for n, (_r, _w, c) in BLOCKS.items()}, "remap": fp.RemapConfig,
                 "lights": fp.LightsConfig, "macros": fp.MacrosConfig}
OPTIONAL = {"lights", "macros"}     # absents sur certaines manettes : lecture rapide sans insister


class BaseLink:
    """Logique commune : numérotation des trames et attente des accusés de réception."""

    def __init__(self):
        self.fb = fp.FrameBuilder()
        self._pending: dict[int, asyncio.Future] = {}
        self.on_log = lambda msg: None
        self.on_disconnect = lambda: None
        self.on_stream = lambda positions: None     # {18: (bx, by, cx, cy), 19: ...}
        self._send_lock = asyncio.Lock()
        self._live_task: asyncio.Task | None = None
        self.live_page = 7              # 7 : flux sticks/gâchettes ; 8 : page boutons
        self.buttons: list | None = None
        self.macro_codes: list | None = None
        self.macro_v2 = False

    # à implémenter
    async def _send_raw(self, data: bytes):
        raise NotImplementedError

    def _handle_notification(self, data: bytes):
        r = fp.parse_notification(bytes(data))
        if r is None:
            self.on_log(tr("← trame ignorée (CRC invalide) : {hex}", hex=bytes(data).hex(' ')))
            return
        if r.cmd == fp.CMD_STREAM:
            pos = fp.parse_stream(r.raw)
            if pos:
                try:
                    self.on_stream(pos)
                except (RuntimeError, TypeError):   # fenêtre en cours de fermeture
                    pass
            return
        if r.cmd == fp.CMD_ACK:
            fut = self._pending.pop(r.serial, None)
            if fut and not fut.done():
                fut.set_result(r)
                return
        log.debug("notification non sollicitée cmd=%s %s", r.cmd, r.raw.hex(" "))

    async def request(self, frame: bytes, timeout: float = 1.5) -> fp.Reply:
        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        self._pending[frame[2]] = fut
        self.on_log(f"→ cmd {frame[0]} : {frame.hex(' ')}")
        await self._send(frame)
        try:
            r = await asyncio.wait_for(fut, timeout)
        except asyncio.TimeoutError:
            self._pending.pop(frame[2], None)
            raise LinkError(tr("pas de réponse de la manette à la commande {cmd}", cmd=frame[0]))
        self.on_log(tr("← réponse : {hex}", hex=r.raw.hex(' ')))
        return r

    async def _send(self, frame: bytes):
        async with self._send_lock:
            await self._send_raw(fp.scramble(frame))

    # --- affichage en direct -------------------------------------------------
    async def _live_loop(self):
        # Sur la page joysticks, KeyLinker envoie e.c0(7) toutes les 750 ms ;
        # tant que ce signal arrive, la manette diffuse la position des sticks (trames 31).
        while True:
            try:
                await self._send(self.fb.mode(self.live_page))
            except Exception as e:  # noqa: BLE001
                self.on_log(tr("Affichage en direct interrompu : {err}", err=e))
                return
            await asyncio.sleep(0.75)

    async def set_live(self, on: bool):
        if on and not self._live_task:
            self._live_task = asyncio.create_task(self._live_loop())
        elif not on and self._live_task:
            self._live_task.cancel()
            self._live_task = None

    async def _request_retry(self, frame_fn, timeout=1.5, modes=(3, 7)):
        try:
            return await self.request(frame_fn(), timeout)
        except LinkError:
            if not modes:
                raise
            # L'appli envoie un « mode » toutes les 750 ms sur les pages de réglage ; on l'imite puis on réessaie
            self.on_log(tr("Pas de réponse : envoi du signal de mode puis nouvel essai…"))
            for page in modes:
                try:
                    await self.request(self.fb.mode(page), timeout=1.0)
                except LinkError:
                    pass
            return await self.request(frame_fn(), timeout=2.5)

    async def read_paged(self, frame_fn, max_pages: int = 24, total_fn=None, modes=(3, 7)) -> list:
        """Lecture en plusieurs pages (z1.j) : page 0 = [total, éléments…], pages suivantes = éléments."""
        r = await self._request_retry(lambda: frame_fn(0), modes=modes)
        p = list(r.payload)
        if not p:
            return []
        total = total_fn(p) if total_fn else p[0]
        items = p[1:]
        page = 1
        while len(items) < total and page < max_pages:
            r = await self._request_retry(lambda: frame_fn(page), modes=modes)
            items += list(r.payload)
            page += 1
        if len(items) < total:
            raise LinkError(tr("liste incomplète ({a}/{b})", a=len(items), b=total))
        return items[:total]

    async def read_features(self):
        """176 [0, 1] (ConnectionActivity.r()) : indique notamment le format des macros."""
        try:
            r = await self.request(self.fb.features(), timeout=1.5)
        except LinkError:
            return None
        p = list(r.payload)
        self.macro_v2 = len(p) > 8 and p[5] > 0 and bool(p[8] & 0b10)
        self.on_log(tr("Capacités : {hex} (format macros {v})", hex=bytes(p).hex(' '), v='v2' if self.macro_v2 else 'v1'))
        return p

    async def read_buttons(self) -> list:
        items = await self.read_paged(lambda pg: self.fb.read_list(pg, fp.LIST_REMAP_BUTTONS))
        codes = fp.decompress_codes(items)
        if not codes:
            raise LinkError(tr("la manette n'a renvoyé aucun bouton remappable"))
        self.on_log(tr("Boutons remappables : {list}", list=", ".join(fp.button_name(c) for c in codes)))
        self.buttons = codes
        return codes

    async def read(self, name: str):
        if name == "lights":
            items = await self.read_paged(self.fb.read_lights, modes=())
            cfg = fp.LightsConfig.from_items(items)
            if not cfg.zones:
                raise LinkError(tr("aucune zone lumineuse"))
            return cfg
        if name == "macros":
            if self.macro_codes is None:
                items = await self.read_paged(lambda pg: self.fb.read_list(pg, fp.LIST_MACRO_CODES), modes=())
                self.macro_codes = fp.decompress_codes(items)
                self.on_log(tr("Boutons utilisables en macro : {list}", list=", ".join(fp.button_name(c) for c in self.macro_codes)))
            macros = []
            for slot in range(fp.MACRO_SLOTS):
                try:
                    items = await self.read_paged(lambda pg, sl=slot: self.fb.read_macro(pg, sl), modes=(2, 8) if slot == 0 else (),
                                                  total_fn=lambda p: fp.Macro.total_items(p, self.macro_v2))
                except LinkError:
                    if slot == 0:
                        raise
                    break
                macros.append(fp.Macro.from_items(slot, items, self.macro_codes))
            return fp.MacrosConfig(codes=list(self.macro_codes), macros=macros, v2=self.macro_v2)
        if name == "remap":
            buttons = self.buttons or await self.read_buttons()
            raw = await self.read_paged(self.fb.read_remap)
            return fp.RemapConfig.from_raw(buttons, raw)
        read_cmd, _w, cls = BLOCKS[name]
        r = await self._request_retry(lambda: self.fb.read_block(read_cmd))
        return cls.from_payload(r.payload)

    async def write(self, name: str, cfg):
        if name == "lights":
            for page, chunk in enumerate(cfg.chunks()):
                await self.request(self.fb.write_lights(chunk, page), timeout=2.5)
            await asyncio.sleep(0.2)
            return await self.read(name)
        if name == "macros":
            old = getattr(self, "_macros_loaded", None)
            for m in cfg.macros:
                prev = next((o for o in (old.macros if old else []) if o.slot == m.slot), None)
                if prev is not None and prev.to_raw(cfg.codes, cfg.v2) == m.to_raw(cfg.codes, cfg.v2):
                    continue                     # emplacement inchangé
                for page, chunk in enumerate(m.chunks(cfg.codes, cfg.v2)):
                    await self.request(self.fb.write_macro(chunk, page, m.slot, cfg.v2), timeout=2.5)
            await asyncio.sleep(0.2)
            res = await self.read(name)
            self._macros_loaded = copy.deepcopy(res)
            return res
        if name == "remap":
            for page, chunk in enumerate(cfg.chunks()):
                await self.request(self.fb.write_remap(chunk, page), timeout=2.5)
            await asyncio.sleep(0.2)
            return await self.read(name)
        _r, write_cmd, _c = BLOCKS[name]
        await self.request(self.fb.write_block(write_cmd, cfg.to_payload()), timeout=2.5)
        await asyncio.sleep(0.2)
        return await self.read(name)            # relecture pour vérifier

    async def read_all(self) -> dict:
        """Lit tous les blocs ; un bloc non pris en charge renvoie l'exception au lieu de la config."""
        out = {}
        if not getattr(self, "_features_read", False):
            await self.read_features()
            self._features_read = True
        for name in ALL_BLOCKS:
            try:
                out[name] = await self.read(name)
            except (LinkError, ValueError) as e:
                out[name] = e
        if not isinstance(out.get("macros"), Exception):
            self._macros_loaded = copy.deepcopy(out["macros"])
        return out

    # compatibilité
    async def read_sticks(self) -> fp.SticksConfig:
        return await self.read("sticks")

    async def write_sticks(self, cfg: fp.SticksConfig) -> fp.SticksConfig:
        return await self.write("sticks", cfg)

    async def device_info(self) -> bytes | None:
        try:
            r = await self.request(self.fb.device_info(), timeout=1.5)
            return r.payload
        except LinkError:
            return None


class BleLink(BaseLink):
    def __init__(self):
        super().__init__()
        self.client = None
        self._write_response = True

    @staticmethod
    async def scan(timeout: float = 6.0) -> list[FoundDevice]:
        from bleak import BleakScanner
        found = await BleakScanner.discover(timeout=timeout, return_adv=True)
        out = []
        for _addr, (dev, adv) in found.items():
            uuids = [u.lower() for u in (adv.service_uuids or [])]
            out.append(FoundDevice(name=adv.local_name or dev.name or "", address=dev.address,
                                   rssi=adv.rssi, has_service=fp.SERVICE_UUID in uuids))
        hint = ("nyxi", "flexi", "gamepad", "controller", "keylinker")
        out.sort(key=lambda d: (not d.has_service,
                                not any(h in d.name.lower() for h in hint),
                                not d.name, -d.rssi))
        return out

    async def connect(self, address: str):
        from bleak import BleakClient
        self.client = BleakClient(address, disconnected_callback=lambda _c: self.on_disconnect())
        await self.client.connect(timeout=15.0)
        svc = self.client.services.get_service(fp.SERVICE_UUID)
        if svc is None:
            uuids = ", ".join(s.uuid for s in self.client.services)
            await self.client.disconnect()
            raise LinkError(tr("Cet appareil n'expose pas le service de configuration KeyLinker.\n"
                               "Services trouvés : {list}", list=uuids))
        ch = svc.get_characteristic(fp.WRITE_UUID)
        if ch is None or svc.get_characteristic(fp.NOTIFY_UUID) is None:
            await self.client.disconnect()
            raise LinkError(tr("Caractéristiques de configuration introuvables."))
        self._write_response = "write" in ch.properties
        await self.client.start_notify(fp.NOTIFY_UUID, lambda _c, d: self._handle_notification(d))
        self.on_log(tr("Connecté à {addr} (écriture avec accusé BLE)", addr=address) if self._write_response
                    else tr("Connecté à {addr} (écriture sans accusé BLE)", addr=address))

    async def _send_raw(self, data: bytes):
        if not self.client or not self.client.is_connected:
            raise LinkError(tr("manette déconnectée"))
        await self.client.write_gatt_char(fp.WRITE_UUID, data, response=self._write_response)

    async def disconnect(self):
        await self.set_live(False)
        if self.client:
            try:
                await self.client.disconnect()
            finally:
                self.client = None


class FakeLink(BaseLink):
    """Manette simulée : décode réellement les trames et répond comme le firmware."""

    def __init__(self):
        super().__init__()
        self.cfg = fp.SticksConfig(
            left=fp.Stick(inner=10, outer=80, curve=[85, 85, 170, 170]),
            right=fp.Stick(inner=10, outer=80, curve=[85, 85, 170, 170]),
        )
        self.blocks = {
            "sticks": self.cfg,
            "triggers": fp.TriggersConfig(left=fp.Trigger(inner=20, outer=180), right=fp.Trigger(inner=20, outer=180)),
            "motors": fp.MotorsConfig(motors=[255, 255, 0, 0], sleep_minutes=10),
        }
        self.fake_buttons = list(range(1, 18)) + [20, 21]      # A..Home + 2 boutons arrière
        self.remap_raw = [0]
        self._remap_rx = []
        self.macro_codes = None
        self.fake_macro_codes = list(range(1, 17)) + [18, 19]
        self.lights_raw = fp.LightsConfig(zones=[fp.LightZone(color=[0, 120, 255], breathing=True, brightness=180, speed=900)]).to_raw()
        self.macro_raw = {s: [0] for s in range(2)}           # 2 emplacements sur la manette simulée
        self._rx = {}

    @staticmethod
    async def scan(timeout: float = 1.0) -> list[FoundDevice]:
        await asyncio.sleep(0.3)
        return [FoundDevice(tr("NYXI Flexi (simulée)"), "DE:MO:00:00:00:01", -48, True),
                FoundDevice(tr("Casque BT"), "AA:BB:CC:DD:EE:FF", -70, False)]

    async def connect(self, address: str):
        await asyncio.sleep(0.2)
        self.on_log(tr("Connecté à {addr} (simulation)", addr=address))

    async def disconnect(self):
        await self.set_live(False)

    async def _send_raw(self, data: bytes):
        f = fp.unscramble(data)
        assert fp.check_crc(f), "trame envoyée avec un CRC invalide"
        cmd, serial, payload = f[0], f[2], list(f[4:-1])
        by_read = {r: n for n, (r, _w, _c) in BLOCKS.items()}
        by_write = {w: n for n, (_r, w, _c) in BLOCKS.items()}
        if cmd in by_write:
            name = by_write[cmd]
            self.blocks[name] = BLOCKS[name][2].from_payload(payload)
            if name == "sticks":
                self.cfg = self.blocks[name]
            reply = []
        elif cmd in by_read:
            reply = self.blocks[by_read[cmd]].to_payload()
        elif cmd == fp.CMD_READ_LIST and payload[1] == fp.LIST_FEATURES:
            reply = [9, 0, 0, 0, 0, 1, 0, 0, 0]
        elif cmd == fp.CMD_READ_LIST and payload[1] == fp.LIST_MACRO_CODES:
            reply = self._page(fp.compress_codes(self.fake_macro_codes), payload[0])
        elif cmd == fp.CMD_READ_LIST:
            reply = self._page(fp.compress_codes(self.fake_buttons), payload[0])
        elif cmd == fp.CMD_READ_LIGHTS:
            reply = self._page(self.lights_raw[1:], payload[0])
        elif cmd == fp.CMD_READ_MACRO:
            slot = payload[1]
            if slot not in self.macro_raw:
                return                                   # emplacement absent : pas de réponse
            raw = self.macro_raw[slot]
            reply = self._page(raw[1:], payload[0], total=raw[0]) if raw != [0] else [0, 0, 0]
        elif cmd in (fp.CMD_WRITE_LIGHTS, fp.CMD_WRITE_MACRO):
            key = (cmd, f[1] >> 5 if cmd == fp.CMD_WRITE_MACRO else 0)
            page = (f[2] >> 3) & 0x0F
            if page == 0:
                self._rx[key] = []
            self._rx[key] += payload
            rx = self._rx[key]
            if rx == [0] or len(rx) >= rx[0] + 1:
                if cmd == fp.CMD_WRITE_LIGHTS:
                    self.lights_raw = rx
                else:
                    self.macro_raw[key[1]] = rx
            reply = []
        elif cmd == fp.CMD_READ_REMAP:
            raw = self.remap_raw if self.remap_raw != [0] else [0]
            reply = self._page(raw[1:] if raw != [0] else [], payload[0], total=None)
        elif cmd == fp.CMD_WRITE_REMAP:
            page = (f[2] >> 3) & 0x0F
            if page == 0:
                self._remap_rx = []
            self._remap_rx += payload
            if self._remap_rx == [0] or len(self._remap_rx) >= self._remap_rx[0] + 1:
                self.remap_raw = self._remap_rx
            reply = []
        else:
            reply = [1]
            if cmd == fp.CMD_MODE and payload[-2:] in ([2, 12], [10, 3], [6, 5]):
                self._stream_until = asyncio.get_running_loop().time() + 1.5
                if not getattr(self, "_streaming", False):
                    self._streaming = True
                    asyncio.get_running_loop().create_task(self._fake_stream())
        body = [fp.CMD_ACK, len(reply) + 5, serial, random.randrange(256), *reply]
        out = fp.scramble(bytes(body + [fp.crc8(body)]))
        asyncio.get_running_loop().call_later(0.05, self._handle_notification, out)

    @staticmethod
    def _page(items, page, total=None):
        """Découpe comme la manette : page 0 = [total, 14 éléments], puis 15 éléments par page."""
        total = len(items) if total is None else total
        if page == 0:
            return [total, *items[:14]]
        start = 14 + (page - 1) * 15
        return items[start:start + 15]

    async def _fake_stream(self):
        """Simule des sticks qui tournent lentement, à ~60 trames/s, tant que le mode 7 est maintenu."""
        import math
        loop = asyncio.get_running_loop()
        t0 = loop.time()
        while loop.time() < self._stream_until:
            t = loop.time() - t0
            lr = 0.55 + 0.45 * math.sin(t * 0.7)            # amplitude variable : traverse la zone morte
            lx, ly = 128 + 127 * lr * math.cos(t * 1.3), 128 + 127 * lr * math.sin(t * 1.3)
            rx, ry = 128 + 60 * math.sin(t * 2.1), 128 + 120 * math.sin(t * 0.9)
            lt = int(100 + 100 * math.sin(t * 1.1))
            rt = int(100 + 100 * math.sin(t * 0.6 + 1))
            ent = [0, 18, 128, 128, int(lx), int(ly), 0, 19, 128, 128, int(rx), int(ry)]
            ent2 = [0, 7, lt, lt, 0, 8, rt, rt]
            body = [fp.CMD_STREAM, len(ent) + 6, 0, random.randrange(256), 0, *ent]
            self._handle_notification(fp.scramble(bytes(body + [fp.crc8(body)])))
            pressed = int(t) % len(self.fake_buttons)                 # un bouton « appuyé » par seconde
            ent2 += [1, self.fake_buttons[pressed], 0, self.fake_buttons[pressed - 1]]
            body2 = [fp.CMD_STREAM, len(ent2) + 6, 0, random.randrange(256), 0, *ent2]
            self._handle_notification(fp.scramble(bytes(body2 + [fp.crc8(body2)])))
            await asyncio.sleep(1 / 60)
        self._streaming = False
