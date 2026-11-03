/* Route Optimizer: pick a start, select bins (wards / threshold / map clicks), choose a
   destination, compare routing algorithms on real roads, and dispatch the route via Kafka. */
WX.views.route = (() => {
  let map, binLayer, routeLayer, markers = {}, selected = [], last = null, built = false;

  function build() {
    const st = WX.static;
    $('#rtStart').innerHTML = '<optgroup label="Depots">' + st.depots.map(d => `<option value="${d.id}">${d.name}</option>`).join('') +
      '</optgroup><optgroup label="Trucks (current position)">' + st.fleet.map(t => `<option value="${t.id}">${t.id} · ${t.type}</option>`).join('') + '</optgroup>';
    $('#rtPlant').innerHTML = '<option value="auto">Auto – best plant (distance × utilisation)</option>' +
      st.plants.filter(p => p.mixed_tpd > 0).map(p => `<option value="${p.id}">${esc(p.name)}</option>`).join('') +
      '<option value="standby">No unloading – park on standby</option>';
    $('#rtTruck').innerHTML = st.fleet.map(t => `<option value="${t.id}">${t.id} · ${t.type} · ${t.capacity_kg / 1000} t</option>`).join('');
    $('#rtZones').innerHTML = st.zones.map(z => `<label><input type="checkbox" value="${z.id}">${z.name}</label>`).join('');
    $('#rtMin').oninput = e => $('#rtMinL').textContent = e.target.value + '%';
    $('#rtPickZones').onclick = pickZones;
    $('#rtPickHigh').onclick = pickUrgent;
    $('#rtClear').onclick = () => { selected = []; last = null; routeLayer.clearLayers(); refresh(); clearResults(); };
    $('#rtGo').onclick = optimise;
    $('#rtDispatch').onclick = dispatch;
    map = L.map('rtMap', { scrollWheelZoom: false }).setView([12.97, 77.62], 12);
    const esri = 'https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/';
    L.tileLayer(esri + 'World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}', { attribution: 'Tiles &copy; Esri &copy; OpenStreetMap contributors · routing OSRM', maxZoom: 16 }).addTo(map);
    L.tileLayer(esri + 'World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}', { maxZoom: 16, opacity: .8 }).addTo(map);
    routeLayer = L.layerGroup().addTo(map);
    binLayer = L.layerGroup().addTo(map);
    st.depots.forEach(d => L.marker([d.lat, d.lon], { icon: L.divIcon({ className: '', html: `<div class="start-ico">${icon('home', 14, 2)}</div>`, iconSize: [28, 28], iconAnchor: [14, 14] }) }).bindTooltip(d.name).addTo(map));
    st.plants.forEach(p => L.marker([p.lat, p.lon], { icon: L.divIcon({ className: '', html: `<div class="site-ico" style="--c:${p.mixed_tpd ? '#c2417a' : '#475569'}">${icon('factory', 12, 2)}</div>`, iconSize: [22, 22], iconAnchor: [11, 11] }) }).bindTooltip(p.name).addTo(map));
    built = true;
  }

  function toggle(id) {
    const i = selected.indexOf(id);
    if (i >= 0) selected.splice(i, 1); else if (selected.length < 25) selected.push(id); else toast('Max 25 bins per route');
    refresh();
  }

  function pickZones() {
    const zones = $$('#rtZones input:checked').map(i => i.value);
    if (!zones.length) { toast('Tick at least one ward'); return; }
    const min = +$('#rtMin').value;
    const add = WX.S.bins.filter(b => zones.includes(b.zone_id) && b.fill_level >= min).map(b => b.bin_id);
    add.forEach(id => { if (!selected.includes(id) && selected.length < 25) selected.push(id); });
    toast(`${add.length} bins ≥ ${min}% added`);
    refresh();
  }

  function pickUrgent() {
    const sched = new Set([...WX.S.trucks.flatMap(t => t.remaining_stops), ...(WX.S.scheduled_bins || [])]);
    const cands = WX.S.bins.filter(b => !sched.has(b.bin_id))
      .map(b => ({ id: b.bin_id, key: b.fill_level >= 100 ? -1 : (b.eta_min ?? 9999) - b.fill_level }))
      .sort((a, b) => a.key - b.key).slice(0, 10).map(x => x.id);
    selected = cands;
    toast('Top 10 unscheduled bins by overflow ETA selected');
    refresh();
  }

  function refresh() {
    if (!WX.S) return;
    $('#rtCount').textContent = `${selected.length} bins selected`;
    WX.S.bins.forEach(b => {
      let m = markers[b.bin_id];
      const sel = selected.includes(b.bin_id);
      if (!m) {
        m = L.circleMarker([b.lat, b.lon], { radius: 6, weight: 1.5, fillOpacity: .9 }).addTo(binLayer);
        m.on('click', () => toggle(b.bin_id));
        markers[b.bin_id] = m;
      }
      const busy = (WX.S.scheduled_bins || []).includes(b.bin_id);
      m.setStyle({ fillColor: fillColor(b.fill_level, b.status), color: sel ? '#4fa3d1' : busy ? '#8b95a3' : '#0f1217', weight: sel ? 4 : busy ? 2.5 : 1.5,
        radius: sel ? 8 : 5, dashArray: busy && !sel ? '2 2' : null });
      const tip = `${b.bin_id} · ${esc(b.zone)} · ${b.fill_level.toFixed(0)}%${sel ? ' · selected' : busy ? ' · already scheduled' : ' · click to select'}`;
      if (m.getTooltip()) m.setTooltipContent(tip); else m.bindTooltip(tip);
    });
  }

  function clearResults() {
    ['#rtAlgo', '#rtPlants', '#rtSeq', '#rtTrucks', '#rtKpis'].forEach(s => $(s).innerHTML = '');
    $('#rtDispatch').disabled = true;
  }

  async function optimise() {
    if (!selected.length) { toast('Select some bins first'); return; }
    $('#rtGo').textContent = 'Optimising…';
    try {
      const r = await fetch('/api/route/plan', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ start: $('#rtStart').value, bin_ids: selected, plant: $('#rtPlant').value }) });
      const j = await r.json();
      if (!r.ok) { toast(j.error || 'failed'); return; }
      last = j;
      render(j);
    } catch (e) { toast('Route request failed: ' + e); }
    finally { $('#rtGo').textContent = 'Optimise route'; }
  }

  function render(j) {
    const best = j.results.find(r => r.key === j.best), naive = j.results[0];
    const byId = Object.fromEntries(j.stops.map(s => [s.bin_id, s]));
    const pts = order => [[j.start.lat, j.start.lon], ...order.map(id => [byId[id].lat, byId[id].lon]), ...(j.end ? [[j.end.lat, j.end.lon]] : [])];
    routeLayer.clearLayers();
    const naiveLine = j.road_naive ? j.road_naive.geometry : pts(naive.order);
    const bestLine = j.road_best ? j.road_best.geometry : pts(best.order);
    L.polyline(naiveLine, { color: '#e0574f', weight: 3, opacity: .6, dashArray: '6 7' }).addTo(routeLayer);
    L.polyline(bestLine, { color: '#4caf7d', weight: 5, opacity: .95 }).addTo(routeLayer);
    best.order.forEach((id, i) => L.marker([byId[id].lat, byId[id].lon], { icon: L.divIcon({ className: '', html: `<div class="stop-ico">${i + 1}</div>`, iconSize: [22, 22], iconAnchor: [11, 11] }), zIndexOffset: 900 })
      .bindTooltip(`${i + 1}. ${id} · ${esc(byId[id].zone)} · ${byId[id].fill_level.toFixed(0)}%`).addTo(routeLayer));
    L.marker([j.start.lat, j.start.lon], { icon: L.divIcon({ className: '', html: `<div class="start-ico">${icon('play', 13, 2)}</div>`, iconSize: [28, 28], iconAnchor: [14, 14] }), zIndexOffset: 1000 }).bindTooltip('Start: ' + esc(j.start.name)).addTo(routeLayer);
    map.fitBounds(L.polyline(bestLine).getBounds(), { padding: [30, 30] });
    $('#rtRoadTag').textContent = j.road_best ? 'routes drawn on real roads (OSRM)' : 'offline: straight segments, modelled road distance';

    const saved = naive.km - best.km;
    const items = [
      ['Optimised distance', fmt(best.km, 1) + ' km', `${best.name}`, '#14b8a6'],
      ['Saved vs as-selected', fmt(saved, 1) + ' km', `−${best.saving_pct}% · ${fmt(saved * 0.95, 1)} kg CO₂`, '#22c55e'],
      ['Duration', fmt(best.minutes, 0) + ' min', `${j.speed_kmh} km/h traffic · ${j.stops.length} stops`, '#38bdf8'],
      ['Route load', fmt(j.load_kg, 0) + ' kg', j.dispose ? 'ends at ' + esc(j.end.name.split(' ')[0]) : 'standby (no unloading)', '#f59e0b'],
    ];
    if (j.road_best) items.push(['Real-road distance', fmt(j.road_best.km, 1) + ' km', `OSRM driving · ~${fmt(j.road_best.minutes, 0)} min free-flow`, '#a855f7']);
    $('#rtKpis').innerHTML = items.map(([l, v, s, c]) => `<div class="kpi" style="--kc:${c}"><div class="k-l">${l}</div><div class="k-v">${v}</div><div class="k-s">${s}</div></div>`).join('');

    $('#rtAlgo').innerHTML = `<table class="t"><tr><th>Algorithm</th><th class="num">Km</th><th class="num">Min</th><th class="num">Saving</th><th class="num">Gap to best</th><th class="num">Runtime</th></tr>
      ${j.results.map(r => `<tr class="${r.key === j.best ? 'best' : ''}"><td>${r.name}${r.key === j.best ? ' <span class="tag">chosen</span>' : ''}</td><td class="num">${r.km}</td><td class="num">${Math.round(r.minutes)}</td>
        <td class="num">${r.saving_pct}%</td><td class="num">${r.gap_pct}%</td><td class="num">${r.runtime_ms} ms</td></tr>`).join('')}</table>
      <p class="muted" style="margin-top:8px">${j.results.some(r => r.key === 'exact') ? 'Held-Karp is the exact optimum (dynamic programming, O(n²·2ⁿ)); the gap shows how close the fast heuristic gets.' : 'More than 11 stops: the exact optimum is too expensive (2ⁿ), so the 2-opt heuristic is used — this is why real systems use heuristics.'}</p>`;

    $('#rtPlants').innerHTML = j.dispose ? `<table class="t"><tr><th>Plant</th><th class="num">Km from last stop</th><th class="num">Util.</th><th class="num">Cost</th><th>Status</th></tr>
      ${j.plants.map(p => `<tr class="${p.status === 'chosen' ? 'best' : ''}"><td>${esc(p.name.replace(' Waste Processing', '').replace(' Plant', '').replace(' Unit', ''))}</td><td class="num">${p.km}</td>
        <td class="num">${p.util_pct ?? '–'}${p.util_pct != null ? '%' : ''}</td><td class="num">${p.cost ?? '–'}</td><td>${p.status}</td></tr>`).join('')}</table>`
      : '<div class="muted">Standby selected: the truck parks after the last stop and keeps collecting (it unloads once ≥ 75% full).</div>';

    $('#rtSeq').innerHTML = `<table class="t"><tr><th>#</th><th>Bin</th><th>Zone</th><th>Fill</th><th class="num">kg</th><th class="num">ETA</th></tr>
      <tr><td class="muted">start</td><td colspan="5">${esc(j.start.name)}</td></tr>
      ${best.order.map((id, i) => { const s = byId[id]; return `<tr><td>${i + 1}</td><td class="mono">${id}</td><td>${esc(s.zone)}</td>
        <td><span class="fillbar"><i style="width:${Math.min(100, s.fill_level)}%;background:${fillColor(s.fill_level)}"></i></span>${s.fill_level.toFixed(0)}%</td>
        <td class="num">${Math.round(s.weight_kg)}</td><td class="num">${s.eta_min == null ? '∞' : Math.round(s.eta_min) + 'm'}</td></tr>`; }).join('')}
      <tr><td class="muted">end</td><td colspan="5">${j.end ? esc(j.end.name) : 'standby'}</td></tr></table>`;

    $('#rtTrucks').innerHTML = `<table class="t"><tr><th>Truck</th><th>Status</th><th class="num">Free kg</th><th class="num">Dead-head</th><th></th></tr>
      ${j.trucks.map(t => `<tr><td class="mono">${t.truck_id}</td><td>${t.status.replace('_', ' ')}</td><td class="num">${fmt(t.free_kg)}</td><td class="num">${t.deadhead_km} km</td>
        <td><span class="verdict ${t.feasible ? 'feasible' : 'insufficient'}">${t.feasible ? 'can take it' : 'cannot'}</span></td></tr>`).join('')}</table>`;
    const busy = Object.entries(j.scheduled || {});
    if (busy.length) toast(`Note: ${busy.map(([b, t]) => b + '→' + t).join(', ')} already on a truck's route — remove them before dispatching`);
    const firstOk = j.trucks.find(t => t.feasible);
    if (firstOk) $('#rtTruck').value = firstOk.truck_id;
    $('#rtDispatch').disabled = false;
  }

  async function dispatch() {
    if (!last) return;
    const best = last.results.find(r => r.key === last.best);
    const r = await fetch('/api/route/dispatch', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ start: $('#rtStart').value, bin_ids: last.results[0].order, order: best.order, plant: $('#rtPlant').value,
        truck_id: $('#rtTruck').value, algorithm: best.name }) });
    const j = await r.json();
    toast(j.message);
    if (j.ok) { $('#rtDispatch').disabled = true; selected = []; refresh(); }
  }

  return {
    show() {
      if (!built) build();
      setTimeout(() => map.invalidateSize(), 60);
      refresh();
      // ?shot (report screenshots): run the top-10 demo automatically once data has arrived
      if (new URLSearchParams(location.search).has('shot') && !last) {
        const wait = setInterval(() => { if (WX.S) { clearInterval(wait); pickUrgent(); optimise(); } }, 300);
      }
    },
    update(S) { if (built) refresh(); },
  };
})();
