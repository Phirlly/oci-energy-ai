import React, { useState } from 'react';

export default function OfficeRun({ run, cancel }) {
  const [technical, setTechnical] = useState(false);
  const result = run.result;
  return <section className="office-result" aria-label="Office analysis result">
    <div className="section-title"><h2>Analyst run</h2><span className="tag" role="status" data-testid="office-run-status">{run.status}</span></div>
    <p className="muted">{run.provider} · {run.model}<br />
      {run.controls.power_kw} kW / {run.controls.capacity_kwh} kWh · {run.controls.efficiency * 100}% efficiency · {run.controls.target_kw} kW target</p>
    <div className="view-switch"><button aria-pressed={!technical} onClick={() => setTechnical(false)}>Demo view</button>
      <button aria-pressed={technical} onClick={() => setTechnical(true)}>Technical view</button></div>
    {run.status === 'running' && <p role="status">The analysts are checking the public sample. <button onClick={cancel}>Cancel analysis</button></p>}
    {run.error && <p className="error" role="alert">{run.error}</p>}
    {run.status === 'cancelled' && <p>Analysis cancelled. You can start another run.</p>}
    {result && <>
      <h3>Energy Analyst</h3><p>{result.energy.explanation}</p>
      <h3>Tariff &amp; Savings Analyst</h3><p>{result.savings.explanation}</p>
      <p className="notice">The numeric result fields were checked against the tools. AI explanations can still contain mistakes; review the source and assumptions.</p>
    </>}
    {technical && <div>
      {result && <p>{result.usage.tool_calls} tool calls · {result.usage.model_requests} model requests · {result.usage.input_tokens} input tokens · {result.usage.output_tokens} output tokens</p>}
      <p className="muted">Actual SDK activity and application verification. The transition between analysts is sequential application orchestration.</p>
      <ol className="office-events">{run.events.map((event, index) => <li key={index}>
        <span>{(event.elapsed_ms / 1000).toFixed(2)}s · {event.agent}</span>
        <strong>{event.kind}{event.tool ? ' · ' + event.tool : ''}</strong>
      </li>)}</ol>
    </div>}
  </section>;
}
