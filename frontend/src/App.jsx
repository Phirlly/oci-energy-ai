import React, { useEffect, useRef, useState } from 'react';
import { api } from './api.js';
import BillEditor from './BillEditor.jsx';
import Insights from './Insights.jsx';

export default function App() {
  const generation = useRef(0);
  const [session, setSession] = useState(null), [code, setCode] = useState('');
  const [docs, setDocs] = useState([]), [selected, setSelected] = useState(null);
  const [draft, setDraft] = useState(null), [dirty, setDirty] = useState(false);
  const [checked, setChecked] = useState([]), [result, setResult] = useState(null);
  const [error, setError] = useState(''), [busy, setBusy] = useState(false);
  const doc = docs.find(item => item.id === selected);
  function clear() {
    generation.current += 1;
    setSession(null); setDocs([]); setSelected(null); setDraft(null); setChecked([]); setResult(null); setDirty(false);
  }
  function handle(error) {
    if (error.stale) return;
    if (error.status === 401) clear();
    setError(error.message);
  }
  async function request(...args) {
    const started = generation.current;
    try {
      const value = await api(...args);
      if (started !== generation.current) throw Object.assign(new Error(), { stale: true });
      return value;
    } catch (error) {
      if (started !== generation.current) error.stale = true;
      throw error;
    }
  }
  async function run(action) {
    setError(''); setBusy(true);
    try { await action(); } catch (error) { handle(error); } finally { setBusy(false); }
  }
  function install(value) {
    setDocs(current => [...current.filter(item => item.id !== value.id), value]);
    setSelected(value.id); setDraft(structuredClone(value.facts)); setDirty(false); setResult(null);
  }
  useEffect(() => {
    let active = true;
    request('/session').then(async value => {
      const documents = await request('/documents');
      if (active) { setSession(value); setDocs(documents); }
    }).catch(() => {});
    return () => { active = false; };
  }, []);
  useEffect(() => {
    if (!session) return;
    const timer = setInterval(() => request('/session').then(setSession).catch(handle), 15000);
    return () => clearInterval(timer);
  }, [!!session]);
  useEffect(() => {
    if (doc?.job?.status !== 'running') return;
    let active = true;
    const timer = setInterval(() => request('/documents/' + doc.id).then(value => {
      if (active) install(value);
    }).catch(handle), 1000);
    return () => { active = false; clearInterval(timer); };
  }, [doc?.id, doc?.job?.status]);
  function change(name, value) {
    setDraft(current => ({ ...current, [name]: value })); setDirty(true); setResult(null);
  }
  const approved = docs.filter(item => item.approved_revision === item.revision);
  return <>
    <header><a className="brand" href="/" aria-label="Energy AI home"><span className="brand-mark">ϟ</span> ENERGY AI</a>
      <div className="header-right"><span className="tag">OCI demo · Local session</span>
        {session && <button className="quiet" disabled={busy} onClick={() => run(async () => { await request('/session', 'DELETE'); clear(); })}>Sign out</button>}</div>
    </header>
    <main>
      {error && <div className="error" role="alert">{error}</div>}
      {!session ? <section className="welcome">
        <p className="eyebrow">From a bill to a clearer picture</p><h1>Understand the energy<br />behind the numbers.</h1>
        <p>Review electricity bills, check the facts and explore your consumption and costs.</p>
        <form onSubmit={e => { e.preventDefault(); run(async () => {
          await request('/session', 'POST', { code }); setCode(''); setSession(await request('/session')); setDocs([]);
        }); }}>
          <label>Launch code<input type="password" autoComplete="off" required value={code} onChange={e => setCode(e.target.value)} /></label>
          <button className="primary" disabled={busy}>Start session</button>
        </form>
        <p className="muted">Use the code printed by the local server. Work is kept in memory for 30 minutes and cleared on sign-out or restart.</p>
      </section> : <>
        <div className="hero"><div><p className="eyebrow">Bill intelligence / Human reviewed</p>
          <h1>Your electricity, understood.</h1><p>One bill or a year of bills. See the facts, review them, then explore what they tell you.</p></div>
          <span className="session-note">{Math.ceil(session.expires_in / 60)} min remaining</span></div>
        <div className="workspace">
          <aside>
            <section className="intake"><p className="eyebrow">01 / Bring your bills</p><h2>Start with a statement</h2>
              <label className="upload">Upload bill PDFs<input aria-label="Upload bill PDFs" type="file" accept=".pdf,application/pdf" multiple disabled={busy || dirty}
                onChange={e => { const files = [...e.target.files]; e.target.value = ''; run(async () => {
                  for (const file of files) install(await request('/documents', 'POST', file));
                }); }} /></label>
              <p className="muted">Text PDFs · 4 MiB each · 20 pages · up to 12 bills. Scanned bills need OCR first.</p>
              <button className="example" disabled={busy || dirty} onClick={() => run(async () => install(await request('/example', 'POST')))}>Try the example</button>
              <p className="muted">A fictional bill, prefilled for review. No API key needed.</p>
            </section>
            <section className="bill-list"><h2>Your bills <span className="count">{docs.length}</span></h2>
              {!docs.length && <p className="muted">Uploaded bills will appear here.</p>}
              {docs.map((item, index) => <div className={'bill-row ' + (selected === item.id ? 'selected' : '')} key={item.id}>
                <button disabled={dirty || busy} onClick={() => { setSelected(item.id); setDraft(structuredClone(item.facts)); setDirty(false); }}>
                  <strong>{item.facts.supplier || 'Bill ' + (index + 1)}</strong>
                  <span>{item.facts.period_start || 'Dates need review'}</span>
                  <small>{item.approved_revision === item.revision ? 'Approved' : 'Needs review'}</small></button>
                <label className="check"><input type="checkbox" aria-label={'Include bill ' + (index + 1) + ' in insights'}
                  disabled={item.approved_revision !== item.revision || dirty || busy}
                  checked={checked.includes(item.id)}
                  onChange={e => { setChecked(current => e.target.checked ? [...current, item.id] : current.filter(id => id !== item.id)); setResult(null); }} />
                  Include in insights</label>
              </div>)}
              <button className="primary full" disabled={busy || dirty || !approved.some(item => checked.includes(item.id))}
                onClick={() => run(async () => setResult(await request('/insights', 'POST', {
                  revisions: Object.fromEntries(approved.filter(item => checked.includes(item.id)).map(item => [item.id, item.revision]))
                })))}>Calculate insights</button>
              <p className="muted">Combining bills requires matching identities, currency and non-overlapping periods.</p>
            </section>
          </aside>
          <div className="content">
            {doc && draft ? <>
              <div className="document-toolbar"><span>Revision {doc.revision}{dirty ? ' · Unsaved corrections' : ''}</span>
                <button className="quiet danger" disabled={busy} onClick={() => run(async () => {
                  await request('/documents/' + doc.id, 'DELETE');
                  setDocs(current => current.filter(item => item.id !== doc.id)); setSelected(null); setDraft(null);
                  setDirty(false); setResult(null); setChecked(current => current.filter(id => id !== doc.id));
                })}>Delete bill</button></div>
              <details className="source" open><summary>View extracted source text</summary>
                {doc.pages.map((text, index) => <div key={index}><h3>Page {index + 1}</h3><pre>{text}</pre></div>)}</details>
              <BillEditor key={doc.id} doc={doc} draft={draft} dirty={dirty} busy={busy} providers={session.providers} models={session.models}
                change={change}
                save={() => run(async () => install(await request('/documents/' + doc.id, 'PUT', { revision: doc.revision, facts: draft })))}
                approve={() => run(async () => {
                  const value = await request('/documents/' + doc.id + '/approve', 'POST', { revision: doc.revision });
                  install(value); setChecked(current => [...new Set([...current, doc.id])]);
                })}
                extract={provider => run(async () => install(await request('/documents/' + doc.id + '/extract', 'POST', { provider, consent: true })))}
                cancel={() => run(async () => install(await request('/documents/' + doc.id + '/extract', 'DELETE')))} />
            </> : <section className="empty"><span className="empty-symbol">↗</span><h2>A useful starting point.</h2>
              <p>Upload a bill or try the example. You’ll be able to inspect the source, correct the facts and approve the results.</p>
              <div className="steps"><span>1. Add bills</span><span>2. Review facts</span><span>3. Get insights</span></div></section>}
            {result && <Insights result={result} documents={docs} />}
          </div>
        </div>
      </>}
    </main>
    <footer>OCI Energy AI · Bill insights are calculated from reviewed facts. AI extraction is optional.</footer>
  </>;
}
