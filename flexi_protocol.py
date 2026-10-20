"""
Protocole de configuration « KeyLinker » (manettes NYXI Flexi et compatibles).

Reconstitué à partir de l'application Android KeyLinker (com.pulsenet.inputset),
classes com.pulsenet.inputset.util.e (trames), .b (Bluetooth) et z1.i (joysticks).

Transport : Bluetooth Low Energy
  service  d7f010e0-660d-46e9-96c3-19c4148bdab5
  écriture d7f010e1-...   (trames brouillées par `scramble`)
  notif.   d7f010e2-...   (trames brouillées, décodées par `unscramble`)

Trame en clair : [commande, longueur/flags, n° de série, octet aléatoire, données..., CRC8]
  - CRC8 calculé avec la table TABLE_CRC sur tous les octets précédents.
  - La manette répond par une trame de commande 25 (accusé) dont l'octet 2 reprend
    le n° de série de la requête ; les données de la réponse sont aux octets 4..-1.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field, asdict

from i18n import tr

SERVICE_UUID = "d7f010e0-660d-46e9-96c3-19c4148bdab5"
WRITE_UUID = "d7f010e1-660d-46e9-96c3-19c4148bdab5"
NOTIFY_UUID = "d7f010e2-660d-46e9-96c3-19c4148bdab5"

CMD_ACK = 25
CMD_MODE = 29            # « heartbeat » / mode de la page en cours
CMD_DEVICE_INFO = 30
CMD_WRITE_STICKS = 49
CMD_READ_STICKS = 177
CMD_WRITE_TRIGGERS = 50
CMD_READ_TRIGGERS = 178
CMD_WRITE_MOTORS = 51       # vibrations + mise en veille (même bloc)
CMD_READ_MOTORS = 179
CMD_READ_LIST = 176         # listes paginées : [page, type] ; type 3 = boutons remappables
LIST_REMAP_BUTTONS = 3
CMD_READ_REMAP = 182        # [page]
CMD_WRITE_REMAP = 54        # tranches de 15 valeurs, n° de tranche dans le n° de série
LIST_FEATURES = 1           # 176 [0, 1] : capacités de la manette (ConnectionActivity.r())
LIST_MACRO_CODES = 5        # 176 [page, 5] : boutons utilisables dans les macros (ordre des bits)
CMD_READ_MACRO = 181        # [page, emplacement]
CMD_WRITE_MACRO = 53        # emplacement (0-7) dans les 3 bits de poids fort de l'octet 1
CMD_READ_LIGHTS = 183       # [page]
CMD_WRITE_LIGHTS = 55
MACRO_SLOTS = 8

TABLE_CRC = [0, 121, 242, 139, 51, 74, 193, 184, 102, 31, 148, 237, 85, 44, 167, 222, 204, 181, 62, 71, 255, 134, 13, 116, 170, 211, 88, 33, 153, 224, 107, 18, 79, 54, 189, 196, 124, 5, 142, 247, 41, 80, 219, 162, 26, 99, 232, 145, 131, 250, 113, 8, 176, 201, 66, 59, 229, 156, 23, 110, 214, 175, 36, 93, 158, 231, 108, 21, 173, 212, 95, 38, 248, 129, 10, 115, 203, 178, 57, 64, 82, 43, 160, 217, 97, 24, 147, 234, 52, 77, 198, 191, 7, 126, 245, 140, 209, 168, 35, 90, 226, 155, 16, 105, 183, 206, 69, 60, 132, 253, 118, 15, 29, 100, 239, 150, 46, 87, 220, 165, 123, 2, 137, 240, 72, 49, 186, 195, 235, 146, 25, 96, 216, 161, 42, 83, 141, 244, 127, 6, 190, 199, 76, 53, 39, 94, 213, 172, 20, 109, 230, 159, 65, 56, 179, 202, 114, 11, 128, 249, 164, 221, 86, 47, 151, 238, 101, 28, 194, 187, 48, 73, 241, 136, 3, 122, 104, 17, 154, 227, 91, 34, 169, 208, 14, 119, 252, 133, 61, 68, 207, 182, 117, 12, 135, 254, 70, 63, 180, 205, 19, 106, 225, 152, 32, 89, 210, 171, 185, 192, 75, 50, 138, 243, 120, 1, 223, 166, 45, 84, 236, 149, 30, 103, 58, 67, 200, 177, 9, 112, 251, 130, 92, 37, 174, 215, 111, 22, 157, 228, 246, 143, 4, 125, 197, 188, 55, 78, 144, 233, 98, 27, 163, 218, 81, 40]
TABLE_G = [51, 99, 157, 121, 242, 219, 162, 26, 170, 33, 139, 232, 116, 211, 88]
TABLE_H = [161, 82, 213, 163, 245, 137, 246, 143, 240, 157, 72, 147, 234, 52, 49, 186, 195, 77, 198, 235, 73, 96, 216, 163, 218, 42, 83, 141, 244, 97, 24, 191, 174, 215, 111, 81, 228, 160, 217, 146]

MAX_FRAME = 20


def crc8(data) -> int:
    c = 0
    for b in data:
        c = TABLE_CRC[(c ^ b) & 0xFF]
    return c


def scramble(frame: bytes) -> bytes:
    """Équivalent de e.h() : trame en clair -> octets envoyés."""
    b = list(frame)
    n = len(b)
    if not 5 <= n <= MAX_FRAME:
        raise ValueError(f"longueur de trame invalide : {n}")
    b0, b1, b2, b3 = b[0], b[1], b[2], b[3]
    out = [0] * n
    out[0] = (b0 ^ ((b2 + b3) - 154)) & 0xFF
    out[1] = (b1 ^ ((b2 + b3) + 155)) & 0xFF
    out[2] = ((b2 - 173) ^ b3) & 0xFF
    out[3] = ((b3 + 191) ^ 219) & 0xFF
    for i in range(4, n - 1):
        out[i] = (b[i] ^ ((b2 + b3) - TABLE_G[i - 4])) & 0xFF
    out[n - 1] = b[n - 1]
    off = (out[3] & 2) * 10
    return bytes((out[i] ^ TABLE_H[off + i]) & 0xFF for i in range(n))


def unscramble(data: bytes) -> bytes:
    """Équivalent de e.g() : octets reçus -> trame en clair."""
    n = len(data)
    if not 1 <= n <= MAX_FRAME:
        raise ValueError(f"longueur de trame invalide : {n}")
    off = 20 if ((data[3] ^ TABLE_H[3]) & 2) else 0
    t = [(data[i] ^ TABLE_H[off + i]) & 0xFF for i in range(n)]
    t[3] = ((t[3] ^ 219) - 191) & 0xFF
    t[2] = ((t[2] ^ t[3]) + 173) & 0xFF
    s = t[2] + t[3]
    t[1] = (t[1] ^ (s + 155)) & 0xFF
    t[0] = (t[0] ^ (s - 154)) & 0xFF
    for i in range(4, n - 1):
        t[i] = (t[i] ^ (s - TABLE_G[i - 4])) & 0xFF
    return bytes(t)


def check_crc(frame: bytes) -> bool:
    return len(frame) >= 2 and crc8(frame[:-1]) == frame[-1]


class FrameBuilder:
    """Reproduit les compteurs de e.java (K(), I(), p()) pour numéroter les trames."""

    def __init__(self, rng: random.Random | None = None):
        self._k = 0      # f2731b
        self._i = 0      # f2732c
        self._p = 8      # f2733d
        self._rng = rng or random.Random()

    def _rand(self) -> int:
        return self._rng.randrange(256)

    def _serial_k(self) -> int:
        self._k += 1
        return (self._k % 128) + 128 if self._k % 2 == 0 else self._k % 128

    def _serial_i(self, bits4: str = "0000") -> int:
        self._i += 1
        return int(str(self._i % 2) + bits4 + format(self._i % 8, "03b"), 2)

    def _len_p(self, payload_len: int) -> int:
        if self._p == 0:
            self._p = 8
        self._p -= 1
        return int(format(self._p % 8, "03b") + format(payload_len + 5, "05b"), 2)

    @staticmethod
    def _finish(header_and_payload) -> bytes:
        body = [x & 0xFF for x in header_and_payload]
        return bytes(body + [crc8(body)])

    def simple(self, cmd: int, payload=()) -> bytes:
        """Trame de type B()/K() : [cmd, len+5, K(), rand, payload, crc]."""
        payload = list(payload)
        return self._finish([cmd, len(payload) + 5, self._serial_k(), self._rand(), *payload])

    def data(self, cmd: int, payload, index: int = 0) -> bytes:
        """Trame de type p()/I() (écriture de bloc de configuration)."""
        payload = list(payload)
        bits4 = format(index, "04b")[-4:] if index < 16 else format(index, "b")
        return self._finish([cmd, self._len_p(len(payload)), self._serial_i(bits4), self._rand(), *payload])

    # --- commandes utilisées -------------------------------------------------
    def device_info(self) -> bytes:
        # e.N() : la longueur est calculée sur [2,223,172] mais les données envoyées sont [2,223,171]
        return self._finish([CMD_DEVICE_INFO, 8, self._serial_k(), self._rand(), 2, 223, 171])

    def mode(self, page: int = 7) -> bytes:
        # page 7 : joysticks/gâchettes (flux des positions) ; page 8 : boutons, vibrations, etc.
        # e.c0(page) — maintien de session envoyé toutes les 750 ms par l'appli
        payloads = {
            1: [5, 223, 171, 0, 0, 0], 2: [5, 223, 171, 0, 6, 5], 3: [5, 223, 171, 0, 6, 2],
            4: [5, 223, 171, 0, 10, 2], 5: [5, 223, 171, 0, 2, 6], 6: [5, 223, 171, 0, 2, 14],
            7: [5, 223, 171, 0, 2, 12], 8: [5, 223, 171, 0, 10, 3],
        }
        return self.simple(CMD_MODE, payloads.get(page, [2, 223, 171]))

    def read_sticks(self) -> bytes:
        return self.simple(CMD_READ_STICKS, [0])            # e.v(0)

    def write_sticks(self, cfg: "SticksConfig") -> bytes:
        return self.data(CMD_WRITE_STICKS, cfg.to_payload(), 0)   # e.o0(iArr, 0)

    def read_block(self, read_cmd: int) -> bytes:
        return self.simple(read_cmd, [0])                   # e.v / e.z / e.u (0)

    def write_block(self, write_cmd: int, payload) -> bytes:
        return self.data(write_cmd, payload, 0)             # e.o0 / e.q0 / e.n0

    def read_list(self, page: int, kind: int) -> bytes:
        return self.simple(CMD_READ_LIST, [page, kind])     # e.m(page, kind)

    def read_remap(self, page: int) -> bytes:
        return self.simple(CMD_READ_REMAP, [page])          # e.l(page)

    def write_remap(self, chunk, page: int) -> bytes:
        return self.data(CMD_WRITE_REMAP, chunk, page)      # e.k0(chunk, page)

    def features(self) -> bytes:
        return self.simple(CMD_READ_LIST, [0, LIST_FEATURES])   # e.t(1)

    def read_lights(self, page: int) -> bytes:
        return self.simple(CMD_READ_LIGHTS, [page])         # e.q(page)

    def write_lights(self, chunk, page: int) -> bytes:
        return self.data(CMD_WRITE_LIGHTS, chunk, page)     # e.l0(chunk, page)

    def read_macro(self, page: int, slot: int) -> bytes:
        return self.simple(CMD_READ_MACRO, [page, slot])    # e.x(page, slot)

    def write_macro(self, chunk, page: int, slot: int, v2: bool = False) -> bytes:
        """e.m0(chunk, page, slot) : octet 1 = emplacement (3 bits) + longueur ; octet 2 = I() ou D()."""
        chunk = list(chunk)
        b1 = ((slot & 7) << 5) | (len(chunk) + 5)
        if v2:
            self._i += 1
            serial = ((self._i % 2) << 7) | ((page & 0x0F) << 3) | ((page >> 4) & 7)
        else:
            serial = self._serial_i(format(page & 0x0F, "04b"))
        return self._finish([CMD_WRITE_MACRO, b1, serial, self._rand(), *chunk])


@dataclass
class Stick:
    inner: int = 0            # zone morte intérieure, 0-100 (%)
    outer: int = 100          # bord extérieur effectif, 0-100 (%) ; envoyé comme 100 - outer
    curve: list = field(default_factory=lambda: [85, 85, 170, 170])   # 2 points (x1,y1,x2,y2) sur 0-255
    invert_x: bool = False
    invert_y: bool = False
    swap: bool = False        # échange gauche/droite (bit commun aux deux sticks)

    def flags(self) -> int:
        return (int(self.swap) << 2) | (int(self.invert_y) << 1) | int(self.invert_x)

    @classmethod
    def from_bytes(cls, b) -> "Stick":
        inner, outer_raw, x1, y1, x2, y2, fl = b
        return cls(inner=inner, outer=100 - outer_raw, curve=[x1, y1, x2, y2],
                   invert_x=bool(fl & 1), invert_y=bool(fl & 2), swap=bool(fl & 4))

    def to_bytes(self) -> list:
        for v in (self.inner, self.outer):
            if not 0 <= v <= 100:
                raise ValueError(tr("les zones mortes doivent être entre 0 et 100"))
        if self.inner >= self.outer:
            raise ValueError(tr("la zone morte intérieure doit être inférieure au bord extérieur"))
        if any(not 0 <= v <= 255 for v in self.curve):
            raise ValueError(tr("les points de courbe doivent être entre 0 et 255"))
        return [self.inner, 100 - self.outer, *self.curve, self.flags()]


@dataclass
class SticksConfig:
    left: Stick
    right: Stick
    tag: int = 14

    @classmethod
    def from_payload(cls, payload) -> "SticksConfig":
        p = list(payload)
        if len(p) < 15:
            raise ValueError(tr("réponse joysticks trop courte ({n} octets) : {data}", n=len(p), data=p))
        return cls(tag=p[0], left=Stick.from_bytes(p[1:8]), right=Stick.from_bytes(p[8:15]))

    def to_payload(self) -> list:
        return [self.tag, *self.left.to_bytes(), *self.right.to_bytes()]

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d) -> "SticksConfig":
        return cls(tag=d.get("tag", 14), left=Stick(**d["left"]), right=Stick(**d["right"]))


@dataclass
class Trigger:
    """Gâchette : échelle interne 0-200 (l'appli affiche la moitié, en %)."""
    inner: int = 0            # début de course ignoré, 0-200
    outer: int = 200          # fin de course effective, 0-200 ; envoyé comme 200 - outer
    curve: list = field(default_factory=lambda: [85, 85, 170, 170])
    swap: bool = False        # échange des gâchettes G/D (bit 2)

    @classmethod
    def from_bytes(cls, b) -> "Trigger":
        inner, outer_raw, x1, y1, x2, y2, fl = b
        return cls(inner=inner, outer=200 - outer_raw, curve=[x1, y1, x2, y2], swap=bool(fl & 4))

    def to_bytes(self) -> list:
        if not (0 <= self.inner < self.outer <= 200):
            raise ValueError(tr("gâchettes : il faut 0 ≤ début < fin ≤ 100 %"))
        if any(not 0 <= v <= 255 for v in self.curve):
            raise ValueError(tr("les points de courbe doivent être entre 0 et 255"))
        return [self.inner, 200 - self.outer, *self.curve, int(self.swap) << 2]


@dataclass
class TriggersConfig:
    left: Trigger
    right: Trigger
    tag: int = 14

    @classmethod
    def from_payload(cls, payload) -> "TriggersConfig":
        p = list(payload)
        if len(p) < 15:
            raise ValueError(tr("réponse gâchettes trop courte ({n} octets) : {data}", n=len(p), data=p))
        return cls(tag=p[0], left=Trigger.from_bytes(p[1:8]), right=Trigger.from_bytes(p[8:15]))

    def to_payload(self) -> list:
        return [self.tag, *self.left.to_bytes(), *self.right.to_bytes()]

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d) -> "TriggersConfig":
        return cls(tag=d.get("tag", 14), left=Trigger(**d["left"]), right=Trigger(**d["right"]))


