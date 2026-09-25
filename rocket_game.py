import math
import random
import pygame

# ============================================================
# COSMIC ROCKET - simple Flappy-Bird-style planet game
# ============================================================
# Controls:
#   Move mouse UP/DOWN  -> rocket altitude
#   SPACE / left click  -> small upward boost
#   R                   -> restart after game over
#   ESC                 -> quit
#
# Collision effects:
#   Venus   -> strike + bounce away
#   Mercury -> rocket bursts
#   Jupiter -> rocket sinks into the planet surface
#   Saturn  -> rocket spirals into the rings
#   Earth   -> rocket crashes
#   Neptune -> rocket crashes
#
# Scheduling mathematics:
#   Same lane  -> same lane: minimum 1.0 second
#   Upper      -> lower: minimum 2.5 seconds
#   Lower      -> upper: minimum 2.5 seconds
#   Lane order: Random
#
# Vertical control mathematics:
#   PLAY_BOTTOM - PLAY_TOP is the full playable height.
#   MAX_VERTICAL_SPEED = full_height / 4 seconds.
#   Thus a bottom-to-top cursor command takes at most 4 seconds.
# ============================================================

pygame.init()

WIDTH, HEIGHT = 1100, 700
SCREEN = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption("Cosmic Rocket")
CLOCK = pygame.time.Clock()
FPS = 60

# -------------------- Game constants --------------------
WORLD_SPEED = 220.0

# Requested minimum time gaps.
SAME_LANE_TIME = 1.0
CROSS_LANE_TIME = 2.5

PLAY_TOP = 65
PLAY_BOTTOM = HEIGHT - 65
FULL_VERTICAL_DISTANCE = PLAY_BOTTOM - PLAY_TOP

# The cursor/rocket must take 4 seconds to cross the full playable height.
MAX_VERTICAL_SPEED = FULL_VERTICAL_DISTANCE / 4.0

ROCKET_X = 190
ROCKET_RADIUS = 24

PLANET_TYPES = ["Venus", "Mercury", "Jupiter", "Saturn", "Earth", "Neptune"]

# Pygame works in pixels, not centimetres. We use a conventional 96-DPI
# screen scale so 0.5 cm corresponds to about 18.9 pixels.
PIXELS_PER_CM = 96.0 / 2.54
RADIUS_INCREASE_PX = 0.5 * PIXELS_PER_CM

BASE_PLANET_RADII = {
    "Venus": 48,
    "Mercury": 42,
    "Jupiter": 60,
    "Saturn": 52,
    "Earth": 47,
    "Neptune": 54,
}

PLANET_RADII = {
    name: int(round(radius + RADIUS_INCREASE_PX))
    for name, radius in BASE_PLANET_RADII.items()
}

SATURN_RING_OUTER_FACTOR = 1.65
SAFE_SEPARATION = 12

MAX_OBSTACLE_RADIUS = max(
    max(PLANET_RADII.values()),
    PLANET_RADII["Saturn"] * SATURN_RING_OUTER_FACTOR,
)


def planet_envelope_radius(name):
    """Returns the outer effective obstacle radius for a given planet type."""
    if name == "Saturn":
        return PLANET_RADII["Saturn"] * SATURN_RING_OUTER_FACTOR
    return PLANET_RADII[name]


# For adjacent planets the maximum type is not repeated (the type sequence
# itself forbids identical neighbours), so this verifies that the 1-second
# same-lane spacing is compatible with the selected sizes.
MAX_DIFFERENT_TYPE_PAIR = max(
    PLANET_RADII[a] + (PLANET_RADII["Saturn"] * SATURN_RING_OUTER_FACTOR if b == "Saturn" else PLANET_RADII[b])
    for a in PLANET_TYPES
    for b in PLANET_TYPES
    if a != b
)

assert WORLD_SPEED * SAME_LANE_TIME > MAX_DIFFERENT_TYPE_PAIR + SAFE_SEPARATION

# -------------------- Colours --------------------
WHITE = (245, 250, 255)
CYAN = (55, 225, 255)
BLUE = (45, 120, 255)
DARK_SPACE = (3, 5, 25)
RED = (255, 65, 70)
ORANGE = (255, 170, 70)
YELLOW = (255, 230, 100)

