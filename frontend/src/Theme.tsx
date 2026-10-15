import {api} from './Auth';
import palettes from './palettes.json';
import {applyBackground, currentBackground, BACKGROUNDS, Background} from './Backgrounds';

export type ThemePref = 'system' | 'light' | 'dark';
export type Palette = keyof typeof palettes;
export const PALETTES = palettes;
const KEY = 'hermes-theme',
  COLOR_KEY = 'hermes-color-palette';
const media = window.matchMedia('(prefers-color-scheme: dark)');
export function resolve(t: ThemePref): 'light' | 'dark' {
  return t === 'system' ? (media.matches ? 'dark' : 'light') : t;
}
export function current(): ThemePref {
  const v = localStorage.getItem(KEY);
  return v === 'light' || v === 'dark' || v === 'system' ? v : 'system';
}
export function currentPalette(): Palette {
  const v = localStorage.getItem(COLOR_KEY);
  return v && Object.hasOwn(palettes, v) ? (v as Palette) : 'blue';
}
export function apply(t: ThemePref, palette: Palette = currentPalette()) {
  localStorage.setItem(KEY, t);
  localStorage.setItem(COLOR_KEY, palette);
  const el = document.documentElement;
  el.dataset.palette = 'kumo';
  el.dataset.color = palette;
  el.dataset.mode = resolve(t);
  el.style.colorScheme = resolve(t);
  window.dispatchEvent(new CustomEvent('hermes:theme', {detail: resolve(t)}));
}
export function initTheme() {
  apply(current(), currentPalette());
  media.addEventListener('change', () => {
    if (current() === 'system') apply('system', currentPalette());
  });
}
export async function syncTheme() {
  try {
    const p = await api('/me/prefs');
    const mode: ThemePref = ['system', 'light', 'dark'].includes(p.theme) ? p.theme : 'system';
    const palette: Palette = Object.hasOwn(palettes, p.palette) ? p.palette : 'blue';
    apply(mode, palette);
    applyBackground(Object.hasOwn(BACKGROUNDS, p.background) ? p.background : 'none');
  } catch {
    /* Keep local preference while offline or logged out. */
  }
}
export async function saveTheme(t: ThemePref, palette: Palette = currentPalette()) {
  const previousMode = current(),
    previousPalette = currentPalette();
  apply(t, palette);
  try {
    await api('/me/prefs', {method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({theme: t, palette})});
  } catch (e) {
    apply(previousMode, previousPalette);
    throw e;
  }
}
export async function saveBackground(b: Background) {
  const previous = currentBackground();
  applyBackground(b);
  try {
    await api('/me/prefs', {method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({background: b})});
  } catch (e) {
    applyBackground(previous);
    throw e;
  }
}
