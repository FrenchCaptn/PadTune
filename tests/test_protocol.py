import os
import random
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import flexi_protocol as fp  # noqa: E402

JAVA_DIR = os.environ.get("JAVA_REF_DIR")  # dossier contenant E.class (code Java d'origine)


def _java(lines):
    out = subprocess.run(["java", "-cp", JAVA_DIR, "E"], input="\n".join(lines) + "\n",
                         capture_output=True, text=True, check=True).stdout
    return [list(map(int, l.split())) for l in out.strip().splitlines()]


def _random_frames(n=400, seed=1):
    rng = random.Random(seed)
    frames = []
    for _ in range(n):
        ln = rng.randint(5, 20)
        frames.append([rng.randrange(256) for _ in range(ln)])
    return frames


def test_roundtrip():
    for f in _random_frames():
        assert list(fp.unscramble(fp.scramble(bytes(f)))) == f


@pytest.mark.skipif(not JAVA_DIR, reason="référence Java absente")
def test_matches_java_reference():
    frames = _random_frames()
    hj = _java(["h " + " ".join(map(str, f)) for f in frames])
    kj = _java(["k " + " ".join(map(str, f)) for f in frames])
    for f, h, k in zip(frames, hj, kj):
        assert list(fp.scramble(bytes(f))) == h
        assert [fp.crc8(f)] == k
    gj = _java(["g " + " ".join(map(str, h)) for h in hj])
    for f, g in zip(frames, gj):
        assert g == f


def test_frames_have_valid_crc_and_length():
    fb = fp.FrameBuilder(random.Random(0))
    cfg = fp.SticksConfig(left=fp.Stick(inner=3, outer=95), right=fp.Stick(inner=5, outer=100))
    for fr in (fb.read_sticks(), fb.write_sticks(cfg), fb.device_info(), fb.mode(7)):
        assert fp.check_crc(fr)
        assert len(fr) <= fp.MAX_FRAME
    w = fb.write_sticks(cfg)
    assert w[0] == 49 and len(w) == 20 and (w[1] & 0x1F) == 20


def test_serial_sequences_match_app():
    fb = fp.FrameBuilder(random.Random(0))
    # K(): 1, 130, 3, 132 ...
    assert [fb.simple(1)[2] for _ in range(4)] == [1, 130, 3, 132]
    # I("0000"): 1er appel c=1 -> "1"+"0000"+"001" = 129 ; 2e -> "0"+"0000"+"010" = 2
    assert [fb._serial_i() for _ in range(3)] == [129, 2, 131]
    # p(): compteur 7,6,... dans les 3 bits de poids fort, longueur+5 dans les 5 autres
    assert fb._len_p(15) == (7 << 5) | 20


def test_sticks_payload_roundtrip():
    cfg = fp.SticksConfig(
        left=fp.Stick(inner=2, outer=97, curve=[35, 35, 136, 204], invert_x=True, swap=True),
        right=fp.Stick(inner=0, outer=100, curve=[85, 85, 170, 170], invert_y=True, swap=True),
    )
    p = cfg.to_payload()
    assert p == [14, 2, 3, 35, 35, 136, 204, 0b101, 0, 0, 85, 85, 170, 170, 0b110]
    assert fp.SticksConfig.from_payload(p) == cfg


def test_validation():
    with pytest.raises(ValueError):
        fp.Stick(inner=50, outer=40).to_bytes()
    with pytest.raises(ValueError):
        fp.Stick(curve=[0, 0, 300, 0]).to_bytes()


def test_parse_ack_notification():
    # La manette répond avec une trame cmd 25 reprenant le n° de série de la requête
    body = [25, 20, 77, 9, 14, 10, 20, 85, 85, 170, 170, 0, 10, 20, 85, 85, 170, 170, 0]
    frame = bytes(body + [fp.crc8(body)])
    r = fp.parse_notification(fp.scramble(frame))
    assert r.cmd == 25 and r.serial == 77
    cfg = fp.SticksConfig.from_payload(r.payload)
    assert cfg.left.inner == 10 and cfg.left.outer == 80
    # CRC faux -> ignoré
    bad = bytearray(fp.scramble(frame)); bad[-1] ^= 1
    assert fp.parse_notification(bytes(bad)) is None


