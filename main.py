#!/usr/bin/env python3
"""BlockCraft Classic (fan game)
A small Minecraft Classic-inspired sandbox written in Python.

Controls:
- WASD: move
- Mouse: look
- LMB: remove block
- RMB: place block
- 1..7: choose block type
- Space: jump
- Esc: release mouse / quit
"""

from __future__ import annotations

import math
import os
import random
import struct
import wave
from dataclasses import dataclass
from typing import Dict, Iterable, Optional, Tuple

import pygame
from OpenGL.GL import (
    GL_COLOR_BUFFER_BIT,
    GL_CULL_FACE,
    GL_DEPTH_BUFFER_BIT,
    GL_DEPTH_TEST,
    GL_LINEAR,
    GL_MODELVIEW,
    GL_NEAREST,
    GL_PROJECTION,
    GL_QUADS,
    GL_RGBA,
    GL_TEXTURE_2D,
    GL_TEXTURE_MAG_FILTER,
    GL_TEXTURE_MIN_FILTER,
    GL_UNSIGNED_BYTE,
    glBegin,
    glBindTexture,
    glClear,
    glColor3f,
    glDisable,
    glEnable,
    glEnd,
    glGenTextures,
    glLoadIdentity,
    glMatrixMode,
    glNormal3f,
    glTexCoord2f,
    glTexImage2D,
    glTexParameteri,
    glTranslatef,
    glVertex3f,
)
from OpenGL.GLU import gluPerspective

Vec3i = Tuple[int, int, int]

WORLD_W = 64
WORLD_D = 64
WORLD_H = 32

BLOCK_AIR = 0
BLOCK_GRASS = 1
BLOCK_DIRT = 2
BLOCK_STONE = 3
BLOCK_WOOD = 4
BLOCK_LEAVES = 5
BLOCK_SAND = 6
BLOCK_BRICK = 7

BLOCK_COLORS = {
    BLOCK_GRASS: (92, 161, 71),
    BLOCK_DIRT: (124, 84, 52),
    BLOCK_STONE: (127, 127, 133),
    BLOCK_WOOD: (152, 118, 74),
    BLOCK_LEAVES: (72, 136, 64),
    BLOCK_SAND: (196, 182, 122),
    BLOCK_BRICK: (168, 70, 60),
}

FACE_VERTS = {
    "top": ((0, 1, 0), (1, 1, 0), (1, 1, 1), (0, 1, 1)),
    "bottom": ((0, 0, 1), (1, 0, 1), (1, 0, 0), (0, 0, 0)),
    "left": ((0, 0, 0), (0, 0, 1), (0, 1, 1), (0, 1, 0)),
    "right": ((1, 0, 1), (1, 0, 0), (1, 1, 0), (1, 1, 1)),
    "front": ((1, 0, 0), (0, 0, 0), (0, 1, 0), (1, 1, 0)),
    "back": ((0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)),
}

FACE_NORMALS = {
    "top": (0, 1, 0),
    "bottom": (0, -1, 0),
    "left": (-1, 0, 0),
    "right": (1, 0, 0),
    "front": (0, 0, -1),
    "back": (0, 0, 1),
}

FACE_NEIGHBOR = {
    "top": (0, 1, 0),
    "bottom": (0, -1, 0),
    "left": (-1, 0, 0),
    "right": (1, 0, 0),
    "front": (0, 0, -1),
    "back": (0, 0, 1),
}


@dataclass
class Player:
    x: float = WORLD_W / 2
    y: float = 20.0
    z: float = WORLD_D / 2
    yaw: float = 0.0
    pitch: float = 0.0
    vy: float = 0.0
    speed: float = 7.0
    on_ground: bool = False


