# PadTune

🇫🇷 [Version française](LISEZMOI.md)

<img src="assets/padtune_128.png" width="96" alt="PadTune logo">

Configure the NYXI Flexi from Windows, no phone needed:

- **Sticks:** center deadzone, outer edge, sensitivity curve, axis inversion, stick swap.
- **Triggers:** start-of-travel deadzone, end of travel, curve, trigger swap.
- **Buttons:** remap any button to another one, or disable it.
- **Macros:** up to 8 macros, edited step by step or recorded straight from the controller, with an optional loop.
- **Lights:** color, static or breathing mode, brightness and speed.
- **Vibration & sleep:** strength of each motor and auto power-off delay.

The interface is available in **English, French, Spanish, German, Italian and Portuguese** (🌐 Language menu).

PadTune uses the same Bluetooth protocol as the KeyLinker app. Settings are saved **in the controller**, so they keep working wired, with the dongle, on Switch, and so on.

## Installation

### Easiest: PadTune.exe

Download **PadTune.exe** and double-click it. Nothing else to install: Python and everything else are included.

- **Windows SmartScreen:** the exe is not digitally signed (a certificate is expensive for a free project), so Windows may show "Windows protected your PC". Click **More info**, then **Run anyway**.
- **Antivirus:** some antivirus programs wrongly flag apps built with PyInstaller. The source code is available, and you can build the exe yourself (see below).
- **Demo mode:** `PadTune.exe --demo` opens the interface with a simulated controller.

### From source

