import React, {useEffect, useRef, useState} from 'react';
import {createPortal} from 'react-dom';
import {ask, toast} from './Feedback';
import {api, peek, User} from './Auth';
import {NotifySettings} from './Notify';
import {UsersSummary, ProfilesSummary, CostChart} from './AdminSummary';
import {ProfileAgentEditor, confirmAgentDraft} from './ProfileAgentEditor';
import './ProfileAgentEditor.css';
import './PalettePicker.css';
import {PermissionEditor} from './Perms';
import {
  Ic,
  KeyRound,
  Diamond,
  Users as UsersIcon,
  Scale,
  SettingsIcon,
  X,
  Star,
  RotateCw,
  Play,
  Square,
  TriangleAlert,
  Ban,
  Check,
  UserIcon,
  Plus,
  ScrollText,
  Trash2,
  Gauge,
  Activity,
  BookOpen,
  Library,
  Box,
  ChevronDown,
  Palette,
  LightMode,
  DarkMode,
  Contrast,
  Notifications,
} from './Icons';
import {
  current as themeNow,
  currentPalette,
  PALETTES,
  resolve,
  saveTheme,
  saveBackground,
  ThemePref,
  Palette as ColorPalette,
} from './Theme';
import {BACKGROUNDS, Background, ChatBackground, currentBackground} from './Backgrounds';
import {SharedModelsEditor, fetchModels, ModelsData, EFFORT, GROUP, MODELS_CHANGED} from './ModelSwitch';
import {MyLimitsCard, AdminLimitsCards} from './Limits';
import {VpsCard} from './Vps';
import type {IconT as LucideIcon} from './Icons';

type Profile = {
  name: string;
  provider: string;
  model: string;
  description: string;
  bridge: string;
  credentials: string[];
  owner: boolean;
  users: number;
};
type OwnerProvider = {provider: string; auth_type: string; rotating: boolean};
type Tool = {name: string; enabled: boolean; label: string; risky: boolean};
type ModelCatalog = {
  current: {provider: string; model: string};
  providers: {slug: string; name: string; authenticated: boolean; models: string[]}[];
};

const json = (method: string, body: unknown): RequestInit => ({
  method,
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify(body),
});
const err = (e: unknown) => String(e).replace(/^Error: /, '');
type Section =
  | 'agent'
  | 'appearance'
  | 'notify'
  | 'myplugins'
  | 'security'
  | 'model'
  | 'myskills'
  | 'myusage'
  | 'overview'
  | 'usage'
  | 'audit'
  | 'users'
  | 'defaults'
  | 'policy'
  | 'profiles'
  | 'library';
type NavItem = [Section, LucideIcon, string];

/** Settings window over the chat. Two levels: groups (headers) -> sections; heavy objects (profile, user) get tabs inside.
 *  Every function lives in exactly one place. Admin groups are shown only to admins (and enforced server-side). */
export function Settings({me, onClose}: {me: User; onClose: () => void}) {
  const admin = me.role === 'admin' && !me.must_enroll;
  const [feat, setFeat] = useState<Record<string, boolean>>(() => peek('/me/permissions') ?? {});
  const [permissionsReady, setPermissionsReady] = useState(me.role === 'admin' || !!peek('/me/permissions'));
  useEffect(() => {
    if (me.role !== 'admin')
      api('/me/permissions')
        .then(setFeat)
        .catch(() => {})
        .finally(() => setPermissionsReady(true));
  }, []);
  const ownSubs = !!feat['feature:own_subscriptions'],
    ownSkills = !!feat['feature:own_skills'],
    ownPlugins = !!feat['feature:own_plugins'];
  const ownSoul = !!feat['feature:own_soul'],
    ownMemory = !!feat['feature:own_memory'],
    cursor = !!feat['feature:cursor_agent'];
  // Warm the slow pages one by one in the background (host calls), so a later click shows them at once.
  useEffect(() => {
    if (!permissionsReady) return;
    let on = true;
    const paths = admin
      ? ['/admin/limits', '/admin/usage', '/admin/host/profiles', '/admin/skills/library']
      : [
          '/me/models',
          ...(ownSubs ? ['/me/providers'] : []),
          ...(cursor ? ['/me/cursor'] : []),
          '/me/limits',
          ownSkills ? '/me/skills/manage' : '/me/skills',
          ...(ownPlugins ? ['/me/plugins'] : []),
          '/me/usage',
        ];
    (async () => {
      for (const x of paths) {
        if (!on) return;
        if (!peek(x)) await api(x).catch(() => {});
      }
    })();
    return () => {
      on = false;
    };
  }, [permissionsReady, admin, ownSubs, ownSkills, ownPlugins, cursor]);
  const defaults = me.role === 'admin' || !!feat['feature:switch_model'] || !!feat['cmd:reasoning'];
  const groups: [string, NavItem[]][] = [
    [
      'Обліковий запис',
      [
        ['security', KeyRound, 'Вхід і безпека'],
        ['appearance', Palette, 'Вигляд'],
        ['notify', Notifications, 'Сповіщення'],
        ...(me.role === 'admin' ? ([['model', Gauge, 'Типова модель']] as NavItem[]) : []),
        ...(me.role !== 'admin'
          ? ([
              ...(ownSubs || cursor || defaults ? [['model', Gauge, 'Модель і підписки']] : []),
              ['myskills', BookOpen, 'Скіли'],
              ...(ownSoul || ownMemory ? [['agent', BookOpen, 'Особистість і памʼять']] : []),
              ...(ownPlugins ? [['myplugins', Box, 'Плагіни']] : []),
              ['myusage', Activity, 'Використання'],
            ] as NavItem[])
          : []),
      ],
    ],
    ...(admin
      ? ([
          [
            'Моніторинг',
            [
              ['overview', Activity, 'Огляд'],
              ['usage', Gauge, 'Витрати і ліміти'],
              ['audit', ScrollText, 'Журнал дій'],
            ],
          ],
          [
            'Люди',
            [
              ['users', UsersIcon, 'Користувачі'],
              ['defaults', Scale, 'Права за замовчуванням'],
              ['policy', Ban, 'Політика безпеки'],
            ],
          ],
          [
            'Агент',
            [
              ['profiles', Diamond, 'Профілі'],
              ['library', Library, 'Бібліотека скілів'],
            ],
          ],
        ] as [string, NavItem[]][])
      : []),
  ];
  const allowedSections = groups.flatMap(([, items]) => items.map(([k]) => k));
  const sectionKey = `shroom-settings-section:${me.username}:${me.profile}`;
  const [section, setSectionRaw] = useState<Section>(admin ? 'overview' : 'security');
  useEffect(() => {
    if (!permissionsReady) return;
    const saved = localStorage.getItem(sectionKey) as Section | null;
    if (saved && allowedSections.includes(saved)) setSectionRaw(saved);
  }, [permissionsReady, sectionKey]);
  const setSection = async (k: Section) => {
    if (k === section) return;
    if (!(await confirmAgentDraft())) return;
    setSectionRaw(k);
    localStorage.setItem(sectionKey, k);
  };
  async function closeSettings() {
    if (await confirmAgentDraft()) onClose();
  }
  useEffect(() => {
    const f = (e: KeyboardEvent) => {
      if (e.key === 'Escape') void closeSettings();
    };
    window.addEventListener('keydown', f);
    return () => window.removeEventListener('keydown', f);
  }, []);
  const page = (title: string, body: React.ReactNode, hint?: string) => (
    <div className="detail-pane">
      <div className="page-head">
        <h1>{title}</h1>
        {hint && <p className="hint">{hint}</p>}
      </div>
      <div className="cards">{body}</div>
    </div>
  );
  return createPortal(
    <div
      className="overlay settings-overlay"
      onMouseDown={e => {
        if (e.target === e.currentTarget) void closeSettings();
      }}
    >
      <div className="settings-window" role="dialog" aria-label="Налаштування">
        <aside>
          <div className="settings-title">
            <Ic i={SettingsIcon} /> Налаштування
          </div>
          <nav>
            {groups.map(([g, items], gi) => (
              <React.Fragment key={g}>
                <div className={'nav-group' + (gi ? '' : ' first')}>{g}</div>
                {items.map(([k, icon, label]) => (
                  <button
                    key={k}
                    title={label}
                    aria-label={label}
                    className={section === k ? 'selected' : ''}
                    onClick={() => setSection(k)}
                  >
                    <Ic i={icon} /> {label}
                  </button>
                ))}
              </React.Fragment>
            ))}
          </nav>
          <div className="aside-foot">
            <Ic i={UserIcon} size={16} /> {me.username} · {me.role === 'admin' ? 'адміністратор' : 'користувач'} · {me.profile}
          </div>
        </aside>
        <main className="settings-main">
          <button className="close icon" title="Закрити (Esc)" onClick={() => void closeSettings()}>
            <Ic i={X} />
          </button>
          {section === 'appearance' &&
            page('Вигляд', <Appearance />, 'Тема зберігається у вашому обліковому записі й діє на всіх пристроях.')}
          {section === 'notify' &&
            page('Сповіщення', <NotifySettings uid={me.id} />, 'Коли агент закінчив відповідь або чекає на вас, а вкладка у фоні.')}
          {section === 'security' &&
            page(
              'Вхід і безпека',
              <>
                <PasswordForm />
                <TwoFactor me={me} />
              </>
            )}
          {section === 'model' &&
            (ownSubs || cursor || defaults) &&
            page(
              me.role === 'admin' ? 'Типова модель' : 'Модель і підписки',
              <>
                {defaults && <ModelDefaults />}
                {me.role !== 'admin' && ownSubs && <MySubscriptions />}
                {me.role !== 'admin' && cursor && <CursorAgent />}
              </>,
              'Типові модель і міркування для нових чатів. У кожному чаті їх можна змінити в шапці, це не впливає на інші чати.'
            )}
          {section === 'agent' &&
            (ownSoul || ownMemory) &&
            page('Особистість і памʼять', <ProfileAgentEditor base="/me/agent" soul={ownSoul} memory={ownMemory} />)}
          {section === 'myskills' && page('Скіли', ownSkills ? <OwnSkills profile={me.profile} /> : <MySkills />)}
          {section === 'myplugins' && ownPlugins && page('Плагіни', <PluginsPane base="/me/plugins" />, 'Плагіни вашого профілю Shroom.')}
          {section === 'myusage' &&
            page(
              'Використання',
              <>
                <MyLimitsCard />
                <MyUsage />
              </>
            )}
          {admin && section === 'overview' && <Overview go={setSection} />}
          {admin && section === 'usage' && <Usage />}
          {admin && section === 'audit' && <Audit />}
          {admin && section === 'users' && <Users me={me} />}
          {admin && section === 'defaults' && <Defaults />}
          {admin &&
            section === 'policy' &&
            page('Політика безпеки', <SecurityPolicy me={me} />, 'Правила входу для всіх облікових записів.')}
          {admin && section === 'profiles' && <Profiles />}
          {admin &&
            section === 'library' &&
            page(
              'Бібліотека скілів',
              <LibraryPane />,
              'Спільні скіли. Підключення бібліотеки та вмикання окремих скілів — у профілі, вкладка «Скіли».'
            )}
        </main>
      </div>
    </div>,
    document.body
  );
}

