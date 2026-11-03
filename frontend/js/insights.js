/* Insights & Results: benchmark (fixed schedule vs WASTEX) + EDA from the dataset */
WX.views.insights = (() => {
  let loaded = false;

  const num = v => fmt(v, Number.isInteger(v) ? 0 : 1);

  async function loadBench() {
    let r;
    try { r = await (await fetch('/api/benchmark?hours=24')).json(); }
    catch (e) { $('#resCards').innerHTML = '<div class="muted pad">Benchmark failed to load</div>'; return; }
    const f = r.fixed, f4 = r.fixed4, w = r.wastex, im = r.improvement, i4 = r.improvement_vs_fixed4;
    $('#benchMeta').textContent = `${r.bins} bins · ${r.trucks} trucks · same seed · ${r.hours} simulated hours`;
    const card = (v, l, s) => `<div class="res"><div class="rv">${v}</div><div class="rl">${l}</div><div class="rs">${s}</div></div>`;
    $('#resCards').innerHTML = [
      card(`−${im.overflow_bin_minutes_pct}%`, 'overflow bin-minutes vs BBMP 2×/day', `${fmt(f.overflow_bin_minutes)} → ${fmt(w.overflow_bin_minutes)} bin-minutes`),
      card(`−${im.overflow_events_pct}%`, 'overflow events vs BBMP 2×/day', `${f.overflow_events} → ${w.overflow_events} bins overflowed`),
      card(`−${i4.overflow_bin_minutes_pct}%`, 'overflow vs 4×/day at comparable distance', `${fmt(f4.km)} km vs ${fmt(w.km)} km driven`),
      card(`+${i4.fill_at_collection_gain} pts`, 'fuller bins at pickup vs 4×/day', `${f4.avg_fill_at_collection}% → ${w.avg_fill_at_collection}% · ${i4.collections_pct}% fewer lifts`),
    ].join('');

    const rows = [
      ['Distance driven (km)', 'km'], ['CO₂ (kg)', 'co2_kg'], ['Operating cost (₹)', 'cost_inr'], ['Bin collections (lifts)', 'collections'],
      ['Avg fill at collection (%)', 'avg_fill_at_collection'], ['Overflow bin-minutes', 'overflow_bin_minutes'], ['Overflow events', 'overflow_events'],
      ['Trips', 'trips'], ['Avg stops / trip', 'avg_stops_per_trip'], ['Disposal trips', 'disposal_trips'], ['km per collection', 'km_per_collection']];
    $('#benchTable').innerHTML = `<table class="t"><tr><th>Metric</th><th class="num">Fixed · BBMP 2×/day</th><th class="num">Fixed · 4×/day</th><th class="num">WASTEX (agents)</th></tr>
      ${rows.map(([l, k]) => `<tr><td>${l}</td><td class="num">${num(f[k])}</td><td class="num">${num(f4[k])}</td><td class="num" style="color:var(--accent);font-weight:600">${num(w[k])}</td></tr>`).join('')}</table>
      <p class="muted" style="margin-top:10px">Same synthetic city, identical fill dynamics and random seed for all three strategies. WASTEX reuses the live Waste / Route / Fleet agent code. The fixed schedules sweep every bin at set times regardless of fill (slide 2); WASTEX dispatches only when the agents decide.</p>`;

    const lab = f.series.map(s => { const h = Math.floor(s.hour), m = Math.round((s.hour - h) * 60); return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`; });
    makeChart('chBenchSeries', {
      type: 'line', data: { labels: lab, datasets: [
        { label: 'Fixed 2×/day', data: f.series.map(s => s.overflowing), borderColor: '#c9564f', backgroundColor: 'rgba(201,86,79,.08)', fill: true, tension: .3, pointRadius: 0 },
        { label: 'Fixed 4×/day', data: f4.series.map(s => s.overflowing), borderColor: '#d49a3e', tension: .3, pointRadius: 0 },
        { label: 'WASTEX', data: w.series.map(s => s.overflowing), borderColor: '#4caf7d', backgroundColor: 'rgba(76,175,125,.12)', fill: true, tension: .3, pointRadius: 0, borderWidth: 2.5 }] },
      options: { plugins: { legend: { position: 'bottom' } }, scales: { y: { beginAtZero: true, title: { display: true, text: 'bins overflowing' } } } }
    });
    const keys = [['Overflow bin-min ÷100', s => s.overflow_bin_minutes / 100], ['Overflow events', s => s.overflow_events], ['Collections ÷10', s => s.collections / 10], ['Avg fill at pickup %', s => s.avg_fill_at_collection], ['Distance ÷20 km', s => s.km / 20]];
    makeChart('chBenchBars', {
      type: 'bar', data: { labels: keys.map(k => k[0]), datasets: [
        { label: 'Fixed 2×/day', data: keys.map(k => +k[1](f).toFixed(1)), backgroundColor: '#c9564f', borderRadius: 4 },
        { label: 'Fixed 4×/day', data: keys.map(k => +k[1](f4).toFixed(1)), backgroundColor: '#d49a3e', borderRadius: 4 },
        { label: 'WASTEX', data: keys.map(k => +k[1](w).toFixed(1)), backgroundColor: '#4caf7d', borderRadius: 4 }] },
      options: { plugins: { legend: { position: 'bottom' } } }
    });
  }

  function eda() {
    const st = WX.static;
    const wards = st.zones.slice().sort((a, b) => b.complaints - a.complaints).slice(0, 6);
    const max = wards[0].complaints;
    $('#edaWards').innerHTML = wards.map(z => `<div class="ward"><div class="wn"><span>${z.name} <span class="muted">Ward ${z.ward}</span></span><b>${z.complaints}</b></div><div class="wb"><i style="width:${100 * z.complaints / max}%"></i></div></div>`).join('') +
      `<div class="muted" style="margin-top:6px">What residents report</div>` + st.complaint_themes.map(t => `<div class="theme"><span class="n">${t.rank}</span><div><b>${t.title}</b><div class="muted">${t.detail}</div></div></div>`).join('');
    const plants = st.plants.map(p => ({ n: p.area, c: p.mixed_tpd, i: p.intake_tpd })).concat([{ n: 'MSGP', c: st.msgp.mixed_tpd, i: st.msgp.intake_tpd }]);
    makeChart('chPlants', {
      type: 'bar', data: { labels: plants.map(p => p.n), datasets: [
        { label: 'Mixed capacity (TPD)', data: plants.map(p => p.c), backgroundColor: '#3d6f9e', borderRadius: 4 },
        { label: 'Current intake (TPD)', data: plants.map(p => p.i), backgroundColor: '#c98a3a', borderRadius: 4 }] },
      options: { plugins: { legend: { position: 'bottom' } }, scales: { x: { ticks: { maxRotation: 60, minRotation: 45 } } } }
    });
    $('#edaSchedule').innerHTML = `<table class="t"><tr><th>Days</th><th>Collection window</th></tr>${st.fixed_schedule.map(s => `<tr><td>${s.days}</td><td class="mono">${s.window}</td></tr>`).join('')}</table>
      <p class="muted" style="margin-top:10px">The fixed schedule ignores how fast each bin actually fills. Total plant capacity 2,900 TPD vs 1,150 TPD intake (40% utilised) — MSGP (83%) and Doddabidarakallu (75%) are near capacity while Kannahalli (8%) and KCDC (16%) are idle, which is why the Route Agent weights plant choice by utilisation.</p>`;
  }

  return { show() { if (!loaded) { loaded = true; eda(); loadBench(); } }, update() { } };
})();

/* Architecture page */
WX.views.about = (() => {
  let built = false;
  function build() {
    const box = (x, y, w, h, c, t, s) => `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="12" fill="${c}22" stroke="${c}" stroke-width="1.5"/><text x="${x + w / 2}" y="${y + h / 2 - (s ? 3 : -4)}" text-anchor="middle" fill="#e2e8f0" font="600 13px IBM Plex Sans" style="font:600 13px IBM Plex Sans">${t}</text>${s ? `<text x="${x + w / 2}" y="${y + h / 2 + 14}" text-anchor="middle" style="font:11px IBM Plex Sans;fill:#94a3b8">${s}</text>` : ''}`;
    const arrow = (x1, y1, x2, y2) => `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="#4caf7d" stroke-width="2" marker-end="url(#aa)"/>`;
    $('#archDiagram').innerHTML = `<svg viewBox="0 0 1180 330" xmlns="http://www.w3.org/2000/svg"><defs><marker id="aa" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0L10,5L0,10z" fill="#4caf7d"/></marker></defs>
      <text x="20" y="24" style="font:600 11px IBM Plex Sans;fill:#8b95a3">1 · Data</text>
      <text x="270" y="24" style="font:600 11px IBM Plex Sans;fill:#8b95a3">2 · Ingestion</text>
      <text x="480" y="24" style="font:600 11px IBM Plex Sans;fill:#8b95a3">3 · Stream processing</text>
      <text x="730" y="24" style="font:600 11px IBM Plex Sans;fill:#8b95a3">4 · Multi-agent layer</text>
      <text x="990" y="24" style="font:600 11px IBM Plex Sans;fill:#8b95a3">5 · Action and UI</text>
      ${box(20, 40, 200, 56, '#c447d6', 'Smart-bin IoT simulator', 'fill · weight · temp · battery')}
      ${box(20, 110, 200, 56, '#c447d6', 'Real Bengaluru data', 'wards · DWCC · plants · landfills')}
      ${box(20, 180, 200, 56, '#c447d6', 'Scenario engine', 'demand · surge · anomalies')}
      ${box(270, 80, 170, 120, '#0e7490', 'Apache Kafka', '8 topics · 28 partitions')}
      ${box(480, 50, 200, 56, '#0ea5e9', 'Sliding fill-rate', 'least squares + EWMA')}
      ${box(480, 120, 200, 56, '#0ea5e9', 'Anomaly + ETA', 'spike · tamper · fire')}
      ${box(480, 190, 200, 56, '#0ea5e9', 'Tumbling windows', '5-min zone aggregates')}
      ${box(730, 40, 210, 50, '#3d7bd9', 'JEV Orchestrator', 'event + periodic triggers')}
      ${box(730, 105, 210, 44, '#22a35a', 'Waste Agent — WHAT?')}
      ${box(730, 160, 210, 44, '#d4943a', 'Route Agent — HOW?')}
      ${box(730, 215, 210, 44, '#d6534f', 'Fleet Agent — WHO?')}
      ${box(990, 50, 170, 56, '#1a9a92', 'Collection plans', 'route + truck')}
      ${box(990, 120, 170, 56, '#d6534f', 'Fleet simulator', 'GPS · loads · pickups')}
      ${box(990, 190, 170, 56, '#4caf7d', 'Web dashboard', 'FastAPI · WebSocket')}
      ${arrow(220, 68, 268, 110)}${arrow(220, 138, 268, 140)}${arrow(220, 208, 268, 170)}
      ${arrow(440, 120, 478, 78)}${arrow(440, 140, 478, 148)}${arrow(440, 160, 478, 218)}
      ${arrow(680, 120, 728, 65)}${arrow(940, 65, 988, 78)}${arrow(1075, 106, 1075, 118)}${arrow(1075, 176, 1075, 188)}
      <path d="M990,160 C900,300 400,300 360,202" fill="none" stroke="#4caf7d" stroke-width="2" stroke-dasharray="5 5" marker-end="url(#aa)"/>
      <text x="640" y="300" text-anchor="middle" style="font:11px IBM Plex Sans;fill:#94a3b8">collection-events + fleet-status close the loop (bin emptied → sensor resets → new decisions)</text>
    </svg>`;
    const cards = [
      ['Why Kafka?', 'Thousands of bins emit readings every minute. Kafka decouples producers from consumers, keeps per-bin ordering through key partitioning, buffers bursts (event surges) and lets every component scale as an independent consumer group.'],
      ['Why stream processing?', 'Decisions must use the growth rate, not just the level (EDA: 78% → 84% in 10 min overflows sooner than a slow 92% bin). Stateful windowed operators compute rates, ETAs and anomalies within milliseconds of each reading.'],
      ['Why multiple agents?', 'WHAT, HOW and WHO are different problems with different inputs. Specialised agents keep each decision explainable; JEV coordinates them adaptively — skipping work when nothing is urgent and re-planning when a constraint is hit.'],
      ['Technology stack', 'Python 3.10 · Apache Kafka 3.7 (KRaft, Docker) · kafka-python · FastAPI + WebSocket · Leaflet · Chart.js. An embedded Kafka-compatible broker lets the project run even without Docker.'],
      ['Topics', Object.entries(WX.static.topics).map(([t, p]) => `<code>${t}</code> ×${p}`).join(' · ')],
      ['Reproducibility', 'All synthetic data is generated from a fixed seed (42). Real reference data (wards, DWCCs, plants, landfills, complaints, capacities) is embedded from the BBMP / OpenCity datasets used in the EDA.'],
    ];
    $('#aboutCards').innerHTML = cards.map(([h, p]) => `<div class="card"><h4>${h}</h4><p>${p}</p></div>`).join('');
    built = true;
  }
  return { show() { if (!built) build(); }, update() { } };
})();
