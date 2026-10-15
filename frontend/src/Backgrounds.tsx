import React, {useEffect, useRef, useState} from 'react';

/*
 * Decorative chat backgrounds: slow looping canvas animations in one tone (--synapse-tone of the active palette).
 * Purely visual: they read no data and react to nothing. Default is 'none' (empty background).
 * Own implementations; "synapse" is inspired by the Odysseus concept (no code copied).
 */
export const BACKGROUNDS = {
  none: {name: 'Без фону', description: 'Чисте тло без анімації'},
  synapse: {name: 'Синапси', description: 'Сітка, якою пробігають світлові імпульси'},
  constellation: {name: 'Сузірʼя', description: 'Точки дрейфують і зʼєднуються лініями'},
  waves: {name: 'Хвилі', description: 'Повільні синусоїди, що переливаються'},
  aurora: {name: 'Сяйво', description: 'Мʼякі кольорові плями пливуть по колу'},
  orbits: {name: 'Орбіти', description: 'Частинки кружляють еліптичними орбітами'},
  spores: {name: 'Спори', description: 'Крихітні спори здіймаються й погойдуються'},
  mycelium: {name: 'Міцелій', description: 'Грибниця розростається тонкими гілками'},
  fireflies: {name: 'Світлячки', description: 'Вогники блукають і мʼяко спалахують'},
  ripples: {name: 'Брижі', description: 'Кола розходяться, наче від крапель на воді'},
  flow: {name: 'Течії', description: 'Нитки пливуть невидимим вихровим потоком'},
  honeycomb: {name: 'Соти', description: 'Шестикутні комірки по черзі засвічуються'},
  warp: {name: 'Зорепад', description: 'Зорі повільно летять назустріч'},
  rain: {name: 'Дощ', description: 'Косі краплі на різній глибині'},
  lissajous: {name: 'Ліссажу', description: 'Гармонічні криві плавно перетікають'},
} as const;
export type Background = keyof typeof BACKGROUNDS;
const KEY = 'hermes-chat-bg';
export function currentBackground(): Background {
  const v = localStorage.getItem(KEY);
  return v && Object.hasOwn(BACKGROUNDS, v) ? (v as Background) : 'none';
}
export function applyBackground(b: Background) {
  localStorage.setItem(KEY, b);
  window.dispatchEvent(new CustomEvent('hermes:bg', {detail: b}));
}

let TONE = '156,222,242';
const readTone = () => {
  const v = getComputedStyle(document.documentElement).getPropertyValue('--synapse-tone').trim();
  if (v) TONE = v;
};
window.addEventListener('hermes:theme', () => requestAnimationFrame(readTone));
requestAnimationFrame(readTone);
const rgba = (a: number) => `rgba(${TONE},${a})`;
const rnd = (a: number, b: number) => a + Math.random() * (b - a);

type Scene = {resize(w: number, h: number): void; draw(ctx: CanvasRenderingContext2D, t: number, dt: number): void};
type Factory = (w: number, h: number, density: number) => Scene;