SLEEP_NEVER = 357913          # au-delà, l'appli envoie FF FF FF FF (« jamais »)


@dataclass
class MotorsConfig:
    """Bloc 8 (z1.i.g / z1.i.h) : intensité des 4 moteurs (0-255) + extinction auto (minutes)."""
    motors: list = field(default_factory=lambda: [255, 255, 0, 0])
    sleep_minutes: int = 10       # >= SLEEP_NEVER : jamais
    tag: int = 8

    @classmethod
    def from_payload(cls, payload) -> "MotorsConfig":
        p = list(payload)
        if len(p) < 9:
            raise ValueError(tr("réponse vibrations trop courte ({n} octets) : {data}", n=len(p), data=p))
        raw = int.from_bytes(bytes(p[5:9]), "little")
        minutes = SLEEP_NEVER if raw == 0xFFFFFFFF else raw * 5 // 60000
        return cls(tag=p[0], motors=p[1:5], sleep_minutes=minutes)

    def to_payload(self) -> list:
        if any(not 0 <= m <= 255 for m in self.motors):
            raise ValueError(tr("intensité des moteurs : 0 à 255"))
        if self.sleep_minutes >= SLEEP_NEVER:
            t = [255, 255, 255, 255]
        else:
            if self.sleep_minutes < 0:
                raise ValueError(tr("délai de mise en veille invalide"))
            t = list((self.sleep_minutes * 60000 // 5).to_bytes(4, "little"))
        return [self.tag, *self.motors, *t]

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d) -> "MotorsConfig":
        return cls(**d)


# --------------------------------------------------------------------------- boutons
# Codes de touches (com.pulsenet.inputset.util.c : noms des icônes ic_big_code_0xNN_*)
DISABLED = 2048
BUTTON_NAMES = {
    1: "A", 2: "B", 3: "X", 4: "Y", 5: "L1 (LB)", 6: "R1 (RB)", 7: "L2 (LT)", 8: "R2 (RT)",
    9: "Select / View", 10: "Start / Menu", 11: "L3 (clic stick G)", 12: "R3 (clic stick D)",
    13: "Croix ↓", 14: "Croix ↑", 15: "Croix →", 16: "Croix ←", 17: "Home",
    18: "Stick gauche", 19: "Stick droit", 20: "L4", 21: "R4", 22: "L5", 23: "R5",
    24: "Souris : clic gauche", 25: "Souris : clic droit", 26: "Souris : clic milieu", 27: "M",
    **{28 + i: f"F{i + 1}" for i in range(12)},
    **{40 + i: ("Touche {k}", str((i + 1) % 10)) for i in range(10)},
    **{50 + i: ("Touche {k}", c) for i, c in enumerate("QWERTYUIOPASDFGHJKLZXCVBNM")},
    76: "Échap", 77: "Tab", 78: "Verr. Maj", 79: "Maj gauche", 80: "Ctrl gauche", 81: "Alt gauche",
    82: "Espace", 83: "Alt droit", 84: "Ctrl droit", 85: "Maj droit", 86: "Entrée",
    87: "Flèche ↑", 88: "Flèche ↓", 89: "Flèche ←", 90: "Flèche →", 91: "Entrée (pavé)",
    93: "Macro −", 94: "Macro +", 95: "Capture", 96: "Bascule", 97: "ML", 98: "MR", 99: "Mode",
    100: "Fn", 101: "SL", 102: "SR", **{103 + i: f"M{i + 1}" for i in range(6)},
    146: "Stick gauche (3D)", 147: "Stick droit (3D)", 155: "M", 220: "Capteur (gyro)",
}


def button_name(code: int) -> str:
    if code == DISABLED:
        return tr("— désactivé —")
    name = BUTTON_NAMES.get(code)
    if name is None:
        return tr("Code {n}", n=code)
    if isinstance(name, tuple):                 # touche de clavier : « Touche Q »
        return tr(name[0], k=name[1])
    return tr(name)


def decompress_codes(items) -> list:
    """z1.i.w() : le 1er élément est ignoré ; une valeur > 128 prolonge la suite
    (v - 128 - 1 codes consécutifs après le dernier)."""
    items = list(items)[1:]
    out = []
    for v in items:
        if v > 128:
            if not out:
                continue
            for _ in range(v - 128 - 1):
                out.append(out[-1] + 1)
        else:
            out.append(v)
    return out


def compress_codes(codes) -> list:
    """Inverse de decompress_codes (pour la manette simulée)."""
    out, i = [len(codes)], 0
    while i < len(codes):
        j = i
        while j + 1 < len(codes) and codes[j + 1] == codes[j] + 1:
            j += 1
        out.append(codes[i])
        if j > i:
            out.append(128 + (j - i) + 1)
        i = j + 1
    return out


@dataclass
class RemapConfig:
    """Remappage : pour chaque bouton physique (buttons[i]), le code envoyé (targets[i]).
    targets[i] == buttons[i] : inchangé ; DISABLED : bouton désactivé."""
    buttons: list
    targets: list

    @classmethod
    def from_raw(cls, buttons, raw) -> "RemapConfig":
        # z1.i.v() : 0 -> inchangé ; même code -> désactivé ; autre -> ce code
        targets = list(buttons)
        for i, v in enumerate(list(raw)[:len(buttons)]):
            if v == 0:
                continue
            targets[i] = DISABLED if v == buttons[i] else v
        return cls(buttons=list(buttons), targets=targets)

    def to_raw(self) -> list:
        # b1.w1() : [nombre, puis 0 / code / code d'origine pour désactiver]
        if all(t == b for b, t in zip(self.buttons, self.targets)):
            return [0]
        return [len(self.buttons)] + [0 if t == b else (b if t == DISABLED else t)
                                      for b, t in zip(self.buttons, self.targets)]

    def to_payload(self) -> list:          # pour comparer / valider
        if len(self.targets) != len(self.buttons):
            raise ValueError(tr("remappage : liste de boutons incohérente"))
        for t in self.targets:
            if t != DISABLED and not 0 < t < 256:
                raise ValueError(tr("code de bouton invalide : {code}", code=t))
        return self.to_raw()

    def chunks(self) -> list:
        raw = self.to_raw()
        return [raw[i:i + 15] for i in range(0, len(raw), 15)]

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d) -> "RemapConfig":
        return cls(buttons=list(d["buttons"]), targets=list(d["targets"]))

    def adapted_to(self, buttons) -> "RemapConfig":
        """Applique ce profil à une liste de boutons (peut-être différente)."""
        m = dict(zip(self.buttons, self.targets))
        return RemapConfig(buttons=list(buttons), targets=[m.get(b, b) for b in buttons])


