// Records the OmniDoc walkthrough from the live site as JPEG frames (CDP screencast), with a log of
// captions, sped-up waits and key moments that make.py turns into the final video.
const path = require('path');
const fs = require('fs');
const { chromium } = require(path.join(process.env.PW_ROOT, 'playwright'));

const OUT = process.env.OUT;
const BASE = process.env.BASE || 'https://omnidoc-silk.vercel.app';
const W = 1600, H = 900;
const FRAMES = path.join(OUT, 'frames');
fs.mkdirSync(FRAMES, { recursive: true });
const log = { frames: [], captions: [], fast: [], marks: {}, shots: [] };
const now = () => Date.now() / 1000;
const wait = (ms) => new Promise((r) => setTimeout(r, ms));

let open = null;
function caption(text) {
  const t = now();
  if (open) { open.end = t; log.captions.push(open); }
  open = text ? { start: t, end: null, text } : null;
}
function fastStart(factor = 6) { log.fast.push({ start: now(), end: null, factor }); }
function fastEnd() { const f = log.fast[log.fast.length - 1]; if (f && !f.end) f.end = now(); }

const CURSOR = `
(() => {
  const install = () => {
    if (document.getElementById('__demo_cursor')) return;
    const c = document.createElement('div');
    c.id = '__demo_cursor';
    c.style.cssText = 'position:fixed;left:0;top:0;width:24px;height:24px;z-index:2147483647;pointer-events:none;transform:translate(-80px,-80px);';
    c.innerHTML = '<svg width="24" height="24" viewBox="0 0 24 24"><path d="M4 2.5l15 9.2-6.6 1.4 3.9 7.2-2.6 1.4-3.9-7.3L4.6 19z" fill="#fff" stroke="#111" stroke-width="1.4" stroke-linejoin="round"/></svg>';
    document.documentElement.appendChild(c);
    const ring = document.createElement('div');
    ring.style.cssText = 'position:fixed;left:0;top:0;width:34px;height:34px;margin:-17px 0 0 -17px;border-radius:50%;border:2px solid rgba(69,137,255,.9);z-index:2147483646;pointer-events:none;opacity:0;transition:opacity .35s, transform .35s;';
    document.documentElement.appendChild(ring);
    document.addEventListener('mousemove', (e) => { c.style.transform = 'translate(' + (e.clientX - 3) + 'px,' + (e.clientY - 2) + 'px)'; }, true);
    document.addEventListener('mousedown', (e) => {
      ring.style.transition = 'none'; ring.style.opacity = '1'; ring.style.transform = 'translate(' + e.clientX + 'px,' + e.clientY + 'px) scale(.5)';
      requestAnimationFrame(() => { ring.style.transition = 'opacity .45s, transform .45s'; ring.style.opacity = '0'; ring.style.transform = 'translate(' + e.clientX + 'px,' + e.clientY + 'px) scale(1.4)'; });
    }, true);
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', install); else install();
})();`;

const CARD = (inner) => `<!doctype html><html><head><meta charset="utf-8"><style>
  html,body{margin:0;height:100%;background:#0b0d12;color:#e7eaf0;font-family:"Helvetica Neue",Helvetica,Arial,sans-serif}
  .wrap{height:100%;display:grid;place-items:center;text-align:center}
  h1{font-size:76px;letter-spacing:-2px;margin:22px 0 10px;font-weight:650}
  p{font-size:28px;color:#aab3c5;margin:8px 0}
  .small{font-size:19px;color:#6f7a90;margin-top:34px}
  a{color:#78a9ff;text-decoration:none}
  @keyframes rise{from{opacity:0;transform:translateY(14px)}to{opacity:1;transform:none}}
  .wrap>div{animation:rise .9s cubic-bezier(.2,0,0,1) both}
</style></head><body><div class="wrap"><div>${inner}</div></div></body></html>`;
const MARK = `<svg width="120" height="120" viewBox="0 0 24 24"><defs><clipPath id="p"><rect x="10" y="3" width="11" height="15" rx="2.6"/></clipPath></defs><rect x="10" y="3" width="11" height="15" rx="2.6" fill="#e7eaf0"/><circle cx="9" cy="14" r="7" fill="#e7eaf0"/><circle cx="9" cy="14" r="7" fill="#78a9ff" clip-path="url(#p)"/></svg>`;