const synapse: Factory = (W, H, k) => {
  const G = 24;
  let pulses: {x: number; y: number; dx: number; dy: number; big: boolean}[] = [],
    acc = 0;
  const spawn = () => {
    const big = Math.random() < 0.25,
      s = Math.random() < 0.5 ? 1 : -1,
      v = big ? rnd(1.2, 2.4) : rnd(0.6, 2);
    if (Math.random() < 0.5) pulses.push({x: s > 0 ? -60 : W + 60, y: Math.floor(Math.random() * (H / G + 1)) * G, dx: v * s, dy: 0, big});
    else pulses.push({x: Math.floor(Math.random() * (W / G + 1)) * G, y: s > 0 ? -60 : H + 60, dx: 0, dy: v * s, big});
  };
  return {
    resize(w, h) {
      W = w;
      H = h;
      pulses = [];
    },
    draw(ctx, _t, dt) {
      ctx.strokeStyle = rgba(0.05);
      ctx.lineWidth = 1;
      ctx.beginPath();
      for (let x = 0; x <= W; x += G) {
        ctx.moveTo(x + 0.5, 0);
        ctx.lineTo(x + 0.5, H);
      }
      for (let y = 0; y <= H; y += G) {
        ctx.moveTo(0, y + 0.5);
        ctx.lineTo(W, y + 0.5);
      }
      ctx.stroke();
      acc += dt * 2.4 * k * Math.max(0.5, (W * H) / 1e6);
      while (acc >= 1 && pulses.length < 80) {
        acc--;
        spawn();
      }
      const f = dt * 60;
      pulses = pulses.filter(p => {
        p.x += p.dx * f;
        p.y += p.dy * f;
        if (p.x < -80 || p.y < -80 || p.x > W + 80 || p.y > H + 80) return false;
        const trail = p.big ? 40 : 16,
          tx = p.x - Math.sign(p.dx) * trail,
          ty = p.y - Math.sign(p.dy) * trail;
        const g = ctx.createLinearGradient(tx, ty, p.x, p.y);
        g.addColorStop(0, rgba(0));
        g.addColorStop(1, rgba(p.big ? 0.9 : 0.5));
        ctx.strokeStyle = g;
        ctx.lineWidth = p.big ? 1.6 : 1;
        ctx.beginPath();
        ctx.moveTo(tx + 0.5, ty + 0.5);
        ctx.lineTo(p.x + 0.5, p.y + 0.5);
        ctx.stroke();
        ctx.shadowColor = rgba(1);
        ctx.shadowBlur = p.big ? 12 : 0;
        ctx.fillStyle = rgba(p.big ? 1 : 0.7);
        ctx.beginPath();
        ctx.arc(p.x + 0.5, p.y + 0.5, p.big ? 2.4 : 1.3, 0, 6.283);
        ctx.fill();
        ctx.shadowBlur = 0;
        return true;
      });
    },
  };
};

const constellation: Factory = (W, H, k) => {
  let pts: {x: number; y: number; vx: number; vy: number}[] = [];
  const seed = () => {
    const n = Math.round(Math.min(110, 18 + ((W * H) / 14000) * k));
    pts = Array.from({length: n}, () => ({x: rnd(0, W), y: rnd(0, H), vx: rnd(-0.25, 0.25), vy: rnd(-0.25, 0.25)}));
  };
  seed();
  return {
    resize(w, h) {
      W = w;
      H = h;
      seed();
    },
    draw(ctx, _t, dt) {
      const f = dt * 60,
        R = 130;
      for (const p of pts) {
        p.x = (p.x + p.vx * f + W) % W;
        p.y = (p.y + p.vy * f + H) % H;
      }
      ctx.lineWidth = 1;
      for (let i = 0; i < pts.length; i++)
        for (let j = i + 1; j < pts.length; j++) {
          const a = pts[i],
            b = pts[j],
            d = Math.hypot(a.x - b.x, a.y - b.y);
          if (d < R) {
            ctx.strokeStyle = rgba((1 - d / R) * 0.22);
            ctx.beginPath();
            ctx.moveTo(a.x, a.y);
            ctx.lineTo(b.x, b.y);
            ctx.stroke();
          }
        }
      ctx.fillStyle = rgba(0.6);
      for (const p of pts) {
        ctx.beginPath();
        ctx.arc(p.x, p.y, 1.6, 0, 6.283);
        ctx.fill();
      }
    },
  };
};

const waves: Factory = (W, H) => ({
  resize(w, h) {
    W = w;
    H = h;
  },
  draw(ctx, t) {
    const n = 6;
    for (let i = 0; i < n; i++) {
      const base = H * (0.3 + (0.5 * i) / (n - 1)),
        amp = 18 + 22 * Math.sin(t * 0.00025 + i),
        len = 380 + i * 90,
        sp = 0.0004 + i * 0.00008;
      ctx.strokeStyle = rgba(0.07 + 0.05 * (i % 3));
      ctx.lineWidth = 1.2;
      ctx.beginPath();
      for (let x = 0; x <= W + 10; x += 8) {
        const y =
          base + amp * Math.sin((x / len) * 6.283 + t * sp + i * 1.7) + amp * 0.4 * Math.sin((x / (len * 0.43)) * 6.283 - t * sp * 1.6);
        x ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
      }
      ctx.stroke();
    }
  },
});

