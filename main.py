#!/usr/bin/env python3
"""Sky Slingers (fan game)
Original physics-puzzle game inspired by slingshot bird games.

Controls:
- Hold LMB on the bird to drag.
- Release LMB to launch.
- R to restart level.
- N to next level (when all targets are defeated).
- ESC to quit.
"""

from __future__ import annotations

import array
import math
import random
from dataclasses import dataclass
from typing import List, Optional, Tuple

import pygame

WIDTH, HEIGHT = 1280, 720
FPS = 60
GRAVITY = 1400.0
GROUND_Y = 630
SLING_X = 210
SLING_Y = 520


@dataclass
class Body:
    x: float
    y: float
    w: float
    h: float
    vx: float = 0.0
    vy: float = 0.0
    mass: float = 1.0
    hp: float = 100.0
    is_target: bool = False
    color: Tuple[int, int, int] = (180, 180, 180)

    @property
    def rect(self) -> pygame.Rect:
        return pygame.Rect(int(self.x - self.w / 2), int(self.y - self.h / 2), int(self.w), int(self.h))


class AudioBank:
    def __init__(self):
        self.rate = 22050
        self.launch = self._tone(320, 0.12, "triangle", 0.35)
        self.hit = self._tone(160, 0.10, "noise", 0.50)
        self.breaking = self._tone(90, 0.15, "square", 0.35)
        self.win = self._chord((392, 494, 587), 0.22)

    def _tone(self, freq: float, duration: float, kind: str, volume: float) -> pygame.mixer.Sound:
        n = int(self.rate * duration)
        data = array.array("h")
        rnd = random.Random(7)
        for i in range(n):
            t = i / self.rate
            env = max(0.0, 1.0 - i / n)
            if kind == "triangle":
                p = (t * freq) % 1.0
                v = 4 * abs(p - 0.5) - 1
            elif kind == "square":
                v = 1.0 if math.sin(2 * math.pi * freq * t) > 0 else -1.0
            elif kind == "noise":
                v = rnd.uniform(-1.0, 1.0)
            else:
                v = math.sin(2 * math.pi * freq * t)
            data.append(int(32767 * v * env * volume))
        return pygame.mixer.Sound(buffer=data.tobytes())

    def _chord(self, freqs: Tuple[float, ...], duration: float) -> pygame.mixer.Sound:
        n = int(self.rate * duration)
        data = array.array("h")
        for i in range(n):
            t = i / self.rate
            env = max(0.0, 1.0 - i / n)
            v = sum(math.sin(2 * math.pi * f * t) for f in freqs) / len(freqs)
            data.append(int(32767 * v * env * 0.30))
        return pygame.mixer.Sound(buffer=data.tobytes())


