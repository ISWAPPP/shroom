import React, {useState} from 'react';
export type Interaction = {
  id: string;
  method: string;
  params: {
    command?: string;
    description?: string;
    choices?: string[];
    questions?: {qid: string; question: string; choices?: string[]; multi_select?: boolean}[];
  };
};
export function RequestCard({request, answer}: {request: Interaction; answer: (r: Interaction, result: object) => Promise<void>}) {
  const [values, setValues] = useState<Record<string, string>>({}),
    [sending, setSending] = useState(false);
  async function submit(result: object) {
    setSending(true);
    try {
      await answer(request, result);
    } finally {
      setSending(false);
    }
  }
  return (
    <article className="assistant interaction">
      <label>{request.method === 'approval' ? 'ДОЗВІЛ НА КОМАНДУ' : 'УТОЧНЕННЯ ВІД SHROOM'}</label>
      {request.method === 'approval' ? (
        <>
          <p>{request.params.description}</p>
          <pre>{request.params.command}</pre>
          <button disabled={sending || !request.params.choices?.includes('once')} onClick={() => submit({choice: 'once'})}>
            Дозволити один раз
          </button>
          <button disabled={sending} onClick={() => submit({choice: 'deny'})}>
            Відхилити
          </button>
        </>
      ) : (
        <form
          onSubmit={e => {
            e.preventDefault();
            submit({answers: Object.fromEntries((request.params.questions ?? []).map(q => [q.qid, values[q.qid] || null]))});
          }}
        >
          {request.params.questions?.map(q => (
            <div key={q.qid}>
              <label>{q.question}</label>
              {q.choices?.map(c => (
                <label key={c}>
                  <input
                    type={q.multi_select ? 'checkbox' : 'radio'}
                    name={q.qid}
                    checked={q.multi_select ? (values[q.qid] ?? '').split(', ').includes(c) : values[q.qid] === c}
                    onChange={e =>
                      setValues(v => ({
                        ...v,
                        [q.qid]: q.multi_select
                          ? (e.target.checked
                              ? [...(v[q.qid] ?? '').split(', ').filter(Boolean), c]
                              : (v[q.qid] ?? '').split(', ').filter(x => x !== c)
                            ).join(', ')
                          : c,
                      }))
                    }
                  />
                  {c}
                </label>
              ))}
              <input
                aria-label={q.question}
                placeholder="Відповідь / інше (не вводьте секрети)"
                maxLength={4000}
                value={values[q.qid] ?? ''}
                onChange={e => setValues(v => ({...v, [q.qid]: e.target.value}))}
              />
            </div>
          ))}
          <button disabled={sending}>Надіслати відповіді (порожні — пропустити)</button>
          <button type="button" disabled={sending} onClick={() => submit({})}>
            Скасувати уточнення
          </button>
        </form>
      )}
    </article>
  );
}