# --------------------------------------------------------------------------- lumières
@dataclass
class LightZone:
    color: list = field(default_factory=lambda: [255, 255, 255])   # R, V, B (0-255)
    breathing: bool = False   # False : fixe ; True : respiration
    brightness: int = 255     # 0-255
    speed: int = 1024         # 0-2048 (mode respiration)

    @classmethod
    def from_bytes(cls, b) -> "LightZone":
        # z1.i.b() : [R, G, B, vitesse bas, (mode << 7) | vitesse haut, luminosité]
        r, g, bl, s_lo, s_hi, br = b
        return cls(color=[r, g, bl], breathing=bool(s_hi & 0x80), brightness=br, speed=((s_hi & 0x0F) << 8) | s_lo)

    def to_bytes(self) -> list:
        if any(not 0 <= c <= 255 for c in self.color) or not 0 <= self.brightness <= 255:
            raise ValueError(tr("couleur / luminosité : 0 à 255"))
        if not 0 <= self.speed <= 4095:
            raise ValueError(tr("vitesse : 0 à 2048"))
        # b1.z1()
        return [*self.color, self.speed & 0xFF, (0x80 if self.breathing else 0) | ((self.speed >> 8) & 0x0F),
                self.brightness]


@dataclass
class LightsConfig:
    zones: list

    @classmethod
    def from_items(cls, items) -> "LightsConfig":
        items = list(items)
        return cls(zones=[LightZone.from_bytes(items[i:i + 6]) for i in range(0, len(items) - 5, 6)][:4])

    def to_raw(self) -> list:
        body = [b for z in self.zones for b in z.to_bytes()]
        return [len(body), *body]

    def to_payload(self) -> list:
        return self.to_raw()

    def chunks(self) -> list:
        raw = self.to_raw()
        return [raw[i:i + 15] for i in range(0, len(raw), 15)]

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d) -> "LightsConfig":
        return cls(zones=[LightZone(**z) for z in d["zones"]])


