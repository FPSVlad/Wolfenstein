const canvas = document.getElementById('game');
const ctx = canvas.getContext('2d');
const statusLine = document.getElementById('status');

const map = [
  '1111111111111111',
  '1000000000000001',
  '1010110111111101',
  '1000100000100001',
  '1111101110101101',
  '1000101010000101',
  '1010101011110101',
  '1010001000010001',
  '1011111111011101',
  '1000000001000001',
  '1011110101110101',
  '1000010100000101',
  '1111010111111101',
  '1000000000000001',
  '1000000000000001',
  '1111111111111111'
];

const state = {
  x: 2.5,
  y: 2.5,
  angle: 0,
  fov: Math.PI / 3,
  speed: 2.2,
  rotSpeed: 2.2,
  mapVisible: true,
  keys: new Set(),
  lastTime: 0,
  shootFlash: 0,
  hp: 100,
  ammo: 30,
  kills: 0,
  points: [
    { x: 11.5, y: 3.5, alive: true },
    { x: 12.5, y: 10.5, alive: true },
    { x: 6.5, y: 8.5, alive: true },
    { x: 9.5, y: 13.5, alive: true }
  ]
};

const audioCtx = new (window.AudioContext || window.webkitAudioContext)();

function beep(freq, duration = 0.08, type = 'square', gainValue = 0.04) {
  const osc = audioCtx.createOscillator();
  const gain = audioCtx.createGain();
  osc.type = type;
  osc.frequency.value = freq;
  gain.gain.value = gainValue;
  osc.connect(gain);
  gain.connect(audioCtx.destination);
  osc.start();
  gain.gain.exponentialRampToValueAtTime(0.0001, audioCtx.currentTime + duration);
  osc.stop(audioCtx.currentTime + duration);
}

function isWall(x, y) {
  const mx = Math.floor(x);
  const my = Math.floor(y);
  if (mx < 0 || my < 0 || my >= map.length || mx >= map[0].length) return true;
  return map[my][mx] === '1';
}

function castRay(angle) {
  const rayDirX = Math.cos(angle);
  const rayDirY = Math.sin(angle);

  let mapX = Math.floor(state.x);
  let mapY = Math.floor(state.y);

  const deltaDistX = Math.abs(1 / (rayDirX || 0.00001));
  const deltaDistY = Math.abs(1 / (rayDirY || 0.00001));

  let sideDistX;
  let sideDistY;
  let stepX;
  let stepY;

  if (rayDirX < 0) {
    stepX = -1;
    sideDistX = (state.x - mapX) * deltaDistX;
  } else {
    stepX = 1;
    sideDistX = (mapX + 1 - state.x) * deltaDistX;
  }

  if (rayDirY < 0) {
    stepY = -1;
    sideDistY = (state.y - mapY) * deltaDistY;
  } else {
    stepY = 1;
    sideDistY = (mapY + 1 - state.y) * deltaDistY;
  }

  let hit = false;
  let side = 0;

  while (!hit) {
    if (sideDistX < sideDistY) {
      sideDistX += deltaDistX;
      mapX += stepX;
      side = 0;
    } else {
      sideDistY += deltaDistY;
      mapY += stepY;
      side = 1;
    }

    if (mapY < 0 || mapY >= map.length || mapX < 0 || mapX >= map[0].length || map[mapY][mapX] === '1') {
      hit = true;
    }
  }

  const distance = side === 0
    ? (mapX - state.x + (1 - stepX) / 2) / rayDirX
    : (mapY - state.y + (1 - stepY) / 2) / rayDirY;

  return { distance: Math.max(distance, 0.0001), side, mapX, mapY };
}

function drawSkyAndFloor() {
  const sky = ctx.createLinearGradient(0, 0, 0, canvas.height / 2);
  sky.addColorStop(0, '#232a4a');
  sky.addColorStop(1, '#394373');
  ctx.fillStyle = sky;
  ctx.fillRect(0, 0, canvas.width, canvas.height / 2);

  const floor = ctx.createLinearGradient(0, canvas.height / 2, 0, canvas.height);
  floor.addColorStop(0, '#2a2530');
  floor.addColorStop(1, '#120f18');
  ctx.fillStyle = floor;
  ctx.fillRect(0, canvas.height / 2, canvas.width, canvas.height / 2);
}

