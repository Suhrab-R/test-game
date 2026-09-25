import argparse
import math
import os
import random
import socket

from pyray import *
from raylib import *

# Imported after pyray on purpose: pyray also exports a name called "struct",
# and the star import would otherwise replace Python's struct module.
import select
import struct
import time

PORT = 5555

# Slot 0 is the host; the other slots go to clients in the order they join.
# The host can cap how many players get in with --max-players.
MAX_PLAYERS_LIMIT = 32
PLAYER_NAMES = ["BLUE", "RED", "GREEN", "ORANGE", "VIOLET", "BROWN", "MAGENTA", "DARKGREEN", "GOLD", "MAROON"]
PLAYER_COLORS = [BLUE, RED, GREEN, ORANGE, VIOLET, BROWN, MAGENTA, DARKGREEN, GOLD, MAROON]
# Hand-picked spawns for the first few slots; later slots get a random spot that isn't in a wall.
SPAWNS = [
    (40.0, 40.0), (1210.0, 40.0), (625.0, 650.0), (40.0, 650.0), (1210.0, 650.0),
    (40.0, 345.0), (1210.0, 345.0), (625.0, 40.0), (625.0, 160.0), (240.0, 650.0),
]

# Power-up kinds. Each one is drawn as a colored circle with a letter on it.
SPEED_UP, RAPID_FIRE, TRIPLE_SHOT, SHIELD, EXTRA_LIFE = range(5)
POWERUP_NAMES = ["SPEED", "RAPID", "TRIPLE", "SHIELD", "LIFE"]
POWERUP_LETTERS = ["S", "R", "3", "O", "+"]
POWERUP_COLORS = [YELLOW, ORANGE, PURPLE, SKYBLUE, PINK]
# How long the timed power-ups last, in seconds. Shield lasts until you get hit,
# and extra life is used up right away.
POWERUP_DURATION = {SPEED_UP: 6.0, RAPID_FIRE: 6.0, TRIPLE_SHOT: 8.0}
POWERUP_RADIUS = 12.0
# A new power-up appears this often (seconds), up to MAX_POWERUPS on the map at once.
POWERUP_INTERVAL = 5.0
MAX_POWERUPS = 4

# Client -> host: the client's input direction (x, y), each -1, 0 or 1, plus a shoot flag.
INPUT_FORMAT = "!bbb"
# Host -> each client: that client's slot and how many slots there are, then
# (x, y, lives, active, effects) for every slot, then how many bullets and power-ups follow.
# effects is a bitmask of the power-up kinds the player currently has. Then each bullet as
# BULLET_FORMAT (x, y, owner), then each power-up as POWERUP_FORMAT (x, y, kind).
STATE_PREFIX_FORMAT = "!BB"
BULLET_FORMAT = "!ffB"
POWERUP_FORMAT = "!ffB"
# Keep state packets under a typical LAN MTU (1500 minus IP/UDP headers) so they never
# get split into fragments. If there are more bullets than fit, the extra ones aren't sent.
MAX_PACKET_SIZE = 1400

# Seconds without hearing from the other side before we treat them as disconnected.
TIMEOUT = 3.0
# With --auto-restart, the host starts a new round this many seconds after one ends.
AUTO_RESTART_DELAY = 3.0

# Bots (--bots) send their input this many times a second, like a client running at 60 FPS,
# and print how smooth their updates from the host were every BOT_REPORT_INTERVAL seconds.
BOT_SEND_RATE = 60
BOT_REPORT_INTERVAL = 2.0

SCREEN_WIDTH = 1280
SCREEN_HEIGHT = 720

PLAYER_SIZE = 30.0
# Pixels per second
SPEED = 300.0
SPEED_BOOST = 1.7
BULLET_SPEED = 700.0
BULLET_RADIUS = 4.0
# Seconds between shots for each player
SHOOT_COOLDOWN = 0.3
RAPID_COOLDOWN = 0.1
# Degrees between the bullets of a triple shot
SPREAD_ANGLE = 15.0
MAX_LIVES = 3
# Extra life power-ups can take you above MAX_LIVES, up to this.
MAX_BONUS_LIVES = 5

FACE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pic", "image.png")
# Square around the face in the original 1080x2400 photo.
FACE_CROP = Rectangle(72.0, 744.0, 1008.0, 1008.0)
FACE_TEXTURE_SIZE = 128


def state_header_format(player_count):
    return STATE_PREFIX_FORMAT + "ffBBB" * player_count + "BB"


def player_name(slot):
    return PLAYER_NAMES[slot] if slot < len(PLAYER_NAMES) else f"P{slot + 1}"