class World:
    def __init__(self, seed: int = 2009):
        self.seed = seed
        self.rng = random.Random(seed)
        self.blocks: Dict[Vec3i, int] = {}
        self._generate()

    def _height(self, x: int, z: int) -> int:
        value = (
            11
            + 4 * math.sin(x * 0.17)
            + 3 * math.cos(z * 0.21)
            + 2 * math.sin((x + z) * 0.11)
        )
        return max(4, min(WORLD_H - 4, int(value)))

    def _generate(self) -> None:
        waterline = 9
        for x in range(WORLD_W):
            for z in range(WORLD_D):
                h = self._height(x, z)
                top_block = BLOCK_GRASS if h > waterline else BLOCK_SAND
                for y in range(h):
                    if y == h - 1:
                        block = top_block
                    elif y > h - 5:
                        block = BLOCK_DIRT if h > waterline else BLOCK_SAND
                    else:
                        block = BLOCK_STONE
                    self.blocks[(x, y, z)] = block

                if h > waterline + 2 and self.rng.random() < 0.06:
                    self._spawn_tree(x, h, z)

    def _spawn_tree(self, x: int, y: int, z: int) -> None:
        if x < 2 or z < 2 or x > WORLD_W - 3 or z > WORLD_D - 3:
            return
        trunk_h = self.rng.randint(3, 5)
        for i in range(trunk_h):
            self.blocks[(x, y + i, z)] = BLOCK_WOOD
        top = y + trunk_h
        for lx in range(x - 2, x + 3):
            for lz in range(z - 2, z + 3):
                for ly in range(top - 2, top + 2):
                    if (lx - x) ** 2 + (lz - z) ** 2 + (ly - top) ** 2 <= 7:
                        self.blocks[(lx, ly, lz)] = BLOCK_LEAVES

    def get(self, pos: Vec3i) -> int:
        return self.blocks.get(pos, BLOCK_AIR)

    def set(self, pos: Vec3i, block: int) -> None:
        x, y, z = pos
        if x < 0 or z < 0 or y < 0 or x >= WORLD_W or z >= WORLD_D or y >= WORLD_H:
            return
        if block == BLOCK_AIR:
            self.blocks.pop(pos, None)
        else:
            self.blocks[pos] = block

    def solid(self, x: float, y: float, z: float) -> bool:
        return self.get((int(math.floor(x)), int(math.floor(y)), int(math.floor(z)))) != BLOCK_AIR


class AudioBank:
    def __init__(self, folder: str = "assets/sfx"):
        self.folder = folder
        os.makedirs(folder, exist_ok=True)
        self.break_path = os.path.join(folder, "break.wav")
        self.place_path = os.path.join(folder, "place.wav")
        self._ensure()
        self.break_sound = pygame.mixer.Sound(self.break_path)
        self.place_sound = pygame.mixer.Sound(self.place_path)

    def _ensure(self) -> None:
        if not os.path.exists(self.break_path):
            self._write_tone(self.break_path, 180, 0.1, "noise")
        if not os.path.exists(self.place_path):
            self._write_tone(self.place_path, 320, 0.08, "square")

    def _write_tone(self, path: str, freq: float, duration: float, kind: str) -> None:
        sample_rate = 22050
        total = int(sample_rate * duration)
        rnd = random.Random(99)
        data = bytearray()

        for i in range(total):
            t = i / sample_rate
            env = max(0.0, 1.0 - (i / total) * 1.15)
            if kind == "square":
                base = 1.0 if math.sin(2 * math.pi * freq * t) >= 0 else -1.0
            elif kind == "noise":
                base = rnd.uniform(-1, 1) * (0.6 + 0.4 * math.sin(2 * math.pi * 36 * t))
            else:
                base = math.sin(2 * math.pi * freq * t)

            v = int(32767 * base * env * 0.35)
            data.extend(struct.pack("<h", v))

        with wave.open(path, "wb") as f:
            f.setnchannels(1)
            f.setsampwidth(2)
            f.setframerate(sample_rate)
            f.writeframes(bytes(data))


