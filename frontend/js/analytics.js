/* Stream Analytics: window aggregates, scenario mix, ETA forecast, anomalies, bin table */
WX.views.analytics = (() => {
  let filter = '';

  function kpis(S) {
    const st = S.stream, t = S.truth.scenario_counts;
    const items = [
      ['Records processed', fmt(st.processed), 'stateful operators', '#0ea5e9'],
      ['Latency p50', st.latency_p50_ms + ' ms', 'produce → processed', '#22c55e'],
      ['Latency p95', st.latency_p95_ms + ' ms', 'end-to-end', '#14b8a6'],
      ['Alerts raised', fmt(Object.values(st.alerts).reduce((a, b) => a + b, 0)), 'de-duplicated', '#ef4444'],
      ['Anomaly readings', fmt(t.anomaly), 'fire · spike · tamper · battery', '#a855f7'],
      ['Window size', WX.static.config.zone_window + ' min', `rate window ${WX.static.config.fill_rate_window} readings`, '#f59e0b'],
    ];
    $('#streamKpis').innerHTML = items.map(([l, v, s, c]) => `<div class="kpi" style="--kc:${c}"><div class="k-l">${l}</div><div class="k-v">${v}</div><div class="k-s">${s}</div></div>`).join('');
  }

  function windows(S) {
    const zones = WX.static.zones;
    const hist = S.zone_history;
    const labels = [...new Set(Object.values(hist).flat().map(w => w.window_end))].sort((a, b) => a - b).slice(-30);
    const c = makeChart('chWindows', {
      type: 'line', data: { labels: [], datasets: zones.map((z, i) => ({ label: z.name, data: [], borderColor: PALETTE[i % PALETTE.length], tension: .3, pointRadius: 0, borderWidth: 1.8 })) },
      options: { scales: { y: { min: 0, max: 100, title: { display: true, text: 'avg fill %' } } }, plugins: { legend: { position: 'right', labels: { font: { size: 10 } } } } }
    });
    if (!c) return;
    c.data.labels = labels.map(m => { const t = new Date(Date.parse(S.clock.iso) - (S.clock.sim_min - m) * 60000); return t.toTimeString().slice(0, 5); });
    zones.forEach((z, i) => {
      const map = Object.fromEntries((hist[z.id] || []).map(w => [w.window_end, w.avg_fill]));
      c.data.datasets[i].data = labels.map(l => map[l] ?? null);
    });
    c.update('none');
  }

  function scenario(S) {
    const t = S.truth.scenario_counts;
    const c = makeChart('chScenario', {
      type: 'doughnut', data: { labels: ['Normal', 'Demand', 'Event surge', 'Anomaly'], datasets: [{ data: [0, 0, 0, 0], backgroundColor: ['#334155', '#3b82f6', '#f59e0b', '#a855f7'], borderColor: '#0b1222', borderWidth: 3 }] },
      options: { cutout: '62%', plugins: { legend: { position: 'right' }, tooltip: { callbacks: { label: x => ` ${x.label}: ${fmt(x.raw)} (${(100 * x.raw / Math.max(1, x.dataset.data.reduce((a, b) => a + b, 0))).toFixed(1)}%)` } } } }
    });
    if (c) { c.data.datasets[0].data = [t.normal, t.demand, t.surge, t.anomaly]; c.update('none'); }
  }

  function alertsChart(S) {
    const types = ['PREDICTED_OVERFLOW', 'CRITICAL_FILL', 'OVERFLOW', 'FIRE', 'SENSOR_SPIKE', 'TAMPER', 'LOW_BATTERY', 'TRUCK_BREAKDOWN'];
    const c = makeChart('chAlerts', {
      type: 'bar', data: { labels: types.map(t => t.replace(/_/g, ' ').toLowerCase()), datasets: [{ data: [], backgroundColor: ['#f59e0b', '#ef4444', '#b91c1c', '#f97316', '#a855f7', '#ec4899', '#38bdf8', '#64748b'], borderRadius: 5 }] },
      options: { indexAxis: 'y', plugins: { legend: { display: false } }, scales: { x: { beginAtZero: true, ticks: { precision: 0 } } } }
    });
    if (c) { c.data.datasets[0].data = types.map(t => S.alert_counts[t] || 0); c.update('none'); }
  }

  function eta(S) {
    const rows = S.bins.filter(b => b.eta_min != null && b.fill_level < 100).sort((a, b) => a.eta_min - b.eta_min).slice(0, 10);
    const sched = new Set(S.trucks.flatMap(t => t.remaining_stops));
    $('#etaTable').innerHTML = `<table class="t"><tr><th>Bin</th><th>Zone</th><th>Fill</th><th class="num">Rate %/h</th><th class="num">ETA</th><th>Truck</th></tr>
      ${rows.map(b => `<tr><td class="mono">${b.bin_id}</td><td>${esc(b.zone)}</td><td><span class="fillbar"><i style="width:${b.fill_level}%;background:${fillColor(b.fill_level)}"></i></span>${b.fill_level.toFixed(0)}%</td>
        <td class="num">${b.rate_per_hr}</td><td class="num" style="color:${b.eta_min < 30 ? '#f87171' : b.eta_min < 60 ? '#fbbf24' : '#cbd5e1'}">${Math.round(b.eta_min)} min</td>
        <td>${sched.has(b.bin_id) ? '<span class="status ok">scheduled</span>' : '<span class="muted">—</span>'}</td></tr>`).join('')}</table>`;
  }

  function table(S) {
    const f = filter.toLowerCase();
    const rows = S.bins.filter(b => !f || `${b.bin_id} ${b.zone} ${b.status} ${b.anomalies.join(' ')}`.toLowerCase().includes(f))
      .sort((a, b) => b.fill_level - a.fill_level);
    $('#binTable').innerHTML = `<table class="t"><tr><th>Bin</th><th>Zone</th><th>Type</th><th>Fill</th><th class="num">Weight</th><th class="num">Rate %/h</th><th class="num">ETA</th><th class="num">Temp</th><th class="num">Battery</th><th>Status</th></tr>
      ${rows.map(b => `<tr><td class="mono">${b.bin_id}</td><td>${esc(b.zone)}</td><td class="muted">${b.bin_type}</td>
        <td><span class="fillbar"><i style="width:${Math.min(100, b.fill_level)}%;background:${fillColor(b.fill_level)}"></i></span>${b.fill_level.toFixed(1)}%</td>
        <td class="num">${b.weight_kg}</td><td class="num">${b.rate_per_hr}</td><td class="num">${b.eta_min == null ? '∞' : Math.round(b.eta_min)}</td>
        <td class="num">${b.temperature_c}°</td><td class="num">${b.battery_pct}%</td>
        <td><span class="status ${b.status}">${b.anomalies.length ? b.anomalies[0].toLowerCase() : b.status}</span></td></tr>`).join('')}</table>`;
  }

  function spark(vals) {
    if (vals.length < 2) return '';
    const w = 90, h = 22, mx = Math.max(...vals, 1), mn = Math.min(...vals, 0);
    const pts = vals.map((v, i) => `${(i / (vals.length - 1) * w).toFixed(1)},${(h - (v - mn) / (mx - mn || 1) * h).toFixed(1)}`).join(' ');
    return `<svg width="${w}" height="${h}" style="vertical-align:middle"><polyline points="${pts}" fill="none" stroke="#5eead4" stroke-width="1.6"/></svg>`;
  }

  function hotspots(S) {
    const H = S.hotspots || [];
    $('#hotTable').innerHTML = `<table class="t"><tr><th>#</th><th>Zone</th><th class="num">kg/h</th><th class="num">Trend</th><th>Last hour</th><th class="num">Avg fill</th><th class="num">≥75%</th><th>State</th></tr>
      ${H.map((h, i) => { const cls = h.trend_pct > 5 ? 'up' : h.trend_pct < -5 ? 'down' : 'flat';
        return `<tr><td>${i + 1}</td><td>${esc(h.zone)}</td><td class="num">${h.gen_kg_per_hr}</td>
        <td class="num"><span class="trend ${cls}">${cls === 'up' ? '▲' : cls === 'down' ? '▼' : '•'} ${h.trend_pct > 0 ? '+' : ''}${h.trend_pct}%</span></td>
        <td>${spark(h.spark)}</td><td class="num">${h.avg_fill}%</td><td class="num">${h.bins_over_75}</td><td><span class="hstat ${h.status}">${h.status}</span></td></tr>`; }).join('')}</table>`;
    const top = H.slice(0, 8);
    const c = makeChart('chHot', {
      type: 'bar', data: { labels: [], datasets: [{ label: 'Waste generation (kg/h)', data: [], backgroundColor: [], borderRadius: 5 }] },
      options: { indexAxis: 'y', plugins: { legend: { display: false } }, scales: { x: { beginAtZero: true, title: { display: true, text: 'kg per hour' } } } }
    });
    if (c) {
      c.data.labels = top.map(h => h.zone);
      c.data.datasets[0].data = top.map(h => h.gen_kg_per_hr);
      c.data.datasets[0].backgroundColor = top.map(h => ({ SURGE: '#ef4444', RISING: '#f59e0b', FALLING: '#22c55e' }[h.status] || '#3b82f6'));
      c.update('none');
    }
  }

  let bound = false;
  return {
    show() { if (!bound) { $('#binSearch').addEventListener('input', e => { filter = e.target.value; WX.S && table(WX.S); }); bound = true; } },
    update(S) { kpis(S); hotspots(S); windows(S); scenario(S); alertsChart(S); eta(S); table(S); },
  };
})();