# --------------------------------------------------------------------------- macros
DPAD = {13: "down", 14: "up", 15: "right", 16: "left"}
# directions 1-8 (N, NE, E, SE, S, SO, O, NO), 0 = aucune — b1.B1() / z1.i.e()
DIR_NAMES = ["—", "↑", "↗", "→", "↘", "↓", "↙", "←", "↖"]
_DPAD_BITS = {  # direction -> codes de croix enfoncés
    0: set(), 1: {14}, 2: {14, 15}, 3: {15}, 4: {13, 15}, 5: {13}, 6: {13, 16}, 7: {16}, 8: {14, 16},
}


def dpad_from_codes(codes) -> int:
    pressed = {c for c in codes if c in DPAD}
    for d, s in _DPAD_BITS.items():
        if s == pressed:
            return d
    return 0


def dir_from_xy(x: float, y: float, dead: float = 40) -> int:
    """Position de stick (0-255) -> direction 0-8 (y vers le bas = ↓)."""
    import math
    dx, dy = x - 128, y - 128
    if (dx * dx + dy * dy) ** 0.5 < dead:
        return 0
    ang = (math.degrees(math.atan2(dx, -dy)) + 360) % 360      # 0° = haut, sens horaire
    return int(((ang + 22.5) % 360) // 45) + 1


@dataclass
class MacroStep:
    duration: int = 100                 # ms (multiple de 5)
    buttons: list = field(default_factory=list)   # codes enfoncés (hors croix et sticks)
    dpad: int = 0                       # 0-8
    lstick: int = 0                     # 0-8
    rstick: int = 0                     # 0-8

    def is_empty(self) -> bool:
        return not self.buttons and not self.dpad and not self.lstick and not self.rstick


@dataclass
class Macro:
    slot: int
    steps: list = field(default_factory=list)
    loop: bool = False
    interval: int = 0                   # ms entre deux répétitions (boucle)

    # ---- encodage (b1.B1)
    def mask(self, step: MacroStep, codes) -> int:
        m, bit = 0, 0
        for c in codes:
            if c in (18, 19):
                d = step.lstick if c == 18 else step.rstick
                m |= (8 if d == 0 else (d - 1)) << bit
                bit += 4
            elif c in DPAD:
                if c in _DPAD_BITS.get(step.dpad, set()):
                    m |= 1 << bit
                bit += 1
            else:
                if c in step.buttons:
                    m |= 1 << bit
                bit += 1
        if bit > 24:
            raise ValueError(tr("trop de boutons pour le format des macros"))
        return m

    def to_raw(self, codes, v2: bool = False) -> list:
        steps = list(self.steps)
        while steps and steps[-1].is_empty():
            steps.pop()
        if not steps:
            return [0, 0, 0] if v2 else [0]
        if not 0 <= self.interval <= 20475:
            raise ValueError(tr("intervalle de boucle : 0 à 20 475 ms"))
        iv = self.interval // 5
        if v2:
            if len(steps) > 511:
                raise ValueError(tr("511 étapes maximum"))
            head = [len(steps) & 0xFF, iv & 0xFF,
                    (0x80 if self.loop else 0) | (((len(steps) >> 8) & 1) << 6) | ((iv >> 8) & 0x0F)]
        else:
            if len(steps) * 5 + 2 > 255:
                raise ValueError(tr("50 étapes maximum"))
            head = [len(steps) * 5 + 2, iv & 0xFF, (0x80 if self.loop else 0) | ((iv >> 8) & 0x0F)]
        body = []
        for st in steps:
            if not 5 <= st.duration <= 327675:
                raise ValueError(tr("durée d'étape : 5 ms minimum"))
            m = self.mask(st, codes)
            d = st.duration // 5
            body += [m & 0xFF, (m >> 8) & 0xFF, (m >> 16) & 0xFF, d & 0xFF, (d >> 8) & 0xFF]
        return head + body

    def chunks(self, codes, v2=False) -> list:
        raw = self.to_raw(codes, v2)
        return [raw[i:i + 15] for i in range(0, len(raw), 15)]

    # ---- décodage (z1.m.l, z1.i.f, z1.i.e)
    @staticmethod
    def total_items(page0, v2: bool) -> int:
        if not page0:
            return 0
        if v2 and page0[0] != 0:
            hi = (page0[2] >> 6) & 1 if len(page0) > 2 else 0
            return ((hi << 8) | page0[0]) * 5 + 2
        return page0[0]

    @classmethod
    def from_items(cls, slot, items, codes) -> "Macro":
        items = list(items)
        if len(items) < 2:
            return cls(slot=slot)
        iv = (((items[1] & 0x0F) << 8) | items[0]) * 5
        loop = bool(items[1] & 0x80)
        steps = []
        for i in range(2, len(items) - 4, 5):
            b = items[i:i + 5]
            m = b[0] | (b[1] << 8) | (b[2] << 16)
            st = MacroStep(duration=((b[4] << 8) | b[3]) * 5)
            bit, pressed = 0, set()
            for c in codes:
                if c in (18, 19):
                    v = (m >> bit) & 0xF
                    d = 0 if v >= 8 else v + 1
                    if c == 18:
                        st.lstick = d
                    else:
                        st.rstick = d
                    bit += 4
                else:
                    if (m >> bit) & 1:
                        pressed.add(c)
                    bit += 1
            st.dpad = dpad_from_codes(pressed)
            st.buttons = sorted(c for c in pressed if c not in DPAD)
            steps.append(st)
        return cls(slot=slot, steps=steps, loop=loop, interval=iv)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d) -> "Macro":
        return cls(slot=d["slot"], steps=[MacroStep(**s) for s in d.get("steps", [])],
                   loop=d.get("loop", False), interval=d.get("interval", 0))


