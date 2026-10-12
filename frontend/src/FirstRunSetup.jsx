import React, { useState } from 'react';
import { api } from './api.js';

export default function FirstRunSetup({ completed }) {
  const [fields, setFields] = useState({ setup_code: '', password: '', openai_key: '', anthropic_key: '' });
  const [busy, setBusy] = useState(false), [error, setError] = useState('');
  function change(name, value) { setFields(current => ({ ...current, [name]: value })); }
  function finish() {
    setFields({ setup_code: '', password: '', openai_key: '', anthropic_key: '' });
    completed();
  }
  async function save(event) {
    event.preventDefault(); setBusy(true); setError('');
    try {
      await api('/setup', 'POST', fields);
      finish();
    } catch (failure) {
      if (failure.status === 409 || failure.status === 503) {
        try {
          if ((await api('/setup')).required === false) { finish(); return; }
        } catch { /* Keep the form available when completion cannot be confirmed. */ }
      }
      const messages = {
        403: 'Incorrect owner code.',
        422: 'Check the owner code, password and optional API keys. Use a nonblank password of up to 200 printable characters.',
        429: 'Too many setup or sign-in attempts. Try again in a minute.',
        409: 'Setup is in progress. Wait a moment before trying again.'
      };
      setError(messages[failure.status] || 'Setup could not be verified. Wait a moment and try again.');
    } finally { setBusy(false); }
  }
  return <section className="welcome first-run">
    <p className="eyebrow">Welcome / First-time setup</p><h1>Set up your demo</h1>
    <p>Choose the password your presenters will use. Your settings are saved securely in OCI Vault.</p>
    <p className="muted" id="setup-guidance">Find <strong>Owner setup secret</strong> in the Resource Manager Apply outputs.
      In the same region, open <strong>Identity &amp; Security → Secret Management</strong>, choose the deployment’s
      compartment and open the secret matching that OCID. Under <strong>Versions</strong>, open the
      <strong> CURRENT</strong> version’s actions, select <strong>View Secret Contents</strong> and enable decoded Base64.
      Copy only the <strong>setup_code</strong> value. This owner code confirms you own this installation.
      Keep it private; after setup it is stored as <strong>owner_code</strong> for updating provider keys.</p>
    {error && <div className="error" role="alert">{error}</div>}
    <form onSubmit={save}>
      <fieldset disabled={busy}>
        <label>Owner code<input type="password" autoComplete="off" required
          aria-describedby="setup-guidance" value={fields.setup_code} onChange={e => change('setup_code', e.target.value)} /></label>
        <label>Demo password<input type="password" autoComplete="new-password" required
          aria-describedby="password-guidance" value={fields.password} onChange={e => change('password', e.target.value)} /></label>
        <p className="muted" id="password-guidance">Choose a nonblank password, up to 200 printable characters.
          Spaces and Unicode are supported; matching is exact.</p>
        <h2>Optional AI providers</h2>
        <p className="muted">OCI uses your deployment’s identity. Add either key, both or neither; you can change them
          later in Owner settings. Keys are saved in OCI Vault. Saving does not test access; run the public office
          example to check each provider. Model requests may incur charges.</p>
        <label>OpenAI API key (optional)<input type="password" autoComplete="off" maxLength={4096}
          value={fields.openai_key} onChange={e => change('openai_key', e.target.value)} /></label>
        <label>Anthropic API key (optional)<input type="password" autoComplete="off" maxLength={4096}
          value={fields.anthropic_key} onChange={e => change('anthropic_key', e.target.value)} /></label>
        <button className="primary" disabled={busy}>{busy ? 'Saving setup…' : 'Save setup'}</button>
      </fieldset>
    </form>
  </section>;
}