const aurora: Factory = (W, H) => {
  const blobs = Array.from({length: 4}, (_, i) => ({
    ax: rnd(0.25, 0.45),
    ay: rnd(0.2, 0.4),
    fx: rnd(0.00004, 0.00009),
    fy: rnd(0.00003, 0.00008),
    ph: i * 1.6,
    r: rnd(0.35, 0.55),
  }));
  return {
    resize(w, h) {
      W = w;
      H = h;
    },
    draw(ctx, t) {
      ctx.globalCompositeOperation = 'lighter';
      for (const b of blobs) {
        const x = W * (0.5 + b.ax * Math.sin(t * b.fx + b.ph)),
          y = H * (0.5 + b.ay * Math.cos(t * b.fy + b.ph * 0.7)),
          r = Math.max(W, H) * b.r;
        const g = ctx.createRadialGradient(x, y, 0, x, y, r);
        g.addColorStop(0, rgba(0.13));
        g.addColorStop(1, rgba(0));
        ctx.fillStyle = g;
        ctx.fillRect(0, 0, W, H);
      }
      ctx.globalCompositeOperation = 'source-over';
    },
  };
};

const orbits: Factory = (W, H, k) => {
  const rings = Array.from({length: 7}, (_, i) => ({
    r: 60 + i * 70,
    tilt: 0.45 + 0.05 * i,
    sp: (i % 2 ? -1 : 1) * (0.00012 + 0.00004 * (7 - i)),
    dots: Array.from({length: Math.max(1, Math.round((2 + i) * k))}, () => rnd(0, 6.283)),
  }));
  return {
    resize(w, h) {
      W = w;
      H = h;
    },
    draw(ctx, t) {
      const cx = W * 0.72,
        cy = H * 0.62,
        s = Math.max(W, H) / 900;
      ctx.lineWidth = 1;
      for (const ring of rings) {
        const rx = ring.r * s,
          ry = rx * ring.tilt;
        ctx.strokeStyle = rgba(0.06);
        ctx.beginPath();
        ctx.ellipse(cx, cy, rx, ry, -0.35, 0, 6.283);
        ctx.stroke();
        for (const a0 of ring.dots) {
          const a = a0 + t * ring.sp,
            x = rx * Math.cos(a),
            y = ry * Math.sin(a),
            c = Math.cos(-0.35),
            sn = Math.sin(-0.35);
          ctx.fillStyle = rgba(0.35 + (0.35 * (Math.sin(a) + 1)) / 2);
          ctx.beginPath();
          ctx.arc(cx + x * c - y * sn, cy + x * sn + y * c, 1.8, 0, 6.283);
          ctx.fill();
        }
      }
    },
  };
};

const spores: Factory = (W, H, k) => {
  type S = {x: number; y: number; v: number; sw: number; ph: number; r: number};
  const make = (y?: number): S => ({
    x: rnd(0, W),
    y: y ?? H + rnd(0, 40),
    v: rnd(0.15, 0.5),
    sw: rnd(6, 22),
    ph: rnd(0, 6.283),
    r: rnd(0.8, 2.4),
  });
  let list: S[] = [];
  const seed = () => {
    list = Array.from({length: Math.round(Math.min(140, 20 + ((W * H) / 9000) * k))}, () => make(rnd(0, H)));
  };
  seed();
  return {
    resize(w, h) {
      W = w;
      H = h;
      seed();
    },
    draw(ctx, t, dt) {
      const f = dt * 60;
      for (let i = 0; i < list.length; i++) {
        const s = list[i];
        s.y -= s.v * f;
        if (s.y < -20) {
          list[i] = make();
          continue;
        }
        const x = s.x + s.sw * Math.sin(t * 0.0007 + s.ph),
          life = Math.min(1, (s.y / H) * 1.4);
        ctx.fillStyle = rgba(0.15 + 0.45 * life);
        ctx.beginPath();
        ctx.arc(x, s.y, s.r, 0, 6.283);
        ctx.fill();
      }
    },
  };
};

