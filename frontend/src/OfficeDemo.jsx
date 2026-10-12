import React, { useEffect, useRef, useState } from 'react';
import DemandChart from './DemandChart.jsx';
import OfficeRun from './OfficeRun.jsx';

const defaults = { power_kw: 25, capacity_kwh: 100, efficiency: .9, target_kw: 80 };
const money = value => new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(Number(value));

export default function OfficeDemo({ session, request, handle }) {
  const [profile, setProfile] = useState(null), [controls, setControls] = useState(defaults);
  const [scenario, setScenario] = useState(null), [run, setRun] = useState(null), [history, setHistory] = useState([]);
  const [provider, setProvider] = useState(session.providers[0] || ''), [question, setQuestion] = useState('evaluate_battery');
  const [consent, setConsent] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState('');
  const mounted = useRef(true), pending = useRef(null), revision = useRef(0);
  useEffect(() => {
    if (!session.providers.includes(provider)) {
      setProvider(session.providers[0] || ''); setConsent(false); pending.current = null;
    }
  }, [session.providers, provider]);
  function fail(error) {
    if (!mounted.current || error.stale) return;
    if (error.status === 401) handle(error);
    else setError(error.message || 'The request failed. Please try again.');
  }
  async function refresh() {
    const items = await request('/office/runs');
    if (mounted.current) setHistory(items);
  }
  useEffect(() => {
    mounted.current = true;
    request('/office').then(value => { if (mounted.current) setProfile(value); }).catch(fail);
    refresh().catch(fail);
    return () => { mounted.current = false; };
  }, []);
  useEffect(() => {
    if (run?.status !== 'running') return;
    let active = true, timer;
    async function poll() {
      try {
        const value = await request('/office/runs/' + run.id);
        if (!active || !mounted.current) return;
        setRun(value); setError('');
        if (value.status === 'running') timer = setTimeout(poll, 700);
        else await refresh();
      } catch (error) {
        if (!active || !mounted.current) return;
        fail(error);
        if (error.status !== 401 && !error.stale) timer = setTimeout(poll, 2000);
      }
    }
    timer = setTimeout(poll, 500);
    return () => { active = false; clearTimeout(timer); };
  }, [run?.id, run?.status]);
  function change(name, value) {
    revision.current += 1; pending.current = null;
    setControls(current => ({ ...current, [name]: value })); setScenario(null); setRun(null); setError('');
  }
  async function act(action) {
    setBusy(true); setError('');
    try { await action(); } catch (error) { fail(error); }
    finally { if (mounted.current) setBusy(false); }
  }
  const numeric = Object.fromEntries(Object.entries(controls).map(([key, value]) => [key, Number(value)]));
  const valid = Object.values(controls).every(value => value !== '' && Number.isFinite(Number(value))) &&
    numeric.power_kw >= 0 && numeric.power_kw <= 500 && numeric.capacity_kwh >= 0 && numeric.capacity_kwh <= 2000 &&
    numeric.efficiency > 0 && numeric.efficiency <= 1 && numeric.target_kw > 0 && numeric.target_kw <= 500;
  const running = run?.status === 'running';
  if (!profile) return <section><p role="status">Loading the prepared office…</p>{error && <p role="alert">{error}</p>}</section>;
  return <div className="office-demo">
    {error && <div className="error" role="alert">{error}</div>}
    <section className="office-overview">
      <p className="eyebrow">Prepared example / June 2018</p><h2>A month in the office.</h2>
      <p>Explore the load, explain the bill and test how a battery changes demand.</p>
      <p className="notice">Public ComStock modeled office data · invented flat tariff · illustrative results.</p>
      <div className="metrics office-metrics">
        <div><span>Illustrative monthly bill</span><strong data-testid="office-total">{money(profile.bill.total_usd)}</strong></div>
        <div><span>Electricity consumed</span><strong>{Number(profile.bill.energy_kwh).toLocaleString('en-US', { maximumFractionDigits: 0 })} kWh</strong></div>
        <div><span>Peak demand</span><strong>{Number(profile.bill.peak_kw).toFixed(2)} kW</strong></div>
      </div>
      <div className="office-links"><a href="/api/office/bill.pdf" download>Download illustrative bill</a>
        <a href={profile.source_url} target="_blank" rel="noreferrer">Public source &amp; provenance ↗</a></div>
      <details><summary>Bill and source assumptions</summary>
        <p>{profile.notice} {profile.clock} {profile.license}</p>
        <p>Energy {money(profile.bill.energy_charge_usd)} + demand {money(profile.bill.demand_charge_usd)} + fixed {money(profile.bill.fixed_charge_usd)}.</p>
        <p>{money(profile.tariff.energy_usd_per_kwh)}/kWh · {money(profile.tariff.demand_usd_per_kw)}/kW · {money(profile.tariff.fixed_usd_per_month)}/month.</p>
      </details>
    </section>
    <div className="office-columns"><section>
      <p className="eyebrow">01 / Inspect demand</p><h2>What happens on the peak day?</h2>
      <p className="muted">Peak interval: {profile.peak_interval_start.replace('T', ' ')}–{profile.peak_interval_end.slice(11)}. Unzoned source clock.</p>
      <DemandChart rows={scenario?.peak_day || profile.peak_day} scenario={!!scenario} />
      <details><summary>Daily peak demand for the month</summary><div className="table-scroll"><table>
        <thead><tr><th>Source day</th><th>Peak (kW)</th></tr></thead>
        <tbody>{profile.daily_peaks.map(row => <tr key={row.day}><td>{row.day}</td><td>{row.peak_kw.toFixed(2)}</td></tr>)}</tbody>
      </table></div></details>
    </section><section>
      <p className="eyebrow">02 / Try a battery</p><h2>Change the scenario.</h2>
      <fieldset disabled={busy || running}><div className="field-grid">
        {[
          ['power_kw', 'Power (kW)', 0, 500, 1], ['capacity_kwh', 'Capacity (kWh)', 0, 2000, 1],
          ['efficiency', 'Round-trip efficiency (0–1)', .01, 1, .01], ['target_kw', 'Target peak (kW)', .01, 500, 1]
        ].map(([name, label, min, max, step]) => <label key={name}>{label}<input type="number" min={min} max={max} step={step}
          value={controls[name]} onChange={e => change(name, e.target.value)} /></label>)}
      </div></fieldset>
      <div className="view-switch"><button className="primary" disabled={!valid || busy || running} onClick={() => act(async () => {
        const version = revision.current, value = await request('/office/scenario', 'POST', numeric);
        if (mounted.current && version === revision.current) setScenario(value);
      })}>Calculate scenario</button><button disabled={busy || running} onClick={() => {
        revision.current += 1; pending.current = null; setControls(defaults); setScenario(null); setRun(null); setError('');
      }}>Reset scenario</button></div>
      {!valid && <p role="alert">Enter battery values within the indicated limits.</p>}
      {scenario && <div className="metrics">
        <div><span>Modeled bill</span><strong>{money(scenario.scenario_bill.total_usd)}</strong></div>
        <div><span>Modeled cost difference</span><strong data-testid="office-difference">{money(scenario.modeled_cost_difference_usd)}</strong></div>
      </div>}
      {scenario && <p>{scenario.battery.target_achieved ? 'Target reached' : 'Target not reached'} · charging losses {scenario.battery.losses_kwh.toFixed(2)} kWh.</p>}
      <p className="muted">No model key needed. Hindsight dispatch includes charging losses and starts/ends empty. Excludes equipment cost, taxes, time-of-use rates and demand ratchets. This is not equipment ROI.</p>
    </section></div>
    <section>
      <p className="eyebrow">03 / Ask the analysts</p><h2>Explain the evidence.</h2>
      <p>Energy Analyst inspects the office. Tariff &amp; Savings Analyst calculates the selected battery and explains its effect.</p>
      {session.providers.length ? <>
        <fieldset disabled={busy || running}><div className="field-grid">
          <label>Office AI provider<select value={provider} onChange={e => { setProvider(e.target.value); setConsent(false); setRun(null); pending.current = null; }}>
            {session.providers.map(name => <option key={name}>{name}</option>)}</select></label>
          <label>Analysis question<select value={question} onChange={e => { setQuestion(e.target.value); setRun(null); pending.current = null; }}>
            <option value="evaluate_battery">How does this battery change the bill?</option><option value="explain_bill">What drives the office bill?</option></select></label>
        </div><p className="muted">Configured model: {session.models[provider]}. Availability is checked when you run it.</p>
          <label className="check"><input type="checkbox" checked={consent} onChange={e => setConsent(e.target.checked)} />
            Send the public office sample and selected scenario to {provider} for AI analysis. No uploaded bills are included.</label>
        </fieldset>
        <button className="primary" disabled={!consent || !session.providers.includes(provider) || !valid || busy || running} onClick={() => act(async () => {
          pending.current ||= crypto.randomUUID();
          const value = await request('/office/runs', 'POST', { request_key: pending.current, provider, consent: true, controls: numeric, question });
          if (mounted.current) { setRun(value); pending.current = null; }
          await refresh();
        })}>Run analysts</button>
      </> : <p className="notice">No AI provider is configured. Explore the bill and battery calculations now; configure a provider to run the analysts.</p>}
    </section>
    {run && <OfficeRun key={run.id} run={run} cancel={() => act(async () => {
      const value = await request('/office/runs/' + run.id, 'DELETE');
      if (mounted.current) setRun(value);
      await refresh();
    })} />}
    <section className="office-history"><div className="section-title"><h2>Public demo history</h2>
      <button disabled={busy} onClick={() => act(refresh)}>Refresh history</button></div>
      <p className="muted">Shared with signed-in presenters. Up to 100 runs for 7 days; retained across sign-out and server restart. Your uploaded bills are session-only.</p>
      {!history.length && <p>No office analyses yet.</p>}
      {history.map(item => <button key={item.id} disabled={busy || running} onClick={() => {
        revision.current += 1; setRun(item); setControls(item.controls);
        setProvider(session.providers.includes(item.provider) ? item.provider : session.providers[0] || '');
        setQuestion(item.question);
        setConsent(false); setScenario(null); pending.current = null;
      }}>{new Date(item.created * 1000).toLocaleString()} · {item.provider} · {item.status} · {item.controls.power_kw} kW / {item.controls.capacity_kwh} kWh</button>)}
    </section>
  </div>;
}
