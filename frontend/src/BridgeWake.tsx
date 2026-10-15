// The user's agent (Hermes bridge) sleeps after an hour without actions (backend bridge_sleeper). After login or a
// reload it is woken behind a small window; while the tab is open and it falls asleep, a banner offers to wake it.
import React, {useEffect, useState} from 'react';
import {api} from './Auth';
import {Logo} from './Logo';

export type BridgeState = 'ready' | 'asleep' | 'starting' | 'unavailable';

/** Backend 503 {asleep} texts (app.py bridge()): the banner already says this, so they are not shown as errors. */
export const isAsleepText = (s: string) => /Агент заснув після години без дій|Агент ще запускається/.test(s);

export async function wakeAgent(): Promise<BridgeState> {
  for (let i = 0; i < 4; i++) {
    try {
      const r = await api('/me/bridge?wake=1');
      if (r.state === 'ready') return 'ready';
    } catch {
      /* keep trying: the bridge may still be binding its socket */
    }
    await new Promise(r => setTimeout(r, 1500));
  }
  return 'starting';
}

/** Full-window "starting" card shown while a sleeping agent is woken (after login / reload / clicking the banner). */
export function WakeWindow({onDone}: {onDone: (s: BridgeState) => void}) {
  const [slow, setSlow] = useState(false);
  useEffect(() => {
    let on = true;
    const t = setTimeout(() => setSlow(true), 15000);
    wakeAgent().then(s => {
      if (on) onDone(s);
    });
    return () => {
      on = false;
      clearTimeout(t);
    };
  }, []);
  return (
    <div className="overlay wake-overlay" role="alertdialog" aria-modal="true" aria-busy="true" aria-label="Запускаємо агента">
      <div className="modal narrow wake-card">
        <div className="wake-logo">
          <Logo size={40} />
        </div>
        <h2>Запускаємо вашого агента</h2>
        <p>Після години без дій агент засинає, щоб не займати памʼять сервера. Зазвичай запуск триває 5–10 секунд.</p>
        <div className="wake-bar">
          <i />
        </div>
        {slow && (
          <p className="hint">Довше, ніж зазвичай. Якщо вікно не зникне за хвилину, перезавантажте сторінку або напишіть адміністратору.</p>
        )}
      </div>
    </div>
  );
}

/** Thin banner over the composer when the agent fell asleep while the tab stayed open. */
export function AsleepBanner({onWake}: {onWake: () => void}) {
  return (
    <div className="asleep-banner" role="status">
      <span>Агент спить після години без дій. Розбудіть його, щоб продовжити розмову.</span>
      <button type="button" className="asleep-wake" onClick={onWake}>
        Розбудити
      </button>
    </div>
  );
}
