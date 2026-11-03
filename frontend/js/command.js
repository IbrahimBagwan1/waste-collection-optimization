/* Command Center: KPIs, live map, alerts, decisions, zone charts */
WX.views.command = (() => {
  let map, binLayer, truckLayer, routeLayer, heatLayer, binMarkers = {}, truckMarkers = {}, routeLines = {}, heatCircles = {};

  function initMap() {
    if (map || !window.L) return;
    map = L.map('map', { zoomControl: true, attributionControl: true, scrollWheelZoom: false }).setView([12.975, 77.62], 12);
    const esri = 'https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/';
    L.tileLayer(esri + 'World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}', { attribution: 'Tiles &copy; Esri, HERE, Garmin, &copy; OpenStreetMap contributors', maxZoom: 16 }).addTo(map);
    L.tileLayer(esri + 'World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}', { maxZoom: 16, pane: 'overlayPane', opacity: .8 }).addTo(map);
    heatLayer = L.layerGroup().addTo(map);
    routeLayer = L.layerGroup().addTo(map);
    $('#heatToggle').onchange = e => e.target.checked ? heatLayer.addTo(map) : map.removeLayer(heatLayer);
    binLayer = L.layerGroup().addTo(map);
    truckLayer = L.layerGroup().addTo(map);
    const st = WX.static;
    const site = (lat, lon, bg, ch, html) => L.marker([lat, lon], {
      icon: L.divIcon({ className: '', html: `<div class="site-ico" style="--c:${bg}">${icon(ch, 12, 2)}</div>`, iconSize: [22, 22], iconAnchor: [11, 11] })
    }).bindPopup(html).addTo(map);
    st.plants.forEach(p => site(p.lat, p.lon, p.mixed_tpd ? '#c2417a' : '#475569', 'factory',
      `<div class="pop"><h5>${esc(p.name)}</h5><div class="row">Mixed capacity<b>${p.mixed_tpd} TPD</b></div><div class="row">Baseline intake<b>${p.intake_tpd} TPD</b></div><div class="row">Utilisation<b>${p.mixed_tpd ? Math.round(100 * p.intake_tpd / p.mixed_tpd) + '%' : 'closed'}</b></div></div>`));
    st.landfills.forEach(l => site(l.lat, l.lon, '#8a5a2b', 'mountain', `<div class="pop"><h5>${esc(l.name)}</h5>Landfill · ward ${l.ward}</div>`));
    st.dwcc.forEach(d => {
      const depot = st.depots.find(x => x.dwcc === d.id);
      site(d.lat, d.lon, depot ? '#2f6fb0' : '#3b6b74', depot ? 'home' : 'box',
        `<div class="pop"><h5>${esc(depot ? depot.name : d.name + ' DWCC')}</h5>${depot ? 'Truck depot + ' : ''}Dry Waste Collection Centre</div>`);
    });
    setTimeout(() => map.invalidateSize(), 200);
  }

  function binPopup(b) {
    return `<div class="pop"><h5>${b.bin_id} · ${esc(b.zone)}</h5>
      <div class="row">Fill<b>${b.fill_level.toFixed(1)}%</b></div>
      <div class="row">Fill rate<b>${b.rate_per_hr}%/hr</b></div>
      <div class="row">Overflow ETA<b>${b.eta_min == null ? '—' : Math.round(b.eta_min) + ' min'}</b></div>
      <div class="row">Weight<b>${b.weight_kg} kg</b></div>
      <div class="row">Temp / battery<b>${b.temperature_c}°C / ${b.battery_pct}%</b></div>
      <div class="row">Type<b>${b.bin_type}</b></div>
      ${b.anomalies.length ? `<div class="row">Anomaly<b style="color:#d8b4fe">${b.anomalies.join(', ')}</b></div>` : ''}</div>`;
  }

  function updateMap(S) {
    if (!map) return;
    const scheduled = new Set(S.trucks.flatMap(t => t.remaining_stops));
    S.bins.forEach(b => {
      const color = fillColor(b.fill_level, b.status);
      let m = binMarkers[b.bin_id];
      const r = 4 + b.fill_level / 22;
      if (!m) {
        m = L.circleMarker([b.lat, b.lon], { radius: r, weight: 1.5, color: '#0f1217', fillColor: color, fillOpacity: .9 }).bindPopup('');
        m.addTo(binLayer);
        binMarkers[b.bin_id] = m;
      }
      m.setStyle({ fillColor: color, radius: r, color: scheduled.has(b.bin_id) ? '#4fa3d1' : (b.fill_level >= 100 ? '#f5c0bb' : '#0f1217'), weight: scheduled.has(b.bin_id) ? 2.5 : 1.5 });
      m.getPopup().setContent(binPopup(b));
    });
    S.trucks.forEach(t => {
      let m = truckMarkers[t.truck_id];
      const html = `<div class="truck-ico ${t.status}">${icon('truck', 15, 2)}</div>`;
      if (!m) {
        m = L.marker([t.lat, t.lon], { icon: L.divIcon({ className: '', html, iconSize: [28, 28], iconAnchor: [14, 14] }), zIndexOffset: 1000 }).bindPopup('').addTo(truckLayer);
        m.bindTooltip(t.truck_id, { direction: 'top', offset: [0, -12] });
        truckMarkers[t.truck_id] = m;
      }
      m.setLatLng([t.lat, t.lon]);
      m.setIcon(L.divIcon({ className: '', html, iconSize: [28, 28], iconAnchor: [14, 14] }));
      m.getPopup().setContent(`<div class="pop"><h5>${t.truck_id} · ${t.type}</h5>
        <div class="row">Status<b>${t.status.replace('_', ' ')}</b></div>
        <div class="row">Load<b>${fmt(t.load_kg)} / ${fmt(t.capacity_kg)} kg</b></div>
        <div class="row">Planned<b>${fmt(t.planned_kg)} kg</b></div>
        <div class="row">Next stop<b>${t.next_stop || '—'}</b></div>
        <div class="row">Km today<b>${t.km_today}</b></div></div>`);
      let line = routeLines[t.truck_id];
      const pts = t.route_line || [];
      if (pts.length > 1) {
        if (!line) { line = L.polyline(pts, { color: '#4fa3d1', weight: 2.5, opacity: .8, dashArray: '6 6' }).addTo(routeLayer); routeLines[t.truck_id] = line; }
        line.setLatLngs(pts);
        line.setStyle({ color: t.status === 'to_plant' ? '#c2417a' : '#4fa3d1' });
      } else if (line) { routeLayer.removeLayer(line); delete routeLines[t.truck_id]; }
    });
  }

  function heat(S) {
    if (!map) return;
    const max = Math.max(1, ...S.hotspots.map(h => h.gen_kg_per_hr));
    S.hotspots.forEach(h => {
      const t = h.gen_kg_per_hr / max;
      const color = h.status === 'SURGE' ? '#e0574f' : h.status === 'RISING' ? '#e0a43a' : '#4f7fb3';
      let c = heatCircles[h.zone_id];
      if (!c) { c = L.circle([h.lat, h.lon], { radius: 800, stroke: false, interactive: true }).addTo(heatLayer); heatCircles[h.zone_id] = c; }
      c.setRadius(500 + 1400 * t);
      c.setStyle({ fillColor: color, fillOpacity: 0.07 + 0.18 * t });
      c.bindTooltip(`${h.zone}: ${h.gen_kg_per_hr} kg/h (${h.trend_pct > 0 ? '+' : ''}${h.trend_pct}%) · ${h.status}`);
    });
  }

  function kpis(S) {
    const bins = S.bins, n = bins.length || 1;
    const avg = bins.reduce((a, b) => a + b.fill_level, 0) / n;
    const crit = bins.filter(b => b.fill_level >= 90).length;
    const over = bins.filter(b => b.fill_level >= 100).length;
    const active = S.trucks.filter(t => !['idle', 'breakdown'].includes(t.status)).length;
    const rate = Object.values(S.rates).reduce((a, b) => a + b, 0);
    const items = [
      ['Bins monitored', fmt(bins.length), `${S.zones.length || 14} wards · Bengaluru`, '#14b8a6'],
      ['Avg fill', fmt(avg, 1) + '%', `${crit} bins ≥ 90%`, '#f59e0b'],
      ['Overflowing', fmt(over), `${S.truth.overflow_events} overflow events today`, '#ef4444'],
      ['Active trucks', `${active}/${S.trucks.length}`, `${S.jev.scheduled} bins scheduled`, '#38bdf8'],
      ['Collections', fmt(S.fleet_metrics.collections), `avg fill at pickup ${S.avg_fill_at_collection ?? '–'}%`, '#22c55e'],
      ['Distance · CO₂', fmt(S.fleet_metrics.km, 0) + ' km', `${fmt(S.fleet_metrics.co2_kg, 0)} kg CO₂`, '#a855f7'],
      ['Kafka throughput', fmt(rate, 0) + '/s', `${fmt(S.bus.produced)} msgs produced`, '#3b82f6'],
      ['JEV decisions', fmt(S.jev.cycles), `${S.jev.plans} plans · ${S.jev.replans} re-plans`, '#ec4899'],
    ];
    $('#kpis').innerHTML = items.map(([l, v, s, c]) => `<div class="kpi" style="--kc:${c}"><div class="k-l">${l}</div><div class="k-v">${v}</div><div class="k-s">${s}</div></div>`).join('');
  }

  function alerts(S) {
    $('#alertCount').textContent = Object.values(S.alert_counts).reduce((a, b) => a + b, 0);
    $('#alertFeed').innerHTML = S.alerts.slice(0, 25).map(a => `<div class="feed-item"><span class="sev ${a.severity}"></span>
      <div class="m"><b>${a.type.replace(/_/g, ' ')}</b> · ${esc(a.bin_id)} <span class="muted">${esc(a.zone)}</span><div class="muted">${esc(a.message)}</div></div>
      <span class="t">${hhmm(a.ts)}</span></div>`).join('') || '<div class="muted">No alerts yet</div>';
    $('#collFeed').innerHTML = S.collections.slice(0, 20).map(c => `<div class="feed-item"><span class="sev info"></span>
      <div class="m"><b>${c.bin_id}</b> emptied by <b>${c.truck_id}</b><div class="muted">${esc(c.zone)} · ${c.kg} kg · was ${c.fill_at_collection != null ? Math.round(c.fill_at_collection) + '%' : '–'}</div></div>
      <span class="t">${hhmm(c.ts)}</span></div>`).join('') || '<div class="muted">Waiting for the first pickup…</div>';
  }

  function lastDecision(S) {
    const d = S.decisions[0];
    if (!d) { $('#lastDecision').innerHTML = '<div class="muted">JEV warming up…</div>'; return; }
    $('#lastDecision').innerHTML = `<span class="ld-out out-${d.outcome}">${d.outcome.replace('_', ' ')}</span> <span class="muted">${d.decision_id} · ${hhmm(d.ts)} · ${d.duration_ms} ms</span>
      <div class="ld-steps">${d.steps.slice(1, 6).map(s => `<div><b>${esc(s.agent)}</b> · ${esc(s.text).slice(0, 140)}</div>`).join('')}</div>`;
  }

  function charts(S) {
    const zones = WX.static.zones;
    const byZone = {};
    S.bins.forEach(b => (byZone[b.zone_id] ||= []).push(b.fill_level));
    const avg = zones.map(z => { const a = byZone[z.id] || []; return a.length ? +(a.reduce((x, y) => x + y, 0) / a.length).toFixed(1) : 0; });
    const mx = zones.map(z => Math.max(0, ...(byZone[z.id] || [0])).toFixed(1));
    const c = makeChart('chZones', {
      type: 'bar', data: { labels: zones.map(z => z.name), datasets: [
        { label: 'Average fill %', data: avg, backgroundColor: '#3d6f9e', borderRadius: 3 },
        { label: 'Max fill %', data: mx, backgroundColor: '#c98a3a', borderRadius: 3 }] },
      options: { scales: { y: { max: 100, beginAtZero: true }, x: { ticks: { maxRotation: 60, minRotation: 45 } } }, plugins: { legend: { position: 'bottom' } } }
    });
    if (c) { c.data.datasets[0].data = avg; c.data.datasets[1].data = mx; c.update('none'); }
    const ks = S.kpi_series;
    const t = makeChart('chTrend', {
      type: 'line', data: { labels: [], datasets: [
        { label: 'Avg fill %', data: [], borderColor: '#4caf7d', backgroundColor: 'rgba(76,175,125,.10)', fill: true, tension: .35, pointRadius: 0, yAxisID: 'y' },
        { label: 'Bins ≥ 90%', data: [], borderColor: '#e0574f', tension: .35, pointRadius: 0, yAxisID: 'y1' },
        { label: 'Active trucks', data: [], borderColor: '#4fa3d1', borderDash: [4, 4], tension: .35, pointRadius: 0, yAxisID: 'y1' }] },
      options: { scales: { y: { min: 0, max: 100, position: 'left' }, y1: { min: 0, position: 'right', grid: { display: false } } }, plugins: { legend: { position: 'bottom' } } }
    });
    if (t) {
      t.data.labels = ks.map(k => k.t);
      t.data.datasets[0].data = ks.map(k => k.avg_fill);
      t.data.datasets[1].data = ks.map(k => k.over_90);
      t.data.datasets[2].data = ks.map(k => k.active_trucks);
      t.update('none');
    }
  }

  return {
    init() { initMap(); },
    show() { initMap(); setTimeout(() => map && map.invalidateSize(), 50); },
    update(S) { kpis(S); updateMap(S); heat(S); alerts(S); lastDecision(S); charts(S); },
  };
})();