function drawWorld() {
  drawSkyAndFloor();

  for (let col = 0; col < canvas.width; col++) {
    const rayAngle = state.angle - state.fov / 2 + (col / canvas.width) * state.fov;
    const ray = castRay(rayAngle);
    const correctedDistance = ray.distance * Math.cos(rayAngle - state.angle);

    const wallHeight = Math.min(canvas.height, Math.floor(canvas.height / correctedDistance));
    const y = Math.floor((canvas.height - wallHeight) / 2);

    const shade = Math.max(20, 210 - correctedDistance * 26 - ray.side * 35);
    ctx.fillStyle = `rgb(${shade}, ${Math.floor(shade * 0.8)}, ${Math.floor(shade * 0.65)})`;
    ctx.fillRect(col, y, 1, wallHeight);

    // Полосы как имитация текстуры кирпича
    if (wallHeight > 12 && col % 4 === 0) {
      ctx.fillStyle = `rgba(20, 10, 5, ${Math.min(0.6, correctedDistance / 12)})`;
      ctx.fillRect(col, y + (wallHeight % 8), 1, wallHeight / 2);
    }
  }
}

function drawSprites() {
  const sprites = state.points
    .filter((p) => p.alive)
    .map((p) => {
      const dx = p.x - state.x;
      const dy = p.y - state.y;
      const distance = Math.hypot(dx, dy);
      const dir = Math.atan2(dy, dx);
      let relative = dir - state.angle;
      while (relative > Math.PI) relative -= Math.PI * 2;
      while (relative < -Math.PI) relative += Math.PI * 2;
      return { ...p, distance, relative };
    })
    .filter((s) => Math.abs(s.relative) < state.fov / 1.5)
    .sort((a, b) => b.distance - a.distance);

  sprites.forEach((s) => {
    const size = Math.min(canvas.height, canvas.height / s.distance);
    const screenX = canvas.width / 2 + (s.relative / (state.fov / 2)) * (canvas.width / 2);
    const screenY = canvas.height / 2;

    ctx.fillStyle = '#9f1f2d';
    ctx.beginPath();
    ctx.arc(screenX, screenY, size * 0.22, 0, Math.PI * 2);
    ctx.fill();

    ctx.fillStyle = '#f8d6b5';
    ctx.fillRect(screenX - size * 0.09, screenY - size * 0.03, size * 0.18, size * 0.2);

    ctx.fillStyle = '#ffd54f';
    ctx.fillRect(screenX - size * 0.08, screenY + size * 0.18, size * 0.16, size * 0.06);
  });
}

function drawWeapon() {
  const gunW = 240;
  const gunH = 140;
  const x = canvas.width / 2 - gunW / 2;
  const y = canvas.height - gunH + (state.shootFlash > 0 ? 10 : 0);

  ctx.fillStyle = '#2f313f';
  ctx.fillRect(x, y + 40, gunW, gunH - 40);
  ctx.fillStyle = '#4b5068';
  ctx.fillRect(x + 90, y, 60, 95);

  if (state.shootFlash > 0) {
    ctx.fillStyle = 'rgba(255, 205, 80, 0.85)';
    ctx.beginPath();
    ctx.moveTo(canvas.width / 2 - 18, y - 8);
    ctx.lineTo(canvas.width / 2 + 18, y - 8);
    ctx.lineTo(canvas.width / 2, y - 46);
    ctx.fill();
  }
}

function drawHUD() {
  ctx.fillStyle = 'rgba(0, 0, 0, 0.48)';
  ctx.fillRect(0, canvas.height - 44, canvas.width, 44);
  ctx.fillStyle = '#fff';
  ctx.font = '20px monospace';
  ctx.fillText(`HP ${state.hp}`, 16, canvas.height - 16);
  ctx.fillText(`AMMO ${state.ammo}`, 150, canvas.height - 16);
  ctx.fillText(`KILLS ${state.kills}/${state.points.length}`, 340, canvas.height - 16);

  ctx.strokeStyle = 'rgba(255,255,255,0.75)';
  ctx.beginPath();
  ctx.moveTo(canvas.width / 2 - 12, canvas.height / 2);
  ctx.lineTo(canvas.width / 2 + 12, canvas.height / 2);
  ctx.moveTo(canvas.width / 2, canvas.height / 2 - 12);
  ctx.lineTo(canvas.width / 2, canvas.height / 2 + 12);
  ctx.stroke();

  if (state.mapVisible) drawMinimap();
}

