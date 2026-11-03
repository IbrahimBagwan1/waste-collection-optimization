/* Boot: static data, navigation, WebSocket stream, scenario controls */
(() => {
  const TITLES = {
    command: ['Command Center', 'Real-time smart-bin telemetry → Kafka → stream analytics → JEV multi-agent decisions'],
    pipeline: ['Kafka Pipeline', 'Live topics, partitions, offsets and consumer-group lag of the running system'],
    lab: ['Kafka Lab', 'Interactive simulation of Kafka internals: partitioning, consumer groups, replication and failure'],
    agents: ['JEV Multi-Agent Decision Layer', 'Specialised agents collaborate to turn processed telemetry into collection actions'],
    route: ['Route Optimizer', 'Select places, compare routing algorithms on real Bengaluru roads, and dispatch the route through Kafka'],
    analytics: ['Stream Analytics', 'Windowed aggregation, fill-rate forecasting and anomaly detection on the telemetry stream'],
    fleet: ['Fleet & Processing Plants', 'Assigning the right vehicle to every collection route'],
    insights: ['Insights & Results', 'EDA on Bengaluru data and evaluation against the fixed collection schedule'],
    about: ['Architecture', 'How WASTEX is built end to end'],
  };
  let current = 'command';

  function go(view) {
    if (!WX.views[view]) return;
    WX.views[current]?.hide?.();
    current = view;
    $$('.nav a').forEach(a => a.classList.toggle('active', a.dataset.view === view));
    $$('.view').forEach(v => v.classList.toggle('active', v.id === 'view-' + view));
    $('#viewTitle').textContent = TITLES[view][0];
    $('#viewSub').textContent = TITLES[view][1];
    WX.views[view].show?.();
    if (WX.S) WX.views[view].update(WX.S);
    history.replaceState(null, '', '#' + view);
  }

  function header(S) {
    $('#clockTime').textContent = S.clock.time;
    $('#clockDay').textContent = `${S.clock.day} · ${S.clock.speed}×`;
    const lt = $('#liveTag');
    lt.textContent = S.clock.paused ? 'Paused' : 'Live';
    lt.classList.toggle('paused', S.clock.paused);
    $('#btnPause').innerHTML = icon(S.clock.paused ? 'play' : 'pause', 15);
    const sp = $('#speed');
    if (document.activeElement !== sp && +sp.value !== S.clock.speed) { sp.value = S.clock.speed; $('#speedLbl').textContent = S.clock.speed + '×'; }
    const b = $('#busBadge');
    b.className = 'bus ' + S.bus.kind;
    $('#busText').textContent = S.bus.kind === 'kafka' ? S.bus.description : 'Embedded Kafka-compatible broker';
    const on = S.truth.demand_mode;
    const pill = $('#demandPill');
    pill.textContent = on ? 'On' : 'Off';
    pill.className = 'pill ' + (on ? 'on' : 'off');
  }

  function connect() {
    const ws = new WebSocket((location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + '/ws');
    ws.onmessage = e => {
      const S = JSON.parse(e.data);
      WX.S = S;
      header(S);
      try { WX.views[current].update(S); } catch (err) { console.error(err); }
    };
    ws.onclose = () => { $('#busText').textContent = 'reconnecting…'; $('#busBadge').className = 'bus'; setTimeout(connect, 1500); };
  }

  function controls() {
    $('#btnPause').onclick = () => control({ action: WX.S?.clock.paused ? 'resume' : 'pause' });
    $('#speed').oninput = e => $('#speedLbl').textContent = e.target.value + '×';
    $('#speed').onchange = e => control({ action: 'speed', value: +e.target.value });
    $('#btnDemand').onclick = () => control({ action: 'demand', value: WX.S?.truth.demand_mode ? 0 : 1 });
    $('#surgeZone').innerHTML = WX.static.zones.map(z => `<option value="${z.id}">${z.name}</option>`).join('');
    $('#btnSurge').onclick = () => control({ action: 'surge', zone_id: $('#surgeZone').value, value: 60 });
    $('#btnAnomaly').onclick = () => control({ action: 'anomaly', kind: $('#anomalyKind').value });
    $('#btnBreakdown').onclick = () => control({ action: 'breakdown' });
    $('#btnSlide13').onclick = async () => { await control({ action: 'slide13' }); go('agents'); };
    $('#btnPlan').onclick = () => control({ action: 'plan_now' });
    $$('.nav a').forEach(a => a.onclick = () => go(a.dataset.view));
    $$('[data-goto]').forEach(a => a.onclick = () => go(a.dataset.goto));
  }

  async function boot() {
    for (let i = 0; i < 60; i++) {
      try { WX.static = await (await fetch('/api/static')).json(); break; }
      catch (e) { await new Promise(r => setTimeout(r, 1000)); }
    }
    applyIcons();
    controls();
    WX.views.command.init();
    const start = location.hash.slice(1);
    go(WX.views[start] ? start : 'command');
    window.addEventListener('hashchange', () => { const v = location.hash.slice(1); if (v !== current && WX.views[v]) go(v); });
    connect();
  }
  boot();
})();
