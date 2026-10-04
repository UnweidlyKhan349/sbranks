// Render a JS page with headless Chromium and save its HTML, visible text and any JSON
// API responses it loaded.  Usage:
//   NODE_PATH=$(npm root -g) node g1_render_page.js <url> <out_prefix> [wait_ms] [click_text...]
// Writes <out_prefix>.html, <out_prefix>.txt and <out_prefix>.api.json ({url: body}).
// After each click_text the visible text is appended to <out_prefix>.txt as a new section.
// All requests are routed through Playwright's own fetch with retries (Chromium's network
// stack fails intermittently behind the sandbox proxy).
const { chromium } = require('playwright');
const fs = require('fs');
(async () => {
  const [url, out, waitMs, ...clicks] = process.argv.slice(2);
  const b = await chromium.launch();
  const ctx = await b.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1600, height: 1200 } });
  const p = await ctx.newPage();
  await p.route('**/*', async route => {
    const u = route.request().url();
    if (u.includes('cloudflareinsights') || u.includes('googletagmanager')) return route.abort();
    for (let i = 0; i < 4; i++) {
      try { const resp = await route.fetch({ timeout: 60000 }); return await route.fulfill({ response: resp }); }
      catch (e) { await new Promise(r => setTimeout(r, 1000 * (i + 1))); }
    }
    return route.abort();
  });
  const api = {};
  p.on('response', async (r) => {
    try {
      const ct = r.headers()['content-type'] || '';
      if (ct.includes('application/json')) api[r.url()] = await r.json();
    } catch (e) { /* ignore */ }
  });
  await p.goto(url, { waitUntil: 'networkidle', timeout: 120000 });
  await p.waitForTimeout(parseInt(waitMs || '3000', 10));
  const texts = ['=== initial\n' + await p.evaluate(() => document.body.innerText)];
  for (const c of clicks) {
    try {
      await p.getByText(c, { exact: true }).first().click();
      await p.waitForTimeout(2500);
      texts.push('=== after click ' + c + '\n' + await p.evaluate(() => document.body.innerText));
    } catch (e) { console.error('click failed', c, e.message.slice(0, 100)); }
  }
  fs.writeFileSync(out + '.html', await p.content());
  fs.writeFileSync(out + '.txt', texts.join('\n'));
  fs.writeFileSync(out + '.api.json', JSON.stringify(api));
  console.log('ok', Object.keys(api).length, 'api responses');
  await b.close();
})().catch(e => { console.error(e); process.exit(1); });