def player_color(slot):
    if slot < len(PLAYER_COLORS):
        return PLAYER_COLORS[slot]
    # Spread extra players around the color wheel.
    return color_from_hsv((slot * 47) % 360, 0.8, 0.8)


def spawn_point(slot):
    if slot < len(SPAWNS):
        return SPAWNS[slot]
    # Seeded by slot so the same slot always spawns in the same place.
    rng = random.Random(slot)
    walls = make_walls()
    while True:
        x = rng.uniform(0.0, SCREEN_WIDTH - PLAYER_SIZE)
        y = rng.uniform(0.0, SCREEN_HEIGHT - PLAYER_SIZE)
        rect = Rectangle(x, y, PLAYER_SIZE, PLAYER_SIZE)
        if not any(check_collision_recs(rect, wall) for wall in walls):
            return x, y


def start_facing(x, y):
    # Direction a player shoots before they've moved: toward the middle of the map.
    dx = SCREEN_WIDTH / 2 - (x + PLAYER_SIZE / 2)
    dy = SCREEN_HEIGHT / 2 - (y + PLAYER_SIZE / 2)
    if abs(dx) >= abs(dy):
        return (1 if dx > 0 else -1, 0)
    return (0, 1 if dy > 0 else -1)


class Player:
    def __init__(self, slot):
        self.slot = slot
        self.rect = Rectangle(0.0, 0.0, PLAYER_SIZE, PLAYER_SIZE)
        # True while someone is playing in this slot.
        self.active = False
        self.input = (0, 0, 0)
        self.reset()

    def reset(self):
        self.rect.x, self.rect.y = spawn_point(self.slot)
        self.lives = MAX_LIVES
        # Direction this player last moved in; that's where their bullets go.
        self.facing = start_facing(self.rect.x, self.rect.y)
        self.last_shot = -SHOOT_COOLDOWN
        # Power-up kind -> time it runs out, for the timed power-ups.
        self.effect_until = {}
        self.shield = False
        # Power-up kinds active right now. The host works this out each frame;
        # clients get it from the host.
        self.effects = set()

    def update_effects(self, now):
        self.effects = {kind for kind, until in self.effect_until.items() if now < until}
        if self.shield:
            self.effects.add(SHIELD)

    def effect_mask(self):
        return sum(1 << kind for kind in self.effects)

    def alive(self):
        return self.active and self.lives > 0

    def center(self):
        return Vector2(self.rect.x + self.rect.width / 2, self.rect.y + self.rect.height / 2)


def make_walls():
    # Mirrored left/right so the two top spawns are fair, with cover near the bottom spawn.
    return [
        Rectangle(600.0, 320.0, 80.0, 80.0),     # center block
        Rectangle(500.0, 220.0, 100.0, 20.0),    # around the center
        Rectangle(680.0, 220.0, 100.0, 20.0),
        Rectangle(500.0, 480.0, 100.0, 20.0),
        Rectangle(680.0, 480.0, 100.0, 20.0),
        Rectangle(560.0, 90.0, 160.0, 20.0),     # top middle
        Rectangle(160.0, 120.0, 20.0, 160.0),    # left pillars
        Rectangle(160.0, 440.0, 20.0, 160.0),
        Rectangle(1100.0, 120.0, 20.0, 160.0),   # right pillars
        Rectangle(1100.0, 440.0, 20.0, 160.0),
        Rectangle(300.0, 340.0, 140.0, 20.0),    # middle left / right
        Rectangle(840.0, 340.0, 140.0, 20.0),
        Rectangle(330.0, 150.0, 60.0, 60.0),     # upper blocks
        Rectangle(890.0, 150.0, 60.0, 60.0),
        Rectangle(330.0, 520.0, 60.0, 60.0),     # lower blocks
        Rectangle(890.0, 520.0, 60.0, 60.0),
        Rectangle(560.0, 600.0, 20.0, 80.0),     # either side of the bottom spawn
        Rectangle(700.0, 600.0, 20.0, 80.0),
    ]


def load_face_texture():
    # Crop the photo to a square around the face, then cut it into a circle
    # by making everything outside the circle transparent.
    image = load_image(FACE_PATH)
    image_crop(image, FACE_CROP)
    image_resize(image, FACE_TEXTURE_SIZE, FACE_TEXTURE_SIZE)
    half = FACE_TEXTURE_SIZE // 2
    mask = gen_image_color(FACE_TEXTURE_SIZE, FACE_TEXTURE_SIZE, BLANK)
    image_draw_circle(mask, half, half, half - 1, WHITE)
    image_alpha_mask(image, mask)
    texture = load_texture_from_image(image)
    set_texture_filter(texture, TEXTURE_FILTER_BILINEAR)
    unload_image(mask)
    unload_image(image)
    return texture