@dataclass
class MacrosConfig:
    codes: list                 # boutons utilisables (ordre des bits)
    macros: list                # Macro par emplacement disponible
    v2: bool = False

    def to_payload(self) -> list:
        return [m.to_raw(self.codes, self.v2) for m in self.macros]

    def to_dict(self) -> dict:
        return {"codes": self.codes, "v2": self.v2, "macros": [m.to_dict() for m in self.macros]}

    @classmethod
    def from_dict(cls, d) -> "MacrosConfig":
        return cls(codes=list(d["codes"]), v2=d.get("v2", False), macros=[Macro.from_dict(m) for m in d["macros"]])


# Préréglages de courbe repris de l'appli (w1.u.D())
CURVE_PRESETS = {
    "Par défaut (linéaire)": [85, 85, 170, 170],
    "Rapide": [35, 35, 136, 204],
    "Lente": [35, 35, 219, 145],
    "Douce": [142, 142, 220, 157],
    "Précise": [67, 67, 72, 106],
}


def preset_name(curve) -> str:
    for name, pts in CURVE_PRESETS.items():
        if list(curve) == pts:
            return name
    return "Personnalisée"


# --------------------------------------------------------------------------- flux en direct
CMD_STREAM = 31
STREAM_LEFT, STREAM_RIGHT = 18, 19
STREAM_LT, STREAM_RT = 7, 8
TRIGGER_PRESS = 30            # sur 200 (15 % de course)