const mycelium: Factory = (W, H, k) => {
  type Tip = {x: number; y: number; a: number; life: number; lx: number; ly: number};
  type Colony = {segs: number[]; tips: Tip[]; fade: number};
  let cols: Colony[] = [];
  const colony = (): Colony => {
    const x = rnd(0.1, 0.9) * W,
      y = rnd(0.1, 0.9) * H,
      n = 3 + Math.floor(Math.random() * 3);
    return {
      segs: [],
      fade: 1,
      tips: Array.from({length: n}, (_, i) => ({
        x,
        y,
        lx: x,
        ly: y,
        a: (i / n) * 6.283 + rnd(-0.3, 0.3),
        life: rnd(90, 200) * Math.max(0.5, Math.min(W, H) / 600),
      })),
    };
  };
  const max = () => Math.max(1, Math.round(3 * k));
  return {
    resize(w, h) {
      W = w;
      H = h;
      cols = [];
    },
    draw(ctx, _t, dt) {
      const f = dt * 60;
      while (cols.length < max()) cols.push(colony());
      ctx.lineWidth = 1;
      ctx.lineCap = 'round';
      cols = cols.filter(c => {
        const born: Tip[] = [];
        c.tips = c.tips.filter(p => {
          const v = 0.45 * f;
          p.a += rnd(-0.12, 0.12) * f;
          p.x += Math.cos(p.a) * v;
          p.y += Math.sin(p.a) * v;
          p.life -= v;
          if (Math.hypot(p.x - p.lx, p.y - p.ly) > 4) {
            c.segs.push(p.lx, p.ly, p.x, p.y);
            p.lx = p.x;
            p.ly = p.y;
          }
          if (c.tips.length + born.length < 36 && Math.random() < 0.012 * f)
            born.push({...p, a: p.a + (Math.random() < 0.5 ? -1 : 1) * rnd(0.4, 0.9), life: p.life * rnd(0.5, 0.8)});
          return p.life > 0 && p.x > -10 && p.y > -10 && p.x < W + 10 && p.y < H + 10;
        });
        c.tips.push(...born);
        if (!c.tips.length) c.fade -= dt / 5;
        ctx.strokeStyle = rgba(0.28 * c.fade);
        ctx.beginPath();
        for (let i = 0; i < c.segs.length; i += 4) {
          ctx.moveTo(c.segs[i], c.segs[i + 1]);
          ctx.lineTo(c.segs[i + 2], c.segs[i + 3]);
        }
        ctx.stroke();
        ctx.fillStyle = rgba(0.75);
        for (const p of c.tips) {
          ctx.beginPath();
          ctx.arc(p.x, p.y, 1.3, 0, 6.283);
          ctx.fill();
        }
        return c.fade > 0;
      });
    },
  };
};

const fireflies: Factory = (W, H, k) => {
  type F = {x: number; y: number; a: number; v: number; ph: number; per: number; r: number};
  let list: F[] = [];
  const seed = () => {
    list = Array.from({length: Math.round(Math.min(60, 8 + ((W * H) / 26000) * k))}, () => ({
      x: rnd(0, W),
      y: rnd(0, H),
      a: rnd(0, 6.283),
      v: rnd(0.15, 0.4),
      ph: rnd(0, 6.283),
      per: rnd(2200, 5200),
      r: rnd(1.2, 2.2),
    }));
  };
  seed();
  return {
    resize(w, h) {
      W = w;
      H = h;
      seed();
    },
    draw(ctx, t, dt) {
      const f = dt * 60;
      for (const p of list) {
        p.a += rnd(-0.06, 0.06) * f;
        p.x = (p.x + Math.cos(p.a) * p.v * f + W) % W;
        p.y = (p.y + Math.sin(p.a) * p.v * f + H) % H;
        const glow = Math.max(0, Math.sin((t / p.per) * 6.283 + p.ph)) ** 3,
          R = p.r * 7;
        if (glow > 0.02) {
          const g = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, R);
          g.addColorStop(0, rgba(0.35 * glow));
          g.addColorStop(1, rgba(0));
          ctx.fillStyle = g;
          ctx.fillRect(p.x - R, p.y - R, R * 2, R * 2);
        }
        ctx.fillStyle = rgba(0.15 + 0.8 * glow);
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.r, 0, 6.283);
        ctx.fill();
      }
    },
  };
};

