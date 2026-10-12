import React from 'react';

const fields = [
  ['supplier', 'Supplier'], ['account', 'Full account identity'], ['meter', 'Meter identity'],
  ['period_start', 'Start date', 'date'], ['period_end', 'End date', 'date'],
  ['days', 'Billed days', 'number'], ['consumption', 'Consumption', 'text'],
  ['current_total', 'Current electricity charges', 'text'], ['currency', 'Currency'],
  ['unit', 'Usage unit']
];
const choices = {
  service: ['Service type', ['unknown', 'electricity', 'water', 'gas', 'mixed']],
  usage_kind: ['Usage meaning', ['unknown', 'consumption', 'net', 'export']]
};

export default function BillEditor({ doc, draft, dirty, busy, providers, models, change, save, approve, extract, cancel }) {
  const [provider, setProvider] = React.useState(providers[0] || '');
  const [consent, setConsent] = React.useState(false);
  React.useEffect(() => {
    if (!providers.includes(provider)) { setProvider(providers[0] || ''); setConsent(false); }
  }, [providers, provider]);
  const running = doc.job?.status === 'running';
  const evidence = doc.proposal?.evidence || {};
  function fieldEvidence(name) {
    const item = evidence[name];
    return item && <details className="evidence"><summary>Source · page {item.page}{doc.corrections.includes(name) ? ' · corrected' : ''}</summary>
      <blockquote>{item.quote}</blockquote>
      <small>AI proposed: {String(doc.proposal.facts[name] ?? '')}</small>
    </details>;
  }
  function updateCharge(index, key, value) {
    change('charges', draft.charges.map((charge, i) => i === index ? { ...charge, [key]: value } : charge));
  }
  return <section aria-labelledby="review-heading">
    <div className="section-title"><div><p className="eyebrow">02 / Review</p><h2 id="review-heading">Check the bill facts</h2></div>
      <span className={'tag ' + (doc.approved_revision === doc.revision && !dirty ? 'approved' : '')}>
        {doc.approved_revision === doc.revision && !dirty ? 'Approved' : 'Needs review'}
      </span></div>
    <p className="muted">Check dates, units and charges against the source. Blank means unknown.
      Keep consumption in the bill’s stated usage unit.
      Monthly totals cannot establish peak demand or battery savings.</p>
    <div className="ai-panel">
      {providers.length ? <>
        <label>AI provider<select value={provider} onChange={e => { setProvider(e.target.value); setConsent(false); }} disabled={busy || running}>
          {providers.map(p => <option key={p}>{p}</option>)}</select></label>
        <p className="muted">Model: {models?.[provider]} · {provider === 'oci'
          ? models?.[provider]?.startsWith('google.') ? 'This Gemini model is externally hosted through OCI.' : 'Check the selected OCI model and region’s hosting arrangement before sending bill text.'
          : 'Bill text is sent to ' + provider + '.'}</p>
        <label className="check"><input type="checkbox" checked={consent} onChange={e => setConsent(e.target.checked)} />
          Send this bill’s extracted text, including identifiers, to the selected provider for a proposal.</label>
        <button disabled={!consent || !providers.includes(provider) || busy || running || dirty} onClick={() => extract(provider)}>Extract with AI</button>
      </> : <p><strong>AI is not configured.</strong> Enter facts manually or use the example.
        Server-side provider credentials enable optional extraction.</p>}
      {running && <p role="status">Reading bill… <button onClick={cancel}>Cancel extraction</button></p>}
      {doc.job?.status === 'failed' && <p role="alert">{doc.job.error}</p>}
      {doc.job?.status === 'complete' && <p className="muted">Proposal ready · {doc.job.usage.requests} model request{doc.job.usage.requests === 1 ? '' : 's'} · review before approving.</p>}
    </div>
    <fieldset disabled={busy || running} className="fact-fields">
      <legend className="sr-only">Editable bill facts</legend>
      <div className="field-grid">
        {Object.entries(choices).map(([name, [label, options]]) => <label key={name}>{label}
          <select value={draft[name]} onChange={e => change(name, e.target.value)}>
            {options.map(option => <option key={option}>{option}</option>)}</select>{fieldEvidence(name)}</label>)}
        {fields.map(([name, label, type = 'text']) => <label key={name}>{label}
          <input type={type} min={type === 'number' ? 1 : undefined} max={type === 'number' ? 366 : undefined}
            maxLength={type === 'text' ? 160 : undefined} value={draft[name] ?? ''}
            onChange={e => change(name, e.target.value === '' ? null : name === 'days' ? Number(e.target.value) : e.target.value)} />
          {fieldEvidence(name)}</label>)}
      </div>
      <h3>Charge breakdown</h3>
      <p className="muted">Additive charges build the current electricity total. Included fees are already in another charge.
        Exclude previous balances, payments and other services.</p>
      {draft.charges.map((charge, index) => <div className="charge" key={index}>
        <label>Charge {index + 1}<input value={charge.label} maxLength={160} onChange={e => updateCharge(index, 'label', e.target.value)} /></label>
        <label>Amount {index + 1}<input value={charge.amount} inputMode="decimal" onChange={e => updateCharge(index, 'amount', e.target.value)} /></label>
        <label>Role {index + 1}<select value={charge.role} onChange={e => updateCharge(index, 'role', e.target.value)}>
          {['additive', 'included', 'excluded'].map(role => <option key={role}>{role}</option>)}</select></label>
        <button className="quiet" aria-label={'Remove charge ' + (index + 1)}
          onClick={() => change('charges', draft.charges.filter((_, i) => i !== index))}>Remove</button>
        {evidence['charges.' + index] && <details className="evidence"><summary>Original charge evidence · page {evidence['charges.' + index].page}</summary>
          <blockquote>{evidence['charges.' + index].quote}</blockquote>
          <small>Evidence belongs to the original proposal; edited or reordered rows require your review.</small>
        </details>}
      </div>)}
      <button className="quiet" disabled={draft.charges.length >= 40}
        onClick={() => change('charges', [...draft.charges, { label: '', amount: '', role: 'additive' }])}>Add charge</button>
    </fieldset>
    <div className="actions">
      <button disabled={busy || running || !dirty} onClick={save}>Save corrections</button>
      <button className="primary" disabled={busy || running || dirty || doc.approved_revision === doc.revision} onClick={approve}>Approve reviewed facts</button>
    </div>
    <p className="muted">Approval confirms you reviewed the available facts. Missing facts keep the affected metrics unavailable.</p>
  </section>;
}
