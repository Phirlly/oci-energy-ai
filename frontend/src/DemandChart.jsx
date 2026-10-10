import React, { useId } from 'react';

export default function DemandChart({ rows, scenario }) {
  const id = useId();
  const maximum = Math.max(1, ...rows.map(row => row.load_kw), ...rows.map(row => row.grid_kw || 0));
  const points = key => rows.map((row, index) => `${48 + index * 640 / (rows.length - 1)},${210 - row[key] * 170 / maximum}`).join(' ');
  return <div className="demand-chart">
    <svg viewBox="0 0 720 250" role="img" aria-labelledby={id}>
      <title id={id}>Peak day demand: original load{scenario ? ' and battery grid demand' : ''}, kW</title>
      <desc>15-minute average demand in the unzoned source clock. Exact values are available in the table below.</desc>
      {[0, .5, 1].map(ratio => <g key={ratio}><line x1="48" x2="690" y1={210 - ratio * 170} y2={210 - ratio * 170} className="chart-grid" />
        <text x="3" y={214 - ratio * 170}>{(maximum * ratio).toFixed(0)}</text></g>)}
      <polyline points={points('load_kw')} className="chart-load" />
      {scenario && <polyline points={points('grid_kw')} className="chart-battery" />}
      <text x="48" y="238">00:00</text><text x="350" y="238">12:00</text><text x="655" y="238">23:45</text>
      <text x="3" y="20">kW</text>
    </svg>
    <p className="muted">Green: original load{scenario && ' · Orange dashed: grid with battery'}. Source clock, 15-minute averages.</p>
    <details><summary>View demand values</summary><div className="table-scroll"><table>
      <thead><tr><th>Interval start</th><th>Load (kW)</th>{scenario && <><th>Grid (kW)</th><th>Stored energy (kWh)</th></>}</tr></thead>
      <tbody>{rows.map(row => <tr key={row.start}><td>{row.start.slice(11)}</td><td>{row.load_kw.toFixed(3)}</td>
        {scenario && <><td>{row.grid_kw.toFixed(3)}</td><td>{row.soc_kwh.toFixed(3)}</td></>}</tr>)}</tbody>
    </table></div></details>
  </div>;
}
