# test-game

A LAN shooter for any number of players. WASD or arrow keys to move, SPACE to shoot.
After you get hit you're invincible for 1 second (you blink red while it lasts).

## Playing

Everyone runs the same app. It opens on a "Looking for a game on your network..." screen.

- **Host:** open the app and click **HOST A GAME** (or press H).
- **Everyone else:** just open the app. It finds the host on the network and joins by
  itself, with no IP to type. It's fine to open it before the host has started.

The host has a **DAMAGE: ON / OFF** button in the top-right corner (or press T). Turn damage
off while people are joining so nobody dies in the meantime. Turning it back on starts a
fresh round with everyone at full lives. The host can also press ENTER to restart a round.

Everyone has to be on the same network (the same Wi-Fi). The game finds the host two ways:

- **Broadcast:** works on home Wi-Fi and phone hotspots, no internet needed.
- **Online relay:** for networks that block broadcasts (like campus Wi-Fi), the host also
  posts its local IP to [ntfy.sh](https://ntfy.sh), a free message relay, and the other
  players' games read it from there. Only the host's local network address (e.g.
  `10.160.60.104`) is posted. This needs internet access.

If a network blocks devices from talking to each other at all, nothing will work there;
use a phone hotspot instead.

## Download

These links always give the newest version (no GitHub account needed):

- **Windows:** [CollisionTest-Windows.exe](https://github.com/Suhrab-R/test-game/releases/latest/download/CollisionTest-Windows.exe)
- **Mac with an M1/M2/M3/M4 chip** (most Macs since 2021): [CollisionTest-Mac-AppleSilicon.zip](https://github.com/Suhrab-R/test-game/releases/latest/download/CollisionTest-Mac-AppleSilicon.zip)
- **Older Intel Mac:** [CollisionTest-Mac-Intel.zip](https://github.com/Suhrab-R/test-game/releases/latest/download/CollisionTest-Mac-Intel.zip)

(Not sure which Mac? Apple menu > About This Mac: "Chip: Apple M..." or "Processor: Intel".)

Every push to `main` builds a new version and publishes it as a release called "Build N".
The game shows its build number on the start screen and in the window title, so everyone
can check they have the same one. Older builds are on the repo's **Releases** page.

To build the Windows exe on your own computer instead (it'll say "Local build"):

```
pip install -r requirements.txt pyinstaller
pyinstaller --noconfirm CollisionTest.spec
```

## First launch warnings

The app isn't signed (that costs money), so the first time it opens:

- **Windows:** the browser may say the file "isn't commonly downloaded": choose **Keep**.
  Then "Windows protected your PC": click **More info**, then **Run anyway**.
  When the host first clicks HOST A GAME, Windows Firewall asks about network access:
  click **Allow** (tick both private and public networks), or nobody can join.
- **Mac:** unzip to get `CollisionTest.app`, then open **Terminal**, type `xattr -cr `
  (with a space at the end), drag `CollisionTest.app` into the Terminal window and press
  Enter. After that it opens normally. If macOS asks to let the app find devices on your
  local network, click **Allow**. That's how it finds the host.

## Running from source

```
pip install -r requirements.txt
python main.py                 # search for a host, or click to host
python main.py --host          # host right away
python main.py --join 1.2.3.4  # join a specific IP instead of searching
python main.py --help          # more options, including load testing with bots
```
