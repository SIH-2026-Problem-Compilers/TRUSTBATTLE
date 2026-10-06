// M5 evaluation — browser JS-heap sampler.
// Connects to a headless Chrome started with --remote-debugging-port=9222,
// navigates to the dashboard, and samples JS heap + DOM size every 15 s.
//
// Usage: node member5_software/eval/browser_heap.mjs <duration_s> <csv_out>

const DURATION_S = parseInt(process.argv[2] ?? '1800', 10);
const OUT = process.argv[3] ?? 'member5_software/eval/browser_heap_log.csv';
const TAB = 'http://localhost:5173/';
const CDP_HOST = 'http://127.0.0.1:9222';

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function getPageTarget() {
  const list = await (await fetch(`${CDP_HOST}/json/list`)).json();
  let page = list.find((t) => t.type === 'page');
  if (!page) {
    page = await (await fetch(`${CDP_HOST}/json/new?${encodeURIComponent(TAB)}`)).json();
  }
  return page;
}

function cdp(ws) {
  let id = 0;
  const pending = new Map();
  ws.addEventListener('message', (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.id && pending.has(msg.id)) {
      const { resolve, reject } = pending.get(msg.id);
      pending.delete(msg.id);
      msg.error ? reject(new Error(msg.error.message)) : resolve(msg.result);
    }
  });
  return {
    send(method, params = {}) {
      const mid = ++id;
      ws.send(JSON.stringify({ id: mid, method, params }));
      return new Promise((resolve, reject) => {
        pending.set(mid, { resolve, reject });
        setTimeout(() => {
          if (pending.delete(mid)) reject(new Error(`timeout: ${method}`));
        }, 10000);
      });
    },
  };
}

async function main() {
  const page = await getPageTarget();
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((res, rej) => {
    ws.addEventListener('open', res);
    ws.addEventListener('error', rej);
  });
  const c = cdp(ws);

  await c.send('Page.enable');
  await c.send('Runtime.enable');
  await c.send('Page.navigate', { url: TAB });

  const rows = ['elapsed_s,used_heap_mb,total_heap_mb,dom_nodes,title'];
  const t0 = Date.now();
  let failures = 0;
  console.log(`sampling for ${DURATION_S}s -> ${OUT}`);

  while ((Date.now() - t0) / 1000 < DURATION_S) {
    try {
      const r = await c.send('Runtime.evaluate', {
        expression: `JSON.stringify({u:performance.memory?.usedJSHeapSize??0,t:performance.memory?.totalJSHeapSize??0,d:document.getElementsByTagName('*').length,x:document.title})`,
        returnByValue: true,
      });
      const v = JSON.parse(r.result.value);
      const elapsed = Math.round((Date.now() - t0) / 1000);
      rows.push(
        `${elapsed},${(v.u / 1048576).toFixed(1)},${(v.t / 1048576).toFixed(1)},${v.d},${JSON.stringify(v.x)}`
      );
      // flush incrementally so a killed session still leaves usable data
      const fs0 = await import('node:fs');
      fs0.writeFileSync(OUT, rows.join('\n') + '\n');
      console.log(`${elapsed}s heap_used=${(v.u / 1048576).toFixed(1)}MB dom=${v.d}`);
    } catch (e) {
      failures++;
      console.log(`sample failed: ${e.message}`);
    }
    await sleep(15000);
  }
  rows.push(`# failures=${failures}`);
  const fs = await import('node:fs');
  fs.writeFileSync(OUT, rows.join('\n') + '\n');
  console.log(`done, ${rows.length - 2} samples`);
  ws.close();
  process.exit(0);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
