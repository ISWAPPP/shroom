// Browser notifications when a reply is ready (or the agent waits for the user) while the portal tab is in the
// background. Per user and per browser (the OS permission is per browser anyway): localStorage `hermes-notify-<uid>`
// = 'on' | 'off'; unset = not decided yet, and the chat offers it once after a finished reply.
import React, {useState} from 'react';
import {Ic, Check, X} from './Icons';

const key = (uid: string) => 'hermes-notify-' + uid;
export const notifySupported = () => typeof window !== 'undefined' && 'Notification' in window && window.isSecureContext;
export type NotifyPref = 'on' | 'off' | '';
export function notifyPref(uid: string): NotifyPref {
  const v = localStorage.getItem(key(uid));
  return v === 'on' || v === 'off' ? v : '';
}
export const notifyOn = (uid: string) => notifySupported() && notifyPref(uid) === 'on' && Notification.permission === 'granted';

/** Ask the OS and remember the answer. Returns the resulting state. */
export async function enableNotify(uid: string): Promise<boolean> {
  if (!notifySupported()) return false;
  const p = Notification.permission === 'default' ? await Notification.requestPermission() : Notification.permission;
  localStorage.setItem(key(uid), p === 'granted' ? 'on' : 'off');
  window.dispatchEvent(new Event('hermes-notify-changed'));
  return p === 'granted';
}
export function disableNotify(uid: string) {
  localStorage.setItem(key(uid), 'off');
  window.dispatchEvent(new Event('hermes-notify-changed'));
}

/** Show a notification only while the tab is hidden; clicking focuses the tab and runs onOpen. */
export function notify(uid: string, title: string, body: string, tag: string, onOpen?: () => void) {
  if (!document.hidden || !notifyOn(uid)) return;
  const opts = {body: body.slice(0, 180), tag, icon: '/icon-192.png', data: {chat: tag.startsWith('chat-') ? tag.slice(5) : ''}};
  try {
    const n = new Notification(title, opts);
    n.onclick = () => {
      window.focus();
      onOpen?.();
      n.close();
    };
  } catch {
    // phones allow notifications only through the service worker (sw.js focuses the tab on click)
    navigator.serviceWorker
      ?.getRegistration()
      .then(r => r?.showNotification(title, opts))
      .catch(() => {});
  }
}

/** Installable app + phone notifications. The worker caches nothing (see public/sw.js). */
export function registerWorker(onOpenChat: (id: string) => void) {
  if (!('serviceWorker' in navigator) || !window.isSecureContext) return () => {};
  navigator.serviceWorker.register('/sw.js').catch(() => {});
  const f = (e: MessageEvent) => {
    if (e.data?.type === 'open-chat' && e.data.chat) onOpenChat(e.data.chat);
  };
  navigator.serviceWorker.addEventListener('message', f);
  return () => navigator.serviceWorker.removeEventListener('message', f);
}

/** One-time offer shown in the chat after a finished reply. */
export function NotifyOffer({uid, onDone}: {uid: string; onDone: () => void}) {
  const [busy, setBusy] = useState(false);
  return (
    <div className="notify-offer" role="status">
      <span>Повідомляти, коли відповідь готова, якщо вкладка у фоні?</span>
      <button
        type="button"
        className="send"
        disabled={busy}
        onClick={async () => {
          setBusy(true);
          await enableNotify(uid);
          onDone();
        }}
      >
        <Ic i={Check} size={18} /> Так
      </button>
      <button
        type="button"
        disabled={busy}
        onClick={() => {
          disableNotify(uid);
          onDone();
        }}
      >
        <Ic i={X} size={18} /> Ні
      </button>
    </div>
  );
}

/** Settings card (Обліковий запис > Сповіщення). */
export function NotifySettings({uid}: {uid: string}) {
  const [, force] = useState(0),
    refresh = () => force(x => x + 1);
  if (!notifySupported())
    return (
      <div className="card">
        <h3>Сповіщення браузера</h3>
        <p className="hint">Цей браузер не підтримує сповіщення.</p>
      </div>
    );
  const denied = Notification.permission === 'denied',
    on = notifyOn(uid);
  return (
    <div className="card">
      <h3>Сповіщення браузера</h3>
      <label className="warn-check">
        <input
          type="checkbox"
          checked={on}
          disabled={denied}
          onChange={async e => {
            if (e.target.checked) await enableNotify(uid);
            else disableNotify(uid);
            refresh();
          }}
        />{' '}
        Повідомляти, коли агент відповів або чекає на вас, а вкладка Shroom у фоні
      </label>
      {denied && (
        <p className="hint">
          Сповіщення для цього сайту заборонені в налаштуваннях браузера. Дозвольте їх там (значок замка біля адреси), потім увімкніть тут.
        </p>
      )}
      <p className="hint">
        Налаштування діє в цьому браузері. Поки вкладка відкрита на екрані, сповіщень немає, лише підказки в самому порталі.
      </p>
    </div>
  );
}
