import React, {useEffect, useRef, useState} from 'react';
import ReactMarkdown, {type Components} from 'react-markdown';
import remarkGfm from 'remark-gfm';

/** Agent replies as GitHub-flavoured Markdown. Raw HTML is not rendered (react-markdown default), links open in a new tab.
 * `components` and the plugin list are module constants: inline ones are new component types on every render, so the
 * chat poll (every 0.5-1.5 s) remounted each code block and table and reset its horizontal scroll to the left. */
const PLUGINS = [remarkGfm];
const COMPONENTS: Components = {
  a: ({href, children}) => (
    <a href={href} target="_blank" rel="noopener noreferrer">
      {children}
    </a>
  ),
  pre: ({children}) => <CodeBlock>{children}</CodeBlock>,
  table: ({children}) => (
    <div className="md-table">
      <table>{children}</table>
    </div>
  ),
};
export const Markdown = React.memo(function Markdown({text}: {text: string}) {
  return (
    <div className="md">
      <ReactMarkdown remarkPlugins={PLUGINS} components={COMPONENTS}>
        {text}
      </ReactMarkdown>
    </div>
  );
});

function CodeBlock({children}: {children: React.ReactNode}) {
  const [copied, setCopied] = useState(false),
    [copying, setCopying] = useState(false),
    [error, setError] = useState('');
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    []
  );
  const copy = async () => {
    if (copying) return;
    setCopying(true);
    setError('');
    setCopied(false);
    try {
      if (!navigator.clipboard?.writeText) throw new Error('Clipboard unavailable');
      await navigator.clipboard.writeText(code);
      setCopied(true);
      if (timer.current) clearTimeout(timer.current);
      timer.current = setTimeout(() => setCopied(false), 1500);
    } catch {
      setError('Не вдалося скопіювати. Виділіть код і натисніть Ctrl+C або ⌘C.');
    } finally {
      setCopying(false);
    }
  };
  const child = React.Children.toArray(children)[0] as React.ReactElement<{className?: string; children?: React.ReactNode}> | undefined;
  const lang = /language-([\w+-]+)/.exec(child?.props?.className ?? '')?.[1] ?? '';
  const code = String(child?.props?.children ?? '').replace(/\n$/, '');
  return (
    <div className="md-code">
      <div className="md-code-bar">
        <span>{lang}</span>
        <button className="md-copy" disabled={copying} aria-busy={copying} onClick={copy}>
          {copying ? 'Копіюємо…' : copied ? 'Скопійовано' : 'Копіювати'}
        </button>
      </div>
      {error && (
        <div className="error" role="alert">
          {error}
        </div>
      )}
      <pre>
        <code>{code}</code>
      </pre>
    </div>
  );
}