def read_input():
    input_x = 0
    input_y = 0

    if is_key_down(KEY_UP) or is_key_down(KEY_W):
        input_y -= 1
    if is_key_down(KEY_DOWN) or is_key_down(KEY_S):
        input_y += 1
    if is_key_down(KEY_LEFT) or is_key_down(KEY_A):
        input_x -= 1
    if is_key_down(KEY_RIGHT) or is_key_down(KEY_D):
        input_x += 1

    shoot = 1 if is_key_down(KEY_SPACE) else 0
    return input_x, input_y, shoot


# The host's collision checks use plain Python math on (x, y, width, height) tuples ("boxes")
# instead of raylib calls. With lots of players they run thousands of times a frame, and every
# call into raylib has overhead that adds up to most of the frame.
def to_box(rect):
    return (rect.x, rect.y, rect.width, rect.height)


def boxes_overlap(x, y, w, h, box):
    bx, by, bw, bh = box
    return x < bx + bw and x + w > bx and y < by + bh and y + h > by


def circle_hits_box(cx, cy, radius, box):
    # Find the point of the box closest to the circle's center and check its distance.
    bx, by, bw, bh = box
    nearest_x = min(max(cx, bx), bx + bw)
    nearest_y = min(max(cy, by), by + bh)
    return (cx - nearest_x) ** 2 + (cy - nearest_y) ** 2 <= radius * radius


def move_and_collide(player, blockers, dx, dy):
    # Move one axis at a time so we know which side we hit and can slide along walls.
    x, y, w, h = player.x + dx, player.y, player.width, player.height
    for box in blockers:
        if boxes_overlap(x, y, w, h, box):
            if dx > 0:
                x = box[0] - w
            elif dx < 0:
                x = box[0] + box[2]

    y += dy
    for box in blockers:
        if boxes_overlap(x, y, w, h, box):
            if dy > 0:
                y = box[1] - h
            elif dy < 0:
                y = box[1] + box[3]

    # Keep players on screen.
    player.x = max(0.0, min(x, SCREEN_WIDTH - w))
    player.y = max(0.0, min(y, SCREEN_HEIGHT - h))


def move_player(player, input_x, input_y, walls, speed):
    # Normalize the direction so diagonal movement is not faster.
    input_length = math.hypot(input_x, input_y)
    if input_length > 0.0:
        distance = speed * get_frame_time()
        dx = input_x / input_length * distance
        dy = input_y / input_length * distance
        move_and_collide(player, walls, dx, dy)


def spawn_bullet(bullets, player, angle_offset):
    # Bullets start at the shooter's center and fly in the direction they last moved,
    # turned by angle_offset degrees (used for triple shot).
    angle = math.atan2(player.facing[1], player.facing[0]) + math.radians(angle_offset)
    vx = math.cos(angle) * BULLET_SPEED
    vy = math.sin(angle) * BULLET_SPEED
    center = player.center()
    bullets.append([center.x, center.y, vx, vy, player.slot])


def try_shoot(bullets, player, now):
    input_x, input_y, shoot = player.input
    if input_x or input_y:
        player.facing = (input_x, input_y)
    cooldown = RAPID_COOLDOWN if RAPID_FIRE in player.effects else SHOOT_COOLDOWN
    if shoot and now - player.last_shot >= cooldown:
        player.last_shot = now
        angles = [-SPREAD_ANGLE, 0.0, SPREAD_ANGLE] if TRIPLE_SHOT in player.effects else [0.0]
        for angle in angles:
            spawn_bullet(bullets, player, angle)


def update_bullets(bullets, wall_boxes, players):
    dt = get_frame_time()
    # Work out every player's center once per frame instead of once per bullet.
    half = PLAYER_SIZE / 2
    targets = [(p, p.rect.x + half, p.rect.y + half) for p in players if p.alive()]
    hit_distance_sq = (BULLET_RADIUS + half) ** 2
    remaining = []
    for bullet in bullets:
        bullet[0] += bullet[2] * dt
        bullet[1] += bullet[3] * dt
        x, y = bullet[0], bullet[1]

        # A bullet can hit anyone except the player who fired it.
        hit = False
        for player, px, py in targets:
            # lives is checked too, in case another bullet killed them earlier this frame.
            if player.slot == bullet[4] or player.lives <= 0:
                continue
            if (x - px) ** 2 + (y - py) ** 2 <= hit_distance_sq:
                if player.shield:
                    player.shield = False
                else:
                    player.lives -= 1
                hit = True
                break
        if hit:
            continue
        if not (0 <= x <= SCREEN_WIDTH and 0 <= y <= SCREEN_HEIGHT):
            continue
        if any(circle_hits_box(x, y, BULLET_RADIUS, box) for box in wall_boxes):
            continue
        remaining.append(bullet)
    bullets[:] = remaining


