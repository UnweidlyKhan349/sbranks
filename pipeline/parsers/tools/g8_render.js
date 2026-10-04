// Render one or more pages with headless Chromium and save HTML (and optionally binary
// downloads like PDFs) for the g8 group (NSB Nationals on science.osti.gov, Challonge).
// science.osti.gov returns 403 to plain scripted clients; a real browser context works.
//   NODE_PATH=$(npm root -g) node pipeline/parsers/tools/g8_render.js <out_dir> <url=file> [<url=file> ...]
// Each url is rendered as a page (HTML saved to <out_dir>/<file>) unless the file ends in
// .pdf/.xlsx, in which case it is fetched with the browser context's request API after the
// first HTML page has warmed up cookies. Requests go through Playwright's own fetch with retries
// (Chromium's network stack fails intermittently behind the sandbox proxy).
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
(async () => {
  const [outDir, ...pairs] = process.argv.slice(2);
  fs.mkdirSync(outDir, { recursive: true });
  const b = await chromium.launch();
  const ctx = await b.newContext({
    ignoreHTTPSErrors: true, viewport: { width: 1600, height: 1200 },
    userAgent: 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36',
  });
  const p = await ctx.newPage();
  await p.route('**/*', async route => {
    const u = route.request().url();
    if (/googletagmanager|doubleclick|google-analytics|adservice|cloudflareinsights|siteimprove|addthis|\.(png|jpg|jpeg|gif|svg|woff2?|ttf)(\?|$)/i.test(u)) return route.abort();
    for (let i = 0; i < 4; i++) {
      try { const resp = await route.fetch({ timeout: 60000 }); return await route.fulfill({ response: resp }); }
      catch (e) { await new Promise(r => setTimeout(r, 1000 * (i + 1))); }
    }
    return route.abort();
  });
  for (const pair of pairs) {
    const i = pair.lastIndexOf('=');
    const url = pair.slice(0, i), file = pair.slice(i + 1);
    const out = path.join(outDir, file);
    fs.mkdirSync(path.dirname(out), { recursive: true });
    try {
      if (/\.(pdf|xlsx|xls|csv|json|jpg|jpeg|png)$/i.test(file)) {
        let r = null;
        for (let k = 0; k < 4; k++) {
          try { r = await ctx.request.get(url, { timeout: 90000 }); break; }
          catch (e) { await new Promise(res => setTimeout(res, 2000 * (k + 1))); }
        }
        if (!r) { console.log('FAIL', url); continue; }
        const body = await r.body();
        if (r.status() === 200) fs.writeFileSync(out, body);
        console.log(r.status(), body.length, url, '->', file);
      } else {
        const resp = await p.goto(url, { waitUntil: 'domcontentloaded', timeout: 120000 });
        for (let k = 0; k < 20; k++) {
          await p.waitForTimeout(2000);
          let t = '';
          try { t = await p.title(); } catch (e) { continue; }
          if (!/just a moment/i.test(t)) break;
        }
        await p.waitForTimeout(2000);
        const html = await p.content();
        const st = resp ? resp.status() : 0;
        if (st === 200) fs.writeFileSync(out, html);
        console.log(st, html.length, url, '->', file);
      }
    } catch (e) { console.log('ERR', url, e.message.slice(0, 200)); }
  }
  await b.close();
})().catch(e => { console.error(e); process.exit(1); });