class Game:
    def __init__(self):
        pygame.init()
        pygame.mixer.init(frequency=22050, size=-16, channels=1)
        pygame.display.set_mode((1280, 720), pygame.OPENGL | pygame.DOUBLEBUF)
        pygame.display.set_caption("BlockCraft Classic 2009 (Fan)")

        glEnable(GL_DEPTH_TEST)
        glEnable(GL_CULL_FACE)
        glEnable(GL_TEXTURE_2D)

        glMatrixMode(GL_PROJECTION)
        gluPerspective(75, 1280 / 720, 0.05, 200.0)
        glMatrixMode(GL_MODELVIEW)

        self.clock = pygame.time.Clock()
        self.world = World()
        self.player = Player()
        self.selected_block = BLOCK_GRASS
        self.font = pygame.font.SysFont("consolas", 20)
        self.sfx = AudioBank()

        self.textures = self._create_textures()
        self.running = True

        pygame.event.set_grab(True)
        pygame.mouse.set_visible(False)

    def _create_textures(self) -> Dict[int, int]:
        textures: Dict[int, int] = {}
        for block, color in BLOCK_COLORS.items():
            surface = pygame.Surface((16, 16))
            r, g, b = color
            for y in range(16):
                for x in range(16):
                    noise = ((x * 13 + y * 19 + block * 7) % 23) - 11
                    px = (
                        max(0, min(255, r + noise)),
                        max(0, min(255, g + noise)),
                        max(0, min(255, b + noise)),
                    )
                    surface.set_at((x, y), px)

            if block == BLOCK_BRICK:
                for y in range(0, 16, 4):
                    pygame.draw.line(surface, (80, 35, 30), (0, y), (15, y))
                for y in range(2, 16, 4):
                    pygame.draw.line(surface, (80, 35, 30), (8, y), (8, y + 2))

            tex = glGenTextures(1)
            glBindTexture(GL_TEXTURE_2D, tex)
            data = pygame.image.tostring(surface, "RGBA", True)
            glTexImage2D(
                GL_TEXTURE_2D,
                0,
                GL_RGBA,
                16,
                16,
                0,
                GL_RGBA,
                GL_UNSIGNED_BYTE,
                data,
            )
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
            textures[block] = tex
        return textures

    def _raycast_block(self, max_dist: float = 8.0) -> Tuple[Optional[Vec3i], Optional[Vec3i]]:
        px, py, pz = self.player.x, self.player.y + 1.6, self.player.z
        pitch = math.radians(self.player.pitch)
        yaw = math.radians(self.player.yaw)
        dx = math.cos(pitch) * math.sin(yaw)
        dy = -math.sin(pitch)
        dz = -math.cos(pitch) * math.cos(yaw)

        last_air: Optional[Vec3i] = None
        step = 0.05
        t = 0.0
        while t <= max_dist:
            cx = px + dx * t
            cy = py + dy * t
            cz = pz + dz * t
            cell = (int(math.floor(cx)), int(math.floor(cy)), int(math.floor(cz)))
            if self.world.get(cell) != BLOCK_AIR:
                return cell, last_air
            last_air = cell
            t += step
        return None, last_air

    def _collides(self, x: float, y: float, z: float) -> bool:
        radius = 0.28
        for ox in (-radius, radius):
            for oz in (-radius, radius):
                for oy in (0.0, 0.9, 1.7):
                    if self.world.solid(x + ox, y + oy, z + oz):
                        return True
        return False

    def _move(self, dt: float, keys: Iterable[bool]) -> None:
        k = keys
        speed = self.player.speed * (1.6 if k[pygame.K_LSHIFT] else 1.0)
        yaw = math.radians(self.player.yaw)

        fwdx = math.sin(yaw)
        fwdz = -math.cos(yaw)
        rightx = math.sin(yaw + math.pi / 2)
        rightz = -math.cos(yaw + math.pi / 2)

        vx = vz = 0.0
        if k[pygame.K_w]:
            vx += fwdx
            vz += fwdz
        if k[pygame.K_s]:
            vx -= fwdx
            vz -= fwdz
        if k[pygame.K_a]:
            vx -= rightx
            vz -= rightz
        if k[pygame.K_d]:
            vx += rightx
            vz += rightz

        length = math.hypot(vx, vz)
        if length > 0:
            vx = vx / length * speed * dt
            vz = vz / length * speed * dt

        nx, nz = self.player.x + vx, self.player.z + vz
        if not self._collides(nx, self.player.y, self.player.z):
            self.player.x = nx
        if not self._collides(self.player.x, self.player.y, nz):
            self.player.z = nz

        self.player.vy -= 18.0 * dt
        ny = self.player.y + self.player.vy * dt
        if self._collides(self.player.x, ny, self.player.z):
            if self.player.vy < 0:
                self.player.on_ground = True
            self.player.vy = 0
        else:
            self.player.on_ground = False
            self.player.y = ny

        if self.player.y < 2:
            self.player.y = 20
            self.player.vy = 0

    def _draw_cube(self, x: int, y: int, z: int, block: int) -> None:
        glBindTexture(GL_TEXTURE_2D, self.textures[block])
        for face, verts in FACE_VERTS.items():
            nx, ny, nz = FACE_NEIGHBOR[face]
            if self.world.get((x + nx, y + ny, z + nz)) != BLOCK_AIR:
                continue

            glNormal3f(*FACE_NORMALS[face])
            glBegin(GL_QUADS)
            uv = ((0, 0), (1, 0), (1, 1), (0, 1))
            for (vx, vy, vz), (u, v) in zip(verts, uv):
                glTexCoord2f(u, v)
                glVertex3f(x + vx, y + vy, z + vz)
            glEnd()

    def _render_world(self) -> None:
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        glLoadIdentity()

        glRotatef(self.player.pitch, 1, 0, 0)
        glRotatef(self.player.yaw, 0, 1, 0)
        glTranslatef(-self.player.x, -self.player.y - 1.6, -self.player.z)

        px, py, pz = int(self.player.x), int(self.player.y), int(self.player.z)
        radius = 24
        for (x, y, z), block in self.world.blocks.items():
            if block == BLOCK_AIR:
                continue
            if abs(x - px) > radius or abs(y - py) > radius or abs(z - pz) > radius:
                continue
            self._draw_cube(x, y, z, block)

    def _draw_crosshair_and_hud(self) -> None:
        screen = pygame.display.get_surface()
        w, h = screen.get_size()

        overlay = pygame.Surface((w, h), pygame.SRCALPHA)
        pygame.draw.line(overlay, (255, 255, 255, 190), (w // 2 - 10, h // 2), (w // 2 + 10, h // 2), 2)
        pygame.draw.line(overlay, (255, 255, 255, 190), (w // 2, h // 2 - 10), (w // 2, h // 2 + 10), 2)

        text = f"BLOCK: {self.selected_block} | POS: ({self.player.x:.1f}, {self.player.y:.1f}, {self.player.z:.1f})"
        label = self.font.render(text, True, (236, 236, 236))
        overlay.blit(label, (14, h - 34))

        glDisable(GL_DEPTH_TEST)
        data = pygame.image.tostring(overlay, "RGBA", True)
        glRasterPos2f(-1, -1)
        glDrawPixels(w, h, GL_RGBA, GL_UNSIGNED_BYTE, data)
        glEnable(GL_DEPTH_TEST)

    def run(self) -> None:
        while self.running:
            dt = self.clock.tick(60) / 1000.0
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.running = False
                elif event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        self.running = False
                    elif event.key == pygame.K_SPACE and self.player.on_ground:
                        self.player.vy = 8.5
                    elif pygame.K_1 <= event.key <= pygame.K_7:
                        self.selected_block = (event.key - pygame.K_0)
                elif event.type == pygame.MOUSEMOTION:
                    dx, dy = event.rel
                    self.player.yaw += dx * 0.14
                    self.player.pitch = max(-89, min(89, self.player.pitch + dy * 0.14))
                elif event.type == pygame.MOUSEBUTTONDOWN:
                    block, target_air = self._raycast_block()
                    if event.button == 1 and block is not None:
                        self.world.set(block, BLOCK_AIR)
                        self.sfx.break_sound.play()
                    elif event.button == 3 and target_air is not None:
                        self.world.set(target_air, self.selected_block)
                        self.sfx.place_sound.play()

            self._move(dt, pygame.key.get_pressed())
            self._render_world()
            self._draw_crosshair_and_hud()
            pygame.display.flip()

        pygame.quit()


if __name__ == "__main__":
    Game().run()