def test_parse_stream():
    body = [31, 18, 5, 9, 0,
            0, 18, 140, 120, 150, 110,     # gauche : corrigé (140,120) brut (150,110)
            1, 3,                           # un bouton
            0, 7, 200, 0,                   # gâchette
            0, 19, 128, 128, 130, 127]      # droit
    f = bytes(body + [fp.crc8(body)])
    s = fp.parse_stream(f)
    assert s[18] == (150, 110, 140, 120) and s[19] == (130, 127, 128, 128)


def test_corrected_position():
    st = fp.Stick(inner=10, outer=80)
    assert fp.corrected_position(135, 128, st) == (128.0, 128.0)        # dans la zone morte
    x, y = fp.corrected_position(128 + 110, 128, st)                    # au-delà du bord : à fond
    assert abs(x - 256) < 0.01 and y == 128
    x, _ = fp.corrected_position(128 + 64, 128, fp.Stick(inner=0, outer=100))   # linéaire, sans zone morte
    assert abs((x - 128) - 64 * 128 / 127.5) < 0.6
    assert fp.curve_value(85, [85, 85, 170, 170]) == 85
    assert fp.curve_value(35, [35, 35, 136, 204]) == 35


def test_triggers_roundtrip():
    cfg = fp.TriggersConfig(left=fp.Trigger(inner=6, outer=190, swap=True), right=fp.Trigger())
    p = cfg.to_payload()
    assert p[:8] == [14, 6, 10, 85, 85, 170, 170, 4]
    assert fp.TriggersConfig.from_payload(p) == cfg
    with pytest.raises(ValueError):
        fp.Trigger(inner=100, outer=50).to_bytes()


def test_motors_roundtrip():
    m = fp.MotorsConfig(motors=[200, 100, 0, 0], sleep_minutes=15)
    p = m.to_payload()
    assert p[0] == 8 and p[1:5] == [200, 100, 0, 0]
    assert int.from_bytes(bytes(p[5:9]), "little") == 15 * 60000 // 5
    assert fp.MotorsConfig.from_payload(p) == m
    never = fp.MotorsConfig(sleep_minutes=fp.SLEEP_NEVER).to_payload()
    assert never[5:] == [255] * 4
    assert fp.MotorsConfig.from_payload(never).sleep_minutes == fp.SLEEP_NEVER


def test_stream_triggers_and_output():
    body = [31, 15, 0, 0, 0, 0, 7, 0, 120, 0, 8, 0, 30]
    s = fp.parse_stream(bytes(body + [fp.crc8(body)]))
    assert s[7] == 120 and s[8] == 30
    assert s["buttons"] == {7: 1, 8: 0}          # L2 appuyée (> 15 %), R2 non
    t = fp.Trigger(inner=20, outer=180)
    assert fp.trigger_output(10, t) == 0 and fp.trigger_output(190, t) == 200
    assert abs(fp.trigger_output(100, t) - 100) < 0.6


def test_codes_compression():
    codes = list(range(1, 18)) + [20, 21]
    comp = fp.compress_codes(codes)
    assert comp == [19, 1, 128 + 17, 20, 21] or fp.decompress_codes(comp) == codes
    assert fp.decompress_codes(comp) == codes
    assert fp.decompress_codes([3, 5, 7, 9]) == [5, 7, 9]