def parse_stream(frame: bytes) -> dict:
    """Trame 31 (envoyée en continu tant que le mode 7 est maintenu) -> positions des sticks.

    D'après b1.l() et z1.b.h() : données à partir de l'octet 5, en entrées [?, type, ...] :
      type 18/19 (stick G/D) : [?, type, corrigéX, corrigéY, brutX, brutY]  (0-255, centre 128)
      type 7/8 (gâchettes)   : 4 octets ; autres (boutons) : 2 octets.
    Renvoie {18: (brutX, brutY, corrX, corrY), 19: (...), 7: valeur, 8: valeur, "buttons": {code: état}}.
    Les entrées de boutons sont [état, code] (b1.l() -> BlueToothService.e(bouton, état)).
    La valeur de gâchette (0-200) est l'octet 3 de l'entrée, comme z1.b.j() sur la page gâchettes.
    """
    data = list(frame[5:-1])
    out = {}
    while len(data) >= 2:
        t = data[1]
        if t in (STREAM_LEFT, STREAM_RIGHT):
            if len(data) < 6:
                break
            out[t] = (data[4], data[5], data[2], data[3])
            n = 6
        elif t in (STREAM_LT, STREAM_RT):
            if len(data) < 4:
                break
            out[t] = data[3]
            # gâchette analogique : considérée « appuyée » au-delà de TRIGGER_PRESS (pour la surbrillance / les macros)
            out.setdefault("buttons", {})[t] = 1 if data[3] > TRIGGER_PRESS else 0
            n = 4
        else:
            out.setdefault("buttons", {})[t] = data[0]     # entrée [état, code]
            n = 2
        del data[:n]
    return out