async function main() {
  const browser = await chromium.launch({ executablePath: process.env.CHROME });
  const ctx = await browser.newContext({ viewport: { width: W, height: H }, colorScheme: 'dark', bypassCSP: true });
  await ctx.addInitScript(CURSOR);
  const page = await ctx.newPage();
  page.setDefaultTimeout(6000);
  const issues = [];
  const tryStep = async (name, fn) => { try { await fn(); } catch (e) { issues.push(`${name}: ${String(e.message || e).split('\n')[0].slice(0, 120)}`); } };
  const cdp = await ctx.newCDPSession(page);
  let n = 0;
  cdp.on('Page.screencastFrame', async (f) => {
    const file = path.join(FRAMES, `${String(n).padStart(6, '0')}.jpg`);
    fs.writeFileSync(file, Buffer.from(f.data, 'base64'));
    log.frames.push([n, f.metadata.timestamp]);
    n++;
    try { await cdp.send('Page.screencastFrameAck', { sessionId: f.sessionId }); } catch {}
  });
  const shot = async (name) => { const p = path.join(OUT, `shot-${name}.png`); await page.screenshot({ path: p }); log.shots.push(name); };
  const move = async (locator, opts = {}) => {
    await locator.scrollIntoViewIfNeeded().catch(() => {});
    const b = await locator.boundingBox();
    if (!b) return null;
    const x = b.x + b.width * (opts.fx ?? 0.5), y = b.y + b.height * (opts.fy ?? 0.5);
    await page.mouse.move(x, y, { steps: opts.steps ?? 28 });
    await wait(opts.pause ?? 250);
    return { x, y };
  };
  const click = async (locator, opts) => { const p = await move(locator, opts); if (p) { await page.mouse.down(); await wait(70); await page.mouse.up(); } else { await locator.click(); } await wait(opts?.after ?? 600); };
  const scrollBy = async (px, ms) => {
    const steps = Math.max(1, Math.round(ms / 16));
    for (let i = 0; i < steps; i++) { await page.evaluate((d) => window.scrollBy(0, d), px / steps); await wait(16); }
  };
  const rail = (name) => page.locator('nav[aria-label="Main"]').getByRole('button', { name, exact: true }).first();

  // ---- title card
  await page.setContent(CARD(`${MARK}<h1>OmniDoc</h1><p>Ask your documents. Check every answer.</p>`));
  await cdp.send('Page.startScreencast', { format: 'jpeg', quality: 92, maxWidth: W, maxHeight: H, everyNthFrame: 2 });
  await wait(3600);

  // ---- product page
  await page.goto(BASE + '/');
  await page.getByRole('heading', { level: 1 }).first().waitFor();
  await page.mouse.move(W * 0.62, H * 0.42, { steps: 1 });
  caption('OmniDoc answers questions about your PDFs, scans, contracts and spreadsheets.');
  await wait(3800);
  await shot('landing');
  caption('Every claim cites the page it came from, and every sentence is checked against its source.');
  await scrollBy(H * 1.1, 2600); await wait(600);
  await scrollBy(H * 1.6, 4200); await wait(800);
  await scrollBy(H * 1.6, 4200); await wait(600);
  caption('Extract fields, compare versions, find personal data and explore a knowledge graph.');
  await page.evaluate(() => document.getElementById('features')?.scrollIntoView({ behavior: 'smooth' }));
  await wait(1800);
  await scrollBy(H * 2.4, 6500); await wait(600);
  caption('Measured on public benchmarks, with answers from free models.');
  await page.evaluate(() => document.getElementById('benchmarks')?.scrollIntoView({ behavior: 'smooth' }));
  await wait(3400);
  await shot('benchmarks');
  caption('Built entirely on free tiers, and open source. Feedback reaches the author by e-mail.');
  await page.evaluate(() => document.getElementById('feedback')?.scrollIntoView({ behavior: 'smooth' }));
  await wait(2200);
  const card = page.locator('form').filter({ has: page.getByLabel('Your feedback') });
  await move(card, { fx: 0.8, fy: 0.2, steps: 30 }); await wait(500);
  await move(card, { fx: 0.25, fy: 0.75, steps: 40 }); await wait(700);
  await shot('feedback');

  // ---- the demo
  caption('Try it without an account: a sample library of five documents.');
  await page.evaluate(() => window.scrollTo({ top: 0, behavior: 'smooth' }));
  await wait(1600);
  await click(page.locator('header').getByRole('button', { name: 'Try the demo' }), { after: 400 });
  await page.getByText('free answers left').waitFor({ timeout: 40000 });
  caption('A short guided tour shows new users around the workspace.');
  await page.locator('#tour-title').waitFor({ timeout: 8000 }).catch(() => {});
  await wait(1800);
  for (let i = 0; i < 2; i++) {
    const next = page.getByRole('dialog').getByRole('button', { name: /Show me around|Next/ });
    if (!(await next.count())) break;
    await click(next, { after: 1700 });
  }
  await shot('tour');
  await page.keyboard.press('Escape');
  await wait(500);

  caption('Ask in plain words.');
  const box = page.getByRole('textbox').first();
  await click(box, { after: 200 });
  await page.keyboard.type("What was Kestrel's revenue in FY2025, and how much did it grow?", { delay: 38 });
  await wait(500);
  await page.keyboard.press('Enter');
  caption('Agents retrieve passages, read the tables, look for conflicts and write the answer. (Sped up.)');
  fastStart(6);
  await page.waitForFunction(() => /Supported by sources|Partly supported|Not verified/.test(document.body.innerText), null, { timeout: 180000 }).catch(() => {});
  await wait(1200);
  fastEnd();
  caption('Every figure is cited, and the table it came from is shown with the query that read it.');
  await page.evaluate(() => document.querySelector('main')?.scrollBy?.(0, 0));
  await tryStep('sql', async () => {
    const sqlBtn = page.getByRole('button', { name: 'SQL', exact: true }).first();
    if (await sqlBtn.count()) { await click(sqlBtn, { after: 1800 }); await click(sqlBtn, { after: 600 }); }
  });
  await shot('answer');
  caption('Click a citation: the page opens with the supporting sentence highlighted.');
  await tryStep('citation', async () => {
    await click(page.getByRole('button', { name: /^Source 1\b/ }).first(), { after: 3800 });
    await shot('viewer');
    await page.keyboard.press('Escape');
    await wait(800);
  });
  const check = page.getByRole('button', { name: /Sentence check/ }).first();
  if (await check.count()) {
    caption('And each sentence of the answer is checked against the passages it cites.');
    await click(check, { after: 3200 });
    await page.keyboard.press('Escape');
    await wait(600);
  }

  caption('Ask and get answers in ten languages.');
  await click(box, { after: 200 });
  await page.keyboard.insertText('वित्त वर्ष 2025 में सब्सक्रिप्शन राजस्व कितना था?');
  await wait(700);
  await page.keyboard.press('Enter');
  fastStart(6);
  await page.waitForFunction(() => (document.body.innerText.match(/Supported by sources|Partly supported|Not verified/g) || []).length >= 2, null, { timeout: 180000 }).catch(() => {});
  await wait(1200);
  fastEnd();
  await wait(2600);
  await shot('hindi');

  // ---- the library tools
  caption('Search every passage in the library, without a model call.');
  await tryStep('search', async () => {
  await click(rail('Search'), { after: 700 });
  const search = page.getByLabel('Search your documents');
  await click(search, { after: 150 });
  await page.keyboard.type('payment terms and late fees', { delay: 40 });
  await page.keyboard.press('Enter');
  await page.waitForSelector('text=/passages? for/', { timeout: 60000 }).catch(() => {});
  await wait(2600);
  });

  caption('The library: every document with its pages, summary, tables and fields.');
  await click(rail('Library'), { after: 2600 });
  await shot('library');

  caption('Every table found in the documents, as data you can open and download.');
  await tryStep('tables', async () => {
  await click(rail('Tables'), { after: 1400 });
  const t1 = page.locator('main').getByRole('button').filter({ hasText: 'Financial highlights' }).first();
  if (await t1.count()) await click(t1, { after: 2800 });
  await shot('tables');
  await page.keyboard.press('Escape');
  });

  caption('Every date in the library, in order, each linked to its page.');
  await click(rail('Timeline'), { after: 1200 });
  await scrollBy(500, 2200); await wait(900);

  caption('A privacy scan finds Aadhaar, PAN, card and phone numbers, and makes redacted copies.');
  await tryStep('privacy', async () => {
  await click(rail('Privacy scan'), { after: 900 });
  const scan = page.getByRole('button', { name: /Scan the library/ });
  if (await scan.count()) await click(scan, { after: 600 });
  await wait(3600);
  await shot('privacy');
  });

  caption('People, companies and places linked across the library, on a globe you can search.');
  await tryStep('globe', async () => {
  await click(rail('Knowledge'), { after: 3800 });
  const globe = page.locator('main canvas').first();
  const g = await globe.boundingBox().catch(() => null);
  if (g) {
    await page.mouse.move(g.x + g.width * 0.45, g.y + g.height * 0.5, { steps: 20 });
    await page.mouse.down(); await page.mouse.move(g.x + g.width * 0.62, g.y + g.height * 0.46, { steps: 45 }); await page.mouse.up();
  }
  await wait(2600);
  await shot('globe');
  });

  caption('Make it yours: light, dark or system theme, accent colours, text size and motion.');
  await tryStep('settings', async () => {
  await page.keyboard.press('Meta+Comma');
  await wait(1200);
  const dialog = page.getByRole('dialog');
  const light = dialog.getByRole('radio', { name: /^Light$/ }).first();
  if (await light.count()) await click(light, { after: 1300 });
  const violet = dialog.getByRole('radio', { name: /Violet/i }).first();
  if (await violet.count()) await click(violet, { after: 1500 });
  await page.keyboard.press('Escape');
  await wait(600);
  await click(rail('Chat'), { after: 900 });
  await page.mouse.move(W * 0.55, H * 0.55, { steps: 25 });
  await wait(1800);
  await shot('light');
  });

  // ---- end card
  caption(null);
  await page.setContent(CARD(`${MARK}<h1>Try OmniDoc</h1><p><a>omnidoc-silk.vercel.app</a></p><p>github.com/muditagrawal-alt/OmniDoc</p>
    <p class="small">Open source under the MIT licence · Built on free model tiers<br>Music: “Inspired” by Kevin MacLeod (incompetech.com), CC BY 4.0</p>`));
  await wait(5200);
  await cdp.send('Page.stopScreencast');
  log.end = now();
  fs.writeFileSync(path.join(OUT, 'log.json'), JSON.stringify(log));
  if (issues.length) console.log('skipped steps:\n  ' + issues.join('\n  '));
  console.log(`frames ${log.frames.length}, captions ${log.captions.length}, sped-up waits ${log.fast.length}, shots ${log.shots.join(', ')}`);
  await browser.close();
}
main().catch((e) => { console.error('FAILED', e); process.exit(1); });