def spawn_powerup(powerups, walls, players):
    # Try a few random spots and use the first one that isn't in a wall or right next to a player.
    for _ in range(30):
        x = random.uniform(40.0, SCREEN_WIDTH - 40.0)
        y = random.uniform(40.0, SCREEN_HEIGHT - 40.0)
        pos = Vector2(x, y)
        if any(check_collision_circle_rec(pos, POWERUP_RADIUS + 5, wall) for wall in walls):
            continue
        if any(check_collision_circles(pos, POWERUP_RADIUS, p.center(), PLAYER_SIZE * 2) for p in players if p.alive()):
            continue
        powerups.append([x, y, random.randrange(len(POWERUP_NAMES))])
        return


def apply_powerup(player, kind, now):
    if kind in POWERUP_DURATION:
        player.effect_until[kind] = now + POWERUP_DURATION[kind]
    elif kind == SHIELD:
        player.shield = True
    elif kind == EXTRA_LIFE:
        player.lives = min(MAX_BONUS_LIVES, player.lives + 1)
    player.update_effects(now)


def pick_up_powerups(powerups, players, now):
    remaining = []
    for powerup in powerups:
        pos = Vector2(powerup[0], powerup[1])
        taker = None
        for player in players:
            if player.alive() and check_collision_circles(pos, POWERUP_RADIUS, player.center(), PLAYER_SIZE / 2):
                taker = player
                break
        if taker is not None:
            apply_powerup(taker, powerup[2], now)
        else:
            remaining.append(powerup)
    powerups[:] = remaining


def round_over(players):
    # The round ends when at least two people are playing and at most one is still alive.
    active = [p for p in players if p.active]
    alive = [p for p in active if p.lives > 0]
    return len(active) >= 2 and len(alive) <= 1


