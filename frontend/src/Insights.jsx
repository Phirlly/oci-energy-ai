import React, { useEffect, useRef } from 'react';

export default function Insights({ result, documents }) {
  const heading = useRef(null);
  useEffect(() => { heading.current?.focus(); }, [result]);
  const aggregate = result.aggregate;
  return <section className="insights" aria-labelledby="insights-heading">
    <p className="eyebrow">03 / Understand</p><h2 id="insights-heading" ref={heading} tabIndex={-1}>{result.label}</h2>
    {aggregate && <div className="metrics">
      <div><span>Daily consumption</span><strong data-testid="daily-usage">{aggregate.daily_kwh} kWh/day</strong></div>
      <div><span>Current electricity charges</span><strong>{aggregate.current_total === null ? 'Unavailable' : aggregate.currency + ' ' + aggregate.current_total}</strong></div>
      <div><span>Supplied consumption</span><strong>{aggregate.total_kwh} kWh</strong></div>
      <div><span>Average billed cost / kWh</span><strong>{aggregate.average_cost_per_kwh === null ? 'Unavailable' : aggregate.currency + ' ' + aggregate.average_cost_per_kwh}</strong></div>
    </div>}
    {aggregate && <p>{aggregate.periods} supplied period{aggregate.periods === 1 ? '' : 's'} · {aggregate.days} billed days · {aggregate.gap_days} gap days.
      The average includes billed charges; it is not a tariff rate.</p>}
    {result.warnings.map((warning, i) => <p className="notice" key={i}>{warning}</p>)}
    <h3>Checks by selected bill</h3>
    {result.bills.map((bill, index) => <div className="bill-check" key={index}>
      <strong>{documents.find(doc => doc.id === result.document_ids[index])?.facts.supplier || 'Selected bill ' + (index + 1)}
        {' · '}{documents.find(doc => doc.id === result.document_ids[index])?.facts.period_start || 'Date unconfirmed'}</strong>
      <p>Daily use: {bill.daily_kwh === null ? 'Unavailable' : bill.daily_kwh + ' kWh'} ·
        Charge difference: {bill.charge_difference ?? 'Unavailable (no additive breakdown)'}</p>
      {bill.warnings.map((warning, i) => <p className="muted" key={i}>{warning}</p>)}
    </div>)}
    {result.comparisons.length > 0 && <><h3>Daily usage changes</h3>
      <ul>{result.comparisons.map((item, i) => <li key={i}>{item.earlier_start} → {item.later_start}: {
        item.daily_usage_change_percent === null ? 'Unavailable (previous usage was zero)' :
        item.daily_usage_change_percent + '%'}</li>)}</ul></>}
    <p className="muted">These results describe supplied, approved periods. Weather, occupancy and equipment can affect usage;
      bill totals alone do not establish the cause of a change or battery savings.</p>
  </section>;
}
