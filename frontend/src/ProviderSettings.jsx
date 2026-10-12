import React, { useState } from 'react';

const empty = () => ({ openai: { action: 'keep', key: '' }, anthropic: { action: 'keep', key: '' } });

export default function ProviderSettings({ session, request, refresh, handle }) {
  const [owner, setOwner] = useState(''), [fields, setFields] = useState(empty);
  const [busy, setBusy] = useState(false), [error, setError] = useState(''), [saved, setSaved] = useState(false);
  function change(provider, action, key = '') {
    setFields(current => ({ ...current, [provider]: { action, key } })); setSaved(false);
  }
  async function save(event) {
    event.preventDefault(); setBusy(true); setError(''); setSaved(false);
    const changes = Object.fromEntries(Object.entries(fields).filter(([, field]) => field.action !== 'keep')
      .map(([name, field]) => [name, field.action === 'remove' ? null : field.key]));
    try {
      await request('/settings', 'POST', { owner_code: owner, changes });
      setOwner(''); setFields(empty());
      await refresh(); setSaved(true);
    } catch (failure) {
      if (failure.stale) return;
      if (failure.status === 401) handle(failure);
      else {
        setError(failure.message || 'Settings could not be verified. Wait a moment and try again.');
        if (failure.status === 409) await refresh().catch(handle);
      }
    } finally { setBusy(false); }
  }
  return <section className="welcome first-run" aria-labelledby="settings-heading">
    <p className="eyebrow">Deployment owner</p><h2 id="settings-heading">Manage provider keys</h2>
    <p>Add, replace or remove OpenAI and Anthropic keys. Saved keys stay in OCI Vault and are never displayed here.</p>
    <p className="muted" id="owner-guidance">Use the owner code from setup, separate from the demo password.
      You can find it as <strong>owner_code</strong> in the settings secret’s CURRENT version in OCI Vault.</p>
    {error && <p className="error" role="alert">{error}</p>}
    {saved && <p className="notice" role="status">Provider keys saved. New analyses use these settings.</p>}
    <form onSubmit={save}><fieldset disabled={busy}>
      <label>Owner code<input type="password" autoComplete="off" required aria-describedby="owner-guidance"
        value={owner} onChange={event => setOwner(event.target.value)} /></label>
      {Object.entries({ openai: 'OpenAI', anthropic: 'Anthropic' }).map(([provider, label]) => <div key={provider}>
        <p>{label}: {session.providers.includes(provider) ? 'Key configured' : 'No key configured'}</p>
        <label>{label} key action<select value={fields[provider].action}
          onChange={event => change(provider, event.target.value)}>
          <option value="keep">Keep unchanged</option><option value="replace">Set a new key</option>
          <option value="remove">Remove key</option>
        </select></label>
        {fields[provider].action === 'replace' && <label>New {label} API key<input type="password"
          autoComplete="off" maxLength={4096} required value={fields[provider].key}
          onChange={event => change(provider, 'replace', event.target.value)} /></label>}
      </div>)}
      <button className="primary" disabled={busy || Object.values(fields).every(field => field.action === 'keep')}>
        {busy ? 'Saving provider keys…' : 'Save provider keys'}</button>
    </fieldset></form>
    <p className="muted">Saving does not test provider access. To check a provider, select it in Office demo
      and run the public example after reviewing the consent checkbox. Model requests may incur charges.
      Analyses already running can finish with the previous key.</p>
  </section>;
}