1. Install **Python 3.14** (not 3.15, which isn't supported yet) from python.org: "Windows installer (64-bit)", and tick "Add python.exe to PATH".
2. Double-click **Launch.bat**. The first time, it installs what it needs (about 1 minute).

`Demo.bat` opens the interface with a simulated controller, so you can explore it safely.

To start PadTune like a normal app, double-click **Create shortcut.bat** after the first run. It adds a PadTune shortcut, with its icon, to the Desktop and the Start menu.

The `.bat` scripts show their messages in French when Windows is in French, and in English otherwise.

### Building PadTune.exe

- **On your PC:** double-click **Build exe.bat**. It installs PyInstaller, builds `dist\PadTune.exe`, checks that it starts correctly, then opens the folder.
- **Automatically on GitHub:** `.github/workflows/build-windows.yml` builds and checks the exe on Windows. It runs each time you publish a version (tag `v1.0.0`, `v1.1.0`…) and attaches `PadTune.exe` to the release page. You can also start it by hand from the **Actions** tab.

## Usage

1. **Close KeyLinker** (and turn off Bluetooth on your phone): the controller only accepts one configuration connection at a time.
2. **Turn the controller on**, in whatever mode you normally use (dongle, Bluetooth…). No need to switch modes or pair it with Windows: PadTune finds it on its own, as long as Bluetooth is turned on on the PC.
3. The search starts by itself when the app opens (click **Search** to run it again). Pick the device marked ★, then **Connect**.
4. The app reads the current settings and makes an **automatic backup** in `%APPDATA%\PadTune\`.
5. Change the settings, then click **Apply to controller**. The app reads the controller back to check that the values were saved.

**Live view** (on by default): move the sticks to see two dots in the circle.

- The **white dot** is the actual stick position.
- The **red dot** is what the game will receive with the settings shown, even before you click Apply.

Under the circle, `raw X % → output Y %` shows how far the stick is pushed. It's the easiest way to set the deadzone as low as possible: push the stick very slightly and check that the output moves.

**Favorite and auto-connect:** once connected, click **☆ Favorite**. The button turns into "★ Favorite" and the device is saved in `%APPDATA%\PadTune\settings.json`. Then:

- every time it starts, the app searches for controllers and connects to the favorite as soon as it's detected;
- if the favorite isn't switched on yet, it quietly searches again every 8 seconds;
- if the connection drops, it reconnects automatically;
- if you click **Disconnect**, it won't reconnect until your next manual search.

Click ★ Favorite again to remove the controller from favorites.

To go back to the original settings, use **Import…** with the backup file, then **Apply**.

## Settings

### Sticks

| Setting | Meaning |
|---|---|
| Center deadzone | Percentage of travel ignored at the center (0 = none) |
| Outer edge | Position from which the stick counts as fully pushed (100 = full travel) |
| Sensitivity curve | 2 control points on a 0–255 grid, same presets as KeyLinker. You can **drag the points with the mouse** right on the curve (the curve then becomes "Custom"). |
| Invert X / Y | Axis inversion |
| Swap sticks | Swaps the left and right sticks |

The dotted cross marks the center of the stick.

### Triggers

Same idea as the sticks. The **deadzone** is the part of the start of travel that is ignored, and the **end of travel** is the point from which the trigger counts as fully pressed. The bar shows the actual position (white line) and the value sent to the game (red bar).

### Buttons

For each physical button, choose what it sends: another button or "— disabled —". Remapped buttons are shown in bold. When live view is on, the row of the button you press lights up in yellow. "Reset all to default" cancels all remaps.

The list of buttons is the one the controller reports itself.

### Macros

A macro is a sequence of **steps**. Each step holds buttons down (and optionally a D-pad or stick direction) for a duration in milliseconds. For example, "A for 50 ms, then nothing for 30 ms, then B for 50 ms" gives A followed by B.

- **Pick a slot:** the "Macro" list shows the slots the controller accepts (up to 8). Macros are triggered with the controller's macro buttons, usually the back buttons, which you assign on the controller itself.
- **Edit:** "+ Step" adds a step. The "Buttons" button on each row opens the list of buttons to tick. ↑ and ↓ move the selected step.
- **Record:** "● Record from controller" captures your presses with their real duration, then "■ Stop recording" turns them into steps. Tick "Include sticks" to record stick directions too.
- **Loop:** the macro repeats, with the given pause between two repeats.

### Lights

Color (click the swatch to open the picker, or type R/G/B values), **Static** or **Breathing** mode, brightness, and breathing speed.

### Vibration & sleep

Strength from 0 to 100 % for each motor (0 % turns vibration off). Auto sleep sets how long the controller stays idle before switching off, or "Never".

**Apply** only sends what changed, and shows it on the button (for example "2 changes"). If a tab is greyed out, the controller didn't answer for that kind of setting.

## Language

The **🌐 Language** menu at the top of the window offers Français, English, Español, Deutsch, Italiano and Português. Your choice is saved, and the app offers to restart to apply it. On the very first start, PadTune uses the Windows language if it's available, otherwise English.

To fix or add a translation, edit `translations.py`: each French text is paired with its translation. Placeholders in braces, like `{name}`, must stay unchanged.

## Other controllers

PadTune doesn't check the controller model. It looks for the **KeyLinker Bluetooth service** (the device marked ★), then asks the controller what it supports: its list of buttons, buttons usable in macros, macro slots, light zones. Tabs it doesn't support stay greyed out.

So it should work with **other KeyLinker-compatible controllers**, meaning those configured with the KeyLinker app. Only the NYXI Flexi has been tested. Controllers from other brands with their own app (Xbox, DualSense, 8BitDo, GameSir…) use different protocols and won't work.

## Troubleshooting

- **The controller doesn't show up:** check that it's on, that Bluetooth is on on the PC, and that KeyLinker is closed on your phone. If it's already paired with Windows as a controller, you may need to remove it in Settings → Bluetooth.
- **It shows up without ★:** connect anyway. The service isn't always advertised before connecting.
- **"No response" from the controller:** disconnect, turn the controller off and on again, and retry.
- The log at the bottom of the window shows the frames exchanged. Copy it if you ask for help.

## How it works

`flexi_protocol.py` holds the protocol, reconstructed from the KeyLinker app (`com.pulsenet.inputset`):

- **Channel:** BLE service `d7f010e0-660d-46e9-96c3-19c4148bdab5`. Writes go to `…e1`, notifications arrive on `…e2`.
- **Frame format:** `[command, length, serial, random, data…, CRC8]`, then scrambled by XOR with fixed tables.
- **Live view:** the app sends command 29 (mode 7) every 750 ms. In return, the controller streams command 31 frames with the raw position of each stick (0–255).
- **Settings blocks:** each block is read and written with a pair of commands. The controller answers with an ACK (command 25) that repeats the request's serial number.
  - Sticks: read 177, write 49 (15 bytes).
  - Triggers: read 178, write 50 (15 bytes, 0–200 scale).
  - Vibration & sleep: read 179, write 51 (9 bytes: 4 motors, then the delay in 5 ms units).
  - Buttons: the button list is read with command 176 `[page, 3]`, as a compressed list. The remap is read with command 182 `[page]` and written with command 54, in chunks of 15 values. Each value is 0 (unchanged), the button's own code (disabled) or the target button's code.
  - Lights: read 183 `[page]`, write 55 in chunks. 6 bytes per zone: R, G, B, speed (low bits), mode and speed (high bits), brightness.
  - Macros: the list of usable buttons is read with command 176 `[page, 5]`, then each slot with command 181 `[page, slot]`. Writes use command 53, with the slot encoded in byte 1. The header holds the size, interval and loop flag, followed by 5 bytes per step: a 24-bit mask (1 bit per button and per D-pad direction, 4 bits per stick) and the duration in 5 ms units. Command 176 `[0, 1]` gives the header format (v1 or v2).
- **Live button display:** command 31 frames also contain `[state, code]` entries. On the Buttons tab, the keep-alive switches to mode 8, as in KeyLinker.

The tests (`tests/`) check that the encoding produces exactly the same bytes as the original Java code.
