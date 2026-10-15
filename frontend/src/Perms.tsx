import React, {useEffect, useMemo, useState} from 'react';
import {api} from './Auth';
import {Ic, Check, X} from './Icons';

type Item = {name: string; kind: string; meta: string};
type Feature = {key: string; meta: string};
type Rows = Record<string, boolean>;

/** Tri-state permission editor. subject = 'role:user' (defaults) or 'user:<id>' (overrides). */
export function PermissionEditor({
  subject,
  title,
  profile,
  inheritFrom,
}: {
  subject: string;
  title: string;
  profile: string;
  inheritFrom?: string;
}) {
  const [items, setItems] = useState<Item[]>([]),
    [features, setFeatures] = useState<Feature[]>([]),
    [providers, setProviders] = useState<{slug: string; name: string}[]>([]);
  const [rows, setRows] = useState<Rows>({}),
    [base, setBase] = useState<Rows>({}),
    [draft, setDraft] = useState<Record<string, boolean | null>>({});
  const [filter, setFilter] = useState(''),
    [error, setError] = useState(''),
    [saved, setSaved] = useState(''),
    [ready, setReady] = useState(false);
  useEffect(() => {
    (async () => {
      try {
        const cat = await api('/admin/catalog?profile=' + encodeURIComponent(profile));
        setItems(cat.items);
        setFeatures(cat.features);
        setProviders(cat.providers ?? []);
        setRows(await api('/admin/permissions/' + subject));
        if (inheritFrom) setBase(await api('/admin/permissions/' + inheritFrom));
      } catch (e) {
        setError(String(e));
      } finally {
        setReady(true);
      }
    })();
  }, [subject, profile]);
  const value = (k: string) => (k in draft ? draft[k] : k in rows ? rows[k] : null);
  const inherited = (k: string): boolean => {
    const kind = k.split(':')[0] + ':*';
    if (k in base) return base[k];
    const own = value(kind);
    if (own !== null && k !== kind) return own;
    if (kind in base) return base[kind];
    return false;
  };
  const set = async (k: string, v: boolean | null) => {
    setDraft(d => ({...d, [k]: v}));
    setError('');
    try {
      setRows(
        await api('/admin/permissions/' + subject, {
          method: 'PUT',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({changes: {[k]: v}}),
        })
      );
      setDraft(d => {
        const n = {...d};
        delete n[k];
        return n;
      });
      setSaved('Збережено');
      setTimeout(() => setSaved(''), 1500);
    } catch (e) {
      setDraft(d => {
        const n = {...d};
        delete n[k];
        return n;
      });
      setError(String(e));
    }
  };
  const shown = useMemo(
    () => items.filter(i => !filter || i.name.includes(filter.toLowerCase()) || i.meta.toLowerCase().includes(filter.toLowerCase())),
    [items, filter]
  );
  const Row = ({k, label, meta}: {k: string; label: string; meta: string}) => {
    const v = value(k),
      eff = v ?? inherited(k);
    return (
      <tr className={eff ? 'perm-on' : 'perm-off'}>
        <td>
          <code>{label}</code>
        </td>
        <td className="meta">{meta}</td>
        <td>
          <div className="tri" role="radiogroup" aria-label={label}>
            <button type="button" className={v === true ? 'on yes' : ''} aria-pressed={v === true} onClick={() => set(k, true)}>
              Так
            </button>
            <button
              type="button"
              className={v === null ? 'on def' : ''}
              aria-pressed={v === null}
              title={(inheritFrom ? 'Як у правах за замовчуванням' : 'Не задано') + ': ' + (inherited(k) ? 'дозволено' : 'заборонено')}
              onClick={() => set(k, null)}
            >
              Типово
              <span className={'tri-inh ' + (inherited(k) ? 'allow' : 'deny')} aria-label={inherited(k) ? '(дозволено)' : '(заборонено)'}>
                <Ic i={inherited(k) ? Check : X} size={14} />
              </span>
            </button>
            <button type="button" className={v === false ? 'on no' : ''} aria-pressed={v === false} onClick={() => set(k, false)}>
              Ні
            </button>
          </div>
        </td>
      </tr>
    );
  };
  return (
    <div className="perms perms-inline">
      {title && (
        <div className="row">
          <h2>{title}</h2>
        </div>
      )}
      <p className="hint">
        Заборонено все, що явно не дозволено. Адміністратори мають усі права. Перевірка — на сервері, недозволені команди не показуються в
        автодоповненні.
      </p>
      {error && <div className="error">{error}</div>}
      {!ready ? (
        <div className="skeleton-block" aria-busy="true">
          <i />
          <i />
          <i />
          <i />
          <i />
        </div>
      ) : (
        <table>
          <tbody>
            <tr className="perm-group">
              <td colSpan={3}>Загальні правила</td>
            </tr>
            <Row k="cmd:*" label="усі команди" meta="Будь-яка slash-команда, якщо окремо не задано" />
            <Row k="skill:*" label="усі скіли" meta="Будь-який скіл/бандл через /" />
            <tr className="perm-group">
              <td colSpan={3}>Можливості порталу</td>
            </tr>
            {features.map(f => (
              <Row key={f.key} k={f.key} label={f.key.replace('feature:', '')} meta={f.meta} />
            ))}
            <tr className="perm-group">
              <td colSpan={3}>Провайдери для власних підписок</td>
            </tr>
            <Row k="provider:*" label="усі провайдери" meta="Будь-який провайдер з API-ключем, якщо окремо не задано" />
            {providers.map(p => (
              <Row key={p.slug} k={'provider:' + p.slug} label={p.slug} meta={p.name} />
            ))}
            <tr className="perm-group">
              <td colSpan={3}>
                Команди та скіли профілю «{profile}»{' '}
                <input placeholder="фільтр…" value={filter} onChange={e => setFilter(e.target.value)} />
              </td>
            </tr>
            {shown.map(i => (
              <Row
                key={i.kind + i.name}
                k={(i.kind === 'skill' ? 'skill:' : 'cmd:') + i.name}
                label={'/' + i.name}
                meta={(i.kind === 'skill' ? '[скіл] ' : '') + i.meta}
              />
            ))}
          </tbody>
        </table>
      )}
      <div className="perm-status">{saved}</div>
    </div>
  );
}

