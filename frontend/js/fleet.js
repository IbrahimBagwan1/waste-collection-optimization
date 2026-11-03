/* Fleet & Plants: truck cards, plant utilisation, collection plans */
WX.views.fleet = (() => {
  function kpis(S) {
    const m = S.fleet_metrics, tr = S.trucks;
    const cap = tr.reduce((a, t) => a + t.capacity_kg, 0) || 1;
    const load = tr.reduce((a, t) => a + t.load_kg, 0);
    const items = [
      ['Fleet', `${tr.length} trucks`, `${fmt(cap / 1000, 1)} t total capacity`, '#38bdf8'],
      ['On duty', `${m.active}`, `${tr.filter(t => t.status === 'breakdown').length} breakdown`, '#22c55e'],
      ['Load on board', fmt(load / 1000, 2) + ' t', `${fmt(100 * load / cap, 0)}% of fleet capacity`, '#f59e0b'],
      ['Delivered to plants', fmt(m.kg_delivered / 1000, 2) + ' t', 'unloaded at processing plants', '#f472b6'],
      ['Distance', fmt(m.km, 1) + ' km', `${fmt(m.km / Math.max(1, m.collections), 2)} km / pickup`, '#a855f7'],
      ['Emissions', fmt(m.co2_kg, 0) + ' kg', 'CO₂ @ 0.95 kg/km', '#64748b'],
      ['Saved by route optimisation', fmt(Math.max(0, S.jev.naive_km - S.jev.optimised_km), 1) + ' km',
        S.jev.naive_km ? `${fmt(100 * (S.jev.naive_km - S.jev.optimised_km) / S.jev.naive_km, 1)}% vs urgency-order routes` : 'waiting for plans', '#14b8a6'],
    ];
    $('#fleetKpis').innerHTML = items.map(([l, v, s, c]) => `<div class="kpi" style="--kc:${c}"><div class="k-l">${l}</div><div class="k-v">${v}</div><div class="k-s">${s}</div></div>`).join('');
  }

  function trucks(S) {
    $('#truckGrid').innerHTML = S.trucks.slice().sort((a, b) => a.truck_id.localeCompare(b.truck_id)).map(t => {
      const lp = 100 * t.load_kg / t.capacity_kg, pp = Math.min(100 - lp, 100 * t.planned_kg / t.capacity_kg);
      return `<div class="truck"><div class="th"><div><div class="tid">${t.truck_id}</div><div class="tt">${t.type} · ${fmt(t.capacity_kg / 1000, 1)} t · ${esc(t.depot)}</div></div>
        <span class="tstat ${t.status}">${t.status.replace('_', ' ')}</span></div>
        <div class="loadbar"><i style="width:${lp}%;background:linear-gradient(90deg,#0ea5e9,#14b8a6)"></i><i style="width:${pp}%;background:rgba(245,158,11,.55)"></i></div>
        <div class="tm"><span>load ${fmt(t.load_kg)} kg</span><span>+${fmt(t.planned_kg)} planned</span></div>
        <div class="tm"><span>${t.km_today} km · ${t.collected_bins} bins</span><span>${t.trips} trips</span></div>
        <div class="stops">${t.remaining_stops.length ? '→ ' + t.remaining_stops.slice(0, 6).join(' → ') + (t.remaining_stops.length > 6 ? ' …' : '') : (t.next_stop ? '→ ' + esc(t.next_stop) : 'standing by')}</div></div>`;
    }).join('');
  }

  function plants(S) {
    const kg = S.fleet_metrics.plant_kg || {};
    $('#plantTable').innerHTML = `<table class="t"><tr><th>Plant</th><th class="num">Mixed TPD</th><th class="num">Wet TPD</th><th class="num">Baseline intake</th><th class="num">Today (WASTEX)</th><th>Utilisation</th></tr>
      ${WX.static.plants.map(p => {
        const add = (kg[p.id] || 0) / 1000;
        const u = p.mixed_tpd ? 100 * (p.intake_tpd + add) / p.mixed_tpd : null;
        const col = u == null ? '#475569' : u > 70 ? '#c0782c' : '#1e5a96';
        return `<tr><td>${esc(p.name.replace(' Waste Processing', '').replace(' Plant', '').replace(' Unit', ''))}</td><td class="num">${p.mixed_tpd}</td><td class="num">${p.wet_tpd}</td>
          <td class="num">${p.intake_tpd}</td><td class="num">${add.toFixed(2)} t</td>
          <td>${u == null ? '<span class="muted">closed — skipped by Route Agent</span>' : `<span class="fillbar" style="width:110px"><i style="width:${Math.min(100, u)}%;background:${col}"></i></span>${u.toFixed(1)}%`}</td></tr>`;
      }).join('')}</table>`;
  }

  function planFeed(S) {
    $('#planFeed').innerHTML = S.plans.map(p => `<div class="feed-item"><span class="sev info"></span><div class="m">
      <b>${p.plan_id}</b> · ${p.truck_id} <span class="muted">(${p.mode})</span><div class="muted mono" style="font-size:11px">${p.stops.map(s => s.bin_id).join(' → ')} → ${esc(p.end.name)}</div>
      <div class="muted">${p.manual ? '<b style="color:#5eead4">operator</b> · ' : ''}${p.stops.length} stops · ${Math.round(p.load_kg)} kg · ${p.distance_km} km${p.naive_km > p.distance_km ? ` (saved ${(p.naive_km - p.distance_km).toFixed(1)} km)` : ''} · ~${Math.round(p.duration_min)} min${p.piggyback.length ? ` · ${p.piggyback.length} opportunistic` : ''}</div></div>
      <span class="t">${hhmm(p.ts)}</span></div>`).join('') || '<div class="muted">No plans yet</div>';
  }

  return { show() { }, update(S) { kpis(S); trucks(S); plants(S); planFeed(S); } };
})();