FONT = pygame.font.SysFont("consolas", 25, bold=True)
SMALL_FONT = pygame.font.SysFont("consolas", 16)
BIG_FONT = pygame.font.SysFont("consolas", 52, bold=True)


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def make_planet_sequence(length=60, previous=None):
    """Balanced random order: each 6-planet block contains all six once."""
    result = []
    last = previous
    blocks = math.ceil(length / len(PLANET_TYPES))

    for _ in range(blocks):
        block = PLANET_TYPES[:]
        while True:
            random.shuffle(block)
            if last is None or block[0] != last:
                break
        result.extend(block)
        last = block[-1]

    return result[:length]


class Star:
    def __init__(self):
        self.x = random.uniform(0, WIDTH)
        self.y = random.uniform(0, HEIGHT)
        self.size = random.choice([1, 1, 1, 2, 2, 3])
        self.speed = random.uniform(0.3, 1.2)

    def update(self, dt):
        self.x -= self.speed * 60 * dt
        if self.x < -5:
            self.x = WIDTH + random.uniform(10, 80)
            self.y = random.uniform(0, HEIGHT)

    def draw(self):
        pygame.draw.circle(
            SCREEN, (170, 215, 255),
            (int(self.x), int(self.y)), self.size
        )


class Particle:
    def __init__(self, x, y, color, speed=300, life=1.0):
        self.x, self.y = x, y
        angle = random.uniform(0, math.tau)
        speed = random.uniform(speed * 0.25, speed)
        self.vx = math.cos(angle) * speed
        self.vy = math.sin(angle) * speed
        self.life = life * random.uniform(0.6, 1.0)
        self.max_life = self.life
        self.radius = random.uniform(2, 5)
        self.color = color

    def update(self, dt):
        self.x += self.vx * dt
        self.y += self.vy * dt
        self.vx *= 0.985
        self.vy *= 0.985
        self.life -= dt
        return self.life > 0

    def draw(self):
        alpha = int(255 * max(0, self.life / self.max_life))
        r = max(1, int(self.radius))
        s = pygame.Surface((r * 4, r * 4), pygame.SRCALPHA)
        pygame.draw.circle(s, (*self.color, alpha), (r * 2, r * 2), r)
        SCREEN.blit(s, (int(self.x - r * 2), int(self.y - r * 2)))