const ripples: Factory = (W, H, k) => {
  let rings: {x: number; y: number; age: number; life: number}[] = [],
    acc = 1;
  return {
    resize(w, h) {
      W = w;
      H = h;
      rings = [];
    },
    draw(ctx, _t, dt) {
      acc += dt * 0.7 * k * Math.max(0.6, (W * H) / 1e6);
      while (acc >= 1) {
        acc--;
        rings.push({x: rnd(0, W), y: rnd(0, H), age: 0, life: rnd(5, 8)});
      }
      ctx.lineWidth = 1;
      rings = rings.filter(r => {
        r.age += dt;
        const p = r.age / r.life;
        if (p >= 1) return false;
        for (let e = 0; e < 3; e++) {
          const rad = (r.age - e * 0.45) * 38 * Math.max(0.35, Math.min(W, H) / 500);
          if (rad <= 0) continue;
          ctx.strokeStyle = rgba((1 - p) * (0.28 - e * 0.07));
          ctx.beginPath();
          ctx.ellipse(r.x, r.y, rad, rad * 0.55, 0, 0, 6.283);
          ctx.stroke();
        }
        return true;
      });
    },
  };
};

const flow: Factory = (W, H, k) => {
  type P = {pts: number[]; life: number};
  let list: P[] = [];
  const make = (): P => ({pts: [rnd(0, W), rnd(0, H)], life: rnd(160, 420)});
  const seed = () => {
    list = Array.from({length: Math.round(Math.min(160, 25 + ((W * H) / 9000) * k))}, make);
  };
  seed();
  const angle = (x: number, y: number, t: number) =>
    Math.sin(x * 0.0042 + t * 0.00011) * 1.6 + Math.cos(y * 0.0051 - t * 0.00008) * 1.6 + Math.sin((x + y) * 0.0017 + t * 0.00005);
  return {
    resize(w, h) {
      W = w;
      H = h;
      seed();
    },
    draw(ctx, t, dt) {
      const f = dt * 60;
      ctx.lineWidth = 1;
      for (let i = 0; i < list.length; i++) {
        const p = list[i],
          n = p.pts.length,
          x = p.pts[n - 2],
          y = p.pts[n - 1],
          a = angle(x, y, t);
        p.pts.push(x + Math.cos(a) * 0.9 * f, y + Math.sin(a) * 0.9 * f);
        if (p.pts.length > 80) p.pts.splice(0, 2);
        p.life -= f;
        if (p.life < 0 || x < -5 || y < -5 || x > W + 5 || y > H + 5) {
          list[i] = make();
          continue;
        }
        const fade = Math.min(1, p.life / 60);
        ctx.strokeStyle = rgba(0.3 * fade);
        ctx.beginPath();
        ctx.moveTo(p.pts[0], p.pts[1]);
        for (let j = 2; j < p.pts.length; j += 2) ctx.lineTo(p.pts[j], p.pts[j + 1]);
        ctx.stroke();
      }
    },
  };
};