class Game:
    def __init__(self) -> None:
        pygame.init()
        pygame.mixer.init(frequency=22050, size=-16, channels=1)
        self.screen = pygame.display.set_mode((WIDTH, HEIGHT))
        pygame.display.set_caption("Sky Slingers — original fan game")
        self.clock = pygame.time.Clock()
        self.font = pygame.font.SysFont("consolas", 24)
        self.big = pygame.font.SysFont("consolas", 52, bold=True)

        self.audio = AudioBank()

        self.level_idx = 0
        self.levels = [self._level_1, self._level_2, self._level_3]

        self.blocks: List[Body] = []
        self.targets: List[Body] = []
        self.projectile: Optional[Body] = None
        self.trail: List[Tuple[float, float]] = []

        self.dragging = False
        self.shot_fired = False
        self.max_pull = 130.0
        self.running = True

        self.reset_level()

    def _spawn_projectile(self) -> Body:
        return Body(SLING_X, SLING_Y, 34, 34, mass=0.8, hp=999, color=(210, 75, 62))

    def _make_block(self, x: float, y: float, w: float, h: float, hp: float = 80) -> Body:
        return Body(x, y, w, h, mass=max(0.5, w * h / 2800), hp=hp, color=(182, 145, 96))

    def _make_target(self, x: float, y: float) -> Body:
        return Body(x, y, 36, 36, mass=0.9, hp=55, is_target=True, color=(90, 188, 90))

    def _level_1(self) -> None:
        self.blocks += [
            self._make_block(920, 595, 170, 22),
            self._make_block(890, 548, 24, 72),
            self._make_block(950, 548, 24, 72),
            self._make_block(920, 502, 100, 20),
        ]
        self.targets += [self._make_target(920, 560)]

    def _level_2(self) -> None:
        self.blocks += [
            self._make_block(900, 595, 190, 22),
            self._make_block(980, 595, 190, 22),
            self._make_block(860, 548, 20, 72),
            self._make_block(940, 548, 20, 72),
            self._make_block(1020, 548, 20, 72),
            self._make_block(900, 503, 100, 18),
            self._make_block(980, 503, 100, 18),
        ]
        self.targets += [self._make_target(900, 565), self._make_target(980, 565)]

    def _level_3(self) -> None:
        self.blocks += [
            self._make_block(880, 598, 260, 18),
            self._make_block(1020, 598, 260, 18),
            self._make_block(840, 552, 22, 82),
            self._make_block(920, 552, 22, 82),
            self._make_block(980, 552, 22, 82),
            self._make_block(1060, 552, 22, 82),
            self._make_block(880, 502, 112, 18),
            self._make_block(1020, 502, 112, 18),
            self._make_block(950, 458, 170, 18),
        ]
        self.targets += [self._make_target(880, 565), self._make_target(1020, 565), self._make_target(950, 520)]

    def reset_level(self) -> None:
        self.blocks.clear()
        self.targets.clear()
        self.projectile = self._spawn_projectile()
        self.trail.clear()
        self.dragging = False
        self.shot_fired = False
        self.levels[self.level_idx]()

    def _aabb_resolve(self, a: Body, b: Body) -> None:
        ra, rb = a.rect, b.rect
        if not ra.colliderect(rb):
            return

        dx = (a.x - b.x)
        dy = (a.y - b.y)
        overlap_x = (a.w + b.w) / 2 - abs(dx)
        overlap_y = (a.h + b.h) / 2 - abs(dy)

        if overlap_x < overlap_y:
            push = overlap_x if dx > 0 else -overlap_x
            a.x += push
            a.vx *= -0.38
            b.vx *= 0.86
            impulse = abs(a.vx) * a.mass
            b.hp -= impulse * 0.25
        else:
            push = overlap_y if dy > 0 else -overlap_y
            a.y += push
            if dy > 0:
                a.vy = max(0.0, a.vy * -0.28)
            else:
                a.vy = min(0.0, a.vy * -0.28)
            impulse = abs(a.vy) * a.mass
            b.hp -= impulse * 0.20

    def _update_body(self, body: Body, dt: float) -> None:
        body.vy += GRAVITY * dt
        body.x += body.vx * dt
        body.y += body.vy * dt

        if body.y + body.h / 2 >= GROUND_Y:
            body.y = GROUND_Y - body.h / 2
            body.vy *= -0.30
            body.vx *= 0.97

        body.vx *= 0.996
        if abs(body.vx) < 0.05:
            body.vx = 0.0
        if abs(body.vy) < 0.05:
            body.vy = 0.0

    def _launch_projectile(self) -> None:
        if not self.projectile:
            return
        dx = SLING_X - self.projectile.x
        dy = SLING_Y - self.projectile.y
        power = math.hypot(dx, dy)
        scale = 6.8
        self.projectile.vx = dx * scale
        self.projectile.vy = dy * scale
        self.shot_fired = True
        self.audio.launch.play()

    def _draw_pixel_ground(self) -> None:
        self.screen.fill((167, 213, 255))
        pygame.draw.rect(self.screen, (86, 156, 88), (0, GROUND_Y, WIDTH, HEIGHT - GROUND_Y))
        for x in range(0, WIDTH, 8):
            noise = (x * 13) % 21
            c = (76 + noise, 138 + noise // 2, 76)
            pygame.draw.rect(self.screen, c, (x, GROUND_Y + 8, 8, HEIGHT - GROUND_Y))

    def _draw_sling(self) -> None:
        if not self.projectile:
            return
        px, py = int(self.projectile.x), int(self.projectile.y)
        pygame.draw.line(self.screen, (92, 58, 40), (SLING_X - 18, SLING_Y + 55), (SLING_X - 5, SLING_Y - 40), 10)
        pygame.draw.line(self.screen, (92, 58, 40), (SLING_X + 18, SLING_Y + 55), (SLING_X + 5, SLING_Y - 40), 10)
        pygame.draw.line(self.screen, (40, 30, 26), (SLING_X - 10, SLING_Y - 15), (px, py), 4)
        pygame.draw.line(self.screen, (40, 30, 26), (SLING_X + 10, SLING_Y - 15), (px, py), 4)

    def _draw_body(self, body: Body) -> None:
        r = body.rect
        color = body.color
        if body.is_target:
            pygame.draw.ellipse(self.screen, color, r)
            pygame.draw.ellipse(self.screen, (255, 255, 255), (r.x + 9, r.y + 9, 6, 6))
            pygame.draw.circle(self.screen, (0, 0, 0), (r.x + 13, r.y + 12), 2)
        else:
            pygame.draw.rect(self.screen, color, r, border_radius=3)
            # pixel pattern
            for y in range(r.top + 2, r.bottom, 6):
                pygame.draw.line(self.screen, (160, 122, 78), (r.left + 2, y), (r.right - 2, y), 1)

    def _handle_input(self) -> None:
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                self.running = False
            elif ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_ESCAPE:
                    self.running = False
                elif ev.key == pygame.K_r:
                    self.reset_level()
                elif ev.key == pygame.K_n and not self.targets:
                    self.level_idx = (self.level_idx + 1) % len(self.levels)
                    self.reset_level()
            elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                if self.projectile and self.projectile.rect.collidepoint(ev.pos) and not self.shot_fired:
                    self.dragging = True
            elif ev.type == pygame.MOUSEBUTTONUP and ev.button == 1:
                if self.dragging:
                    self.dragging = False
                    self._launch_projectile()

        if self.dragging and self.projectile:
            mx, my = pygame.mouse.get_pos()
            dx = mx - SLING_X
            dy = my - SLING_Y
            d = math.hypot(dx, dy)
            if d > self.max_pull:
                scale = self.max_pull / d
                dx *= scale
                dy *= scale
            self.projectile.x = SLING_X + dx
            self.projectile.y = SLING_Y + dy

    def _simulate(self, dt: float) -> None:
        if self.projectile:
            self._update_body(self.projectile, dt)
            self.trail.append((self.projectile.x, self.projectile.y))
            if len(self.trail) > 35:
                self.trail.pop(0)

            for b in self.blocks + self.targets:
                self._aabb_resolve(self.projectile, b)

            if abs(self.projectile.vx) + abs(self.projectile.vy) > 40:
                for t in self.targets:
                    if self.projectile.rect.colliderect(t.rect):
                        t.hp -= 45
                        self.audio.hit.play()

        for body in self.blocks + self.targets:
            self._update_body(body, dt)

        # stacked collisions for structures
        solids = self.blocks + self.targets
        for i in range(len(solids)):
            for j in range(i + 1, len(solids)):
                a, b = solids[i], solids[j]
                if a.rect.colliderect(b.rect):
                    if a.y < b.y:
                        a.y -= 1.2
                        b.y += 1.2
                    else:
                        a.y += 1.2
                        b.y -= 1.2
                    a.vy *= 0.8
                    b.vy *= 0.8

        before = len(self.blocks) + len(self.targets)
        self.blocks = [b for b in self.blocks if b.hp > 0 and b.y < HEIGHT + 120]
        self.targets = [t for t in self.targets if t.hp > 0 and t.y < HEIGHT + 120]
        after = len(self.blocks) + len(self.targets)
        if after < before:
            self.audio.breaking.play()

        if self.projectile and (self.projectile.x > WIDTH + 120 or self.projectile.y > HEIGHT + 120):
            self.projectile = None

        if self.shot_fired and not self.projectile:
            self.projectile = self._spawn_projectile()
            self.shot_fired = False
            self.trail.clear()

    def _render(self) -> None:
        self._draw_pixel_ground()

        for i, (x, y) in enumerate(self.trail):
            alpha = int(255 * (i + 1) / len(self.trail))
            surf = pygame.Surface((8, 8), pygame.SRCALPHA)
            pygame.draw.circle(surf, (250, 250, 250, alpha // 2), (4, 4), 3)
            self.screen.blit(surf, (x - 4, y - 4))

        for b in self.blocks:
            self._draw_body(b)
        for t in self.targets:
            self._draw_body(t)

        self._draw_sling()
        if self.projectile:
            pygame.draw.circle(self.screen, self.projectile.color, (int(self.projectile.x), int(self.projectile.y)), 18)
            pygame.draw.circle(self.screen, (255, 230, 220), (int(self.projectile.x - 6), int(self.projectile.y - 5)), 4)

        panel = pygame.Surface((WIDTH, 56), pygame.SRCALPHA)
        panel.fill((0, 0, 0, 120))
        self.screen.blit(panel, (0, 0))

        info = f"Level {self.level_idx + 1}/{len(self.levels)}   Targets left: {len(self.targets)}   [R] Restart"
        self.screen.blit(self.font.render(info, True, (255, 255, 255)), (16, 16))

        if not self.targets:
            self.screen.blit(self.big.render("LEVEL CLEARED!", True, (255, 240, 120)), (WIDTH // 2 - 215, 80))
            self.screen.blit(self.font.render("Press N for next level", True, (255, 255, 255)), (WIDTH // 2 - 128, 142))

        pygame.display.flip()

    def run(self) -> None:
        won_last_state = False
        while self.running:
            dt = self.clock.tick(FPS) / 1000.0
            self._handle_input()
            self._simulate(dt)
            self._render()

            won_now = not self.targets
            if won_now and not won_last_state:
                self.audio.win.play()
            won_last_state = won_now

        pygame.quit()


if __name__ == "__main__":
    Game().run()