def test_remap():
    btn = [1, 2, 3, 4, 5]
    r = fp.RemapConfig.from_raw(btn, [0, 0, 0, 0, 0])
    assert r.targets == btn and r.to_raw() == [0]
    r.targets[0] = 2           # A -> B
    r.targets[1] = 1           # B -> A
    r.targets[4] = fp.DISABLED  # L1 désactivé
    raw = r.to_raw()
    assert raw == [5, 2, 1, 0, 0, 5]
    assert fp.RemapConfig.from_raw(btn, raw[1:]) == r
    long = fp.RemapConfig(buttons=list(range(1, 21)), targets=list(range(2, 22)))
    assert [len(c) for c in long.chunks()] == [15, 6]
    assert fp.RemapConfig.from_dict(r.to_dict()).adapted_to([1, 2, 9]).targets == [2, 1, 9]


def test_stream_buttons():
    body = [31, 12, 0, 0, 0, 1, 3, 0, 5, 1, 17]
    s = fp.parse_stream(bytes(body + [fp.crc8(body)]))
    assert s["buttons"] == {3: 1, 5: 0, 17: 1}


def test_lights_roundtrip():
    z = fp.LightZone(color=[255, 0, 128], breathing=True, brightness=200, speed=1500)
    b = z.to_bytes()
    assert b == [255, 0, 128, 1500 & 0xFF, 0x80 | (1500 >> 8), 200]
    assert fp.LightZone.from_bytes(b) == z
    cfg = fp.LightsConfig(zones=[z, fp.LightZone()])
    raw = cfg.to_raw()
    assert raw[0] == 12 and fp.LightsConfig.from_items(raw[1:]) == cfg
    assert [len(c) for c in cfg.chunks()] == [13]


CODES = list(range(1, 17)) + [18, 19]   # A..croix, sticks : 16 bits + 2 x 4 bits = 24


def test_macro_encoding_matches_app_rules():
    # Étape : A + croix ↗ (haut + droite), stick G ←, durée 100 ms
    st = fp.MacroStep(duration=100, buttons=[1], dpad=2, lstick=7, rstick=0)
    m = fp.Macro(slot=1, steps=[st], loop=True, interval=500)
    raw = m.to_raw(CODES)
    assert raw[:3] == [7, 100, 0x80]            # 1 étape * 5 + 2 ; 500/5 = 100 ; bit de boucle
    mask = raw[3] | raw[4] << 8 | raw[5] << 16
    assert mask & 1                              # A = 1er code -> bit 0
    assert (mask >> 13) & 1 and (mask >> 14) & 1  # haut (14) bit 13, droite (15) bit 14
    assert not (mask >> 12) & 1 and not (mask >> 15) & 1
    assert (mask >> 16) & 0xF == 6               # stick G : direction 7 -> 6
    assert (mask >> 20) & 0xF == 8               # stick D neutre -> 1000
    assert raw[6:8] == [20, 0]                   # 100 ms / 5
    back = fp.Macro.from_items(1, raw[1:], CODES)
    assert back == m


def test_macro_empty_and_v2():
    assert fp.Macro(slot=0).to_raw(CODES) == [0]
    assert fp.Macro(slot=0, steps=[fp.MacroStep()]).to_raw(CODES) == [0]   # étapes vides retirées
    m = fp.Macro(slot=2, steps=[fp.MacroStep(buttons=[2])] * 3)
    raw = m.to_raw(CODES, v2=True)
    assert raw[0] == 3 and fp.Macro.total_items(raw, True) == 17
    assert fp.Macro.total_items(m.to_raw(CODES), False) == 17
    fb = fp.FrameBuilder(random.Random(0))
    fr = fb.write_macro(raw[:15], 0, 2, v2=True)
    assert fr[0] == 53 and fr[1] >> 5 == 2 and (fr[1] & 0x1F) == 20 and fp.check_crc(fr)


def test_dir_from_xy():
    assert fp.dir_from_xy(128, 128) == 0
    assert fp.dir_from_xy(128, 0) == 1 and fp.dir_from_xy(255, 128) == 3
    assert fp.dir_from_xy(128, 255) == 5 and fp.dir_from_xy(0, 128) == 7
    assert fp.dir_from_xy(255, 0) == 2
