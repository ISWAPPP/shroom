import React from 'react';
import {Logo} from './Logo';

/** Session check: use the same centered shell as login, never a blank screen. */
export function SessionLoading() {
  return (
    <div className="login-wrap">
      <div className="login" role="status" aria-label="Перевіряємо сесію" aria-busy="true">
        <div className="brand">
          <Logo size={26} />
          <span>SHROOM</span>
        </div>
        <div className="skeleton-block" aria-hidden="true">
          <i />
          <i />
          <i />
        </div>
      </div>
    </div>
  );
}