function Appearance() {
  const [t, setT] = useState<ThemePref>(themeNow()),
    [palette, setPalette] = useState<ColorPalette>(currentPalette()),
    [err, setErr] = useState(''),
    [saving, setSaving] = useState(false);
  const opts: [ThemePref, LucideIcon, string, string][] = [
    ['system', Contrast, 'Як у системі', 'Перемикається разом з налаштуванням ОС'],
    ['light', LightMode, 'Світла', 'Світлий фон, темний текст'],
    ['dark', DarkMode, 'Темна', 'Темний фон, світлий текст'],
  ];
  const [bg, setBg] = useState<Background>(currentBackground());
  async function chooseBg(next: Background) {
    if (saving || next === bg) return;
    const old = bg;
    setBg(next);
    setErr('');
    setSaving(true);
    try {
      await saveBackground(next);
    } catch (e) {
      setBg(old);
      setErr(String(e));
    } finally {
      setSaving(false);
    }
  }
  async function choose(mode: ThemePref, color: ColorPalette) {
    if (saving || (mode === t && color === palette)) return;
    const oldMode = t,
      oldPalette = palette;
    setT(mode);
    setPalette(color);
    setErr('');
    setSaving(true);
    try {
      await saveTheme(mode, color);
    } catch (e) {
      setT(oldMode);
      setPalette(oldPalette);
      setErr(String(e));
    } finally {
      setSaving(false);
    }
  }
  return (
    <div className="card">
      <h3>Режим оформлення</h3>
      {err && (
        <div className="error" role="alert">
          {err}
        </div>
      )}
      <div className="theme-pick" role="radiogroup" aria-label="Світлий або темний режим">
        {opts.map(([k, icon, l, d]) => (
          <button
            key={k}
            role="radio"
            aria-checked={t === k}
            disabled={saving}
            className={'theme-opt' + (t === k ? ' on' : '')}
            onClick={() => choose(k, palette)}
          >
            <span className={'theme-preview ' + k}>
              <i />
              <i />
              <i />
            </span>
            <b>
              <Ic i={icon} size={18} /> {l}
            </b>
            <small>{d}</small>
          </button>
        ))}
      </div>
      <h3 className="palette-heading">Кольорова палітра</h3>
      <div className="palette-pick" role="radiogroup" aria-label="Кольорова палітра">
        {(Object.keys(PALETTES) as ColorPalette[]).map(k => {
          const p = PALETTES[k],
            colors = p[resolve(t)];
          return (
            <button
              key={k}
              role="radio"
              aria-label={p.name}
              aria-checked={palette === k}
              disabled={saving}
              className={'theme-opt palette-opt' + (palette === k ? ' on' : '')}
              onClick={() => choose(t, k)}
            >
              <span className="palette-preview" aria-hidden="true" style={{background: colors.surface}}>
                <i style={{background: colors.accent}} />
                <i style={{background: colors.text}} />
                <i style={{background: colors.muted}} />
              </span>
              <b>
                {p.name}
                {palette === k && <Ic i={Check} size={16} />}
              </b>
              <small>{p.description}</small>
            </button>
          );
        })}
      </div>
      <p className="hint">Кожна палітра має світлий і темний варіанти. Вибір зберігається у вашому акаунті й застосовується одразу.</p>
      <h3 className="palette-heading">Фон чату</h3>
      <div className="palette-pick bg-pick" role="radiogroup" aria-label="Фон чату">
        {(Object.keys(BACKGROUNDS) as Background[]).map(k => (
          <button
            key={k}
            role="radio"
            aria-label={BACKGROUNDS[k].name}
            aria-checked={bg === k}
            disabled={saving}
            className={'theme-opt palette-opt' + (bg === k ? ' on' : '')}
            onClick={() => chooseBg(k)}
          >
            <span className="palette-preview bg-preview" aria-hidden="true">
              <ChatBackground kind={k} density={0.6} />
            </span>
            <b>
              {BACKGROUNDS[k].name}
              {bg === k && <Ic i={Check} size={16} />}
            </b>
            <small>{BACKGROUNDS[k].description}</small>
          </button>
        ))}
      </div>
      <p className="hint">Фон суто декоративний і нічого не показує. За замовчуванням його немає.</p>
      {saving && (
        <p className="hint" role="status">
          Зберігаємо оформлення…
        </p>
      )}
    </div>
  );
}

/** M3 secondary tabs */
function Tabs<T extends string>({tabs, value, onChange}: {tabs: [T, string][]; value: T; onChange: (t: T) => void}) {
  const nav = useRef<HTMLDivElement>(null);
  useEffect(() => {
    nav.current?.querySelector<HTMLElement>('[aria-selected="true"]')?.scrollIntoView?.({block: 'nearest', inline: 'nearest'});
  }, [value]);
  return (
    <div ref={nav} className="tabs" role="tablist">
      {tabs.map(([k, l]) => (
        <button
          key={k}
          role="tab"
          aria-selected={value === k}
          className={value === k ? 'on' : ''}
          onClick={async () => {
            if (k === value || (await confirmAgentDraft())) onChange(k);
          }}
        >
          {l}
        </button>
      ))}
    </div>
  );
}

function TwoFactor({me}: {me: User}) {
  const [on, setOn] = useState(!!me.totp),
    [setup, setSetup] = useState<{secret: string; uri: string} | null>(null),
    [code, setCode] = useState(''),
    [pw, setPw] = useState(''),
    [msg, setMsg] = useState(''),
    [ok, setOk] = useState(false);
  async function run(fn: () => Promise<void>) {
    setMsg('');
    setOk(false);
    try {
      await fn();
    } catch (e) {
      setMsg(err(e));
    }
  }
  return (
    <div className="card">
      <h3>Двофакторний вхід</h3>
      {on ? (
        <>
          <p className="hint">Увімкнено: при вході потрібен 6-значний код із застосунку-автентифікатора.</p>
          <div className="row grow">
            <label>
              Пароль
              <input type="password" autoComplete="current-password" value={pw} onChange={e => setPw(e.target.value)} />
            </label>
            <label>
              Код
              <input inputMode="numeric" maxLength={6} value={code} onChange={e => setCode(e.target.value.replace(/\D/g, ''))} />
            </label>
            <button
              disabled={!pw || code.length !== 6}
              onClick={() =>
                run(async () => {
                  await api('/auth/totp/disable', json('POST', {code, password: pw}));
                  setOn(false);
                  setPw('');
                  setCode('');
                  setOk(true);
                  setMsg('Двофакторний вхід вимкнено.');
                })
              }
            >
              Вимкнути
            </button>
          </div>
        </>
      ) : setup ? (
        <>
          <p className="hint">
            Додайте ключ у застосунок-автентифікатор (Google Authenticator, Aegis, 1Password тощо) вручну або через посилання, потім введіть
            код для підтвердження.
          </p>
          <label>
            Ключ<code className="secret-key">{setup.secret.match(/.{1,4}/g)?.join(' ')}</code>
          </label>
          <a className="hint" href={setup.uri}>
            Відкрити в застосунку-автентифікаторі
          </a>
          <div className="row grow">
            <label>
              Код
              <input inputMode="numeric" maxLength={6} value={code} onChange={e => setCode(e.target.value.replace(/\D/g, ''))} />
            </label>
            <button
              className="send"
              disabled={code.length !== 6}
              onClick={() =>
                run(async () => {
                  await api('/auth/totp/enable', json('POST', {code}));
                  setOn(true);
                  setSetup(null);
                  setCode('');
                  setOk(true);
                  setMsg('Двофакторний вхід увімкнено.');
                })
              }
            >
              Підтвердити
            </button>
          </div>
        </>
      ) : (
        <>
          <p className="hint">Додатковий захист облікового запису кодом із телефона. Рекомендовано для адміністраторів.</p>
          <button onClick={() => run(async () => setSetup(await api('/auth/totp/setup', {method: 'POST'})))}>Увімкнути</button>
        </>
      )}
      {msg && <div className={ok ? 'warning' : 'error'}>{msg}</div>}
    </div>
  );
}

function PasswordForm() {
  const [old, setOld] = useState(''),
    [next, setNext] = useState(''),
    [repeat, setRepeat] = useState(''),
    [msg, setMsg] = useState(''),
    [ok, setOk] = useState(false);
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setOk(false);
    if (next !== repeat) {
      setMsg('Нові паролі не збігаються');
      return;
    }
    try {
      await api('/auth/password', json('POST', {old, new: next}));
      setOk(true);
      setMsg('Пароль змінено. Інші сесії завершено.');
      toast('Пароль змінено');
      setOld('');
      setNext('');
      setRepeat('');
    } catch (er) {
      setMsg(err(er));
    }
  }
  return (
    <form className="card" onSubmit={submit}>
      <h3>Зміна пароля</h3>
      <label>
        Поточний пароль
        <input type="password" autoComplete="current-password" value={old} onChange={e => setOld(e.target.value)} required />
      </label>
      <label>
        Новий пароль (мін. 12 символів)
        <input type="password" autoComplete="new-password" minLength={12} value={next} onChange={e => setNext(e.target.value)} required />
      </label>
      <label>
        Повторіть новий
        <input
          type="password"
          autoComplete="new-password"
          minLength={12}
          value={repeat}
          onChange={e => setRepeat(e.target.value)}
          required
        />
      </label>
      {msg && <div className={ok ? 'warning' : 'error'}>{msg}</div>}
      <div className="actions">
        <button className="send">Змінити пароль</button>
      </div>
    </form>
  );
}

function Profiles() {
  const [list, setList] = useState<Profile[]>(() => peek('/admin/host/profiles') ?? []),
    [owner, setOwner] = useState<OwnerProvider[]>([]);
  const [sel, setSel] = useState(''),
    [error, setError] = useState(''),
    [busy, setBusy] = useState(false),
    [creating, setCreating] = useState(false);
  const [q, setQ] = useState('');
  async function load() {
    try {
      setList(await api('/admin/host/profiles'));
    } catch (e) {
      setError(err(e));
    }
  }
  useEffect(() => {
    load();
    api('/admin/host/owner-providers')
      .then(setOwner)
      .catch(() => {});
  }, []);
  async function act(fn: () => Promise<unknown>) {
    setBusy(true);
    setError('');
    try {
      await fn();
      await load();
      toast('Готово');
    } catch (e) {
      setError(err(e));
      toast('Не вдалося: ' + err(e).slice(0, 120), 'error');
    } finally {
      setBusy(false);
    }
  }
  const cur = list.find(p => p.name === sel);
  return (
    <div className="split">
      <section className="list-pane">
        <div className="row">
          <h2>Профілі</h2>
          <button
            className="new"
            onClick={async () => {
              if (!(await confirmAgentDraft())) return;
              setCreating(true);
              setSel('');
            }}
          >
            <Ic i={Plus} /> Створити
          </button>
        </div>
        {list.length > 5 && <input className="list-search" placeholder="Пошук профілю" value={q} onChange={e => setQ(e.target.value)} />}
        {list
          .filter(p => !q.trim() || (p.name + ' ' + (p.model ?? '')).toLowerCase().includes(q.trim().toLowerCase()))
          .map(p => (
            <button
              key={p.name}
              className={'item ' + (p.name === sel ? 'selected' : '')}
              onClick={async () => {
                if (p.name !== sel && !(await confirmAgentDraft())) return;
                setSel(p.name);
                setCreating(false);
              }}
            >
              <b>
                {p.name}
                {p.owner && <Ic i={Star} size={12} className="owner" />}
              </b>
              <small>
                {p.model || '—'} ·{' '}
                <span className={'st ' + p.bridge}>
                  <i className="dot" />
                  {p.bridge === 'active' ? 'працює' : 'зупинено'}
                </span>{' '}
                · {p.users} корист.
              </small>
            </button>
          ))}
        {!list.length && !error && (
          <div className="skeleton-block" aria-busy="true">
            <i />
            <i />
            <i />
          </div>
        )}
      </section>
      <section className="detail-pane">
        {error && <div className="error">{error}</div>}
        {busy && <div className="warning">Виконується… (операції з профілем можуть тривати до хвилини)</div>}
        {creating && (
          <CreateProfile
            owner={owner}
            onDone={async name => {
              setCreating(false);
              await load();
              setSel(name);
            }}
            setError={setError}
          />
        )}
        {cur && <ProfileDetail key={cur.name} p={cur} owner={owner} act={act} />}
        {!cur &&
          !creating &&
          (list.length ? (
            <ProfilesSummary
              list={list}
              onPick={async name => {
                if (!(await confirmAgentDraft())) return;
                setSel(name);
              }}
            />
          ) : (
            <p className="hint">Оберіть профіль або створіть новий.</p>
          ))}
      </section>
    </div>
  );
}

