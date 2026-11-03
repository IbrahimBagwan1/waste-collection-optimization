/* JEV Agents: decision log, animated adaptive workflow (slide 13) and reasoning trace */
WX.views.agents = (() => {
  let selected = null, built = false, lastRendered = null;
  const NODES = {
    event: { x: 10, y: 150, w: 140, h: 52, c: '#c447d6', label: 'Streaming Event', ico: '((•))' },
    jev: { x: 200, y: 150, w: 150, h: 52, c: '#3d7bd9', label: 'JEV Orchestrator', ico: 'cpu' },
    waste: { x: 420, y: 40, w: 150, h: 52, c: '#22a35a', label: 'Waste Agent', ico: 'trash' },
    route: { x: 420, y: 150, w: 150, h: 52, c: '#d4943a', label: 'Route Agent', ico: 'route' },
    fleet: { x: 420, y: 260, w: 150, h: 52, c: '#d6534f', label: 'Fleet Agent', ico: 'truck' },
    priority: { x: 650, y: 40, w: 120, h: 56, c: '#eab308', label: 'Priority bins?', d: true },
    feasible: { x: 650, y: 258, w: 120, h: 56, c: '#eab308', label: 'Feasible?', d: true },
    plan: { x: 850, y: 40, w: 150, h: 52, c: '#1a9a92', label: 'Collection Plan', ico: 'check' },
    noaction: { x: 850, y: 150, w: 150, h: 52, c: '#64748b', label: 'No Action Needed', ico: '–' },
  };
  const EDGES = {
    'event-jev': ['event', 'r', 'jev', 'l', ''],
    'jev-waste': ['jev', 'r', 'waste', 'l', 'what needs attention?'],
    'waste-priority': ['waste', 'r', 'priority', 'l', ''],
    'priority-route': ['priority', 'b', 'route', 'r', 'YES'],
    'priority-noaction': ['priority', 'r', 'noaction', 't', 'NO'],
    'route-fleet': ['route', 'b', 'fleet', 't', 'how should we collect?'],
    'fleet-feasible': ['fleet', 'r', 'feasible', 'l', 'which truck?'],
    'feasible-plan': ['feasible', 'r', 'plan', 'r', 'YES'],
    'feasible-jev': ['feasible', 'b', 'jev', 'b', 'NO · re-plan / retry'],
  };

  function port(n, s) {
    const o = NODES[n];
    return s === 'r' ? [o.x + o.w, o.y + o.h / 2] : s === 'l' ? [o.x, o.y + o.h / 2] : s === 't' ? [o.x + o.w / 2, o.y] : [o.x + o.w / 2, o.y + o.h];
  }
  function d(e) {
    const [a, as, b, bs] = e;
    const [x1, y1] = port(a, as), [x2, y2] = port(b, bs);
    if (a === 'feasible' && b === 'jev') return `M${x1},${y1} L${x1},${y1 + 50} L${x2},${y1 + 50} L${x2},${y2}`;
    if (a === 'feasible' && b === 'plan') return `M${x1},${y1} L1035,${y1} L1035,${y2} L${x2 + 2},${y2}`;
    if (a === 'priority' && b === 'noaction') return `M${x1},${y1} L${x2},${y1} L${x2},${y2}`;
    if (a === 'priority' && b === 'route') return `M${x1},${y1} L${x1},${y2} L${x2},${y2}`;
    const k = 50;
    const c1 = as === 'r' ? [x1 + k, y1] : as === 'b' ? [x1, y1 + k] : [x1, y1 - k];
    const c2 = bs === 'l' ? [x2 - k, y2] : bs === 't' ? [x2, y2 - k] : [x2, y2 + k];
    return `M${x1},${y1} C${c1} ${c2} ${x2},${y2}`;
  }

  function build() {
    let s = `<svg viewBox="0 0 1075 380" xmlns="http://www.w3.org/2000/svg"><defs>
      <marker id="ar" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#64748b"/></marker>
      <marker id="arOn" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="#4caf7d"/></marker>
      <style>.fe{fill:none;stroke:#334155;stroke-width:2}.fe.on{stroke:#4caf7d;stroke-width:3;stroke-dasharray:7 6;animation:fd .8s linear infinite}
      @keyframes fd{to{stroke-dashoffset:-26}}.fl{fill:#94a3b8;font:11px IBM Plex Sans}.nl{fill:#fff;font:600 13px IBM Plex Sans}
      .nd{opacity:.35}.nd.on{opacity:1}</style></defs>`;
    Object.entries(EDGES).forEach(([id, e]) => {
      s += `<path id="fe-${id}" class="fe" d="${d(e)}" marker-end="url(#ar)"/>`;
      if (e[4]) {
        const [x1, y1] = port(e[0], e[1]), [x2, y2] = port(e[2], e[3]);
        let lx = (x1 + x2) / 2, ly = (y1 + y2) / 2 - 6;
        if (id === 'feasible-jev') { lx = (x1 + x2) / 2; ly = y1 + 44; }
        if (id === 'priority-route') { lx = x1 + 8; ly = (y1 + y2) / 2; }
        if (id === 'route-fleet') { lx = x1 + 8; ly = (y1 + y2) / 2 + 4; }
        if (id === 'feasible-plan') { lx = 1041; ly = (y1 + y2) / 2; }
        if (id === 'priority-noaction') { lx = x2 + 8; ly = y1 + 40; }
        s += `<text class="fl" x="${lx}" y="${ly}" text-anchor="${['priority-route', 'route-fleet', 'feasible-plan', 'priority-noaction'].includes(id) ? 'start' : 'middle'}">${e[4]}</text>`;
      }
    });
    Object.entries(NODES).forEach(([k, n]) => {
      if (n.d) {
        const cx = n.x + n.w / 2, cy = n.y + n.h / 2;
        s += `<g id="nd-${k}" class="nd" style="--g:${n.c}"><polygon class="glow" points="${cx},${n.y} ${n.x + n.w},${cy} ${cx},${n.y + n.h} ${n.x},${cy}" fill="#2a2614" stroke="${n.c}" stroke-width="2"/>
          <text x="${cx}" y="${cy + 4}" text-anchor="middle" style="fill:#fde68a;font:600 12px IBM Plex Sans">${n.label}</text></g>`;
      } else {
        s += `<g id="nd-${k}" class="nd" style="--g:${n.c}"><rect class="glow" x="${n.x}" y="${n.y}" width="${n.w}" height="${n.h}" rx="14" fill="${n.c}"/>
          <text class="nl" x="${n.x + n.w / 2}" y="${n.y + n.h / 2 + 5}" text-anchor="middle">${n.label}</text></g>`;
      }
    });
    s += `<g id="nd-badge"></g></svg>`;
    $('#flow').innerHTML = s;
    built = true;
  }

  function highlight(dec) {
    const nodes = new Set(['event', 'jev']);
    const edges = new Set(['event-jev']);
    const kinds = dec.steps.map(s => s.node);
    if (kinds.includes('waste')) { nodes.add('waste'); nodes.add('priority'); edges.add('jev-waste'); edges.add('waste-priority'); }
    if (kinds.includes('noaction')) { nodes.add('noaction'); edges.add('priority-noaction'); }
    if (kinds.includes('route')) { nodes.add('route'); edges.add('priority-route'); }
    if (kinds.includes('fleet')) { nodes.add('fleet'); nodes.add('feasible'); edges.add('route-fleet'); edges.add('fleet-feasible'); }
    if (kinds.includes('replan') || kinds.includes('constraint') || dec.steps.some(s => s.title.includes('Not feasible'))) edges.add('feasible-jev');
    if (kinds.includes('plan')) { nodes.add('plan'); edges.add('feasible-plan'); }
    Object.keys(NODES).forEach(k => $('#nd-' + k)?.classList.toggle('on', nodes.has(k)));
    Object.keys(EDGES).forEach(k => {
      const el = $('#fe-' + k);
      if (!el) return;
      el.classList.toggle('on', edges.has(k));
      el.setAttribute('marker-end', edges.has(k) ? 'url(#arOn)' : 'url(#ar)');
    });
    $('#flowLabel').textContent = `${dec.decision_id} · ${dec.trigger.label}`;
  }

  const AG = { 'JEV': ['#3d7bd9', 'cpu'], 'Waste Agent': ['#22a35a', 'trash'], 'Route Agent': ['#d4943a', 'route'], 'Fleet Agent': ['#d6534f', 'truck'] };

  function stepData(s) {
    const dt = s.data;
    if (!dt) return '';
    if (dt.top) {
      return `<table class="mini"><tr><th>Bin</th><th>Zone</th><th>Fill</th><th>Rate/h</th><th>ETA</th><th>Score components</th><th>Score</th><th></th></tr>
        ${dt.top.map(a => `<tr><td>${a.bin_id}</td><td style="font-family:var(--sans)">${esc(a.zone)}</td><td>${a.fill_level.toFixed(0)}%</td><td>${(a.rate_per_min * 60).toFixed(1)}</td>
          <td>${a.eta_min == null ? '∞' : Math.round(a.eta_min) + 'm'}</td>
          <td><span class="comp" title="fill · urgency · rate · history">
            <i style="width:${a.components.fill * 35}%;background:#22c55e"></i><i style="width:${a.components.urgency * 35}%;background:#ef4444"></i>
            <i style="width:${a.components.rate * 15}%;background:#f59e0b"></i><i style="width:${a.components.history * 15}%;background:#a855f7"></i></span></td>
          <td>${a.score.toFixed(2)}</td><td><span class="prio ${a.priority}">${a.priority}</span></td></tr>`).join('')}</table>`;
    }
    if (dt.routes) {
      return `<table class="mini"><tr><th>Route</th><th>Stops</th><th>Load</th><th>Km</th><th>Min</th><th>Piggyback</th></tr>
        ${dt.routes.map(r => `<tr><td style="font-family:var(--sans)">${esc(r.label)}</td><td>${r.stops.length}</td><td>${Math.round(r.load_kg)} kg</td><td>${r.distance_km}</td><td>${Math.round(r.duration_min)}</td><td>${r.piggyback.length}</td></tr>`).join('')}</table>`;
    }
    if (dt.candidates) {
      return `<table class="mini"><tr><th>Truck</th><th>Type</th><th>Status</th><th>Free</th><th>Dead-head</th><th>Mode</th><th>Score</th><th>Verdict</th></tr>
        ${dt.candidates.map(c => `<tr><td>${c.truck_id}</td><td style="font-family:var(--sans)">${c.type}</td><td>${c.status}</td><td>${c.remaining_pct}% (${fmt(c.remaining_kg)}kg)</td>
          <td>${c.deadhead_km} km</td><td>${c.mode || '–'}</td><td>${c.score ?? '–'}</td><td><span class="verdict ${c.verdict}">${c.verdict}</span></td></tr>`).join('')}</table>`;
    }
    return '';
  }

  function renderTrace(dec) {
    $('#traceMeta').textContent = `${dec.ts.replace('T', ' ')} · decided in ${dec.duration_ms} ms`;
    $('#trace').innerHTML = dec.steps.map((s, i) => {
      const [c, ico] = AG[s.agent] || ['#64748b', 'info'];
      const color = s.node === 'constraint' || s.node === 'replan' ? '#eab308' : s.node === 'plan' ? '#1a9a92' : s.node === 'noaction' ? '#64748b' : c;
      return `<div class="step"><div class="si" style="background:${color}">${icon(s.node === 'constraint' || s.node === 'replan' ? 'flag' : s.node === 'plan' ? 'check' : s.node === 'noaction' ? 'minus' : ico, 16, 2)}</div>
        <div class="sb"><div class="sa">${i + 1} · ${esc(s.agent)}</div><div class="st">${esc(s.title)}</div><div class="sx">${esc(s.text)}</div>${stepData(s)}</div></div>`;
    }).join('');
  }

  function renderList(S) {
    $('#decList').innerHTML = `<div class="dec ${selected ? '' : 'sel'}" data-id=""><div class="d1"><b>Follow live</b><span class="muted">auto-select newest</span></div></div>` +
      S.decisions.map(d => `<div class="dec ${selected === d.decision_id ? 'sel' : ''}" data-id="${d.decision_id}">
        <div class="d1"><b>${d.decision_id}</b><span class="ld-out out-${d.outcome}" style="margin:0">${d.outcome.replace('_', ' ')}</span></div>
        <div class="d2">${esc(d.trigger.label)}</div><div class="d3">${hhmm(d.ts)} · ${d.plans.length} plan(s) · ${d.duration_ms} ms</div></div>`).join('');
    $$('#decList .dec').forEach(el => el.onclick = () => { selected = el.dataset.id || null; lastRendered = null; renderList(WX.S); render(WX.S); });
  }

  function render(S) {
    if (!built) build();
    // ?shot (report screenshots): prefer the newest decision that produced a plan
    const shot = new URLSearchParams(location.search).has('shot');
    const dec = (selected && WX.decisionCache[selected]) || (shot && S.decisions.find(d => d.outcome === 'PLAN')) || S.decisions[0];
    if (!dec) { $('#trace').innerHTML = '<div class="muted">Waiting for the first JEV decision…</div>'; return; }
    if (lastRendered === dec.decision_id) return;
    lastRendered = dec.decision_id;
    highlight(dec);
    renderTrace(dec);
  }

  WX.decisionCache = {};
  return {
    show() { if (!built) build(); lastRendered = null; },
    update(S) {
      S.decisions.forEach(d => WX.decisionCache[d.decision_id] = d);
      renderList(S); render(S);
    },
  };
})();
