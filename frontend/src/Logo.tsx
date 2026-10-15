/** Shroom mark: a mushroom drawn with currentColor (cap with spots + stem). */
export function Logo({size = 20}: {size?: number}) {
  return (
    <svg className="logo" width={size} height={size} viewBox="0 0 24 24" aria-hidden="true">
      <path fill="currentColor" d="M12 2.5C6.4 2.5 2 6.6 2 11.2c0 1 .8 1.8 1.8 1.8h16.4c1 0 1.8-.8 1.8-1.8C22 6.6 17.6 2.5 12 2.5z" />
      <circle cx="8" cy="7.6" r="1.5" fill="var(--logo-spot, #fff)" opacity=".85" />
      <circle cx="14.6" cy="6.2" r="1.1" fill="var(--logo-spot, #fff)" opacity=".85" />
      <circle cx="16.8" cy="10" r="1" fill="var(--logo-spot, #fff)" opacity=".85" />
      <path fill="currentColor" d="M9 14.2h6l.6 5.6c.2 1.5-1 2.7-2.4 2.7h-2.4c-1.5 0-2.6-1.2-2.4-2.7z" opacity=".8" />
    </svg>
  );
}