/** Searchable model list (M3 menu). Typing filters; a value not in the list can still be used explicitly. */
function ModelSelect({
  value,
  models,
  onChange,
  disabled,
}: {
  value: string;
  models: string[];
  onChange: (m: string) => void;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false),
    [q, setQ] = useState(''),
    box = React.useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const f = (e: MouseEvent) => {
      if (!box.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', f);
    return () => document.removeEventListener('mousedown', f);
  }, [open]);
  const t = q.trim().toLowerCase(),
    list = models.filter(m => !t || m.toLowerCase().includes(t));
  const pick = (m: string) => {
    onChange(m);
    setOpen(false);
    setQ('');
  };
  return (
    <div className="msel" ref={box}>
      <button type="button" className="msel-field" disabled={disabled} onClick={() => setOpen(!open)}>
        <span>{value || 'Оберіть модель'}</span>
        <Ic i={ChevronDown} size={18} />
      </button>
      {open && (
        <div className="msel-menu">
          <input
            autoFocus
            placeholder={models.length ? `Пошук серед ${models.length}…` : 'Назва моделі'}
            value={q}
            onChange={e => setQ(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter' && (list[0] || t)) {
                e.preventDefault();
                pick(list[0] ?? q.trim());
              }
              if (e.key === 'Escape') {
                e.stopPropagation();
                setOpen(false);
              }
            }}
          />
          <div className="msel-list">
            {list.map(m => (
              <button type="button" key={m} className={m === value ? 'on' : ''} onClick={() => pick(m)}>
                {m}
              </button>
            ))}
            {t && !models.includes(q.trim()) && (
              <button type="button" className="custom" onClick={() => pick(q.trim())}>
                Використати «{q.trim()}»
              </button>
            )}
            {!list.length && !t && <p className="hint">Список моделей недоступний. Введіть назву вручну.</p>}
          </div>
        </div>
      )}
    </div>
  );
}

function ModelPicker({
  profile,
  provider,
  model,
  onChange,
}: {
  profile?: string;
  provider: string;
  model: string;
  onChange: (p: string, m: string) => void;
}) {
  const [cat, setCat] = useState<ModelCatalog | null>(null);
  useEffect(() => {
    if (profile)
      api(`/admin/host/profiles/${profile}/models`)
        .then(setCat)
        .catch(() => setCat(null));
  }, [profile]);
  const models = cat?.providers.find(p => p.slug === provider)?.models ?? [];
  return (
    <div className="row grow">
      <label>
        Провайдер
        <select
          value={provider}
          onChange={e => {
            const ms = cat?.providers.find(p => p.slug === e.target.value)?.models ?? [];
            onChange(e.target.value, ms[0] ?? '');
          }}
          required
        >
          {cat ? (
            <>
              {[
                ['Підключені', true],
                ['Без ключа', false],
              ].map(([g, a]) => (
                <optgroup key={String(g)} label={String(g)}>
                  {cat.providers
                    .filter(p => p.authenticated === a)
                    .map(p => (
                      <option key={p.slug} value={p.slug}>
                        {p.name}
                      </option>
                    ))}
                </optgroup>
              ))}
              {!cat.providers.some(p => p.slug === provider) && provider && <option value={provider}>{provider}</option>}
            </>
          ) : (
            [...new Set([provider, 'anthropic', 'openai-codex', 'openrouter', 'openai'])].filter(Boolean).map(p => (
              <option key={p} value={p}>
                {p}
              </option>
            ))
          )}
        </select>
      </label>
      <label>
        Модель
        <ModelSelect value={model} models={models} onChange={m => onChange(provider, m)} />
      </label>
    </div>
  );
}

function CreateProfile({owner, onDone, setError}: {owner: OwnerProvider[]; onDone: (name: string) => void; setError: (s: string) => void}) {
  const [name, setName] = useState(''),
    [provider, setProvider] = useState('anthropic'),
    [model, setModel] = useState('claude-haiku-4-5'),
    [description, setDescription] = useState('');
  const [cred, setCred] = useState(''),
    [rotation, setRotation] = useState(false),
    [busy, setBusy] = useState(false);
  const rot = owner.find(o => o.provider === cred)?.rotating;
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError('');
    try {
      await api(
        '/admin/host/profiles',
        json('POST', {name, provider, model, description, credential_from: cred || null, accept_rotation: rotation})
      );
      onDone(name);
    } catch (er) {
      setError(err(er));
    } finally {
      setBusy(false);
    }
  }
  return (
    <form className="card" onSubmit={submit}>
      <h2>Новий профіль</h2>
      <label>
        Назва (латиниця, a-z 0-9 _ -)
        <input value={name} onChange={e => setName(e.target.value.toLowerCase())} pattern="[a-z0-9][a-z0-9_-]{0,31}" required />
      </label>
      <label>
        Опис
        <input value={description} onChange={e => setDescription(e.target.value)} maxLength={300} />
      </label>
      <ModelPicker
        profile="default"
        provider={provider}
        model={model}
        onChange={(p, m) => {
          setProvider(p);
          setModel(m);
        }}
      />
      <label>
        Підписка від власника (необовʼязково)
        <select
          value={cred}
          onChange={e => {
            setCred(e.target.value);
            setRotation(false);
          }}
        >
          <option value="">— не копіювати —</option>
          {owner.map(o => (
            <option key={o.provider} value={o.provider}>
              {o.provider} ({o.auth_type}
              {o.rotating ? ', ротаційний токен' : ''})
            </option>
          ))}
        </select>
      </label>
      {rot && (
        <label className="warn-check">
          <input type="checkbox" checked={rotation} onChange={e => setRotation(e.target.checked)} /> Розумію: цей OAuth-токен оновлюється з
          ротацією, спільне використання може розлогінити власника.
        </label>
      )}
      <p className="hint">
        Нові профілі отримують безпечний набір інструментів: термінал, файли, код, браузер, cron, делегування вимкнені. Термінал, файли і
        код можна увімкнути після ввімкнення пісочниці Docker. Міст запуститься автоматично.
      </p>
      <button className="send" disabled={busy}>
        {busy ? 'Створення…' : 'Створити профіль'}
      </button>
    </form>
  );
}

