/* Kafka Pipeline (live): topology, topics/partitions, consumer-group lag, message inspector */
WX.views.pipeline = (() => {
  const N = {
    iot: { x: 20, y: 165, w: 150, h: 54, t: 'svc', label: 'IoT Simulator', sub: '140 smart bins', c: '#c447d6' },
    tel: { x: 205, y: 172, w: 150, h: 40, t: 'topic', label: 'bin-telemetry' },
    sp: { x: 390, y: 165, w: 160, h: 54, t: 'svc', label: 'Stream Processor', sub: 'windows · ETA · anomalies', c: '#0ea5e9' },
    ana: { x: 590, y: 70, w: 150, h: 40, t: 'topic', label: 'bin-analytics' },
    alr: { x: 590, y: 172, w: 150, h: 40, t: 'topic', label: 'bin-alerts' },
    agg: { x: 590, y: 262, w: 150, h: 40, t: 'topic', label: 'zone-aggregates' },
    jev: { x: 780, y: 120, w: 170, h: 64, t: 'svc', label: 'JEV Orchestrator', sub: 'Waste · Route · Fleet agents', c: '#3d7bd9' },
    dec: { x: 1000, y: 50, w: 160, h: 40, t: 'topic', label: 'agent-decisions' },
    pln: { x: 1000, y: 150, w: 160, h: 40, t: 'topic', label: 'collection-plans' },
    flt: { x: 1000, y: 262, w: 160, h: 54, t: 'svc', label: 'Fleet Simulator', sub: '8 trucks · GPS', c: '#d6534f' },
    fst: { x: 790, y: 270, w: 150, h: 40, t: 'topic', label: 'fleet-status' },
    col: { x: 390, y: 345, w: 160, h: 40, t: 'topic', label: 'collection-events' },
    ui: { x: 780, y: 360, w: 380, h: 40, t: 'ui', label: 'Dashboard bridge  →  WebSocket  →  this UI', sub: '' },
  };
  const E = [
    ['iot', 'r', 'tel', 'l', 'bin-telemetry'], ['tel', 'r', 'sp', 'l', 'bin-telemetry'],
    ['sp', 'r', 'ana', 'l', 'bin-analytics'], ['sp', 'r', 'alr', 'l', 'bin-alerts'], ['sp', 'r', 'agg', 'l', 'zone-aggregates'],
    ['ana', 'r', 'jev', 'l', 'bin-analytics'], ['alr', 'r', 'jev', 'l', 'bin-alerts'],
    ['jev', 'r', 'dec', 'l', 'agent-decisions'], ['jev', 'r', 'pln', 'l', 'collection-plans'],
    ['pln', 'b', 'flt', 't', 'collection-plans'], ['flt', 'l', 'fst', 'r', 'fleet-status'], ['fst', 't', 'jev', 'b', 'fleet-status'],
    ['flt', 'b', 'col', 'r', 'collection-events'], ['col', 'l', 'iot', 'b', 'collection-events'], ['col', 't', 'sp', 'b', 'collection-events'],
  ];
  let built = false, tailTopic = 'bin-telemetry';

  function port(n, s) {
    const o = N[n];
    return s === 'r' ? [o.x + o.w, o.y + o.h / 2] : s === 'l' ? [o.x, o.y + o.h / 2] : s === 't' ? [o.x + o.w / 2, o.y] : [o.x + o.w / 2, o.y + o.h];
  }
  function pathD(a, as, b, bs) {
    const [x1, y1] = port(a, as), [x2, y2] = port(b, bs);
    const k = 60;
    const c1 = as === 'r' ? [x1 + k, y1] : as === 'l' ? [x1 - k, y1] : as === 't' ? [x1, y1 - k] : [x1, y1 + k];
    const c2 = bs === 'r' ? [x2 + k, y2] : bs === 'l' ? [x2 - k, y2] : bs === 't' ? [x2, y2 - k] : [x2, y2 + k];
    return `M${x1},${y1} C${c1} ${c2} ${x2},${y2}`;
  }

  function build() {
    let s = `<svg viewBox="0 0 1180 410" xmlns="http://www.w3.org/2000/svg">
      <defs><style>
        .edge{fill:none;stroke:rgba(148,163,184,.22);stroke-width:2}
        .flowln{fill:none;stroke:#4caf7d;stroke-linecap:round;stroke-dasharray:2 14;animation:dash 1s linear infinite}
        @keyframes dash{to{stroke-dashoffset:-32}}
        .svc rect{fill:#1c222b;stroke-width:1.5}
        .tp rect{fill:#161b22;stroke:#2e3743;stroke-width:1.2}
        .lbl{fill:#e2e8f0;font:600 13px IBM Plex Sans}.sub{fill:#94a3b8;font:11px IBM Plex Sans}
        .tlbl{fill:#e6e9ee;font:500 12px 'IBM Plex Mono'}.rate{fill:#4caf7d;font:600 10.5px 'IBM Plex Mono'}
      </style></defs>`;
    E.forEach((e, i) => { const d = pathD(e[0], e[1], e[2], e[3]); s += `<path class="edge" d="${d}"/><path class="flowln" id="fl${i}" d="${d}"/>`; });
    Object.entries(N).forEach(([k, n]) => {
      if (n.t === 'svc') s += `<g class="svc"><rect x="${n.x}" y="${n.y}" width="${n.w}" height="${n.h}" rx="12" stroke="${n.c}"/>
        <rect x="${n.x}" y="${n.y}" width="5" height="${n.h}" rx="2" fill="${n.c}" stroke="none"/>
        <text class="lbl" x="${n.x + 16}" y="${n.y + 24}">${n.label}</text><text class="sub" x="${n.x + 16}" y="${n.y + 42}">${n.sub}</text></g>`;
      else if (n.t === 'topic') s += `<g class="tp"><rect x="${n.x}" y="${n.y}" width="${n.w}" height="${n.h}" rx="20"/>
        <text class="tlbl" x="${n.x + n.w / 2}" y="${n.y + 18}" text-anchor="middle">${n.label}</text>
        <text class="rate" id="r-${n.label}" x="${n.x + n.w / 2}" y="${n.y + 32}" text-anchor="middle">0 msg/s</text></g>`;
      else s += `<g><rect x="${n.x}" y="${n.y}" width="${n.w}" height="${n.h}" rx="10" fill="#161b22" stroke="#2e3743" stroke-dasharray="4 4"/>
        <text class="lbl" x="${n.x + n.w / 2}" y="${n.y + 25}" text-anchor="middle" style="font-size:12px">${n.label}</text></g>`;
    });
    s += `<text class="sub" x="20" y="402">consumer groups: wastex-stream-processor · wastex-jev-orchestrator · wastex-fleet-simulator · wastex-iot-gateway · wastex-dashboard-bridge</text></svg>`;
    $('#topology').innerHTML = s;
    $('#tailTabs').innerHTML = Object.keys(WX.static.topics).map(t => `<button data-t="${t}" class="${t === tailTopic ? 'on' : ''}">${t}</button>`).join('');
    $$('#tailTabs button').forEach(b => b.onclick = () => { tailTopic = b.dataset.t; $$('#tailTabs button').forEach(x => x.classList.toggle('on', x === b)); loadTail(); });
    built = true;
  }

  function updateTopology(S) {
    E.forEach((e, i) => {
      const r = S.rates[e[4]] || 0;
      const el = document.getElementById('fl' + i);
      if (!el) return;
      el.style.strokeWidth = r > 0 ? Math.min(2 + Math.log2(1 + r) * 1.1, 10) : 0;
      el.style.animationDuration = (r > 0 ? Math.max(0.25, 2.2 - Math.log10(1 + r)) : 2) + 's';
    });
    Object.keys(WX.static.topics).forEach(t => { const el = document.getElementById('r-' + t); if (el) el.textContent = `${fmt(S.rates[t] || 0, 1)} msg/s`; });
  }

  function topics(S) {
    $('#busDesc').textContent = S.bus.description;
    const k = S.kafka.topics || {};
    $('#topicCards').innerHTML = Object.keys(WX.static.topics).map(t => {
      const info = k[t] || { partitions: [], messages: 0 };
      const max = Math.max(1, ...info.partitions.map(p => p.end));
      return `<div class="tc"><div class="tc-h"><span class="tc-n">${t}</span><span class="tc-r">${fmt(S.rates[t] || 0, 1)}/s</span></div>
        <div class="tc-meta">${info.partitions.length} partitions · ${fmt(info.messages)} messages · log-end offsets</div>
        <div class="parts">${info.partitions.map(p => `<div class="part"><span>P${p.id}</span><div class="bar"><i style="width:${100 * p.end / max}%"></i></div><span>${fmt(p.end)}</span></div>`).join('')}</div></div>`;
    }).join('');
  }

  function groups(S) {
    const g = S.kafka.groups || {};
    const rows = Object.entries(g).map(([name, v]) => {
      const parts = Object.values(v.topics).flat();
      const lag = parts.reduce((a, p) => a + p.lag, 0);
      const committed = parts.reduce((a, p) => a + p.committed, 0);
      const color = lag < 50 ? 'var(--ok)' : lag < 500 ? 'var(--warn)' : 'var(--bad)';
      return `<tr><td class="mono" style="color:#7dd3fc">${name}</td><td>${Object.keys(v.topics).map(t => `<code>${t}</code>`).join(' ')}</td>
        <td class="num">${parts.length}</td><td class="num">${fmt(committed)}</td>
        <td class="num"><span class="lagbar" style="width:${Math.min(60, 4 + Math.log2(1 + lag) * 6)}px;background:${color}"></span>${fmt(lag)}</td></tr>`;
    }).join('');
    $('#groupTable').innerHTML = `<table class="t"><tr><th>Group</th><th>Subscribed topics</th><th class="num">Parts</th><th class="num">Committed</th><th class="num">Lag</th></tr>${rows}</table>
      <p class="muted" style="margin-top:10px">Lag = log-end offset − committed offset. Near-zero lag means every consumer keeps up with the stream in real time.</p>`;
  }

  async function loadTail() {
    try {
      const rows = await (await fetch('/api/topic/' + tailTopic)).json();
      $('#tail').innerHTML = rows.slice().reverse().map(r => `<div><span class="po">p${r.p}@${r.o}</span> <span class="ky">${esc(r.k ?? 'null')}</span> ${esc(r.s)}</div>`).join('') || '<div class="muted">no messages yet</div>';
    } catch (e) { /* server restarting */ }
  }

  return {
    show() { if (!built) build(); },
    update(S) { if (!built) build(); updateTopology(S); topics(S); groups(S); loadTail(); },
  };
})();