function drawMinimap() {
  const cell = 11;
  const miniX = canvas.width - map[0].length * cell - 14;
  const miniY = 12;
  ctx.fillStyle = 'rgba(5,10,18,0.8)';
  ctx.fillRect(miniX - 6, miniY - 6, map[0].length * cell + 12, map.length * cell + 12);

  for (let y = 0; y < map.length; y++) {
    for (let x = 0; x < map[0].length; x++) {
      ctx.fillStyle = map[y][x] === '1' ? '#5f6578' : '#202635';
      ctx.fillRect(miniX + x * cell, miniY + y * cell, cell - 1, cell - 1);
    }
  }

  state.points.filter((p) => p.alive).forEach((p) => {
    ctx.fillStyle = '#ef5350';
    ctx.fillRect(miniX + p.x * cell - 2, miniY + p.y * cell - 2, 4, 4);
  });

  ctx.fillStyle = '#53d9a5';
  ctx.beginPath();
  ctx.arc(miniX + state.x * cell, miniY + state.y * cell, 3, 0, Math.PI * 2);
  ctx.fill();

  ctx.strokeStyle = '#53d9a5';
  ctx.beginPath();
  ctx.moveTo(miniX + state.x * cell, miniY + state.y * cell);
  ctx.lineTo(
    miniX + (state.x + Math.cos(state.angle) * 1.2) * cell,
    miniY + (state.y + Math.sin(state.angle) * 1.2) * cell
  );
  ctx.stroke();
}

function tryMove(nx, ny) {
  const margin = 0.18;
  if (!isWall(nx + margin, ny) && !isWall(nx - margin, ny) && !isWall(nx, ny + margin) && !isWall(nx, ny - margin)) {
    state.x = nx;
    state.y = ny;
  }
}

function shoot() {
  if (state.ammo <= 0) {
    beep(120, 0.05, 'sawtooth', 0.03);
    return;
  }

  state.ammo--;
  state.shootFlash = 0.12;
  beep(220, 0.06, 'square', 0.09);
  beep(110, 0.12, 'triangle', 0.05);

  const target = state.points.find((p) => {
    if (!p.alive) return false;
    const dx = p.x - state.x;
    const dy = p.y - state.y;
    const dist = Math.hypot(dx, dy);
    if (dist > 8) return false;
    const dir = Math.atan2(dy, dx);
    let rel = dir - state.angle;
    while (rel > Math.PI) rel -= Math.PI * 2;
    while (rel < -Math.PI) rel += Math.PI * 2;
    return Math.abs(rel) < 0.09;
  });

  if (target) {
    target.alive = false;
    state.kills++;
    beep(440, 0.09, 'sine', 0.04);
    statusLine.textContent = `Попадание! Устранено целей: ${state.kills}/${state.points.length}`;
    if (state.kills === state.points.length) {
      statusLine.textContent = 'Уровень зачищен! Перезагрузи страницу для нового захода.';
    }
  }
}

function update(dt) {
  const runMultiplier = state.keys.has('ShiftLeft') || state.keys.has('ShiftRight') ? 1.8 : 1;
  const moveStep = state.speed * runMultiplier * dt;
  const rotStep = state.rotSpeed * dt;

  if (state.keys.has('ArrowLeft')) state.angle -= rotStep;
  if (state.keys.has('ArrowRight')) state.angle += rotStep;

  let moveX = 0;
  let moveY = 0;

  if (state.keys.has('KeyW')) {
    moveX += Math.cos(state.angle) * moveStep;
    moveY += Math.sin(state.angle) * moveStep;
  }
  if (state.keys.has('KeyS')) {
    moveX -= Math.cos(state.angle) * moveStep;
    moveY -= Math.sin(state.angle) * moveStep;
  }
  if (state.keys.has('KeyA')) {
    moveX += Math.cos(state.angle - Math.PI / 2) * moveStep;
    moveY += Math.sin(state.angle - Math.PI / 2) * moveStep;
  }
  if (state.keys.has('KeyD')) {
    moveX += Math.cos(state.angle + Math.PI / 2) * moveStep;
    moveY += Math.sin(state.angle + Math.PI / 2) * moveStep;
  }

  tryMove(state.x + moveX, state.y + moveY);

  state.shootFlash = Math.max(0, state.shootFlash - dt);
}

function loop(t) {
  const time = t / 1000;
  const dt = Math.min(0.05, time - state.lastTime || 0.016);
  state.lastTime = time;

  update(dt);
  drawWorld();
  drawSprites();
  drawWeapon();
  drawHUD();

  requestAnimationFrame(loop);
}

window.addEventListener('keydown', (e) => {
  if (['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'Space'].includes(e.code)) e.preventDefault();
  state.keys.add(e.code);

  if (e.code === 'KeyM') {
    state.mapVisible = !state.mapVisible;
  }

  if (e.code === 'Space') shoot();
});

window.addEventListener('keyup', (e) => {
  state.keys.delete(e.code);
});

canvas.addEventListener('click', async () => {
  if (audioCtx.state === 'suspended') await audioCtx.resume();
  statusLine.textContent = 'В бой! Очисти локацию от всех целей.';
});

requestAnimationFrame(loop);
