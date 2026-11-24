# CRC Shift Bookmarks

CRC recalls bookmarks 0–9 with **Ctrl+Numpad**, but it has no keybind for any other bookmark. This small helper adds one: press **Shift+Numpad** in a CRC display window and it recalls a bookmark of your choice.

Behind the scenes, each press types three things into CRC, instantly:

1. **ESC** clears whatever is on the command line.
2. **`.##`** is the bookmark command, for example `.51`.
3. **ENTER** sends it.

> **Note:** the keys are typed into the display you're on, so the ESC clears anything you've already typed on that display's command line.

## Default keys

| Key        | Bookmark |
|------------|----------|
| Shift+Num0 | `.51`    |
| Shift+Num1 | `.11`    |
| Shift+Num2 | `.12`    |
| Shift+Num3 | `.13`    |
| Shift+Num4 | `.14`    |
| Shift+Num5 | `.15`    |
| Shift+Num6 | `.16`    |
| Shift+Num7 | `.17`    |
| Shift+Num8 | `.18`    |
| Shift+Num9 | `.19`    |

Left and Right Shift both work, with NumLock on or off. To use different bookmarks, see [Changing the bookmarks](#changing-the-bookmarks).

## Quick start

1. Install [Python 3.8 or newer](https://www.python.org/downloads/). No extra packages are needed.
2. Put this folder wherever you like.
3. Choose how to start the helper:
   - **Automatically, every time CRC opens (recommended):** double-click `setup_task.cmd` and choose **Install**. See [Starting it automatically](#starting-it-automatically-when-crc-opens).
   - **Manually:** double-click `crc_shift_bookmarks.pyw` before or after opening CRC. No window appears; it runs in the background.
4. The helper closes itself when CRC closes.

## Changing the bookmarks

Open `crc_shift_bookmarks.pyw` in a text editor. The settings are at the top:

```python
BOOKMARKS = {
    0: 51,  # Shift + Num0
    1: 11,  # Shift + Num1
    2: 12,  # Shift + Num2
    3: 13,  # Shift + Num3
    4: 14,  # Shift + Num4
    5: 15,  # Shift + Num5
    6: 16,  # Shift + Num6
    7: 17,  # Shift + Num7
    8: 18,  # Shift + Num8
    9: 19,  # Shift + Num9
}

SKIP_BROWSER_DISPLAYS = True   # don't type into an embedded Browser display
STARTUP_TIMEOUT = 300          # seconds to wait for CRC if the helper starts first
INTER_KEY_DELAY = 0.0          # seconds between typed keys; leave at 0
```

- Change the number after the colon to pick a different bookmark. For example, `5: 42,` makes Shift+Num5 recall `.42`.
- Set a key to `None` (for example `5: None,`) to leave Shift+that key alone.

Save the file, then restart the helper (or close and reopen CRC) for the change to take effect.

## When it fires, and when it doesn't

It fires only when all of these are true:

- A CRC **display window** is the active window. Display windows have titles like `CRC : 1` or `CRC : 2 : cab : MIA`.
- Shift is held, and Ctrl, Alt and Win are not.
- The key is on the **numpad**.

Everything else passes through to CRC untouched:

- Plain numpad keys, and Ctrl+Numpad (CRC's own bookmarks 0–9).
- The dedicated arrow, Home and End keys.
- CRC's side windows, such as `Messages`, `Voice Switch` and `CRC Profiles`.
- A **Browser display** that has keyboard focus, so a bookmark key never types `.51` and ENTER into a web page.
- Every other program. The helper doesn't listen to the keyboard at all unless a CRC window is active.

**Pressing keys quickly:** every press is sent instantly, however fast you press. Holding Shift and running across Num0–9 sends all ten bookmarks, and CRC works through them in order.

Only one copy runs at a time; starting a second copy does nothing. If the helper starts before CRC, it waits up to 5 minutes for CRC to open, then gives up.

## Starting it automatically when CRC opens

**Double-click `setup_task.cmd`.** A terminal window opens with a menu. Which options it shows depends on whether the task is already installed:

| Task status   | Options shown                 |
|---------------|-------------------------------|
| Not installed | `1) Install`                  |
| Installed     | `2) Validate`, `3) Uninstall` |

- **Install** asks you to pick `crc_shift_bookmarks.pyw` in a file dialog (only that file can be picked). It then creates a Task Scheduler task that starts the helper whenever CRC opens. Windows asks for admin rights once; see [Why Install needs admin](#why-install-needs-admin).
- **Validate** checks the installed task: that it's enabled, that Python and the helper are still where the task expects, that it triggers when CRC opens, and that it runs as you without admin rights. It also shows when the task last ran.
- **Uninstall** removes the task.

If you move the helper to another folder later, Validate will report it. Uninstall, then Install again.

### How the trigger works

Task Scheduler can't watch for a program opening. It can only react to an entry in a Windows event log. When CRC opens, it reads your saved login from Windows Credential Manager (under the name `Consolidated Radar Client`), and Windows records that read in the Security log as event 5379. The task starts the helper when that event appears.

Windows records this event by default, so Install doesn't change any Windows settings.

> **Note:** CRC only reads a saved login if you have one. If you don't save your login in CRC, the task won't start; start the helper manually instead.

### Why Install needs admin

Windows only lets admins create or remove a task that watches the Security log. The task itself runs as you, without admin rights, and only while you're logged on.

### Running the setup from a terminal

`setup_task.ps1` can also run without the menu:

```powershell
powershell -ExecutionPolicy Bypass -File .\setup_task.ps1 -Action Install -ScriptPath "D:\Tools\crc_shift_bookmarks.pyw"
```

```powershell
powershell -ExecutionPolicy Bypass -File .\setup_task.ps1 -Action Validate
```

```powershell
powershell -ExecutionPolicy Bypass -File .\setup_task.ps1 -Action Uninstall
```

Add `-DryRun` to Install to check what it would do without changing anything. Add `-PythonwPath` to point it at a specific `pythonw.exe`.

## Troubleshooting

Start by running the helper with a console window so you can see what it's doing:

```powershell
python crc_shift_bookmarks.pyw --debug
```

It logs to `%TEMP%\crc_shift_bookmarks.log`, with or without `--debug`. In debug mode the log also records window titles and Shift/Numpad key presses. It never records any other keys.

| Problem | What to check |
|---------|---------------|
| Nothing happens | Look in the log for `ignoring Shift+Numpad in window '...'`. It names the window that was rejected and why. |
| The bookmark comes out shifted, as `>%!` | Send the log. The helper should release Shift before typing. |
| `SendInput was blocked` in the log | CRC is running as administrator, so the helper must be too. |
| The task doesn't start when CRC opens | Run `setup_task.cmd` and choose **Validate**. If every check passes, open Task Scheduler and look at the History tab of the "CRC Shift Bookmarks" task. Also make sure CRC has your login saved. |

## How it works

With NumLock on, Windows turns Shift+Numpad into navigation keys: Shift+Num7 becomes Home, Shift+Num1 becomes End, and so on. It also wraps the key in fake Shift up/down events, marked with `0x200` in the scan code (`0x22A` / `0x236`). This is why CRC can't bind Shift+Numpad itself.

The helper tells numpad keys apart from the dedicated navigation keys by their physical scan code: the numpad versions aren't flagged as extended, while the dedicated keys are. It ignores the fake Shift events and blocks the original key. It then sends ESC, the dot command and ENTER as a single batch that starts by releasing Shift, so the typed characters aren't shifted.