/** Slash autocomplete popup for the composer. */
export function useSlash(text: string) {
  const [items, setItems] = useState<{text: string; meta: string; kind: string}[]>([]);
  const [index, setIndex] = useState(0);
  const active = text.startsWith('/') && !text.includes('\n');
  useEffect(() => {
    if (!active) {
      setItems([]);
      return;
    }
    const t = setTimeout(() => {
      api('/commands?text=' + encodeURIComponent(text))
        .then(r => {
          setItems(r.items);
          setIndex(0);
        })
        .catch(() => setItems([]));
    }, 120);
    return () => clearTimeout(t);
  }, [text, active]);
  return {items: active ? items : [], index, setIndex};
}

export function SlashMenu({
  items,
  index,
  pick,
}: {
  items: {text: string; meta: string; kind: string}[];
  index: number;
  pick: (t: string) => void;
}) {
  if (!items.length) return null;
  return (
    <div className="slash-menu" role="listbox">
      {items.map((it, i) => (
        <div
          key={it.text}
          role="option"
          aria-selected={i === index}
          className={i === index ? 'on' : ''}
          onMouseDown={e => {
            e.preventDefault();
            pick(it.text);
          }}
        >
          <b>/{it.text.trim().replace(/^\//, '')}</b>
          {it.kind === 'skill' && <em>скіл</em>}
          <span>{it.meta.replace(/^\u26A1\s*/, '')}</span>
        </div>
      ))}
    </div>
  );
}