class Rocket:
    def __init__(self):
        self.reset()

    def reset(self):
        self.x = float(ROCKET_X)
        self.y = float(HEIGHT // 2)
        self.target_y = self.y
        self.angle = 0.0
        self.visible = True
        self.scale = 1.0

    def update(self, mouse_y, dt):
        if not self.visible:
            return

        self.target_y = clamp(mouse_y, PLAY_TOP, PLAY_BOTTOM)
        delta = self.target_y - self.y
        step = MAX_VERTICAL_SPEED * dt

        # Constant maximum speed guarantees the 4-second full-height rule.
        if abs(delta) <= step:
            self.y = self.target_y
        else:
            self.y += step if delta > 0 else -step

        self.angle = clamp(delta * 0.12, -18, 18)

    def draw(self):
        if not self.visible:
            return

        sprite = pygame.Surface((130, 100), pygame.SRCALPHA)
        cy = 50

        # Engine glow and exhaust
        for r, a in [(24, 18), (18, 32), (12, 55)]:
            pygame.draw.circle(sprite, (20, 180, 255, a), (23, cy), r)
        pygame.draw.polygon(sprite, (50, 215, 255, 220),
                            [(41, cy - 10), (5, cy), (41, cy + 10)])
        pygame.draw.polygon(sprite, WHITE,
                            [(40, cy - 4), (14, cy), (40, cy + 4)])

        # Fins
        pygame.draw.polygon(sprite, (15, 95, 175),
                            [(43, cy - 16), (27, cy - 31), (50, cy - 19)])
        pygame.draw.polygon(sprite, (15, 95, 175),
                            [(43, cy + 16), (27, cy + 31), (50, cy + 19)])

        # Main body
        body = [(34, cy), (55, cy - 22), (95, cy - 17),
                (116, cy), (95, cy + 17), (55, cy + 22)]
        pygame.draw.polygon(sprite, (20, 85, 145), body)
        pygame.draw.lines(sprite, CYAN, True, body, 3)

        # Nose
        pygame.draw.polygon(sprite, (150, 240, 255),
                            [(90, cy - 17), (116, cy), (90, cy + 17), (82, cy)])

        # Cockpit
        cockpit = pygame.Rect(57, cy - 15, 30, 30)
        pygame.draw.ellipse(sprite, (60, 210, 255, 100), cockpit)
        pygame.draw.ellipse(sprite, (190, 250, 255), cockpit, 2)

        # Boy's helmet and body
        pygame.draw.circle(sprite, (235, 235, 238), (71, cy - 1), 8)
        pygame.draw.circle(sprite, (40, 100, 140), (71, cy - 1), 5)
        pygame.draw.ellipse(sprite, (35, 85, 150), pygame.Rect(63, cy + 5, 16, 12))

        rotated = pygame.transform.rotate(sprite, -self.angle)
        if self.scale != 1.0:
            w = max(1, int(rotated.get_width() * self.scale))
            h = max(1, int(rotated.get_height() * self.scale))
            rotated = pygame.transform.smoothscale(rotated, (w, h))

        rect = rotated.get_rect(center=(int(self.x), int(self.y)))
        SCREEN.blit(rotated, rect)

    def radius(self):
        return ROCKET_RADIUS


class Planet:
    def __init__(self, name, x, y, lane):
        self.name = name
        self.x = float(x)
        self.y = float(y)
        self.lane = lane
        self.radius = PLANET_RADII[name]
        self.rotation = random.uniform(0, math.tau)
        self.passed = False

        if name == "Saturn":
            self.ring_inner = self.radius * 1.05
            self.ring_outer = self.radius * SATURN_RING_OUTER_FACTOR
        else:
            self.ring_inner = self.ring_outer = None

        self.obstacle_radius = planet_envelope_radius(name)

    def update(self, dt):
        self.x -= WORLD_SPEED * dt
        self.rotation += 0.18 * dt

    def collides(self, rocket):
        dx = rocket.x - self.x
        dy = rocket.y - self.y

        if self.name != "Saturn":
            return math.hypot(dx, dy) <= self.radius + rocket.radius()

        # Saturn: collision with its ring ellipse or the planet body.
        c = math.cos(-self.rotation)
        s = math.sin(-self.rotation)
        lx = dx * c - dy * s
        ly = dx * s + dy * c

        outer = (lx / self.ring_outer) ** 2 + (ly / (self.ring_outer * 0.35)) ** 2
        inner = (lx / self.ring_inner) ** 2 + (ly / (self.ring_inner * 0.35)) ** 2
        ring_hit = outer <= 1.0 and inner >= 1.0
        planet_hit = math.hypot(dx, dy) <= self.radius + rocket.radius()
        return ring_hit or planet_hit

    def draw_glow(self, color):
        for extra, alpha in [(15, 10), (9, 18)]:
            r = self.radius + extra
            s = pygame.Surface((2 * r, 2 * r), pygame.SRCALPHA)
            pygame.draw.circle(s, (*color, alpha), (r, r), r)
            SCREEN.blit(s, (int(self.x - r), int(self.y - r)))

    def draw_banded_sphere(self, base_color, band_colors, band_spacing=14, band_width=6):
        cx = int(self.x)
        cy = int(self.y)
        r = int(self.radius)

        pygame.draw.circle(SCREEN, base_color, (cx, cy), r)

        for i, local_y in enumerate(range(-r + band_spacing, r, band_spacing * 2)):
            points = []
            for local_x in range(-r, r + 1, 3):
                curved_y = local_y + 0.035 * (local_x * local_x) / max(1, r)
                if abs(curved_y) <= r - 1:
                    x_limit = math.sqrt(max(0, r * r - curved_y * curved_y))
                    if abs(local_x) <= x_limit:
                        points.append((cx + local_x, cy + int(curved_y)))

            if len(points) > 1:
                pygame.draw.lines(
                    SCREEN,
                    band_colors[i % len(band_colors)],
                    False,
                    points,
                    band_width,
                )

    def draw(self):
        if self.name == "Venus":
            self.draw_venus()
        elif self.name == "Mercury":
            self.draw_mercury()
        elif self.name == "Jupiter":
            self.draw_jupiter()
        elif self.name == "Saturn":
            self.draw_saturn()
        elif self.name == "Earth":
            self.draw_earth()
        else:
            self.draw_neptune()

    def draw_venus(self):
        self.draw_glow((240, 165, 75))
        self.draw_banded_sphere(
            (220, 150, 75),
            [(248, 195, 110), (205, 135, 70), (235, 175, 88)],
            band_spacing=15,
            band_width=6,
        )

    def draw_mercury(self):
        self.draw_glow((185, 185, 190))
        pygame.draw.circle(SCREEN, (145, 145, 155), (int(self.x), int(self.y)), self.radius)
        for i in range(8):
            a = i * 2.4
            rr = self.radius * 0.55
            cx = self.x + math.cos(a) * rr
            cy = self.y + math.sin(a) * rr
            pygame.draw.circle(SCREEN, (95, 95, 105), (int(cx), int(cy)), 4)

    def draw_jupiter(self):
        self.draw_glow((210, 155, 95))
        self.draw_banded_sphere(
            (195, 145, 100),
            [(232, 192, 142), (165, 115, 85), (238, 200, 155), (175, 122, 92)],
            band_spacing=13,
            band_width=7,
        )

        pygame.draw.ellipse(
            SCREEN,
            (180, 75, 60),
            pygame.Rect(
                int(self.x - self.radius * 0.40),
                int(self.y + self.radius * 0.18),
                int(self.radius * 0.48),
                int(self.radius * 0.24),
            ),
        )

    def draw_saturn(self):
        size = int(self.ring_outer * 2 + 30)
        ring = pygame.Surface((size, size), pygame.SRCALPHA)
        c = size // 2
        for rr in range(int(self.ring_outer), int(self.ring_inner), -5):
            pygame.draw.ellipse(
                ring, (130, 220, 250, 125),
                (c - rr, int(c - rr * 0.35), rr * 2, int(rr * 0.70)), 3
            )
        ring = pygame.transform.rotate(ring, math.degrees(self.rotation))
        SCREEN.blit(ring, ring.get_rect(center=(int(self.x), int(self.y))))

        pygame.draw.circle(SCREEN, (105, 185, 205), (int(self.x), int(self.y)), self.radius)
        pygame.draw.circle(SCREEN, (175, 230, 235),
                           (int(self.x - 12), int(self.y - 12)), int(self.radius * 0.65), 4)

    def draw_earth(self):
        self.draw_glow((65, 155, 255))
        pygame.draw.circle(SCREEN, (35, 100, 215), (int(self.x), int(self.y)), self.radius)
        pygame.draw.ellipse(SCREEN, (55, 185, 100),
                            pygame.Rect(int(self.x - 29), int(self.y - 20), 32, 26))
        pygame.draw.ellipse(SCREEN, (50, 180, 95),
                            pygame.Rect(int(self.x + 7), int(self.y + 2), 25, 28))
        pygame.draw.circle(SCREEN, (130, 225, 255),
                           (int(self.x), int(self.y)), self.radius, 3)

    def draw_neptune(self):
        self.draw_glow((55, 120, 250))
        self.draw_banded_sphere(
            (45, 85, 205),
            [(80, 140, 240), (35, 75, 190), (92, 150, 245)],
            band_spacing=15,
            band_width=6,
        )


class CollisionEffect:
    def __init__(self, planet, rocket):
        self.planet = planet
        self.rocket = rocket
        self.name = planet.name
        self.timer = 0.0
        self.duration = 1.8 if self.name != "Venus" else 1.4
        self.start_x = rocket.x
        self.start_y = rocket.y
        self.angle = random.uniform(0, math.tau)
        self.burst_done = False

    def update(self, dt, particles):
        self.timer += dt
        t = clamp(self.timer / self.duration, 0, 1)

        if self.name == "Venus":
            self.rocket.x = self.start_x + 75 * math.sin(t * math.pi)
            self.rocket.y = self.start_y - 80 * math.sin(t * math.pi)
            self.rocket.angle = -35 * math.sin(t * math.pi)

        elif self.name == "Mercury":
            if not self.burst_done:
                self.burst_done = True
                for _ in range(90):
                    particles.append(Particle(
                        self.rocket.x, self.rocket.y,
                        random.choice([WHITE, CYAN, BLUE, ORANGE]),
                        360, 1.3
                    ))
            if self.timer > 0.18:
                self.rocket.visible = False

        elif self.name == "Jupiter":
            self.rocket.x = self.start_x + (self.planet.x - self.start_x) * t
            self.rocket.y = self.start_y + (self.planet.y - self.start_y) * t
            self.rocket.scale = max(0.05, 1.0 - t)

        elif self.name == "Saturn":
            self.angle += dt * 8.5
            radius = 125 * (1 - t) + 18
            self.rocket.x = self.planet.x + math.cos(self.angle) * radius
            self.rocket.y = self.planet.y + math.sin(self.angle) * radius * 0.35
            self.rocket.scale = max(0.18, 1.0 - 0.72 * t)

        elif self.name in ("Earth", "Neptune"):
            self.rocket.y += 120 * dt
            self.rocket.angle += 330 * dt
            if not self.burst_done:
                self.burst_done = True
                colors = ([BLUE, WHITE, CYAN] if self.name == "Neptune"
                          else [RED, ORANGE, WHITE])
                for _ in range(70):
                    particles.append(Particle(
                        self.rocket.x, self.rocket.y,
                        random.choice(colors), 320, 1.2
                    ))
            if t > 0.5:
                self.rocket.visible = False

        return self.timer < self.duration


class Game:
    def __init__(self):
        self.stars = [Star() for _ in range(220)]
        self.particles = []
        self.rocket = Rocket()
        self.planets = []

        self.score = 0
        self.best = 0
        self.game_over = False
        self.effect = None
        self.reason = ""
        self.reason_color = WHITE

        self.type_sequence = make_planet_sequence(240)
        self.type_index = 0
        self.previous_lane = random.choice(["upper", "lower"])
        self.next_x = WIDTH + 320

        for _ in range(13):
            self.spawn_planet()

    def next_planet_type(self):
        if self.type_index >= len(self.type_sequence):
            self.type_sequence = make_planet_sequence(
                240,
                self.type_sequence[-1],
            )
            self.type_index = 0

        name = self.type_sequence[self.type_index]
        self.type_index += 1
        return name

    def choose_lane_and_gap(self):
        lane = random.choice(["upper", "lower"])
        gap_time = SAME_LANE_TIME if lane == self.previous_lane else CROSS_LANE_TIME
        return lane, gap_time

    def choose_y(self, name, lane, x):
        obstacle_r = planet_envelope_radius(name)

        if lane == "upper":
            low = int(PLAY_TOP + obstacle_r + 12)
            high = int(HEIGHT * 0.44 - obstacle_r)
        else:
            low = int(HEIGHT * 0.56 + obstacle_r)
            high = int(PLAY_BOTTOM - obstacle_r - 12)

        if high <= low:
            return (low + high) / 2

        for _ in range(1000):
            y = random.uniform(low, high)
            valid = True

            for p in self.planets:
                required = obstacle_r + p.obstacle_radius + SAFE_SEPARATION
                if math.hypot(x - p.x, y - p.y) < required:
                    valid = False
                    break

            if valid:
                return y

        return random.uniform(low, high)

    def spawn_planet(self):
        name = self.next_planet_type()
        lane, gap_time = self.choose_lane_and_gap()
        x = self.next_x
        y = self.choose_y(name, lane, x)

        self.planets.append(Planet(name, x, y, lane))

        self.next_x += WORLD_SPEED * gap_time
        self.previous_lane = lane

    def reset(self):
        self.best = max(self.best, self.score)
        self.score = 0
        self.game_over = False
        self.effect = None
        self.reason = ""
        self.reason_color = WHITE

        self.particles.clear()
        self.planets.clear()
        self.rocket.reset()

        self.type_sequence = make_planet_sequence(240)
        self.type_index = 0

        self.previous_lane = random.choice(["upper", "lower"])
        self.next_x = WIDTH + 320

        for _ in range(13):
            self.spawn_planet()

    def trigger_collision(self, planet):
        self.effect = CollisionEffect(planet, self.rocket)

        reasons = {
            "Venus": ("VENUS - STRIKE & BOUNCE", ORANGE),
            "Mercury": ("MERCURY - ROCKET BURST", RED),
            "Jupiter": ("JUPITER - LOST INTO SURFACE", ORANGE),
            "Saturn": ("SATURN - RING SPIRAL", CYAN),
            "Earth": ("EARTH - CRASH", RED),
            "Neptune": ("NEPTUNE - CRASH", BLUE),
        }
        self.reason, self.reason_color = reasons[planet.name]

    def update(self, dt):
        for star in self.stars:
            star.update(dt)

        self.particles = [p for p in self.particles if p.update(dt)]

        if self.effect is not None:
            if not self.effect.update(dt, self.particles):
                self.game_over = True
                self.rocket.visible = False
                self.rocket.scale = 1.0
            return

        if self.game_over:
            return

        mouse_y = pygame.mouse.get_pos()[1]
        self.rocket.update(mouse_y, dt)

        for p in self.planets:
            p.update(dt)

        self.next_x -= WORLD_SPEED * dt

        for p in self.planets:
            if not p.passed and p.x + p.obstacle_radius < self.rocket.x:
                p.passed = True
                self.score += 1

        for p in self.planets:
            if p.collides(self.rocket):
                self.trigger_collision(p)
                return

        self.rocket.y = clamp(
            self.rocket.y,
            PLAY_TOP + self.rocket.radius(),
            PLAY_BOTTOM - self.rocket.radius(),
        )

        self.planets = [p for p in self.planets if p.x > -220]

        while self.next_x < WIDTH + WORLD_SPEED * CROSS_LANE_TIME * 5:
            self.spawn_planet()

    def draw_background(self):
        SCREEN.fill(DARK_SPACE)

        nebula = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        pygame.draw.circle(nebula, (50, 25, 120, 24), (160, 160), 190)
        pygame.draw.circle(nebula, (20, 60, 150, 20), (850, 490), 220)
        pygame.draw.circle(nebula, (100, 20, 120, 16), (540, 350), 270)
        SCREEN.blit(nebula, (0, 0))

        for star in self.stars:
            star.draw()

    def draw_hud(self):
        score = FONT.render(f"SCORE  {self.score:03d}", True, WHITE)
        SCREEN.blit(score, (25, 18))

        best = SMALL_FONT.render(
            f"BEST  {max(self.best, self.score):03d}",
            True,
            (160, 205, 230),
        )
        SCREEN.blit(best, (27, 48))

        info = SMALL_FONT.render(
            "MOUSE = ALTITUDE   SPACE/CLICK = BOOST   R = RESTART   ESC = QUIT",
            True,
            (130, 180, 210),
        )
        SCREEN.blit(
            info,
            (WIDTH // 2 - info.get_width() // 2, HEIGHT - 25),
        )

        travel = SMALL_FONT.render(
            "TOP <-> BOTTOM = 4.0 s",
            True,
            (110, 180, 220),
        )
        SCREEN.blit(
            travel,
            (WIDTH - travel.get_width() - 20, 24),
        )

        spacing = SMALL_FONT.render(
            "SAME SIDE >= 1.0 s | OTHER SIDE >= 2.5 s",
            True,
            (110, 180, 220),
        )
        SCREEN.blit(
            spacing,
            (WIDTH - spacing.get_width() - 20, 44),
        )

        random_text = SMALL_FONT.render(
            "LANE ORDER = RANDOM",
            True,
            (110, 180, 220),
        )
        SCREEN.blit(
            random_text,
            (WIDTH - random_text.get_width() - 20, 64),
        )

    def draw_game_over(self):
        overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        overlay.fill((0, 0, 15, 155))
        SCREEN.blit(overlay, (0, 0))

        title = BIG_FONT.render("GAME OVER", True, WHITE)
        reason = FONT.render(self.reason, True, self.reason_color)
        restart = FONT.render("Press R to launch again", True, WHITE)

        SCREEN.blit(
            title,
            (WIDTH // 2 - title.get_width() // 2, HEIGHT // 2 - 95),
        )
        SCREEN.blit(
            reason,
            (WIDTH // 2 - reason.get_width() // 2, HEIGHT // 2 - 25),
        )
        SCREEN.blit(
            restart,
            (WIDTH // 2 - restart.get_width() // 2, HEIGHT // 2 + 35),
        )

    def draw(self):
        self.draw_background()

        for p in self.planets:
            p.draw()

        for p in self.particles:
            p.draw()

        self.rocket.draw()
        self.draw_hud()

        if self.game_over:
            self.draw_game_over()

        pygame.display.flip()


def main():
    game = Game()
    running = True

    while running:
        dt = min(CLOCK.tick(FPS) / 1000.0, 0.033)

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                elif event.key == pygame.K_r and game.game_over:
                    game.reset()

            elif event.type == pygame.MOUSEBUTTONDOWN:
                if event.button == 1 and game.effect is None and not game.game_over:
                    game.rocket.y -= 35

        keys = pygame.key.get_pressed()
        mouse = pygame.mouse.get_pressed()

        if (
            game.effect is None
            and not game.game_over
            and (keys[pygame.K_SPACE] or mouse[0])
        ):
            game.rocket.y -= 110.0 * dt

        game.update(dt)
        game.draw()

    pygame.quit()


if __name__ == "__main__":
    main()