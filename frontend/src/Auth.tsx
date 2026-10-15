import {humanize} from './Errors';
import {Logo} from './Logo';
import React, {useEffect, useState} from 'react';
import {Ic, Diamond} from './Icons';

export type User = {
  id: string;
  username: string;
  role: 'admin' | 'user';
  profile: string;
  blocked: number;
  created: number;
  last_login?: number | null;
  totp?: boolean;
  must_enroll?: boolean;
  impersonated_by?: string | null;
};

let csrf = '';
/** Last good answers of slow read-only pages, so they render at once and refresh in place. Kept in sessionStorage
 *  (this tab only) under the session's CSRF token: another login or impersonation never sees the previous data. */
const CACHE_PATHS =
  /^\/(me\/(models|providers|skills(\/manage)?|plugins|usage|permissions|cursor|limits)|admin\/(limits|usage|overview|users|profiles|host\/profiles(\/[^/?]+\/(skills|plugins|tools))?|skills\/library))$/;
const cacheKey = (path: string) => 'hermes-cache:' + csrf.slice(0, 12) + ':' + path;
export function peek<T = any>(path: string): T | undefined {
  if (!csrf || !CACHE_PATHS.test(path)) return undefined;
  try {
    const s = sessionStorage.getItem(cacheKey(path));
    return s ? JSON.parse(s) : undefined;
  } catch {
    return undefined;
  }
}
export function clearCache() {
  try {
    for (const k of Object.keys(sessionStorage)) if (k.startsWith('hermes-cache:')) sessionStorage.removeItem(k);
  } catch {
    /* storage off */
  }
}
if (typeof window !== 'undefined') window.addEventListener('hermes-logout', clearCache);
export function setCsrf(token: string) {
  csrf = token;
  try {
    for (const k of Object.keys(sessionStorage))
      if (k.startsWith('hermes-cache:') && !k.startsWith(cacheKey(''))) sessionStorage.removeItem(k);
  } catch {
    /* storage off */
  }
}
export class AuthError extends Error {}
export class TotpRequired extends Error {}

/** toString() without the 'Error: ' prefix — many call sites render String(e). */
export class ApiError extends Error {
  toString() {
    return this.message;
  }
}
export async function api(path: string, options: RequestInit = {}) {
  const headers = new Headers(options.headers);
  if (options.method && options.method !== 'GET') headers.set('X-CSRF-Token', csrf);
  let r: Response;
  try {
    r = await fetch('/api' + path, {...options, headers, credentials: 'same-origin'});
  } catch {
    throw new ApiError(humanize('Failed to fetch'));
  }
  if (r.status === 401 && path !== '/auth/login') {
    window.dispatchEvent(new Event('hermes-logout'));
    throw new AuthError('Сесія завершилась');
  }
  if (!r.ok) {
    let detail = (await r.text()).slice(0, 600);
    let totp = false;
    try {
      const j = JSON.parse(detail);
      if (j.detail && typeof j.detail === 'object') {
        totp = !!j.detail.totp_required;
        if (j.detail.asleep) window.dispatchEvent(new Event('hermes-asleep'));
        detail = j.detail.message ?? detail;
      } else if (typeof j.detail === 'string') detail = j.detail;
    } catch {
      /* keep text */
    }
    if (detail.length > 300 || detail.startsWith('<')) detail = String(r.status);
    detail = humanize(detail);
    throw totp ? new TotpRequired(detail) : new ApiError(detail);
  }
  const data = await r.json();
  if ((!options.method || options.method === 'GET') && csrf && CACHE_PATHS.test(path)) {
    try {
      sessionStorage.setItem(cacheKey(path), JSON.stringify(data));
    } catch {
      /* full or off */
    }
  }
  return data;
}
const json = (method: string, body: unknown): RequestInit => ({
  method,
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify(body),
});

export function Login({onLogin}: {onLogin: (u: User) => void}) {
  const [username, setUsername] = useState(''),
    [password, setPassword] = useState(''),
    [error, setError] = useState(''),
    [busy, setBusy] = useState(false),
    [code, setCode] = useState(''),
    [needCode, setNeedCode] = useState(false);
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError('');
    try {
      const r = await api('/auth/login', json('POST', {username, password, code}));
      setCsrf(r.csrf);
      setPassword('');
      setCode('');
      onLogin(r.user);
    } catch (err) {
      if (err instanceof TotpRequired) {
        if (needCode) setError(err.message);
        setNeedCode(true);
      } else setError(String(err).replace(/^Error: /, ''));
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="login-wrap">
      <form className="login" onSubmit={submit}>
        <div className="brand">
          <Logo size={26} /> <span>SHROOM</span>
        </div>
        <label>
          Логін
          <input autoComplete="username" value={username} onChange={e => setUsername(e.target.value)} required />
        </label>
        <label>
          Пароль
          <input type="password" autoComplete="current-password" value={password} onChange={e => setPassword(e.target.value)} required />
        </label>
        {needCode && (
          <label>
            Код з застосунку-автентифікатора
            <input
              inputMode="numeric"
              autoComplete="one-time-code"
              pattern="[0-9]{6}"
              maxLength={6}
              value={code}
              onChange={e => setCode(e.target.value.replace(/\D/g, ''))}
              autoFocus
              required
            />
          </label>
        )}
        {error && (
          <div className="error" role="alert">
            {error}
          </div>
        )}
        <button className="new" disabled={busy}>
          {busy ? 'Вхід…' : 'Увійти'}
        </button>
      </form>
    </div>
  );
}
