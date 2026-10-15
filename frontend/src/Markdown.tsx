import React from 'react';
/** Markdown renderer is loaded on demand (react-markdown + remark-gfm ~ 1/3 of the bundle); plain text shows meanwhile. */
const Impl = React.lazy(() => import('./MarkdownImpl').then(m => ({default: m.Markdown})));
export const Markdown = React.memo(function Markdown({text}: {text: string}) {
  return (
    <React.Suspense
      fallback={
        <div className="md" style={{whiteSpace: 'pre-wrap'}}>
          {text}
        </div>
      }
    >
      <Impl text={text} />
    </React.Suspense>
  );
});