def clamp_to_circle(x: float, y: float) -> tuple[float, float]:
    dx, dy = x - 128, y - 128
    r = (dx * dx + dy * dy) ** 0.5
    if r > 128:
        return 128 + dx * 128 / r, 128 + dy * 128 / r
    return x, y


def curve_value(s: float, curve) -> float:
    """Courbe linéaire par morceaux (0,0)->(x1,y1)->(x2,y2)->(255,255), comme SimplifyRockCircleView.a()."""
    x1, y1, x2, y2 = curve
    pts = [(0, 0), (x1, y1), (x2, y2), (255, 255)]
    for (ax, ay), (bx, by) in zip(pts, pts[1:]):
        if s <= bx:
            return ay if bx == ax else ay + (by - ay) * (s - ax) / (bx - ax)
    return 255


def corrected_position(x: int, y: int, stick: "Stick") -> tuple[float, float]:
    """Position après zone morte + courbe, calculée comme l'aperçu de KeyLinker
    (SimplifyRockCircleView.k(), .l(), .m())."""
    dx, dy = x - 128, y - 128
    r = (dx * dx + dy * dy) ** 0.5
    if r == 0:
        return 128.0, 128.0
    r_in = stick.inner / 100 * 127.5
    r_out = stick.outer / 100 * 127.5
    if r < r_in:
        return 128.0, 128.0
    mag = 128.0 if r > r_out or stick.outer <= stick.inner else (r - r_in) * 100 / (stick.outer - stick.inner)
    mag = min(mag, 128.0)
    out = curve_value(mag / 128 * 255, stick.curve) / 255 * 128
    return clamp_to_circle(128 + dx * out / r, 128 + dy * out / r)


def trigger_output(v: int, trig: "Trigger") -> float:
    """Valeur de gâchette (0-200) après zone morte + courbe, même logique que les sticks."""
    v = max(0, min(200, v))
    if v < trig.inner:
        return 0.0
    if v > trig.outer or trig.outer <= trig.inner:
        lin = 200.0
    else:
        lin = (v - trig.inner) * 200 / (trig.outer - trig.inner)
    return curve_value(lin / 200 * 255, trig.curve) / 255 * 200


@dataclass
class Reply:
    cmd: int
    serial: int
    payload: bytes
    raw: bytes


def parse_notification(data: bytes) -> Reply | None:
    """Décode une notification ; renvoie None si le CRC est faux."""
    try:
        f = unscramble(data)
    except ValueError:
        return None
    if not check_crc(f):
        return None
    return Reply(cmd=f[0], serial=f[2], payload=f[4:-1], raw=f)
