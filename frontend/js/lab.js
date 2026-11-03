/* Kafka Lab: an interactive, visual simulation of Kafka internals.
   Producers -> partitioned, replicated topic on 3 brokers -> consumer group.
   Demonstrates murmur2 key partitioning, ordering, rebalancing (range assignor),
   consumer lag, leader election from the ISR and acks=0/1/all semantics. */
WX.views.lab = (() => {
  const BROKERS = 3, MIN_ISR = 2;
  const KEYS = Array.from({ length: 24 }, (_, i) => `BIN-${String(1 + (i % 14)).padStart(2, '0')}${String(1 + ((i * 7) % 10)).padStart(2, '0')}`);
  const KEY_COLORS = KEYS.map((_, i) => `hsl(${(i * 137.5) % 360} 70% 58%)`);
  const CONS_COLORS = ['#38bdf8', '#f472b6', '#facc15', '#4ade80', '#c084fc', '#fb923c'];
  let cv, ctx, W = 1000, H = 600, running = false, last = 0;
  let st;

  // ---------- Kafka's murmur2 (same as backend/bus.py) ----------
  function murmur2(str) {
    const data = new TextEncoder().encode(str);
    const m = 0x5bd1e995, r = 24, len = data.length;
    let h = (0x9747b28c ^ len) >>> 0;
    const mul = (a, b) => (Math.imul(a, b) >>> 0);
    let i = 0;
    for (; i + 4 <= len; i += 4) {
      let k = (data[i] | (data[i + 1] << 8) | (data[i + 2] << 16) | (data[i + 3] << 24)) >>> 0;
      k = mul(k, m); k = (k ^ (k >>> r)) >>> 0; k = mul(k, m);
      h = mul(h, m); h = (h ^ k) >>> 0;
    }
    const extra = len % 4, base = len & ~3;
    if (extra >= 3) h = (h ^ (data[base + 2] << 16)) >>> 0;
    if (extra >= 2) h = (h ^ (data[base + 1] << 8)) >>> 0;
    if (extra >= 1) { h = (h ^ data[base]) >>> 0; h = mul(h, m); }
    h = (h ^ (h >>> 13)) >>> 0; h = mul(h, m); h = (h ^ (h >>> 15)) >>> 0;
    return h;
  }

  function reset() {
    st = {
      partitions: [], consumers: [], flights: [], retry: [], produceAcc: 0, rr: 0, prodRR: 0,
      brokers: Array.from({ length: BROKERS }, (_, i) => ({ id: i + 1, alive: true })),
      produced: 0, consumed: 0, lost: 0, rebalances: 0, elections: 0, errors: 0, rebalancingUntil: 0,
      rateIn: 0, rateOut: 0, winIn: 0, winOut: 0, winT: 0,
    };
    setPartitions(+$('#lPart').value, true);
    setConsumers(+$('#lCons').value, true);
    $('#labLog').innerHTML = '';
    log('Topic <b>bin-telemetry</b> created · RF=3 · min.insync.replicas=2');
  }

  function newPartition(id) {
    const replicas = [0, 1, 2].map(j => (id + j) % BROKERS + 1);
    return { id, log: [], committed: 0, replicas, leader: replicas[0], isr: [...replicas], electingUntil: 0 };
  }

  function setPartitions(n, silent) {
    const cur = st.partitions.length;
    if (n > cur) {
      for (let i = cur; i < n; i++) st.partitions.push(newPartition(i));
      if (!silent) log(`Added partitions → ${n}. <span style="color:#fbbf24">Key→partition mapping changes for existing keys!</span>`);
    } else if (n < cur) {
      st.partitions = [];
      for (let i = 0; i < n; i++) st.partitions.push(newPartition(i));
      st.flights = [];
      if (!silent) log(`Kafka cannot shrink partitions → topic recreated with ${n} partitions`);
    }
    st.partitions.forEach(p => electIfNeeded(p, true));
    if (!silent) rebalance('partition count changed');
  }

  function setConsumers(n, silent) {
    while (st.consumers.length < n) st.consumers.push({ id: st.consumers.length + 1, parts: [], acc: 0, done: 0 });
    while (st.consumers.length > n) st.consumers.pop();
    rebalance(silent ? null : (n > 0 ? `group membership changed (${n} consumers)` : ''));
  }

  function rebalance(reason) {
    // range assignor
    const P = st.partitions.length, C = st.consumers.length;
    st.consumers.forEach(c => c.parts = []);
    const per = Math.floor(P / C), extra = P % C;
    let p = 0;
    st.consumers.forEach((c, i) => { const cnt = per + (i < extra ? 1 : 0); for (let k = 0; k < cnt; k++) c.parts.push(p++); });
    if (reason) {
      st.rebalances++;
      st.rebalancingUntil = performance.now() + 700;
      log(`Rebalance (${reason}) → ` + st.consumers.map(c => `C${c.id}:[${c.parts.map(x => 'P' + x).join(',') || 'idle'}]`).join(' '));
    }
  }

  function electIfNeeded(p, instant) {
    const leaderAlive = st.brokers[p.leader - 1].alive;
    p.isr = p.replicas.filter(b => st.brokers[b - 1].alive);
    if (!leaderAlive && p.isr.length) {
      const old = p.leader;
      p.leader = p.isr[0];
      p.electingUntil = instant ? 0 : performance.now() + 800;
      if (!instant) { st.elections++; log(`P${p.id}: leader B${old} lost → controller elects <b>B${p.leader}</b> from ISR {${p.isr.map(b => 'B' + b).join(',')}}`); }
    } else if (!p.isr.length) {
      p.leader = null;
    }
  }

  function killBroker() {
    const alive = st.brokers.filter(b => b.alive);
    if (alive.length <= 1) { log('Refusing to kill the last broker'); return; }
    // prefer the broker that leads most partitions -> visible election
    const counts = alive.map(b => ({ b, n: st.partitions.filter(p => p.leader === b.id).length })).sort((a, b) => b.n - a.n);
    const victim = counts[0].b;
    victim.alive = false;
    log(`Broker B${victim.id} crashed`);
    st.partitions.forEach(p => electIfNeeded(p, false));
  }

  function restore() {
    st.brokers.forEach(b => b.alive = true);
    st.partitions.forEach(p => { p.isr = [...p.replicas]; });
    log('Brokers restarted · followers caught up · ISR restored (leaders unchanged — preferred-leader election can rebalance later)');
  }

  function log(html) {
    const el = $('#labLog');
    const t = new Date().toLocaleTimeString().slice(0, 8);
    el.insertAdjacentHTML('afterbegin', `<div class="feed-item"><span class="t">${t}</span><div class="m">${html}</div></div>`);
    while (el.children.length > 60) el.lastChild.remove();
  }

  // ---------- geometry ----------
  const prodY = i => 120 + i * ((H - 240) / 2);
  const rowGeom = () => {
    const P = st.partitions.length, top = 78, bottom = H - 110;
    const h = Math.min(78, (bottom - top) / P);
    return { top, h, x0: 190, x1: W - 230 };
  };
  const rowY = i => { const g = rowGeom(); return g.top + i * g.h + g.h / 2; };
  const consY = i => { const C = st.consumers.length; const span = H - 200; return 100 + (C === 1 ? span / 2 : i * span / (C - 1)); };

  // ---------- simulation ----------
  function produceOne() {
    const keyed = $('#lKeyMode .on').dataset.v === 'key';
    const acks = $('#lAcks .on').dataset.v;
    const prod = st.prodRR++ % 3;
    let key = null, part;
    if (keyed) { key = KEYS[Math.floor(Math.random() * KEYS.length)]; part = (murmur2(key) & 0x7fffffff) % st.partitions.length; }
    else part = st.rr++ % st.partitions.length;
    const color = key ? KEY_COLORS[KEYS.indexOf(key)] : '#94a3b8';
    send({ prod, key, part, color, acks, tries: 0 });
  }

  function send(m) {
    const p = st.partitions[m.part];
    if (!p) return;
    const now = performance.now();
    const unavailable = !p.leader || p.electingUntil > now;
    if (unavailable || (m.acks === 'all' && p.isr.length < MIN_ISR)) {
      if (m.acks === '0') { st.lost++; flash(m, '#ef4444'); return; }
      st.errors++;
      if (m.tries++ < 20) st.retry.push({ at: now + 300, m });
      else st.lost++;
      return;
    }
    const g = rowGeom();
    st.flights.push({ x: 92, y: prodY(m.prod), tx: g.x1 - 4, ty: rowY(m.part), t: 0, dur: 520, color: m.color, kind: 'in', m });
  }

  function flash(m, color) { st.flights.push({ x: 92, y: prodY(m.prod), tx: 150, ty: prodY(m.prod) - 20, t: 0, dur: 400, color, kind: 'lost' }); }

  function step(dt) {
    const now = performance.now();
    st.produceAcc += dt * (+$('#lRate').value);
    while (st.produceAcc >= 1) { st.produceAcc--; produceOne(); }
    st.retry = st.retry.filter(r => { if (r.at <= now) { send(r.m); return false; } return true; });
    st.partitions.forEach(p => { if (p.electingUntil && p.electingUntil < now) p.electingUntil = 0; });
    // flights
    st.flights = st.flights.filter(f => {
      f.t += dt * 1000;
      if (f.t >= f.dur) {
        if (f.kind === 'in') {
          const p = st.partitions[f.m.part];
          if (p) { p.log.push({ o: p.log.length, c: f.color, k: f.m.key }); st.produced++; st.winIn++; }
        }
        return false;
      }
      return true;
    });
    // consumers
    if (now > st.rebalancingUntil) {
      const speed = +$('#lSpeed').value;
      st.consumers.forEach((c, ci) => {
        c.acc += dt * speed;
        let guard = 0;
        while (c.acc >= 1 && guard++ < 50) {
          const ready = c.parts.map(i => st.partitions[i]).filter(p => p && p.committed < p.log.length && p.leader && !p.electingUntil);
          if (!ready.length) { c.acc = Math.min(c.acc, 1); break; }
          const p = ready[c.done++ % ready.length];
          const rec = p.log[p.committed];
          p.committed++;
          st.consumed++; st.winOut++;
          c.acc--;
          const g = rowGeom();
          st.flights.push({ x: g.x1, y: rowY(p.id), tx: W - 120, ty: consY(ci), t: 0, dur: 450, color: rec.c, kind: 'out' });
        }
      });
    }
    st.winT += dt;
    if (st.winT >= 1) { st.rateIn = st.winIn / st.winT; st.rateOut = st.winOut / st.winT; st.winIn = st.winOut = 0; st.winT = 0; metrics(); }
  }

  function metrics() {
    const lag = st.partitions.reduce((a, p) => a + p.log.length - p.committed, 0);
    const under = st.partitions.filter(p => p.isr.length < 3).length;
    const items = [['Produced', st.produced], ['Consumed', st.consumed], ['Total lag', lag], ['In / out', `${st.rateIn.toFixed(0)}/${st.rateOut.toFixed(0)}`],
      ['Rebalances', st.rebalances], ['Leader elections', st.elections], ['Under-replicated', under], ['Retries / lost', `${st.errors}/${st.lost}`]];
    $('#labMetrics').innerHTML = items.map(([l, v]) => `<div class="lm"><div class="l">${l}</div><div class="v">${v}</div></div>`).join('');
  }

  // ---------- drawing ----------
  function rr(x, y, w, h, r) { ctx.beginPath(); ctx.roundRect(x, y, w, h, r); }

  function draw() {
    ctx.clearRect(0, 0, W, H);
    const now = performance.now();
    const g = rowGeom();
    ctx.font = '600 12px IBM Plex Sans';
    ctx.fillStyle = '#64748b';
    ctx.fillText('PRODUCERS', 28, 40);
    ctx.fillText('TOPIC  bin-telemetry  ·  RF=3  ·  min.insync=2', g.x0, 40);
    ctx.fillText('CONSUMER GROUP  wastex-stream-processor', W - 330, 40);
    // producers
    for (let i = 0; i < 3; i++) {
      const y = prodY(i);
      rr(20, y - 24, 72, 48, 12); ctx.fillStyle = '#1a1030'; ctx.fill(); ctx.strokeStyle = '#c447d6'; ctx.lineWidth = 1.5; ctx.stroke();
      ctx.fillStyle = '#e2e8f0'; ctx.font = '600 12px IBM Plex Sans'; ctx.fillText(`IoT GW ${i + 1}`, 30, y - 3);
      ctx.fillStyle = '#94a3b8'; ctx.font = '10px IBM Plex Sans'; ctx.fillText('producer', 30, y + 12);
    }
    // consumer assignment lines
    st.consumers.forEach((c, ci) => {
      c.parts.forEach(pi => {
        ctx.strokeStyle = CONS_COLORS[ci % 6] + '55'; ctx.lineWidth = 2; ctx.setLineDash([5, 5]);
        ctx.beginPath(); ctx.moveTo(g.x1 + 2, rowY(pi)); ctx.bezierCurveTo(g.x1 + 60, rowY(pi), W - 180, consY(ci), W - 122, consY(ci)); ctx.stroke(); ctx.setLineDash([]);
      });
    });
    // partitions
    const cellW = 24, cells = Math.floor((g.x1 - g.x0 - 70) / (cellW + 3));
    st.partitions.forEach((p, i) => {
      const y = rowY(i), hh = Math.min(30, g.h - 26);
      const owner = st.consumers.findIndex(c => c.parts.includes(i));
      ctx.fillStyle = '#e2e8f0'; ctx.font = '600 13px IBM Plex Mono'; ctx.fillText(`P${i}`, g.x0, y + 4);
      const electing = p.electingUntil > now;
      ctx.font = '10.5px IBM Plex Mono';
      ctx.fillStyle = !p.leader ? '#ef4444' : electing ? '#fbbf24' : '#64748b';
      const leaderTxt = !p.leader ? 'OFFLINE' : electing ? `electing… → B${p.leader}` : `leader B${p.leader}`;
      ctx.fillText(`${leaderTxt} · ISR {${p.isr.map(b => 'B' + b).join(',')}}`, g.x0 + 40, y - hh / 2 - 6);
      const lag = p.log.length - p.committed;
      ctx.textAlign = 'right'; ctx.fillStyle = lag > 20 ? '#f87171' : '#4ade80';
      ctx.fillText(`end ${p.log.length} · lag ${lag}`, g.x1, y - hh / 2 - 6); ctx.textAlign = 'left';
      const start = Math.max(0, p.log.length - cells);
      for (let k = 0; k < cells; k++) {
        const o = start + k, x = g.x0 + 40 + k * (cellW + 3);
        rr(x, y - hh / 2, cellW, hh, 4);
        if (o < p.log.length) {
          const rec = p.log[o];
          ctx.fillStyle = rec.c; ctx.globalAlpha = o < p.committed ? 0.28 : 0.95; ctx.fill(); ctx.globalAlpha = 1;
          if (cellW >= 22 && hh >= 18) { ctx.fillStyle = '#0b1220'; ctx.font = '9px IBM Plex Mono'; ctx.textAlign = 'center'; ctx.fillText(o % 1000, x + cellW / 2, y + 3); ctx.textAlign = 'left'; }
        } else { ctx.strokeStyle = 'rgba(148,163,184,.15)'; ctx.lineWidth = 1; ctx.stroke(); }
        if (o === p.committed && owner >= 0) { ctx.fillStyle = CONS_COLORS[owner % 6]; ctx.fillRect(x - 2, y - hh / 2 - 3, 2, hh + 6); }
      }
    });
    // brokers
    const bw = (g.x1 - g.x0) / 3 - 12;
    st.brokers.forEach((b, i) => {
      const x = g.x0 + i * (bw + 18), y = H - 80;
      rr(x, y, bw, 54, 10);
      ctx.fillStyle = b.alive ? '#0b1a2e' : '#2a0f12'; ctx.fill();
      ctx.strokeStyle = b.alive ? '#0e7490' : '#ef4444'; ctx.lineWidth = 1.5; ctx.stroke();
      ctx.fillStyle = b.alive ? '#e2e8f0' : '#fca5a5'; ctx.font = '600 13px IBM Plex Sans';
      ctx.fillText(`Broker B${b.id}${b.alive ? '' : '  · down'}`, x + 12, y + 22);
      const leads = st.partitions.filter(p => p.leader === b.id).map(p => 'P' + p.id);
      const follows = st.partitions.filter(p => p.replicas.includes(b.id) && p.leader !== b.id).map(p => 'P' + p.id);
      ctx.font = '10.5px IBM Plex Mono'; ctx.fillStyle = '#94a3b8';
      ctx.fillText(`leader: ${leads.join(' ') || '–'}`, x + 12, y + 38);
      ctx.fillText(`follower: ${follows.join(' ') || '–'}`, x + 12, y + 50);
    });
    // consumers
    const rebal = now < st.rebalancingUntil;
    st.consumers.forEach((c, ci) => {
      const y = consY(ci), x = W - 120;
      rr(x, y - 26, 100, 52, 12);
      ctx.fillStyle = '#0d1628'; ctx.fill(); ctx.strokeStyle = CONS_COLORS[ci % 6]; ctx.lineWidth = rebal ? 3 : 1.5; ctx.stroke();
      ctx.fillStyle = '#e2e8f0'; ctx.font = '600 12px IBM Plex Sans'; ctx.fillText(`Consumer C${c.id}`, x + 10, y - 6);
      ctx.font = '10.5px IBM Plex Mono'; ctx.fillStyle = c.parts.length ? '#94a3b8' : '#f87171';
      ctx.fillText(rebal ? 'rebalancing…' : (c.parts.map(p => 'P' + p).join(',') || 'idle'), x + 10, y + 12);
    });
    // flights
    st.flights.forEach(f => {
      const t = Math.min(1, f.t / f.dur), e = t < .5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2;
      const x = f.x + (f.tx - f.x) * e, y = f.y + (f.ty - f.y) * e;
      ctx.beginPath(); ctx.arc(x, y, f.kind === 'lost' ? 6 : 4.5, 0, 7);
      ctx.fillStyle = f.color; ctx.shadowColor = f.color; ctx.shadowBlur = 10; ctx.fill(); ctx.shadowBlur = 0;
      if (f.kind === 'lost') { ctx.strokeStyle = '#ef4444'; ctx.lineWidth = 2; ctx.beginPath(); ctx.moveTo(x - 5, y - 5); ctx.lineTo(x + 5, y + 5); ctx.moveTo(x + 5, y - 5); ctx.lineTo(x - 5, y + 5); ctx.stroke(); }
    });
  }

  function frame(t) {
    if (!running) return;
    const dt = Math.min(0.1, (t - (last || t)) / 1000);
    last = t;
    step(dt);
    draw();
    requestAnimationFrame(frame);
  }

  function resize() {
    const dpr = window.devicePixelRatio || 1;
    W = cv.clientWidth; H = cv.clientHeight;
    cv.width = W * dpr; cv.height = H * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }

  function bind() {
    cv = $('#labCanvas'); ctx = cv.getContext('2d');
    const lbl = (id, f) => { const el = $('#' + id); const upd = () => $('#' + id + 'L').textContent = f(el.value); el.addEventListener('input', upd); upd(); };
    lbl('lRate', v => `${v} msg/s`); lbl('lSpeed', v => `${v} msg/s`); lbl('lPart', v => v); lbl('lCons', v => v);
    $('#lPart').addEventListener('change', e => setPartitions(+e.target.value));
    $('#lCons').addEventListener('change', e => setConsumers(+e.target.value));
    $$('.seg').forEach(seg => seg.addEventListener('click', e => {
      if (e.target.tagName !== 'BUTTON') return;
      $$('button', seg).forEach(b => b.classList.toggle('on', b === e.target));
      if (seg.id === 'lAcks') log(`Producer acks=${e.target.dataset.v} — ` + ({ '0': 'fire-and-forget: fastest, may lose data', '1': 'leader ack: lost only if leader dies before replication', 'all': 'all ISR ack: no loss, needs ≥ min.insync replicas' })[e.target.dataset.v]);
      if (seg.id === 'lKeyMode') log(e.target.dataset.v === 'key' ? 'Keyed: murmur2(bin_id) mod N → per-bin ordering preserved' : 'No key: round-robin → even spread, no per-bin ordering');
    }));
    $('#lKillBroker').onclick = killBroker;
    $('#lRestore').onclick = restore;
    $('#lBurst').onclick = () => { for (let i = 0; i < 50; i++) produceOne(); log('Burst of 50 messages (event surge) — watch lag grow then drain'); };
    $('#lReset').onclick = reset;
    window.addEventListener('resize', () => running && resize());
    reset();
  }

  let bound = false;
  return {
    show() {
      if (!bound) { bind(); bound = true; }
      resize();
      if (new URLSearchParams(location.search).has('shot') && !st.produced) {
        // report screenshots: headless browsers do not run animation frames, so pre-run the simulation
        for (let i = 0; i < 400; i++) step(0.05);
        killBroker();
        st.partitions.forEach(p => p.electingUntil = 0);  // no wall-clock time passes in this loop
        for (let i = 0; i < 400; i++) step(0.05);
        draw();
      }
      if (!running) { running = true; last = 0; requestAnimationFrame(frame); }
    },
    hide() { running = false; },
    update() { },
  };
})();