const honeycomb: Factory = (W, H, k) => {
  const R = 22,
    dx = R * Math.sqrt(3),
    dy = R * 1.5;
  let lit = new Map<string, {x: number; y: number; age: number; life: number}>(),
    acc = 0;
  const hex = (ctx: CanvasRenderingContext2D, x: number, y: number, r: number) => {
    for (let i = 0; i < 6; i++) {
      const a = Math.PI / 6 + (i * Math.PI) / 3;
      i ? ctx.lineTo(x + r * Math.cos(a), y + r * Math.sin(a)) : ctx.moveTo(x + r * Math.cos(a), y + r * Math.sin(a));
    }
    ctx.closePath();
  };
  const center = (c: number, r: number): [number, number] => [c * dx + (r % 2 ? dx / 2 : 0), r * dy];
  return {
    resize(w, h) {
      W = w;
      H = h;
      lit = new Map();
    },
    draw(ctx, _t, dt) {
      const cols = Math.ceil(W / dx) + 1,
        rows = Math.ceil(H / dy) + 1;
      ctx.lineWidth = 1;
      ctx.strokeStyle = rgba(0.06);
      ctx.beginPath();
      for (let r = 0; r <= rows; r++)
        for (let c = 0; c <= cols; c++) {
          const [x, y] = center(c, r);
          hex(ctx, x, y, R - 1);
        }
      ctx.stroke();
      acc += dt * 3 * k * Math.max(0.5, (W * H) / 1e6);
      while (acc >= 1) {
        acc--;
        const c = Math.floor(rnd(0, cols + 1)),
          r = Math.floor(rnd(0, rows + 1)),
          [x, y] = center(c, r);
        lit.set(c + ':' + r, {x, y, age: 0, life: rnd(2.5, 5)});
        if (Math.random() < 0.5) {
          const n = Math.floor(rnd(0, 6)),
            nc = c + [1, -1, 0, 0, r % 2 ? 1 : -1, r % 2 ? 1 : -1][n],
            nr = r + [0, 0, 1, -1, 1, -1][n],
            [nx, ny] = center(nc, nr);
          lit.set(nc + ':' + nr, {x: nx, y: ny, age: -0.4, life: rnd(2.5, 5)});
        }
      }
      for (const [key, cell] of lit) {
        cell.age += dt;
        if (cell.age >= cell.life) {
          lit.delete(key);
          continue;
        }
        if (cell.age < 0) continue;
        const a = Math.sin((cell.age / cell.life) * Math.PI);
        ctx.fillStyle = rgba(0.1 * a);
        ctx.strokeStyle = rgba(0.4 * a);
        ctx.beginPath();
        hex(ctx, cell.x, cell.y, R - 1);
        ctx.fill();
        ctx.stroke();
      }
    },
  };
};

const warp: Factory = (W, H, k) => {
  type S = {x: number; y: number; z: number; pz: number};
  let list: S[] = [];
  const make = (z = rnd(0.2, 1)): S => ({x: rnd(-1, 1), y: rnd(-1, 1), z, pz: z});
  const seed = () => {
    list = Array.from({length: Math.round(Math.min(220, 40 + ((W * H) / 6000) * k))}, () => make());
  };
  seed();
  return {
    resize(w, h) {
      W = w;
      H = h;
      seed();
    },
    draw(ctx, _t, dt) {
      const cx = W / 2,
        cy = H / 2,
        s = Math.max(W, H) * 0.5;
      ctx.lineCap = 'round';
      for (let i = 0; i < list.length; i++) {
        const p = list[i];
        p.z -= dt * 0.08;
        p.pz = Math.min(1.2, p.z + 0.025);
        if (p.z <= 0.02) {
          list[i] = make(1);
          continue;
        }
        const x = cx + (p.x / p.z) * s,
          y = cy + (p.y / p.z) * s,
          px = cx + (p.x / p.pz) * s,
          py = cy + (p.y / p.pz) * s;
        if (x < -10 || y < -10 || x > W + 10 || y > H + 10) {
          list[i] = make(1);
          continue;
        }
        const near = 1 - p.z;
        ctx.strokeStyle = rgba(0.18 + 0.5 * near * near);
        ctx.lineWidth = 0.8 + 1.1 * near * near;
        ctx.beginPath();
        ctx.moveTo(px, py);
        ctx.lineTo(x + 0.01, y);
        ctx.stroke();
      }
    },
  };
};

const rain: Factory = (W, H, k) => {
  type D = {x: number; y: number; v: number; len: number; depth: number};
  let list: D[] = [];
  const slant = 0.18;
  const make = (y?: number): D => {
    const depth = rnd(0.3, 1);
    return {x: rnd(-H * slant, W), y: y ?? rnd(-H * 0.3, -10), v: 2 + 5 * depth, len: 10 + 26 * depth, depth};
  };
  const seed = () => {
    list = Array.from({length: Math.round(Math.min(180, 20 + ((W * H) / 9000) * k))}, () => make(rnd(-H, H)));
  };
  seed();
  return {
    resize(w, h) {
      W = w;
      H = h;
      seed();
    },
    draw(ctx, _t, dt) {
      const f = dt * 60;
      ctx.lineCap = 'round';
      for (let i = 0; i < list.length; i++) {
        const d = list[i];
        d.y += d.v * f;
        d.x += d.v * slant * f;
        if (d.y - d.len > H) {
          list[i] = make();
          continue;
        }
        const g = ctx.createLinearGradient(d.x - d.len * slant, d.y - d.len, d.x, d.y);
        g.addColorStop(0, rgba(0));
        g.addColorStop(1, rgba(0.12 + 0.3 * d.depth));
        ctx.strokeStyle = g;
        ctx.lineWidth = 0.6 + 0.8 * d.depth;
        ctx.beginPath();
        ctx.moveTo(d.x - d.len * slant, d.y - d.len);
        ctx.lineTo(d.x, d.y);
        ctx.stroke();
      }
    },
  };
};

