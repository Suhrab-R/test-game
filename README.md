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

## Getting the app to send out

**Windows:** build it yourself:

```
pip install -r requirements.txt pyinstaller
pyinstaller --noconfirm CollisionTest.spec
```

This makes `dist/CollisionTest.exe`, one file you can send to anyone on Windows.

**Mac:** PyInstaller can only build a Mac app on a Mac, so GitHub builds it (and the
Windows exe) every time you push to `main`. Open the repo's **Actions** tab, click the
newest "Build game" run and download the files under **Artifacts** at the bottom:

- `CollisionTest-Windows`: the .exe
- `CollisionTest-Mac-AppleSilicon`: for Macs with an M1/M2/M3/M4 chip (most Macs since 2021)
- `CollisionTest-Mac-Intel`: for older Intel Macs

GitHub wraps each one in an extra zip. Unzip it once and send the file inside
(`CollisionTest.exe`, or `CollisionTest-Mac-....zip`, which the Mac player unzips to get
`CollisionTest.app`).

## First launch warnings

The app isn't signed (that costs money), so the first time it opens:

- **Windows:** "Windows protected your PC": click **More info**, then **Run anyway**.
  When the host first clicks HOST A GAME, Windows Firewall asks about network access:
  click **Allow** (tick both private and public networks), or nobody can join.
- **Mac:** "CollisionTest can't be opened": click **Done**, then go to **System Settings >
  Privacy & Security**, scroll down and click **Open Anyway**. If macOS asks to let the app
  find devices on your local network, click **Allow**. That's how it finds the host.

## Running from source

```
pip install -r requirements.txt
python main.py                 # search for a host, or click to host
python main.py --host          # host right away
python main.py --join 1.2.3.4  # join a specific IP instead of searching
python main.py --help          # more options, including load testing with bots
```