def pack_state(players, bullets, powerups):
    # Builds the state packet with the receiver's slot left as 0. Everything else is the same
    # for every client, so the host builds it once per frame and uses with_slot() per client.
    header_format = state_header_format(len(players))
    room = MAX_PACKET_SIZE - struct.calcsize(header_format) - len(powerups) * struct.calcsize(POWERUP_FORMAT)
    sent = bullets[: max(0, min(255, room // struct.calcsize(BULLET_FORMAT)))]
    values = [0, len(players)]
    for player in players:
        values += [player.rect.x, player.rect.y, player.lives, 1 if player.active else 0, player.effect_mask()]
    values += [len(sent), len(powerups)]
    parts = [struct.pack(header_format, *values)]
    parts += [struct.pack(BULLET_FORMAT, bullet[0], bullet[1], bullet[4]) for bullet in sent]
    parts += [struct.pack(POWERUP_FORMAT, *powerup) for powerup in powerups]
    return b"".join(parts)


def with_slot(packet, slot):
    # The receiver's slot is the packet's first byte.
    return bytes((slot,)) + packet[1:]


def unpack_header(data):
    # Returns (header values, header size) for a valid state packet, otherwise None.
    # header values are: your_slot, player count, (x, y, lives, active, effects) per player,
    # bullet count, power-up count.
    if len(data) < struct.calcsize(STATE_PREFIX_FORMAT):
        return None
    player_count = struct.unpack_from(STATE_PREFIX_FORMAT, data)[1]
    header_format = state_header_format(player_count)
    header_size = struct.calcsize(header_format)
    if len(data) < header_size:
        return None
    values = struct.unpack_from(header_format, data)
    bullet_count, powerup_count = values[-2], values[-1]
    expected = header_size + bullet_count * struct.calcsize(BULLET_FORMAT) + powerup_count * struct.calcsize(POWERUP_FORMAT)
    if len(data) != expected:
        return None
    return values, header_size


def unpack_state(data, players):
    # Copies the host's player info into `players` (growing or shrinking it to match the host)
    # and returns (your_slot, bullets, powerups), or None if the packet is not a valid state packet.
    header = unpack_header(data)
    if header is None:
        return None
    values, header_size = header
    player_count, bullet_count, powerup_count = values[1], values[-2], values[-1]
    bullet_size = struct.calcsize(BULLET_FORMAT)
    powerup_size = struct.calcsize(POWERUP_FORMAT)
    while len(players) < player_count:
        players.append(Player(len(players)))
    del players[player_count:]
    for i, player in enumerate(players):
        x, y, lives, active, mask = values[2 + i * 5 : 7 + i * 5]
        player.rect.x, player.rect.y, player.lives, player.active = x, y, lives, bool(active)
        player.effects = {kind for kind in range(len(POWERUP_NAMES)) if mask >> kind & 1}
    offset = header_size
    bullets = []
    for _ in range(bullet_count):
        bullets.append(struct.unpack_from(BULLET_FORMAT, data, offset))
        offset += bullet_size
    powerups = []
    for _ in range(powerup_count):
        powerups.append(struct.unpack_from(POWERUP_FORMAT, data, offset))
        offset += powerup_size
    return values[0], bullets, powerups


def draw_player(player, face):
    rect = player.rect
    source = Rectangle(0.0, 0.0, face.width, face.height)
    draw_texture_pro(face, source, rect, Vector2(0.0, 0.0), 0.0, WHITE)
    # Colored ring so you can tell who is who.
    radius = rect.width / 2
    draw_ring(player.center(), radius - 2, radius + 1, 0.0, 360.0, 36, player_color(player.slot))
    if SHIELD in player.effects:
        draw_ring(player.center(), radius + 3, radius + 6, 0.0, 360.0, 36, SKYBLUE)


def draw_powerup(powerup):
    x, y, kind = powerup
    draw_circle_v(Vector2(x, y), POWERUP_RADIUS, POWERUP_COLORS[kind])
    draw_circle_lines(int(x), int(y), POWERUP_RADIUS, BLACK)
    letter = POWERUP_LETTERS[kind]
    width = measure_text(letter, 16)
    draw_text(letter, int(x - width / 2), int(y - 8), 16, BLACK)


def draw_world(walls, players, bullets, powerups, status, face, show_hud):
    begin_drawing()
    clear_background(Color(160, 200, 255, 255))
    for wall in walls:
        draw_rectangle_rec(wall, DARKGRAY)
    for powerup in powerups:
        draw_powerup(powerup)
    for player in players:
        if player.alive():
            draw_player(player, face)
    for bullet in bullets:
        draw_circle_v(Vector2(bullet[0], bullet[1]), BULLET_RADIUS, player_color(bullet[2]))
    draw_text(status, 10, 10, 20, BLACK)

    if show_hud:
        # Lives and active power-ups go in the bottom-left corner.
        active = [p for p in players if p.active]
        # Smaller lines once there are too many players to fit.
        line_height, font_size = (25, 20) if len(active) <= 20 else (17, 15)
        y = SCREEN_HEIGHT - line_height * len(active) - 5
        for player in active:
            text = f"{player_name(player.slot)} lives: {player.lives}"
            if player.effects:
                text += "  " + " ".join(POWERUP_NAMES[kind] for kind in sorted(player.effects))
            draw_text(text, 10, y, font_size, player_color(player.slot))
            y += line_height

        legend = "S speed   R rapid fire   3 triple shot   O shield   + extra life"
        width = measure_text(legend, 20)
        draw_text(legend, SCREEN_WIDTH - width - 10, SCREEN_HEIGHT - 25, 20, BLACK)

        if round_over(players):
            alive = [p for p in players if p.alive()]
            winner = player_name(alive[0].slot) if alive else "NOBODY"
            message = f"{winner} WINS! Host presses ENTER to restart"
            width = measure_text(message, 40)
            draw_text(message, (SCREEN_WIDTH - width) // 2, SCREEN_HEIGHT // 2 - 20, 40, BLACK)
    end_drawing()


def get_local_ip():
    # Connecting a UDP socket sends nothing; it just makes the OS pick the
    # network interface it would use, which tells us our LAN IP.
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def run_host(max_players, debug, auto_restart):
    # debug shows the load stats on screen; auto_restart is only offered with --debug.
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", PORT))
    sock.setblocking(False)

    init_window(SCREEN_WIDTH, SCREEN_HEIGHT, "Collision Test - Host")
    set_target_fps(60)
    face = load_face_texture()

    walls = make_walls()
    wall_boxes = [to_box(wall) for wall in walls]
    # Starts with just the host; a slot is added each time someone joins and no old slot is free.
    players = [Player(0)]
    players[0].active = True
    bullets = []
    powerups = []
    next_powerup_time = get_time() + POWERUP_INTERVAL

    # Client address -> the slot they're playing in.
    clients = {}
    last_heard = [0.0]
    local_ip = get_local_ip()
    round_over_since = None

    # Load stats, shown on screen with --debug and refreshed once a second. "work" is the time the host
    # spends on game logic and networking each frame; if it gets near 16.7 ms (one frame at
    # 60 FPS) the host can't keep up and every client's updates slow down.
    packet_size = 0
    bytes_this_second = 0
    work_times = []
    stats = "measuring..."
    stats_start = get_time()

    while not window_should_close():
        work_start = time.perf_counter()
        # Read every packet that arrived since last frame; only the newest input matters.
        while True:
            try:
                data, addr = sock.recvfrom(64)
            except BlockingIOError:
                break
            except ConnectionResetError:
                # Windows reports "client closed" this way for UDP; just ignore it.
                continue
            if len(data) != struct.calcsize(INPUT_FORMAT):
                continue
            slot = clients.get(addr)
            if slot is None:
                # Reuse the slot of someone who left, otherwise add a new one.
                free = [p.slot for p in players if not p.active]
                if free:
                    slot = free[0]
                elif len(players) < max_players:
                    slot = len(players)
                    players.append(Player(slot))
                    last_heard.append(0.0)
                else:
                    # Game is full.
                    continue
                clients[addr] = slot
                players[slot].reset()
                players[slot].active = True
            players[slot].input = struct.unpack(INPUT_FORMAT, data)
            last_heard[slot] = get_time()

        # Free the slots of clients we haven't heard from in a while.
        for addr, slot in list(clients.items()):
            if get_time() - last_heard[slot] >= TIMEOUT:
                del clients[addr]
                players[slot].active = False
                players[slot].input = (0, 0, 0)

        players[0].input = read_input()
        now = get_time()

        if not round_over(players):
            round_over_since = None
            alive = [p for p in players if p.alive()]
            for player in alive:
                player.update_effects(now)
            # Players block each other like walls do. boxes[i] is kept up to date as each one moves.
            boxes = [to_box(p.rect) for p in alive]
            for i, player in enumerate(alive):
                blockers = wall_boxes + boxes[:i] + boxes[i + 1:]
                speed = SPEED * SPEED_BOOST if SPEED_UP in player.effects else SPEED
                move_player(player.rect, player.input[0], player.input[1], blockers, speed)
                boxes[i] = to_box(player.rect)
                try_shoot(bullets, player, now)
            update_bullets(bullets, wall_boxes, players)
            pick_up_powerups(powerups, players, now)

            if now >= next_powerup_time:
                next_powerup_time = now + POWERUP_INTERVAL
                if len(powerups) < MAX_POWERUPS:
                    spawn_powerup(powerups, walls, players)
        elif round_over_since is None:
            round_over_since = now

        auto_restart_due = auto_restart and round_over_since is not None and now - round_over_since >= AUTO_RESTART_DELAY
        if is_key_pressed(KEY_ENTER) or auto_restart_due:
            for player in players:
                player.reset()
            bullets.clear()
            powerups.clear()
            next_powerup_time = now + POWERUP_INTERVAL
            round_over_since = None

        packet = pack_state(players, bullets, powerups)
        packet_size = len(packet)
        for addr, slot in clients.items():
            try:
                sock.sendto(with_slot(packet, slot), addr)
                bytes_this_second += packet_size
            except OSError:
                pass

        work_times.append(time.perf_counter() - work_start)
        if now - stats_start >= 1.0:
            average_ms = sum(work_times) / len(work_times) * 1000
            worst_ms = max(work_times) * 1000
            stats = (
                f"{get_fps()} FPS | work {average_ms:.1f} ms avg, {worst_ms:.1f} ms worst (budget 16.7)"
                f" | {len(bullets)} bullets | {packet_size} B/packet, {bytes_this_second / (now - stats_start) / 1024:.0f} KB/s sent"
            )
            work_times.clear()
            bytes_this_second = 0
            stats_start = now

        count = sum(1 for p in players if p.active)
        status = (
            f"You are {player_name(0)} - hosting on {local_ip}:{PORT} - {count} players"
            " (SPACE to shoot, ENTER to restart)"
        )
        if debug:
            status += "\n" + stats
        # Bullets are drawn as (x, y, owner) on both host and client.
        drawn_bullets = [(b[0], b[1], b[4]) for b in bullets]
        draw_world(walls, players, drawn_bullets, powerups, status, face, True)

    unload_texture(face)
    close_window()
    sock.close()


def run_client(host_ip, debug):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", 0))
    sock.setblocking(False)

    init_window(SCREEN_WIDTH, SCREEN_HEIGHT, "Collision Test - Client")
    set_target_fps(60)
    face = load_face_texture()

    walls = make_walls()
    # Filled in from the host's state packets, which say how many slots there are.
    players = []
    bullets = []
    powerups = []
    my_slot = None

    have_state = False
    last_heard = 0.0
    # State packets received per second, shown with --debug to see how smooth the connection is.
    packets_this_second = 0
    updates_per_second = 0
    second_start = get_time()

    while not window_should_close():
        # The client only sends its keys; the host does all the movement, shooting and collision.
        try:
            sock.sendto(struct.pack(INPUT_FORMAT, *read_input()), (host_ip, PORT))
        except OSError:
            pass

        while True:
            try:
                data, _ = sock.recvfrom(4096)
            except BlockingIOError:
                break
            except ConnectionResetError:
                # Windows reports "host not running" this way for UDP; keep trying.
                continue
            state = unpack_state(data, players)
            if state is not None:
                my_slot, bullets, powerups = state
                have_state = True
                last_heard = get_time()
                packets_this_second += 1

        if get_time() - second_start >= 1.0:
            updates_per_second = packets_this_second
            packets_this_second = 0
            second_start = get_time()

        connected = have_state and get_time() - last_heard < TIMEOUT

        if connected:
            status = f"You are {player_name(my_slot)} - connected (SPACE to shoot)"
            if debug:
                status += f"\n{get_fps()} FPS | {updates_per_second} updates/s from host"
            draw_world(walls, players, bullets, powerups, status, face, True)
        else:
            status = f"Connecting to {host_ip}:{PORT}..."
            draw_world(walls, [], [], [], status, face, False)

    unload_texture(face)
    close_window()
    sock.close()


class Bot:
    # A fake player for load testing that plays roughly like a person. It holds shoot the whole
    # time and fights the nearest enemy from its own preferred distance: it walks closer when too
    # far, otherwise dodges sideways and every so often turns toward the enemy to line up a shot
    # (you shoot the way you last moved). Now and then it wanders off in a random direction,
    # which also gets it unstuck from walls.
    def __init__(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("0.0.0.0", 0))
        self.sock.setblocking(False)
        self.slot = None
        # (x, y, lives, active) for every slot, from the newest state packet.
        self.players = []
        self.preferred_range = random.uniform(150.0, 450.0)
        self.aiming = False
        self.mode_until = 0.0
        self.strafe = random.choice((-1, 1))
        self.last_pos = None
        self.stuck_check_at = 0.0
        self.wander = (0, 0, 0)
        self.wander_until = 0.0
        # Stats since the last report.
        self.packets = 0
        self.last_packet = None
        self.worst_gap = 0.0

    def receive(self, now):
        newest = None
        while True:
            try:
                data, _ = self.sock.recvfrom(4096)
            except BlockingIOError:
                break
            except ConnectionResetError:
                # Windows reports "host not running" this way for UDP; keep trying.
                continue
            newest = data
            self.packets += 1
            if self.last_packet is not None:
                self.worst_gap = max(self.worst_gap, now - self.last_packet)
            self.last_packet = now
        # Only the newest state matters. Bots only read the player list, not bullets.
        header = unpack_header(newest) if newest is not None else None
        if header is not None:
            values = header[0]
            self.slot = values[0]
            self.players = [values[2 + i * 5 : 6 + i * 5] for i in range(values[1])]

    def choose_input(self, now):
        if self.slot is None or self.slot >= len(self.players):
            return (0, 0, 0)
        x, y, lives, _ = self.players[self.slot]
        if lives == 0:
            return (0, 0, 0)
        # Barely moved in the last quarter second: it's pressing against a wall or the screen
        # edge, so dodge the other way, like a person would.
        if now >= self.stuck_check_at:
            if self.last_pos is not None and math.hypot(x - self.last_pos[0], y - self.last_pos[1]) < 10:
                self.strafe = -self.strafe
                self.mode_until = now
            self.last_pos = (x, y)
            self.stuck_check_at = now + 0.25
        if now < self.wander_until:
            return self.wander
        if random.random() < 0.005:
            self.wander_until = now + random.uniform(0.3, 1.0)
            self.wander = (random.randint(-1, 1), random.randint(-1, 1), 1)
            return self.wander
        enemies = [
            (ex - x, ey - y)
            for i, (ex, ey, enemy_lives, active) in enumerate(self.players)
            if i != self.slot and active and enemy_lives > 0
        ]
        if not enemies:
            return (0, 0, 0)
        dx, dy = min(enemies, key=lambda d: d[0] * d[0] + d[1] * d[1])
        # The closest of the 8 directions toward the enemy.
        toward_x = ((dx > 0) - (dx < 0)) if abs(dx) > PLAYER_SIZE / 2 else 0
        toward_y = ((dy > 0) - (dy < 0)) if abs(dy) > PLAYER_SIZE / 2 else 0

        if now >= self.mode_until:
            # Switch between a short moment of aiming and a longer stretch of dodging.
            self.aiming = not self.aiming
            self.mode_until = now + (random.uniform(0.1, 0.25) if self.aiming else random.uniform(0.3, 0.8))
            if not self.aiming and random.random() < 0.5:
                self.strafe = -self.strafe

        if self.aiming or math.hypot(dx, dy) > self.preferred_range:
            return (toward_x, toward_y, 1)
        return (-toward_y * self.strafe, toward_x * self.strafe, 1)


def report_bots(bots, elapsed, now):
    connected = [b for b in bots if b.last_packet is not None and now - b.last_packet < TIMEOUT]
    if not connected:
        print(f"0/{len(bots)} bots connected - waiting for the host...")
    else:
        rates = [b.packets / elapsed for b in connected]
        worst_gap_ms = max(b.worst_gap for b in connected) * 1000
        print(
            f"{len(connected)}/{len(bots)} bots connected | updates/s per bot: avg {sum(rates) / len(rates):.1f},"
            f" lowest {min(rates):.1f} | longest gap between updates: {worst_gap_ms:.0f} ms"
        )
    for bot in bots:
        bot.packets = 0
        bot.worst_gap = 0.0


def run_bots(host_ip, count):
    # Runs `count` bots in this one process. Each has its own socket, so the host sees each
    # one as a separate player, exactly like separate copies of the game.
    bots = [Bot() for _ in range(count)]
    bot_by_sock = {bot.sock: bot for bot in bots}
    send_interval = 1.0 / BOT_SEND_RATE
    next_send = time.perf_counter()
    report_start = next_send

    print(f"Running {count} bots against {host_ip}:{PORT}. Press Ctrl+C to stop.")
    print("Smooth looks like ~60 updates/s and gaps under ~50 ms; bigger gaps are visible stutter.")
    try:
        while True:
            now = time.perf_counter()
            if now >= next_send:
                for bot in bots:
                    try:
                        bot.sock.sendto(struct.pack(INPUT_FORMAT, *bot.choose_input(now)), (host_ip, PORT))
                    except OSError:
                        pass
                next_send += send_interval
                # If this process fell far behind, don't try to catch up with a burst of sends.
                if now - next_send > 0.1:
                    next_send = now + send_interval
            if now - report_start >= BOT_REPORT_INTERVAL:
                report_bots(bots, now - report_start, now)
                report_start = now
            # Sleep until the next send, but wake up as soon as a state packet arrives
            # so the arrival times (and gaps) are measured accurately.
            wait = max(0.0, next_send - time.perf_counter())
            readable, _, _ = select.select(list(bot_by_sock), [], [], wait)
            arrived = time.perf_counter()
            for sock in readable:
                bot_by_sock[sock].receive(arrived)
    except KeyboardInterrupt:
        pass
    finally:
        for bot in bots:
            bot.sock.close()


def main():
    parser = argparse.ArgumentParser(description="LAN shooter for any number of players")
    parser.add_argument("--join", metavar="HOST_IP", help="join a host at this IP instead of hosting")
    parser.add_argument(
        "--max-players", type=int, default=MAX_PLAYERS_LIMIT,
        help=f"when hosting, optional cap on players, host included (default and highest: {MAX_PLAYERS_LIMIT})",
    )

    # Everything below is for load testing. Without --debug the game plays normally.
    testing = parser.add_argument_group("testing (all need --debug)")
    testing.add_argument(
        "--debug", action="store_true",
        help="show load stats (FPS, host frame time, bullets, bandwidth, updates/s) and allow the options below",
    )
    testing.add_argument(
        "--auto-restart", action="store_true",
        help=f"when hosting, start a new round {AUTO_RESTART_DELAY:.0f} seconds after one ends (handy for long load tests)",
    )
    testing.add_argument(
        "--bots", type=int, metavar="N",
        help="with --join, run N simulated players in this window-less process instead of opening the game",
    )
    args = parser.parse_args()

    if not 1 <= args.max_players <= MAX_PLAYERS_LIMIT:
        parser.error(f"--max-players must be between 1 and {MAX_PLAYERS_LIMIT}")
    if (args.bots is not None or args.auto_restart) and not args.debug:
        parser.error("--bots and --auto-restart are testing options; add --debug to use them")
    if args.bots is not None and (not args.join or args.bots < 1):
        parser.error("--bots needs --join HOST_IP and a count of at least 1")

    if args.join and args.bots:
        run_bots(args.join, args.bots)
    elif args.join:
        run_client(args.join, args.debug)
    else:
        run_host(args.max_players, args.debug, args.auto_restart)


if __name__ == "__main__":
    main()