const lissajous: Factory = (W, H) => ({
  resize(w, h) {
    W = w;
    H = h;
  },
  draw(ctx, t) {
    const cx = W / 2,
      cy = H / 2,
      ax = W * 0.42,
      ay = H * 0.4;
    ctx.lineWidth = 1;
    for (let c = 0; c < 3; c++) {
      const a = 3 + c,
        b = 2 + c,
        d = t * (0.00006 + c * 0.00002) + c * 1.1;
      ctx.strokeStyle = rgba(0.14 - c * 0.03);
      ctx.beginPath();
      for (let i = 0; i <= 720; i++) {
        const s = (i / 720) * 6.283,
          x = cx + ax * Math.sin(a * s + d),
          y = cy + ay * Math.sin(b * s);
        i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
      }
      ctx.stroke();
    }
    const s = (t * 0.00012) % 6.283,
      x = cx + ax * Math.sin(3 * s + t * 0.00006),
      y = cy + ay * Math.sin(2 * s);
    ctx.shadowColor = rgba(1);
    ctx.shadowBlur = 10;
    ctx.fillStyle = rgba(0.9);
    ctx.beginPath();
    ctx.arc(x, y, 2.2, 0, 6.283);
    ctx.fill();
    ctx.shadowBlur = 0;
  },
});

const SCENES: Record<Exclude<Background, 'none'>, Factory> = {
  synapse,
  constellation,
  waves,
  aurora,
  orbits,
  spores,
  mycelium,
  fireflies,
  ripples,
  flow,
  honeycomb,
  warp,
  rain,
  lissajous,
};

/** Canvas filling its positioned parent. Without `kind` it follows the user's preference (chat background). */
export function ChatBackground({kind, density = 1}: {kind?: Background; density?: number}) {
  const [pref, setPref] = useState<Background>(currentBackground());
  useEffect(() => {
    if (kind) return;
    const f = (e: Event) => setPref((e as CustomEvent).detail);
    window.addEventListener('hermes:bg', f);
    return () => window.removeEventListener('hermes:bg', f);
  }, [kind]);
  const bg = kind ?? pref,
    ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    if (bg === 'none') return;
    const canvas = ref.current!,
      ctx = canvas.getContext('2d')!,
      dpr = Math.min(window.devicePixelRatio || 1, 2);
    let W = 1,
      H = 1,
      raf = 0,
      last = performance.now();
    const size = () => {
      const r = canvas.parentElement!.getBoundingClientRect();
      W = Math.max(1, r.width);
      H = Math.max(1, r.height);
      canvas.width = W * dpr;
      canvas.height = H * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    size();
    const scene = SCENES[bg](W, H, density);
    const ro = new ResizeObserver(() => {
      size();
      scene.resize(W, H);
    });
    ro.observe(canvas.parentElement!);
    const frame = (t: number) => {
      raf = requestAnimationFrame(frame);
      const dt = Math.min(0.1, (t - last) / 1000);
      last = t;
      ctx.clearRect(0, 0, W, H);
      scene.draw(ctx, t, dt);
    };
    // Only animate while on screen: the settings picker holds many preview canvases at once.
    const io = new IntersectionObserver(([e]) => {
      cancelAnimationFrame(raf);
      raf = 0;
      if (e.isIntersecting) {
        last = performance.now();
        raf = requestAnimationFrame(frame);
      }
    });
    io.observe(canvas);
    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
      io.disconnect();
    };
  }, [bg, density]);
  return bg === 'none' ? null : <canvas ref={ref} className="chat-bg" aria-hidden="true" />;
}