function ProfileDetail({p, owner, act}: {p: Profile; owner: OwnerProvider[]; act: (fn: () => Promise<unknown>) => Promise<void>}) {
  const [provider, setProvider] = useState(p.provider),
    [model, setModel] = useState(p.model);
  const [tools, setTools] = useState<Tool[]>([]),
    [draft, setDraft] = useState<Record<string, boolean>>({});
  const [cred, setCred] = useState(''),
    [rotation, setRotation] = useState(false),
    [confirm, setConfirm] = useState('');
  const [iso, setIso] = useState<{enabled: boolean; memory_mb: number; cpus: number; network: boolean} | null>(null),
    [isoDraft, setIsoDraft] = useState<{memory_mb: number; cpus: number; network: boolean} | null>(null);
  useEffect(() => {
    api(`/admin/host/profiles/${p.name}/tools`)
      .then(setTools)
      .catch(() => {});
    api(`/admin/host/profiles/${p.name}/isolation`)
      .then(x => {
        setIso(x);
        setIsoDraft({memory_mb: x.memory_mb > 6144 ? 2048 : x.memory_mb, cpus: x.cpus, network: x.network});
      })
      .catch(() => {});
  }, [p.name]);
  const SANDBOXED = ['terminal', 'file', 'code_execution'];
  async function saveIso(enabled: boolean) {
    await act(async () => {
      setIso(await api(`/admin/host/profiles/${p.name}/isolation`, json('PUT', {enabled, ...isoDraft})));
      setTools(await api(`/admin/host/profiles/${p.name}/tools`));
    });
  }
  const changed = Object.keys(draft).filter(k => tools.find(t => t.name === k)?.enabled !== draft[k]);
  const rot = owner.find(o => o.provider === cred)?.rotating;
  const [tab, setTab] = useState<'main' | 'model' | 'tools' | 'skills' | 'plugins' | 'identity'>('main');
  const [skErr, setSkErr] = useState('');
  return (
    <div className="cards">
      <div className="page-head">
        <h1>
          {p.name}
          {p.owner && <span className="tag">власник</span>}
        </h1>
        {p.description && <p className="hint">{p.description}</p>}
      </div>
      <Tabs
        tabs={[
          ['main', 'Загальне'],
          ['model', 'Модель і ключі'],
          ['tools', 'Інструменти'],
          ['skills', 'Скіли'],
          ['plugins', 'Плагіни'],
          ['identity', 'Особистість і памʼять'],
        ]}
        value={tab}
        onChange={setTab}
      />
      {tab === 'identity' && <ProfileAgentEditor base={`/admin/host/profiles/${p.name}`} admin />}
      {tab === 'plugins' && <PluginsPane base={`/admin/host/profiles/${p.name}/plugins`} owner={p.owner} />}
      {tab === 'skills' && (
        <>
          {skErr && <div className="error">{skErr}</div>}
          <ProfileSkills name={p.name} setError={setSkErr} />
        </>
      )}
      {tab === 'main' && (
        <div className="card">
          <div className="row">
            <h3>Міст</h3>
            <span className={'st ' + p.bridge}>
              <i className="dot" />
              {p.bridge === 'active' ? 'працює' : 'зупинено'}
            </span>
          </div>
          <div className="row">
            {p.bridge === 'active' ? (
              <>
                {!p.owner && (
                  <button onClick={() => act(() => api(`/admin/host/profiles/${p.name}/bridge`, json('POST', {action: 'stop'})))}>
                    <Ic i={Square} size={13} /> Зупинити
                  </button>
                )}
                <button onClick={() => act(() => api(`/admin/host/profiles/${p.name}/bridge`, json('POST', {action: 'restart'})))}>
                  <Ic i={RotateCw} /> Перезапустити
                </button>
              </>
            ) : (
              <button
                className="new"
                onClick={() => act(() => api(`/admin/host/profiles/${p.name}/bridge`, json('POST', {action: 'start'})))}
              >
                <Ic i={Play} /> Запустити міст
              </button>
            )}
            <span className="hint">Користувачів: {p.users}. Перезапуск обриває активні відповіді.</span>
          </div>
        </div>
      )}

      {tab === 'model' && (
        <div className="card">
          <h3>Модель</h3>
          {p.owner ? (
            <p>
              {p.provider} / {p.model}
            </p>
          ) : (
            <ModelPicker
              profile={p.bridge === 'active' ? p.name : undefined}
              provider={provider}
              model={model}
              onChange={(a, b) => {
                setProvider(a);
                setModel(b);
              }}
            />
          )}
          {p.owner ? (
            <p className="hint">
              Модель головного профілю змінюється на сервері власника (команда hermes model), щоб випадково не зачепити месенджери та інші
              сервіси.
            </p>
          ) : (
            <button
              className="send"
              disabled={provider === p.provider && model === p.model}
              onClick={() => act(() => api(`/admin/host/profiles/${p.name}/model`, json('PUT', {provider, model})))}
            >
              Зберегти модель
            </button>
          )}
        </div>
      )}

      {tab === 'model' && (
        <div className="card">
          <h3>Підписки і ключі</h3>
          <p className="hint">
            Збережені в профілі: {p.credentials.length ? p.credentials.join(', ') : 'немає'}. Shroom також сам підхоплює вхід Claude Code /
            Codex, наявний на сервері, тому провайдер може працювати і без запису тут.
          </p>
          {p.credentials.map(
            c =>
              !p.owner && (
                <button key={c} onClick={() => act(() => api(`/admin/host/profiles/${p.name}/credentials/${c}`, {method: 'DELETE'}))}>
                  <Ic i={X} /> Прибрати {c}
                </button>
              )
          )}
          {!p.owner && (
            <div className="row">
              <select
                value={cred}
                onChange={e => {
                  setCred(e.target.value);
                  setRotation(false);
                }}
              >
                <option value="">Надати підписку власника…</option>
                {owner.map(o => (
                  <option key={o.provider} value={o.provider}>
                    {o.provider} ({o.auth_type})
                  </option>
                ))}
              </select>
              {rot && (
                <label className="warn-check">
                  <input type="checkbox" checked={rotation} onChange={e => setRotation(e.target.checked)} /> ротаційний токен — розумію
                  ризик
                </label>
              )}
              <button
                disabled={!cred}
                onClick={() =>
                  act(() => api(`/admin/host/profiles/${p.name}/credentials`, json('POST', {provider: cred, accept_rotation: rotation})))
                }
              >
                Надати
              </button>
            </div>
          )}
          <p className="hint">
            Власні ключі користувачі підключають самі в «Обліковому записі», якщо їм дозволено «own_subscriptions» у правах.
          </p>
        </div>
      )}

      {tab === 'tools' && !p.owner && iso && isoDraft && (
        <div className="card">
          <div className="row">
            <h3>Пісочниця Docker</h3>
            <span className={'st ' + (iso.enabled ? 'active' : 'inactive')}>
              <i className="dot" />
              {iso.enabled ? 'увімкнено' : 'вимкнено'}
            </span>
          </div>
          <p className="hint">
            Термінал, файли та виконання коду працюють в окремому контейнері (нативний terminal.backend: docker) без доступу до файлів
            сервера, ключів і Docker. Лише з пісочницею ці інструменти можна увімкнути.
          </p>
          <div className="row grow">
            <label>
              Памʼять, МБ
              <input
                type="number"
                min={256}
                max={6144}
                step={256}
                value={isoDraft.memory_mb}
                onChange={e => setIsoDraft({...isoDraft, memory_mb: Number(e.target.value)})}
              />
            </label>
            <label>
              CPU
              <input
                type="number"
                min={0.25}
                max={2}
                step={0.25}
                value={isoDraft.cpus}
                onChange={e => setIsoDraft({...isoDraft, cpus: Number(e.target.value)})}
              />
            </label>
            <label className="warn-check">
              <input type="checkbox" checked={isoDraft.network} onChange={e => setIsoDraft({...isoDraft, network: e.target.checked})} />{' '}
              доступ до інтернету
            </label>
          </div>
          <div className="row">
            {iso.enabled ? (
              <>
                <button onClick={() => saveIso(true)}>Зберегти параметри</button>
                <button
                  onClick={async () =>
                    (await ask('Вимкнути пісочницю?', {text: 'Термінал, файли і код буде вимкнено.', danger: true, ok: 'Вимкнути'})) &&
                    saveIso(false)
                  }
                >
                  Вимкнути
                </button>
              </>
            ) : (
              <button className="send" onClick={() => saveIso(true)}>
                Увімкнути пісочницю
              </button>
            )}
            <span className="hint">Застосування перезапускає міст профілю.</span>
          </div>
        </div>
      )}

      {tab === 'tools' && (
        <div className="card">
          <h3>Інструменти агента</h3>
          <div className="tools">
            {tools.map(t => {
              const on = draft[t.name] ?? t.enabled;
              return (
                <label key={t.name} className={on ? 'on' : ''}>
                  <input
                    type="checkbox"
                    checked={on}
                    disabled={p.owner || (!on && SANDBOXED.includes(t.name) && !iso?.enabled)}
                    onChange={e => setDraft(d => ({...d, [t.name]: e.target.checked}))}
                  />{' '}
                  {t.label}
                  {SANDBOXED.includes(t.name) ? (
                    <em title={iso?.enabled ? 'Виконується в пісочниці' : 'Потрібна пісочниця Docker'}>
                      <Ic i={iso?.enabled ? Box : TriangleAlert} size={13} />
                    </em>
                  ) : (
                    t.risky && (
                      <em title="Працює на сервері без ізоляції">
                        <Ic i={TriangleAlert} size={13} />
                      </em>
                    )
                  )}
                </label>
              );
            })}
          </div>
          {p.owner ? (
            <p className="hint">Інструменти профілю власника тут не змінюються.</p>
          ) : (
            <button
              className="send"
              disabled={!changed.length}
              onClick={() =>
                act(async () => {
                  setTools(
                    await api(
                      `/admin/host/profiles/${p.name}/tools`,
                      json('PUT', {enable: changed.filter(k => draft[k]), disable: changed.filter(k => !draft[k])})
                    )
                  );
                  setDraft({});
                })
              }
            >
              Зберегти інструменти ({changed.length})
            </button>
          )}
        </div>
      )}

      {tab === 'main' && !p.owner && (
        <div className="card danger">
          <h3>Видалити профіль</h3>
          <p className="hint">Незворотно: памʼять, скіли, історія. Спершу переведіть користувачів на інший профіль.</p>
          <div className="row">
            <input placeholder={`введіть «${p.name}»`} value={confirm} onChange={e => setConfirm(e.target.value)} />
            <button
              disabled={confirm !== p.name || p.users > 0}
              onClick={() => act(() => api(`/admin/host/profiles/${p.name}/delete`, json('POST', {confirm})))}
            >
              Видалити
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function SecurityPolicy({me}: {me: User}) {
  const [p, setP] = useState<{require_admin_totp: boolean} | null>(null),
    [e, setE] = useState('');
  useEffect(() => {
    api('/admin/policy')
      .then(setP)
      .catch(x => setE(err(x)));
  }, []);
  if (!p) return null;
  return (
    <div className="card">
      <h3>Адміністратори</h3>
      <label className="warn-check">
        <input
          type="checkbox"
          checked={p.require_admin_totp}
          onChange={x =>
            api('/admin/policy', json('PUT', {require_admin_totp: x.target.checked}))
              .then(setP)
              .catch(y => setE(err(y)))
          }
        />{' '}
        Обовʼязковий двофакторний вхід для адміністраторів
      </label>
      <p className="hint">
        Адміністратор без 2FA після входу зможе лише налаштувати його. Спершу увімкніть 2FA для себе: Обліковий запис → Вхід і безпека
        {me.totp ? '' : ' (у вас ще не увімкнено)'}.
      </p>
      {e && <div className="error">{e}</div>}
    </div>
  );
}

function Users({me}: {me: User}) {
  const [users, setUsers] = useState<User[]>(() => peek('/admin/users') ?? []),
    [profiles, setProfiles] = useState<string[]>(() => peek('/admin/profiles') ?? []),
    [sel, setSel] = useState(''),
    [error, setError] = useState('');
  const [q, setQ] = useState('');
  const [name, setName] = useState(''),
    [role, setRole] = useState<'user' | 'admin'>('user'),
    [profile, setProfile] = useState(''),
    [creating, setCreating] = useState(false);
  const [secret, setSecret] = useState<{username: string; password: string} | null>(null);
  async function load() {
    try {
      setUsers(await api('/admin/users'));
      const p: string[] = await api('/admin/profiles');
      setProfiles(p);
      setProfile(x => x || p.find(v => v !== 'default') || '');
    } catch (e) {
      setError(err(e));
    }
  }
  useEffect(() => {
    load();
  }, []);
  async function patch(u: User, body: object) {
    setError('');
    try {
      await api(`/admin/users/${u.id}`, json('PATCH', body));
      load();
    } catch (e) {
      setError(err(e));
    }
  }
  async function create(e: React.FormEvent) {
    e.preventDefault();
    setError('');
    try {
      const r = await api('/admin/users', json('POST', {username: name, role, profile}));
      setSecret({username: r.username, password: r.password});
      setName('');
      setCreating(false);
      await load();
      setSel(r.id);
    } catch (er) {
      setError(err(er));
    }
  }
  async function reset(u: User) {
    if (!(await ask(`Згенерувати новий пароль для ${u.username}? Активні сесії буде завершено.`, {danger: true, ok: 'Так'}))) return;
    try {
      const r = await api(`/admin/users/${u.id}/password`, {method: 'POST'});
      setSecret({username: u.username, password: r.password});
    } catch (e) {
      setError(err(e));
    }
  }
  const u = users.find(x => x.id === sel);
  return (
    <div className="split">
      <section className="list-pane">
        <div className="row">
          <h2>Користувачі</h2>
          <button
            className="new"
            onClick={() => {
              setCreating(true);
              setSel('');
            }}
          >
            <Ic i={Plus} /> Створити
          </button>
        </div>
        {users.length > 5 && (
          <input className="list-search" placeholder="Пошук: логін, профіль, роль" value={q} onChange={e => setQ(e.target.value)} />
        )}
        {users
          .filter(
            x =>
              !q.trim() ||
              [x.username, x.profile, x.role, x.blocked ? 'заблоковано' : ''].join(' ').toLowerCase().includes(q.trim().toLowerCase())
          )
          .map(x => (
            <button
              key={x.id}
              className={'item ' + (x.id === sel ? 'selected' : '')}
              onClick={() => {
                setSel(x.id);
                setCreating(false);
              }}
            >
              <b>
                {x.username}
                {x.id === me.id && ' (ви)'}
              </b>
              <small>
                {x.role} · {x.profile}
                {x.blocked ? ' · заблоковано' : ''}
                {x.totp ? ' · 2FA' : ''} · {x.last_login ? 'вхід ' + fmt(x.last_login) : 'не входив'}
              </small>
            </button>
          ))}
      </section>
      <section className="detail-pane">
        {error && <div className="error">{error}</div>}
        {secret && (
          <div className="warning secret">
            Одноразовий пароль для <b>{secret.username}</b>: <code>{secret.password}</code>
            <br />
            Передайте захищеним каналом; більше не відобразиться. <button onClick={() => setSecret(null)}>Сховати</button>
          </div>
        )}
        {creating && (
          <form className="card" onSubmit={create}>
            <h2>Новий користувач</h2>
            <label>
              Логін
              <input value={name} onChange={e => setName(e.target.value)} pattern="[A-Za-z0-9._-]{3,40}" required />
            </label>
            <label>
              Роль
              <select value={role} onChange={e => setRole(e.target.value as 'user' | 'admin')}>
                <option value="user">user</option>
                <option value="admin">admin</option>
              </select>
            </label>
            <label>
              Профіль Shroom
              <select value={profile} onChange={e => setProfile(e.target.value)} required>
                {profiles.map(p => (
                  <option key={p} value={p} disabled={p === 'default' && role !== 'admin'}>
                    {p}
                  </option>
                ))}
              </select>
            </label>
            <p className="hint">
              Рекомендовано: окремий профіль на кожну людину (спільний профіль = спільна памʼять і скіли). Створіть його в розділі
              «Профілі».
            </p>
            <button className="send">Створити й показати пароль</button>
          </form>
        )}
        {u && (
          <UserDetail key={u.id} u={u}>
            {tab => (
              <>
                {tab === 'main' && (
                  <div className="card">
                    <div className="row">
                      <h3>Обліковий запис</h3>
                      <span>
                        {u.blocked ? (
                          <>
                            <Ic i={Ban} /> заблоковано
                          </>
                        ) : (
                          <>
                            <Ic i={Check} /> активний
                          </>
                        )}
                      </span>
                    </div>
                    <div className="row grow">
                      <label>
                        Роль
                        <select value={u.role} disabled={u.id === me.id} onChange={e => patch(u, {role: e.target.value})}>
                          <option value="user">user</option>
                          <option value="admin">admin</option>
                        </select>
                      </label>
                      <label>
                        Профіль
                        <select value={u.profile} onChange={e => patch(u, {profile: e.target.value})}>
                          {[...new Set([u.profile, ...profiles])].map(p => (
                            <option key={p} value={p} disabled={p === 'default' && u.role !== 'admin'}>
                              {p}
                            </option>
                          ))}
                        </select>
                      </label>
                    </div>
                    <div className="row">
                      {u.id !== me.id && (
                        <button onClick={() => patch(u, {blocked: !u.blocked})}>{u.blocked ? 'Розблокувати' : 'Заблокувати'}</button>
                      )}
                      <button onClick={() => reset(u)}>Новий пароль</button>
                      {u.role !== 'admin' && !u.blocked && (
                        <button
                          title="Відкрити портал так, як його бачить користувач. Дії записуються в журнал від вашого імені."
                          onClick={async () =>
                            (await ask(`Увійти як ${u.username}?`, {
                              text: 'Ви побачите чати, налаштування й ліміти цього користувача та зможете діяти від його імені. Сесія діє 1 годину; кожна дія записується в журнал із вашим іменем. Пароль і 2FA користувача змінити не можна.',
                              ok: 'Увійти',
                            })) &&
                            api(`/admin/users/${u.id}/impersonate`, {method: 'POST'})
                              .then(() => {
                                location.assign('/');
                              })
                              .catch(e => setError(err(e)))
                          }
                        >
                          <Ic i={UserIcon} /> Увійти як {u.username}
                        </button>
                      )}
                      {u.totp && (
                        <button
                          onClick={async () =>
                            (await ask(`Скинути двофакторний вхід для ${u.username}?`, {danger: true, ok: 'Скинути'})) &&
                            api(`/admin/users/${u.id}/totp/reset`, {method: 'POST'})
                              .then(load)
                              .catch(e => setError(err(e)))
                          }
                        >
                          Скинути 2FA
                        </button>
                      )}
                      <span className="hint">Зміна ролі/профілю/блокування завершує сесії користувача.</span>
                    </div>
                  </div>
                )}
                {tab === 'models' && (
                  <div className="card">
                    <h3>Моделі спільної підписки</h3>
                    <SharedModelsEditor uid={u.id} />
                  </div>
                )}
                {tab === 'perms' && (
                  <div className="card">
                    <PermissionEditor
                      key={u.id + u.profile}
                      subject={'user:' + u.id}
                      title=""
                      profile={u.profile}
                      inheritFrom="role:user"
                    />
                  </div>
                )}
                {tab === 'main' && u.id !== me.id && (
                  <DeleteUser
                    key={'del' + u.id}
                    u={u}
                    onDone={async () => {
                      setSel('');
                      await load();
                    }}
                    setError={setError}
                  />
                )}
              </>
            )}
          </UserDetail>
        )}
        {!u &&
          !creating &&
          (users.length ? (
            <UsersSummary users={users} onPick={setSel} />
          ) : (
            <p className="hint">Оберіть користувача або створіть нового.</p>
          ))}
      </section>
    </div>
  );
}

function UserDetail({u, children}: {u: User; children: (tab: 'main' | 'perms' | 'models') => React.ReactNode}) {
  const [tab, setTab] = useState<'main' | 'perms' | 'models'>('main');
  return (
    <div className="cards">
      <div className="page-head">
        <h1>{u.username}</h1>
        <p className="hint">
          {u.role === 'admin' ? 'адміністратор' : 'користувач'} · профіль {u.profile} · {u.blocked ? 'заблоковано' : 'активний'}
          {u.totp ? ' · 2FA' : ''}
        </p>
      </div>
      {u.role !== 'admin' && (
        <Tabs
          tabs={[
            ['main', 'Загальне'],
            ['perms', 'Права'],
            ['models', 'Моделі'],
          ]}
          value={tab}
          onChange={setTab}
        />
      )}
      {children(u.role === 'admin' ? 'main' : tab)}
      {u.role === 'admin' && <p className="hint">Адміністратор має всі права.</p>}
    </div>
  );
}

const fmt = (t: number) =>
  new Date(t * 1000).toLocaleString('uk-UA', {day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit'});

function DeleteUser({u, onDone, setError}: {u: User; onDone: () => void; setError: (s: string) => void}) {
  const [confirm, setConfirm] = useState(''),
    [purge, setPurge] = useState(true),
    [busy, setBusy] = useState(false);
  async function del() {
    setBusy(true);
    setError('');
    try {
      await api(`/admin/users/${u.id}?purge_history=${purge}`, {method: 'DELETE'});
      onDone();
    } catch (e) {
      setError(err(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="card danger">
      <h3>Видалити користувача</h3>
      <p className="hint">Незворотно: обліковий запис, сесії, особисті права, діалоги та файли порталу.</p>
      <label className="warn-check">
        <input type="checkbox" checked={purge} onChange={e => setPurge(e.target.checked)} /> також видалити історію цих діалогів у Shroom
        (профіль {u.profile})
      </label>
      <div className="row">
        <input placeholder={`введіть «${u.username}»`} value={confirm} onChange={e => setConfirm(e.target.value)} />
        <button disabled={confirm !== u.username || busy} onClick={del}>
          <Ic i={Trash2} /> Видалити
        </button>
      </div>
    </div>
  );
}

const ACTIONS: Record<string, string> = {
  'auth.login': 'вхід',
  'auth.impersonate_start': 'вхід від імені',
  'auth.impersonate_stop': 'повернення з входу від імені',
  'auth.login_failed': 'невдалий вхід',
  'auth.logout': 'вихід',
  'auth.password_change': 'зміна пароля',
  'auth.totp_enabled': '2FA увімкнено',
  'auth.totp_disabled': '2FA вимкнено',
  'auth.totp_failed': 'невірний код 2FA',
  'user.totp_reset': 'скинуто 2FA',
  'policy.update': 'змінено політику',
  'user.create': 'створено користувача',
  'user.update': 'змінено користувача',
  'user.password_reset': 'скинуто пароль',
  'user.delete': 'видалено користувача',
  'perms.update': 'змінено права',
  'profile.create': 'створено профіль',
  'profile.set_model': 'змінено модель',
  'profile.set_isolation': 'пісочниця',
  'profile.set_tools': 'змінено інструменти',
  'profile.bridge': 'міст',
  'profile.copy_credential': 'надано підписку',
  'profile.remove_credential': 'прибрано підписку',
  'profile.delete': 'видалено профіль',
  'command.run': 'команда',
  'limit.update': 'змінено ліміт',
  'subscription.add': 'підключено підписку',
  'subscription.remove': 'відʼєднано підписку',
  'cursor.connect': 'підключено Cursor',
  'cursor.disconnect': 'відʼєднано Cursor',
  'profile.set_skill': 'скіл профілю',
  'profile.set_library': 'бібліотека профілю',
  'profile.promote': 'скіл до бібліотеки',
  'profile.library_delete': 'скіл з бібліотеки',
  'profile.delete_personal': 'видалено скіл',
  'limit.blocked': 'ліміт вичерпано',
  'command.denied': 'команду заборонено',
  'chat.turn': 'запит до агента',
  'chat.delete': 'видалено чат',
};
type AuditRow = {id: number; ts: number; actor_name: string | null; ip: string; action: string; target: string; details: unknown};

function Audit() {
  const [rows, setRows] = useState<AuditRow[]>([]),
    [group, setGroup] = useState(''),
    [actor, setActor] = useState(''),
    [more, setMore] = useState(true),
    [error, setError] = useState('');
  const [from, setFrom] = useState(''),
    [to, setTo] = useState(''); // yyyy-mm-dd, local days
  const dayStart = (v: string) => (v ? new Date(v + 'T00:00:00').getTime() / 1000 : 0);
  async function load(reset: boolean) {
    try {
      const before = reset || !rows.length ? 0 : rows[rows.length - 1].id;
      const range = `&since=${dayStart(from)}&until=${to ? dayStart(to) + 86400 : 0}`;
      const r: AuditRow[] = await api(
        `/admin/audit?limit=100&before=${before}&action=${encodeURIComponent(group)}&actor=${encodeURIComponent(actor)}${range}`
      );
      setRows(x => (reset ? r : [...x, ...r]));
      setMore(r.length === 100);
    } catch (e) {
      setError(err(e));
    }
  }
  useEffect(() => {
    load(true);
  }, [group, from, to]);
  const detail = (d: unknown) =>
    d == null
      ? ''
      : Object.entries(d as Record<string, unknown>)
          .map(([k, v]) => `${k}: ${typeof v === 'object' ? JSON.stringify(v) : String(v)}`)
          .join(', ');
  return (
    <div className="detail-pane">
      <div className="page-head">
        <h1>Журнал дій</h1>
        <p className="hint">Вхід, зміни прав і профілів, запити до агента. Події з помилкою позначено червоним.</p>
      </div>
      <div className="card">
        <div className="row filters">
          <select value={group} onChange={e => setGroup(e.target.value)}>
            <option value="">усі події</option>
            <option value="auth.">вхід і вихід</option>
            <option value="user.">користувачі</option>
            <option value="perms.">права</option>
            <option value="profile.">профілі</option>
            <option value="command.">команди</option>
            <option value="chat.">запити до агента</option>
          </select>
          <input
            placeholder="користувач"
            value={actor}
            onChange={e => setActor(e.target.value)}
            onKeyDown={e => {
              if (e.key === 'Enter') load(true);
            }}
          />
          <label className="date-range">
            з<input type="date" value={from} max={to || undefined} onChange={e => setFrom(e.target.value)} />
          </label>
          <label className="date-range">
            по
            <input type="date" value={to} min={from || undefined} onChange={e => setTo(e.target.value)} />
          </label>
          {(from || to) && (
            <button
              type="button"
              className="icon"
              title="Скинути дати"
              aria-label="Скинути дати"
              onClick={() => {
                setFrom('');
                setTo('');
              }}
            >
              <Ic i={X} />
            </button>
          )}
          <button onClick={() => load(true)}>Оновити</button>
        </div>
        {error && <div className="error">{error}</div>}
        <table className="audit">
          <thead>
            <tr>
              <th>Час</th>
              <th>Хто</th>
              <th>Дія</th>
              <th>Обʼєкт</th>
              <th>Деталі</th>
              <th>IP</th>
            </tr>
          </thead>
          <tbody>
            {!rows.length && (
              <tr>
                <td colSpan={6} className="meta">
                  Подій за цим фільтром немає.
                </td>
              </tr>
            )}
            {rows.map((r, i) => {
              const day = new Date(r.ts * 1000).toLocaleDateString('uk-UA', {weekday: 'long', day: 'numeric', month: 'long'});
              const prev = i
                ? new Date(rows[i - 1].ts * 1000).toLocaleDateString('uk-UA', {weekday: 'long', day: 'numeric', month: 'long'})
                : '';
              return (
                <React.Fragment key={r.id}>
                  {day !== prev && (
                    <tr className="day-row">
                      <td colSpan={6}>{day}</td>
                    </tr>
                  )}
                  <tr className={r.action.endsWith('failed') || r.action.endsWith('denied') ? 'warn' : ''}>
                    <td>{new Date(r.ts * 1000).toLocaleTimeString('uk-UA', {hour: '2-digit', minute: '2-digit', second: '2-digit'})}</td>
                    <td>{r.actor_name ?? '—'}</td>
                    <td>{ACTIONS[r.action] ?? r.action}</td>
                    <td title={r.target ?? ''}>{r.target}</td>
                    <td className="meta">{detail(r.details).replace(/_/g, '_\u200b')}</td>
                    <td className="meta">{r.ip}</td>
                  </tr>
                </React.Fragment>
              );
            })}
          </tbody>
        </table>
        {more && rows.length > 0 && <button onClick={() => load(false)}>Показати ще 100</button>}
        {!rows.length && <p className="hint">Подій немає.</p>}
      </div>
    </div>
  );
}

const money = (v: number) => '$' + v.toFixed(v < 1 ? 4 : 2);
const tokens = (v: number) => (v >= 1e6 ? (v / 1e6).toFixed(1) + ' млн' : v >= 1e3 ? (v / 1e3).toFixed(1) + ' тис.' : String(v));
type UsageRow = {turns: number; tokens: number; cost: number; own_cost?: number; limit: number | null};

function MyUsage() {
  const [u, setU] = useState<UsageRow | null>(() => peek('/me/usage') ?? null);
  useEffect(() => {
    api('/me/usage')
      .then(setU)
      .catch(() => {});
  }, []);
  if (!u) return null;
  const pct = u.limit ? Math.min(100, (u.cost / u.limit) * 100) : 0;
  return (
    <div className="card">
      <h3>Цей місяць</h3>
      <div className="row">
        <span>
          Запитів: {u.turns} · токенів: {tokens(u.tokens)} · вартість: {money(u.cost)}
          {u.own_cost ? ` · на власних ключах: ${money(u.own_cost)}` : ''}
        </span>
        <span className="hint">{u.limit != null ? `ліміт ${money(u.limit)}` : 'без ліміту'}</span>
      </div>
      {u.limit != null && (
        <div className="bar">
          <i style={{width: pct + '%'}} className={pct >= 90 ? 'hot' : ''} />
        </div>
      )}
    </div>
  );
}

function LimitInput({subject, value, onSaved}: {subject: string; value: number | null; onSaved: () => void}) {
  const [v, setV] = useState(value == null ? '' : String(value)),
    [err, setErr] = useState('');
  async function save() {
    setErr('');
    try {
      await api('/admin/limits/' + encodeURIComponent(subject), json('PUT', {usd_month: v.trim() === '' ? null : Number(v)}));
      onSaved();
      toast('Ліміт збережено');
    } catch (e) {
      setErr(String(e));
      toast('Ліміт не збережено', 'error');
    }
  }
  const dirty = v !== (value == null ? '' : String(value));
  return (
    <span className="limit">
      <input
        inputMode="decimal"
        placeholder="без ліміту"
        value={v}
        onChange={e => setV(e.target.value.replace(',', '.'))}
        onKeyDown={e => {
          if (e.key === 'Enter') save();
        }}
        title={err}
      />
      {dirty && <button onClick={save}>Зберегти</button>}
    </span>
  );
}

function Usage() {
  const [d, setD] = useState<{
      since: number;
      users: (UsageRow & {id: string; username: string; profile: string})[];
      profiles: (UsageRow & {name: string})[];
      daily: {day: number; cost: number}[];
    } | null>(() => peek('/admin/usage') ?? null),
    [error, setError] = useState('');
  async function load() {
    try {
      setD(await api('/admin/usage'));
    } catch (e) {
      setError(err(e));
    }
  }
  useEffect(() => {
    load();
  }, []);
  if (!d)
    return (
      <div className="detail-pane">
        {error ? (
          <div className="error">{error}</div>
        ) : (
          <div className="skeleton-block" aria-busy="true">
            <i />
            <i />
            <i />
          </div>
        )}
      </div>
    );
  const total = d.users.reduce((a, u) => a + u.cost, 0);
  const Row = ({label, sub, u, subject}: {label: string; sub?: string; u: UsageRow; subject: string}) => {
    const pct = u.limit ? Math.min(100, (u.cost / u.limit) * 100) : 0;
    return (
      <tr>
        <td>
          <b>{label}</b>
          {sub && <small> {sub}</small>}
        </td>
        <td>{u.turns}</td>
        <td>{tokens(u.tokens)}</td>
        <td>{money(u.cost)}</td>
        <td>
          <LimitInput key={subject + u.limit} subject={subject} value={u.limit} onSaved={load} />
          {u.limit != null && (
            <div className="bar">
              <i style={{width: pct + '%'}} className={pct >= 90 ? 'hot' : ''} />
            </div>
          )}
        </td>
      </tr>
    );
  };
  return (
    <div className="detail-pane">
      <div className="page-head">
        <h1>Витрати і ліміти</h1>
        <p className="hint">
          Ліміт у доларах на календарний місяць (UTC); при вичерпанні нові запити блокуються. Порожнє поле — без ліміту.
        </p>
      </div>
      <div className="cards">
        <div className="card">
          <div className="row">
            <h3>Цей місяць по днях</h3>
            <span className="total">
              Разом <b>{money(total)}</b>
            </span>
          </div>
          <CostChart daily={d.daily} />
          <p className="hint">Вартість — оцінка Shroom за тарифами провайдера (для підписок без поштучної оплати це умовна сума).</p>
        </div>
        <AdminLimitsCards />
        <div className="card">
          <h3>Користувачі</h3>
          <table className="usage">
            <thead>
              <tr>
                <th>Користувач</th>
                <th>Запитів</th>
                <th>Токенів</th>
                <th>Вартість</th>
                <th>Ліміт, $/міс</th>
              </tr>
            </thead>
            <tbody>
              {d.users.map(u => (
                <Row key={u.id} label={u.username} sub={u.profile} u={u} subject={'user:' + u.id} />
              ))}
            </tbody>
          </table>
        </div>
        <div className="card">
          <h3>Профілі Shroom</h3>
          <table className="usage">
            <thead>
              <tr>
                <th>Профіль</th>
                <th>Запитів</th>
                <th>Токенів</th>
                <th>Вартість</th>
                <th>Ліміт, $/міс</th>
              </tr>
            </thead>
            <tbody>
              {d.profiles.map(p => (
                <Row key={p.name} label={p.name} u={p} subject={'profile:' + p.name} />
              ))}
            </tbody>
          </table>
          <p className="hint">Ліміт профілю спільний для всіх його користувачів.</p>
        </div>
      </div>
    </div>
  );
}

type OverviewData = {
  backup?: {last: number | null; count: number; size: number} | null;
  active: {created: number; state: string; title: string; profile: string; username: string}[];
  users: {username: string; role: string; profile: string; blocked: number; last_login: number | null; sessions: number}[];
  profiles: {name: string; bridge: string; model: string}[];
  last24h: {turns: number; failed_logins: number; failed_internal?: number; denied_commands: number};
  month_cost: number;
};

function Overview({go}: {go: (s: Section) => void}) {
  const [d, setD] = useState<OverviewData | null>(() => peek('/admin/overview') ?? null),
    [error, setError] = useState('');
  useEffect(() => {
    let on = true;
    const load = () =>
      api('/admin/overview')
        .then(x => on && setD(x))
        .catch(e => on && setError(err(e)));
    load();
    const t = setInterval(() => {
      if (!document.hidden) load();
    }, 5000);
    return () => {
      on = false;
      clearInterval(t);
    };
  }, []);
  if (!d)
    return (
      <div className="detail-pane">
        {error ? (
          <div className="error">{error}</div>
        ) : (
          <div className="skeleton-block" aria-busy="true">
            <i />
            <i />
            <i />
          </div>
        )}
      </div>
    );
  const online = d.users.filter(u => u.sessions > 0),
    down = d.profiles.filter(p => p.bridge !== 'active' && d.users.some(u => u.profile === p.name));
  const Tile = ({label, value, warn, to}: {label: string; value: string | number; warn?: boolean; to?: Section}) => (
    <button className={'tile' + (warn ? ' warn' : '')} onClick={() => to && go(to)} disabled={!to}>
      <b>{value}</b>
      <span>{label}</span>
    </button>
  );
  const ago = (t: number) => {
    const s = Math.round(Date.now() / 1000 - t);
    return s < 60 ? s + ' с' : Math.round(s / 60) + ' хв';
  };
  return (
    <div className="detail-pane">
      <div className="page-head">
        <h1>Огляд</h1>
        <p className="hint">Стан порталу зараз. Оновлюється кожні 5 секунд.</p>
      </div>
      <div className="cards">
        <div className="tiles">
          <Tile label="відповідей зараз" value={d.active.length} />
          <Tile label="користувачів онлайн" value={online.length} to="users" />
          <Tile label="мостів зупинено (з користувачами)" value={down.length} warn={down.length > 0} to="profiles" />
          <Tile label="витрати за місяць" value={money(d.month_cost)} to="usage" />
          {d.backup &&
            (() => {
              const age = d.backup.last ? (Date.now() / 1000 - d.backup.last) / 3600 : Infinity;
              return (
                <Tile
                  label={`резервна копія · ${d.backup.count} шт., щодня о 03:30`}
                  value={
                    d.backup.last
                      ? age < 1
                        ? 'щойно'
                        : age < 48
                          ? Math.round(age) + ' год тому'
                          : Math.round(age / 24) + ' дн тому'
                      : 'немає'
                  }
                  warn={age > 30}
                />
              );
            })()}
          <Tile label="запитів за добу" value={d.last24h.turns} to="audit" />
          <Tile
            label={`невдалих входів за добу${d.last24h.failed_internal ? ` · ще ${d.last24h.failed_internal} внутрішніх (тести)` : ''}`}
            value={d.last24h.failed_logins}
            warn={d.last24h.failed_logins > 0}
            to="audit"
          />
          <Tile label="заборонених команд за добу" value={d.last24h.denied_commands} to="audit" />
        </div>
        <VpsCard />
        <div className="card">
          <h3>Активні відповіді</h3>
          {d.active.length ? (
            <table className="usage">
              <tbody>
                {d.active.map((a, i) => (
                  <tr key={i}>
                    <td>
                      <b>{a.username ?? '—'}</b>
                    </td>
                    <td>{a.profile}</td>
                    <td>{a.title}</td>
                    <td>{a.state === 'waiting' ? 'чекає відповіді користувача' : 'працює'}</td>
                    <td>{ago(a.created)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="hint">Зараз агент нікому не відповідає — мости можна безпечно перезапускати.</p>
          )}
        </div>
        <div className="card">
          <h3>Онлайн</h3>
          {online.length ? <p>{online.map(u => u.username).join(', ')}</p> : <p className="hint">Нікого.</p>}
        </div>
      </div>
    </div>
  );
}

type Skill = {name: string; category: string; source: string; enabled: boolean; description: string};
const SOURCE: Record<string, string> = {builtin: 'вбудований', hub: 'з каталогу', local: 'особистий', external: 'бібліотека'};

/** Defaults for NEW chats: profile model (restarts the agent, as Hermes reads it at start) and reasoning level.
 *  Every chat may override both from the header; that pick is per chat and needs no restart. */
function ModelDefaults() {
  const [d, setD] = useState<ModelsData | null>(() => peek('/me/models') ?? null),
    [error, setError] = useState(''),
    [saving, setSaving] = useState('');
  const [pick, setPick] = useState<{provider: string; model: string}>(() => peek('/me/models')?.current ?? {provider: '', model: ''});
  const load = async (tries = 1) => {
    try {
      const x = await fetchModels(tries);
      setD(x);
      setPick(x.current);
    } catch (e) {
      setError(err(e));
    }
  };
  useEffect(() => {
    load(3);
  }, []);
  if (error && !d)
    return (
      <div className="card">
        <h3>Типова модель</h3>
        <div className="error">{error}</div>
      </div>
    );
  if (!d)
    return (
      <div className="card">
        <h3>Типова модель</h3>
        <div className="skeleton-block" aria-busy="true">
          <i />
          <i />
        </div>
      </div>
    );
  const prov = d.providers.find(p => p.slug === pick.provider),
    changed = pick.provider !== d.current.provider || pick.model !== d.current.model;
  async function save(path: string, body: object, label: string) {
    setSaving(label);
    setError('');
    try {
      await api(path, json('PUT', body));
      await load(20);
      window.dispatchEvent(new Event(MODELS_CHANGED));
      toast('Збережено: ' + label);
    } catch (e) {
      setError(err(e));
    } finally {
      setSaving('');
    }
  }
  return (
    <div className="card">
      <h3>Типові для нових чатів</h3>
      {d.can_switch && d.providers.length > 0 ? (
        <div className="row grow">
          <label>
            Провайдер
            <select
              value={pick.provider}
              disabled={!!saving}
              onChange={e =>
                setPick({provider: e.target.value, model: d.providers.find(p => p.slug === e.target.value)?.models?.[0] ?? ''})
              }
            >
              {(['own', 'shared', 'owner'] as const).map(k => {
                const v = d.providers.filter(p => p.kind === k);
                return v.length ? (
                  <optgroup key={k} label={GROUP[k]}>
                    {v.map(p => (
                      <option key={p.slug} value={p.slug}>
                        {p.name}
                      </option>
                    ))}
                  </optgroup>
                ) : null;
              })}
            </select>
          </label>
          <label>
            Модель
            <ModelSelect value={pick.model} models={prov?.models ?? []} disabled={!!saving} onChange={m => setPick({...pick, model: m})} />
          </label>
          <button
            className="send"
            disabled={!!saving || !changed || !pick.model}
            aria-busy={saving === pick.model}
            onClick={() => save('/me/models', pick, pick.model)}
          >
            {saving === pick.model ? <span className="spinner" /> : 'Застосувати'}
          </button>
        </div>
      ) : (
        <p className="hint">
          Модель: {d.current.provider} / {d.current.model}
          {d.can_switch ? '' : ' (задає адміністратор)'}.
        </p>
      )}
      {d.can_switch && (
        <p className="hint">
          Зараз: {d.current.provider} / {d.current.model}. Зміна перезапускає агента; відкриті чати зі своєю моделлю її зберігають.
        </p>
      )}
      {d.can_reason && (
        <>
          <h4>Міркування</h4>
          <div className="tri" role="radiogroup" aria-label="Типові міркування">
            {['', ...d.efforts].map(e => (
              <button
                key={e}
                role="radio"
                aria-checked={e === d.effort}
                className={e === d.effort ? 'on' : ''}
                disabled={!!saving}
                onClick={() => e !== d.effort && save('/me/reasoning', {effort: e}, 'міркування «' + (EFFORT[e] ?? e) + '»')}
              >
                {EFFORT[e] ?? e}
              </button>
            ))}
          </div>
          <p className="hint">Більше міркувань — точніше, але повільніше й дорожче. «Типово» — як вирішує сама модель.</p>
        </>
      )}
      {error && <div className="error">{error}</div>}
    </div>
  );
}

type OwnProvider = {slug: string; name: string; own: boolean; models: string[]};
function MySubscriptions() {
  const [allowed, setAllowed] = useState(() => !!peek('/me/permissions')?.['feature:own_subscriptions']),
    [d, setD] = useState<{
      providers: OwnProvider[];
      oauth: OwnProvider[];
      current: {provider: string; model: string};
      assigned: {provider: string; model: string} | null;
    } | null>(() => peek('/me/providers') ?? null);
  const [flow, setFlow] = useState<{slug: string; job: string; url: string; code: string; state: string; paste?: boolean} | null>(null),
    [paste, setPaste] = useState('');
  const [error, setError] = useState(''),
    [slug, setSlug] = useState(''),
    [key, setKey] = useState(''),
    [busy, setBusy] = useState(false),
    [model, setModel] = useState<{provider: string; model: string}>(() => peek('/me/providers')?.current ?? {provider: '', model: ''});
  useEffect(() => {
    api('/me/permissions')
      .then(p => {
        if (p['feature:own_subscriptions']) {
          setAllowed(true);
          api('/me/providers')
            .then(x => {
              setD(x);
              setModel(x.current);
            })
            .catch(e => setError(err(e)));
        }
      })
      .catch(() => {});
  }, []);
  async function run(fn: () => Promise<unknown>) {
    setBusy(true);
    setError('');
    try {
      const r = await fn();
      if (r && (r as {providers?: unknown}).providers) setD(r as typeof d);
    } catch (e) {
      setError(err(e));
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => {
    if (!flow || flow.state !== 'running' || flow.paste) return;
    const t = setInterval(async () => {
      try {
        const st = await api('/me/oauth/' + flow.job);
        setFlow({...flow, ...st});
        if (st.state === 'succeeded') {
          const x = await api('/me/providers');
          setD(x);
        }
      } catch (e) {
        setError(err(e));
        setFlow(null);
      }
    }, 3000);
    return () => clearInterval(t);
  }, [flow]);
  if (!allowed) return null;
  const all = [...(d?.providers ?? []), ...(d?.oauth ?? [])];
  const own = all.filter(p => p.own),
    rest = d?.providers.filter(p => !p.own) ?? [];
  const models = all.find(p => p.slug === model.provider)?.models ?? [];
  return (
    <>
      <div className="card">
        <h3>Підписки</h3>
        <p className="hint">
          Ключ зберігається лише у вашому профілі Shroom і більше не показується. Витрати на власних ключах не входять у ліміт
          адміністратора.
        </p>
        {error && <div className="error">{error}</div>}
        {!d ? (
          !error && (
            <div className="skeleton-block" aria-busy="true">
              <i />
              <i />
              <i />
            </div>
          )
        ) : (
          <>
            {own.length > 0 && (
              <table className="usage">
                <tbody>
                  {own.map(p => (
                    <tr key={p.slug}>
                      <td>
                        <b>{p.name}</b>
                      </td>
                      <td className="meta">{p.slug}</td>
                      <td>{d.oauth.some(o => o.slug === p.slug) ? 'вхід виконано' : 'ключ підключено'}</td>
                      <td>
                        <button
                          className="icon"
                          title="Відʼєднати"
                          disabled={busy}
                          onClick={async () =>
                            (await ask(`Відʼєднати ${p.name}?`, {danger: true, ok: 'Так'})) &&
                            run(() => api('/me/providers/' + p.slug, {method: 'DELETE'}))
                          }
                        >
                          <Ic i={Trash2} size={20} />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            {rest.length > 0 && (
              <form
                className="row grow"
                onSubmit={e => {
                  e.preventDefault();
                  run(async () => {
                    const r = await api('/me/providers/' + slug, json('PUT', {api_key: key}));
                    setKey('');
                    setSlug('');
                    return r;
                  });
                }}
              >
                <label>
                  Провайдер
                  <select value={slug} onChange={e => setSlug(e.target.value)} required>
                    <option value="">оберіть…</option>
                    {rest.map(p => (
                      <option key={p.slug} value={p.slug}>
                        {p.name}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  API-ключ
                  <input type="password" autoComplete="off" value={key} onChange={e => setKey(e.target.value)} required minLength={8} />
                </label>
                <button className="send" disabled={busy || !slug || !key}>
                  Підключити
                </button>
              </form>
            )}
            {d.oauth.filter(p => !p.own).length > 0 && (
              <div className="row">
                {d.oauth
                  .filter(p => !p.own)
                  .map(p => (
                    <button
                      key={p.slug}
                      disabled={busy || !!(flow && flow.state === 'running')}
                      onClick={() =>
                        run(async () => {
                          const st = await api('/me/oauth/' + p.slug, {method: 'POST'});
                          setFlow({slug: p.slug, ...st});
                        })
                      }
                    >
                      Увійти: {p.name}
                    </button>
                  ))}
              </div>
            )}
            {flow && (
              <div className="warning">
                {flow.state === 'running' ? (
                  flow.paste ? (
                    <form
                      className="oauth-paste"
                      onSubmit={e => {
                        e.preventDefault();
                        run(async () => {
                          const st = await api('/me/oauth/' + flow.job + '/code', json('POST', {code: paste.trim()}));
                          setPaste('');
                          setFlow({...flow, ...st});
                          if (st.state === 'succeeded') return api('/me/providers');
                        });
                      }}
                    >
                      <ol>
                        <li>
                          <a href={flow.url} target="_blank" rel="noreferrer">
                            Відкрийте сторінку входу Claude
                          </a>{' '}
                          і увійдіть у свій акаунт Claude Pro або Max.
                        </li>
                        <li>Після підтвердження Claude покаже код. Скопіюйте його повністю і вставте сюди.</li>
                      </ol>
                      <div className="row grow">
                        <label>
                          Код авторизації
                          <input
                            type="password"
                            autoComplete="off"
                            value={paste}
                            onChange={e => setPaste(e.target.value)}
                            required
                            minLength={10}
                            placeholder="код#стан"
                          />
                        </label>
                        <button className="send" disabled={busy || paste.trim().length < 10}>
                          Підтвердити
                        </button>
                        <button
                          type="button"
                          onClick={() => {
                            api('/me/oauth/' + flow.job, {method: 'DELETE'}).catch(() => {});
                            setFlow(null);
                            setPaste('');
                          }}
                        >
                          Скасувати
                        </button>
                      </div>
                      <p className="hint">
                        Після входу ваш профіль працюватиме лише на вашій підписці Claude, без спільної підписки адміністратора.
                      </p>
                    </form>
                  ) : (
                    <>
                      Відкрийте{' '}
                      <a href={flow.url} target="_blank" rel="noreferrer">
                        {flow.url}
                      </a>{' '}
                      і введіть код <code className="secret-key">{flow.code}</code>. Сторінка оновиться сама після входу.
                      <button
                        onClick={() => {
                          api('/me/oauth/' + flow.job, {method: 'DELETE'}).catch(() => {});
                          setFlow(null);
                        }}
                      >
                        Скасувати
                      </button>
                    </>
                  )
                ) : flow.state === 'succeeded' ? (
                  'Підписку підключено.'
                ) : (
                  'Вхід не завершено. Спробуйте ще раз.'
                )}
              </div>
            )}
            {!d.providers.length && !d.oauth.length && <p className="hint">Адміністратор ще не дозволив жодного провайдера.</p>}
          </>
        )}
      </div>
    </>
  );
}

type CursorState = {
  connected: boolean;
  valid: boolean | null;
  email: string;
  key_name: string;
  sandbox: boolean;
  network: boolean;
  terminal: boolean;
  check_error?: string;
};
function CursorAgent() {
  const [d, setD] = useState<CursorState | null>(() => peek('/me/cursor') ?? null),
    [key, setKey] = useState(''),
    [busy, setBusy] = useState(''),
    [error, setError] = useState('');
  useEffect(() => {
    api('/me/cursor')
      .then(setD)
      .catch(e => setError(err(e)));
  }, []);
  async function run(kind: string, fn: () => Promise<CursorState>, done: string) {
    setBusy(kind);
    setError('');
    try {
      setD(await fn());
      setKey('');
      toast(done);
    } catch (e) {
      setError(err(e));
      toast('Не вдалося', 'error');
    } finally {
      setBusy('');
    }
  }
  const missing = d
    ? ([
        !d.sandbox && 'пісочниця Docker',
        d.sandbox && !d.network && 'доступ пісочниці до інтернету',
        !d.terminal && 'інструмент «Термінал»',
      ].filter(Boolean) as string[])
    : [];
  return (
    <>
      <div className="card">
        <h3>Cursor</h3>
        <p className="hint">Агент Shroom доручає задачі з коду Cursor Agent CLI за вашою підпискою Cursor.</p>
        <p className="hint">
          Створіть ключ на{' '}
          <a href="https://cursor.com/dashboard?tab=integrations" target="_blank" rel="noreferrer">
            cursor.com: Dashboard, Integrations, User API Keys
          </a>
          . Ключ зберігається лише у вашому профілі Shroom, більше не показується і передається тільки у вашу пісочницю. Використання
          оплачується з вашої підписки Cursor.
        </p>
        {error && <div className="error">{error}</div>}
        {!d ? (
          !error && (
            <div className="skeleton-block" aria-busy="true">
              <i />
              <i />
              <i />
            </div>
          )
        ) : d.connected ? (
          <>
            <table className="usage">
              <tbody>
                <tr>
                  <td>
                    <b>{d.email || 'Обліковий запис Cursor'}</b>
                  </td>
                  <td className="meta">{d.key_name}</td>
                  <td>
                    {d.valid === false ? (
                      <b style={{color: 'var(--md-sys-color-error)'}}>ключ більше не діє</b>
                    ) : d.valid ? (
                      'підключено'
                    ) : (
                      'не вдалося перевірити'
                    )}
                  </td>
                  <td>
                    <button
                      className="icon"
                      title="Відʼєднати"
                      disabled={!!busy}
                      onClick={async () =>
                        (await ask('Відʼєднати Cursor? Ключ буде видалено з профілю.', {danger: true, ok: 'Так'})) &&
                        run('del', () => api('/me/cursor', {method: 'DELETE'}), 'Cursor відʼєднано')
                      }
                    >
                      {busy === 'del' ? <span className="spinner" aria-hidden /> : <Ic i={Trash2} size={20} />}
                    </button>
                  </td>
                </tr>
              </tbody>
            </table>
            {d.check_error && <p className="hint">{d.check_error}</p>}
            {d.valid === false && <p className="hint">Видаліть цей ключ і підключіть новий.</p>}
          </>
        ) : (
          <form
            className="row grow key-inline"
            onSubmit={e => {
              e.preventDefault();
              run('save', () => api('/me/cursor', json('PUT', {api_key: key})), 'Cursor підключено');
            }}
          >
            <label>
              API-ключ Cursor
              <input type="password" autoComplete="off" value={key} onChange={e => setKey(e.target.value)} required minLength={16} />
            </label>
            <button className="send" disabled={!!busy || key.trim().length < 16}>
              {busy === 'save' ? 'Перевіряємо…' : 'Підключити'}
            </button>
          </form>
        )}
        {d && <p className="hint">Збереження чи видалення ключа перезапускає ваш профіль (кілька секунд).</p>}
      </div>
      {missing.length > 0 && (
        <div className="card">
          <div className="warning">
            Для роботи Cursor у вашому профілі бракує: {missing.join(', ')}. Попросіть адміністратора це увімкнути.
          </div>
        </div>
      )}
      {d && (
        <div className="card">
          <h3>Як користуватися</h3>
          <p className="hint">
            Попросіть у чаті, наприклад: «Доручи Cursor: створи в /workspace/app сторінку входу і додай тести». Агент завантажить скіл
            cursor-agent, запустить Cursor Agent CLI у вашій пісочниці і перекаже результат. Файли лишаються в /workspace.
          </p>
          <p className="hint">Перший запуск встановлює Cursor CLI у пісочниці, це займає близько хвилини.</p>
        </div>
      )}
    </>
  );
}

function OwnSkills({profile}: {profile: string}) {
  const [e, setE] = useState('');
  return (
    <>
      {e && <div className="error">{e}</div>}
      <ProfileSkills name={profile} own setError={setE} />
    </>
  );
}

function MySkills() {
  const [d, setD] = useState<{personal: Skill[]; library: Skill[]; builtin_count: number; can_delete: boolean} | null>(
      () => peek('/me/skills') ?? null
    ),
    [error, setError] = useState('');
  useEffect(() => {
    api('/me/skills')
      .then(setD)
      .catch(e => setError(err(e)));
  }, []);
  async function del(n: string) {
    if (!(await ask(`Видалити скіл ${n}?`, {danger: true, ok: 'Так'}))) return;
    try {
      setD(await api('/me/skills/' + encodeURIComponent(n), {method: 'DELETE'}));
    } catch (e) {
      setError(err(e));
    }
  }
  if (!d)
    return error ? (
      <div className="card">
        <div className="error">{error}</div>
      </div>
    ) : null;
  return (
    <div className="card">
      <p className="hint">
        Особисті скіли агент створює сам під час роботи (наприклад, після /learn). Скіли бібліотеки підключає адміністратор. Вбудованих:{' '}
        {d.builtin_count}. Усі викликаються через «/назва».
      </p>
      {error && <div className="error">{error}</div>}
      <table className="usage">
        <tbody>
          {d.personal.map(x => (
            <tr key={x.name}>
              <td>
                <code>/{x.name}</code>
              </td>
              <td className="meta">{x.description}</td>
              <td>особистий</td>
              <td>
                {d.can_delete && (
                  <button className="icon" title="Видалити" onClick={() => del(x.name)}>
                    <Ic i={Trash2} size={20} />
                  </button>
                )}
              </td>
            </tr>
          ))}
          {d.library.map(x => (
            <tr key={x.name}>
              <td>
                <code>/{x.name}</code>
              </td>
              <td className="meta">{x.description}</td>
              <td>бібліотека</td>
              <td />
            </tr>
          ))}
        </tbody>
      </table>
      {!d.personal.length && !d.library.length && <p className="hint">Поки немає особистих скілів і скілів бібліотеки.</p>}
    </div>
  );
}

function LibraryPane() {
  const [error, setError] = useState('');
  const [lib, setLib] = useState<{name: string; category: string; description: string}[] | null>(
    () => peek('/admin/skills/library') ?? null
  );
  useEffect(() => {
    api('/admin/skills/library')
      .then(setLib)
      .catch(e => setError(err(e)));
  }, []);
  const [q, setQ] = useState(''),
    [cat, setCat] = useState('');
  const cats = [...new Set((lib ?? []).map(x => x.category).filter(Boolean))].sort();
  const needle = q.trim().toLowerCase();
  const shown = (lib ?? []).filter(
    x => (!cat || x.category === cat) && (!needle || (x.name + ' ' + x.description + ' ' + x.category).toLowerCase().includes(needle))
  );
  async function del(n: string) {
    if (!(await ask(`Прибрати ${n} з бібліотеки для всіх профілів?`, {danger: true, ok: 'Так'}))) return;
    try {
      setLib(await api('/admin/skills/library/' + encodeURIComponent(n), {method: 'DELETE'}));
    } catch (e) {
      setError(err(e));
    }
  }
  return (
    <div className="card">
      {error && <div className="error">{error}</div>}
      <p className="hint">
        Тека /root/.hermes/shared-skills, підключена до профілів через нативний skills.external_dirs (лише читання для агентів).
        Поповнюється кнопкою «До бібліотеки» біля особистого скіла: Профілі → профіль → Скіли.
      </p>
      {lib && lib.length > 0 && (
        <div className="row filters">
          <input type="search" placeholder="Пошук: назва, опис" aria-label="Пошук скілів" value={q} onChange={e => setQ(e.target.value)} />
          <select aria-label="Категорія" value={cat} onChange={e => setCat(e.target.value)}>
            <option value="">Усі категорії ({lib.length})</option>
            {cats.map(c => (
              <option key={c} value={c}>
                {c} ({lib.filter(x => x.category === c).length})
              </option>
            ))}
          </select>
        </div>
      )}
      {lib && lib.length > 0 && (needle || cat) && <p className="hint">Знайдено: {shown.length}</p>}
      {!lib ? (
        <div className="skeleton-block" aria-busy="true">
          <i />
          <i />
          <i />
        </div>
      ) : lib.length ? (
        <table className="usage">
          <tbody>
            {shown.map(x => (
              <tr key={x.name}>
                <td>
                  <code>/{x.name}</code>
                </td>
                <td className="meta">{x.description}</td>
                <td>{x.category}</td>
                <td>
                  <button className="icon" title="Прибрати з бібліотеки" onClick={() => del(x.name)}>
                    <Ic i={Trash2} size={20} />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="hint">Бібліотека порожня.</p>
      )}
    </div>
  );
}

function ProfileSkills({name, setError, own = false}: {name: string; setError: (s: string) => void; own?: boolean}) {
  const P = own
    ? {list: '/me/skills/manage', lib: '/me/library', one: '/me/skills/'}
    : {
        list: `/admin/host/profiles/${name}/skills`,
        lib: `/admin/host/profiles/${name}/library`,
        one: `/admin/host/profiles/${name}/skills/`,
      };
  const [d, setD] = useState<{library_enabled: boolean; skills: Skill[]} | null>(() => peek(P.list) ?? null),
    [filter, setFilter] = useState(''),
    [busy, setBusy] = useState('');
  async function act(key: string, fn: () => Promise<unknown>) {
    setBusy(key);
    setError('');
    try {
      await fn();
      setD(await api(P.list));
      toast('Збережено');
    } catch (e) {
      setError(err(e));
      toast('Не вдалося зберегти', 'error');
    } finally {
      setBusy('');
    }
  }
  useEffect(() => {
    api(P.list)
      .then(setD)
      .catch(e => setError(err(e)));
  }, [name]);
  if (!d)
    return (
      <div className="skeleton-block" aria-busy="true">
        <i />
        <i />
        <i />
      </div>
    );
  const order = ['local', 'external', 'hub', 'builtin'];
  const shown = d.skills
    .filter(x => !filter || x.name.includes(filter.toLowerCase()) || x.category.includes(filter.toLowerCase()))
    .sort((a, b) => order.indexOf(a.source) - order.indexOf(b.source) || a.name.localeCompare(b.name));
  const on = d.skills.filter(x => x.enabled).length;
  return (
    <div className="cards">
      <div className="card">
        <div className="row">
          <h3>Бібліотека</h3>
          <span className="hint">
            увімкнено {on} з {d.skills.length}
          </span>
        </div>
        <label className="warn-check">
          <input
            type="checkbox"
            checked={d.library_enabled}
            disabled={!!busy}
            onChange={e => act('lib', () => api(P.lib, json('PUT', {enabled: e.target.checked})))}
          />{' '}
          Підключити загальну бібліотеку
        </label>
        <p className="hint">
          Вимкнений скіл не завантажується агентом і не показується в «/».{' '}
          {own ? 'Зміни застосовуються до нових діалогів.' : 'Хто з користувачів може викликати скіл — задається у правах.'}
        </p>
      </div>
      <div className="card">
        <div className="row">
          <h3>Скіли профілю</h3>
          <input placeholder="фільтр…" value={filter} onChange={e => setFilter(e.target.value)} />
        </div>
        <table className="usage">
          <tbody>
            {shown.map(x => (
              <tr key={x.source + x.name} className={x.enabled ? '' : 'off'}>
                <td>
                  <label className="inline">
                    <input
                      type="checkbox"
                      checked={x.enabled}
                      disabled={busy === x.name}
                      onChange={e => act(x.name, () => api(P.one + encodeURIComponent(x.name), json('PUT', {enabled: e.target.checked})))}
                    />{' '}
                    <code>{x.name}</code>
                  </label>
                </td>
                <td>{SOURCE[x.source] ?? x.source}</td>
                <td className="meta">{x.category}</td>
                <td>
                  {x.source === 'local' && (
                    <div className="row">
                      {!own && (
                        <button
                          onClick={() =>
                            act(x.name, () =>
                              api(`/admin/host/profiles/${name}/skills/${encodeURIComponent(x.name)}/promote`, {method: 'POST'})
                            )
                          }
                        >
                          До бібліотеки
                        </button>
                      )}
                      <button
                        className="icon"
                        title="Видалити особистий скіл"
                        onClick={async () =>
                          (await ask(`Видалити ${x.name}?`, {danger: true, ok: 'Так'})) &&
                          act(x.name, () => api(P.one + encodeURIComponent(x.name), {method: 'DELETE'}))
                        }
                      >
                        <Ic i={Trash2} size={20} />
                      </button>
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

type Plugin = {name: string; enabled: boolean; description: string; group: string};
function PluginsPane({base, owner = false}: {base: string; owner?: boolean}) {
  const [d, setD] = useState<{sandbox: boolean; plugins: Plugin[]} | null>(() => peek(base) ?? null),
    [error, setError] = useState(''),
    [busy, setBusy] = useState('');
  useEffect(() => {
    api(base)
      .then(setD)
      .catch(e => setError(err(e)));
  }, [base]);
  async function toggle(x: Plugin, on: boolean) {
    setBusy(x.name);
    setError('');
    try {
      setD(await api(base + '/' + encodeURIComponent(x.name), json('PUT', {enabled: on})));
    } catch (e) {
      setError(err(e));
    } finally {
      setBusy('');
    }
  }
  if (!d)
    return error ? (
      <div className="error">{error}</div>
    ) : (
      <div className="skeleton-block" aria-busy="true">
        <i />
        <i />
        <i />
      </div>
    );
  const groups = [...new Set(d.plugins.map(p => p.group))];
  return (
    <>
      {error && <div className="error">{error}</div>}
      {owner ? (
        <div className="warning">Плагіни головного профілю керуються на сервері (команда hermes plugins), тут лише перегляд.</div>
      ) : (
        !d.sandbox && (
          <div className="warning">
            <Ic i={TriangleAlert} /> Увімкнути плагін можна лише для профілю з пісочницею Docker. Вимикати можна завжди.
          </div>
        )
      )}
      <p className="hint">
        Плагін завантажується агентом під час старту, тому кожна зміна перезапускає профіль (активні відповіді обриваються). Встановлення
        нових плагінів — лише адміністратором на сервері.
      </p>
      {busy && <div className="warning">Застосовуємо {busy}, перезапуск профілю…</div>}
      {groups.map(g => (
        <div className="card" key={g}>
          <h3>{g}</h3>
          <div className="tools">
            {d.plugins
              .filter(p => p.group === g)
              .map(p => (
                <label key={p.name} title={p.description}>
                  <input
                    type="checkbox"
                    checked={p.enabled}
                    disabled={owner || !!busy || (!p.enabled && !d.sandbox)}
                    onChange={e => toggle(p, e.target.checked)}
                  />
                  <span>
                    {p.name}
                    <br />
                    <small className="hint">
                      {p.description.slice(0, 90)}
                      {p.description.length > 90 ? '…' : ''}
                    </small>
                  </span>
                </label>
              ))}
          </div>
        </div>
      ))}
    </>
  );
}

function Defaults() {
  const [profiles, setProfiles] = useState<string[]>([]),
    [profile, setProfile] = useState('');
  useEffect(() => {
    api('/admin/profiles')
      .then((p: string[]) => {
        setProfiles(p);
        setProfile(p.includes('default') ? 'default' : p[0] || '');
      })
      .catch(() => {});
  }, []);
  return (
    <div className="detail-pane">
      <div className="page-head">
        <h1>Права за замовчуванням</h1>
        <p className="hint">Застосовуються до всіх звичайних користувачів, якщо в їхніх особистих правах не задано інше.</p>
      </div>
      <div className="card">
        <div className="row filters">
          <label>
            Список команд узято з профілю
            <select value={profile} onChange={e => setProfile(e.target.value)}>
              {profiles.map(p => (
                <option key={p}>{p}</option>
              ))}
            </select>
          </label>
        </div>
        {profile && <PermissionEditor key={profile} subject="role:user" title="" profile={profile} />}
      </div>
    </div>
  );
}
