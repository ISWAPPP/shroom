import {Markdown} from './Markdown';
import React, {useEffect, useRef, useState} from 'react';

/** Reveals streamed text smoothly: catches up with the backlog at a rate that grows with its size,
 *  so chunks arriving every poll look like continuous typing instead of jumps. */
export function Typewriter({text}: {text: string}) {
  const [n, setN] = useState(0),
    shown = useRef(0),
    target = useRef(text);
  target.current = text;
  useEffect(() => {
    if (text.length < shown.current) {
      shown.current = 0;
      setN(0);
    } // new message
    let raf = 0,
      last = performance.now();
    const step = (t: number) => {
      const backlog = target.current.length - shown.current;
      if (backlog > 0) {
        const cps = Math.max(40, backlog * 2.5); // chars per second
        shown.current = Math.min(target.current.length, shown.current + Math.max(1, Math.round((cps * (t - last)) / 1000)));
        setN(shown.current);
      }
      last = t;
      raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [text]);
  return (
    <div className="typing">
      <Markdown text={text.slice(0, n)} />
      <i className="caret" aria-hidden="true" />
    </div>
  );
}
