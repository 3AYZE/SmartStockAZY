// Optional real Chromium UI smoke test. Supply SMARTSTOCK_PLAYWRIGHT_CORE to run.
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');

let chromium;
try {
  ({chromium} = require(process.env.SMARTSTOCK_PLAYWRIGHT_CORE || 'playwright-core'));
} catch {}

const root = path.join(__dirname, '..');
const stock = ticker => ({
  ticker, quote: {ticker, name: 'Example Semiconductor Co.', exchange: 'NASDAQ', currency: 'USD',
    price: 135, change_percent: 1.8, updated_at: '2026-11-20T20:00:00Z',
    day_low: 131, day_high: 137, fifty_two_low: 90, fifty_two_high: 160},
  history: Array.from({length: 24}, (_, i) => ({
    date: `2026-10-${String(i + 1).padStart(2, '0')}`, open: 110 + i, close: 111 + i,
    volume: 1200000 + 5000 * i,
  })),
  indicators: {rsi14: 54.2, sma20: 125, avg_volume20: 1200000, gap_risk: 12, falling_knife_risk: 9},
  price_model: {buy_zone: [120, 129], strong_buy_zone: [114, 119],
    take_profit_zone: [140, 150], nearest_support: 119, first_resistance: 145,
    risk_exit: 112, risk_reward: 2, overextension_risk: 24, timing_status: 'NEUTRAL'},
  exit_risk: {score: 20, label: 'NORMAL'},
  scores: {quality: 75, entry: 65, opportunity: 72, risk: 24, momentum: 68, confidence: 80},
  score_explanations: {}, earnings: {available: false}, news_risk: {score: 0, events: []},
  news: [], fundamentals: {source: 'QA fixture', revenue: 100000000},
  filings: [{form: '10-K', date: '2026-10-01', importance: 'HIGH',
    description: 'Sample SEC filing', url: 'https://www.sec.gov/'}],
  decision_layer: {company_quality: 75, entry_quality: 65, market_regime: {label: 'NEUTRAL'}},
  core_research: {status: 'WATCH', confidence: 80, summary: 'Sample research data'},
  research_history: [{status: 'WATCH', price: 135, opportunity: 72, entry: 65, risk: 24,
    created_at: '2026-11-20T20:00:00Z'}],
  source_summary: {sec_available: true, primary_filings: 1, news_sources: 0},
  freshness: {market: '2026-11-20T20:00:00Z'},
});
const hunter = {scanned: 2, successful: 2, updated_at: '2026-11-20T20:00:00Z',
  regime: {label: 'NEUTRAL', entry_adjust: 0}, results: [
    {ticker: 'NVDA', name: 'Example Semiconductor Co.', price: 135, change_percent: 1.8,
      setup_rank: 80, status: 'STRONG SETUP', sector: {sector: 'Technology'},
      scores: {opportunity: 72, entry: 65, risk: 24, quality: 75, momentum: 76, confidence: 80},
      indicators: {rsi14: 54, falling_knife_risk: 9, avg_volume20: 1200000, relative_volume: 1.8},
      price_model: {risk_reward: 2}, why: 'Sample evidence'},
    {ticker: 'MSFT', name: 'Example Software Co.', price: 390, change_percent: -0.5,
      setup_rank: 40, status: 'WAIT FOR PULLBACK', sector: {sector: 'Technology'},
      scores: {opportunity: 40, entry: 35, risk: 56, quality: 82, momentum: 45, confidence: 60},
      indicators: {rsi14: 59, falling_knife_risk: 42, relative_volume: 1},
      price_model: {risk_reward: 1.2}, why: 'Sample pullback watch'},
  ]};

test('real browser: terminal navigation, scanner, research, portfolio, settings, compact layouts', {
  skip: !chromium && 'Set SMARTSTOCK_PLAYWRIGHT_CORE to the installed playwright-core module path',
}, async t => {
  const positions = [];
  let nextId = 1;
  let prefs = {hunter_max_symbols: 36, hunter_universe: '', ollama_enabled: false,
    ollama_url: 'http://localhost:11434', ollama_model: 'auto', sec_user_agent: 'QA Fixture'};
  let updateState = {status: 'available', message: 'QA fixture update available', latest_sha: 'sample'};
  let dashboardFailure = false;
  let missingConfidence = false;
  let deferResearch = false;
  const pendingResearch = [];
  const server = http.createServer(async (req, res) => {
    const pathname = new URL(req.url, 'http://localhost').pathname;
    let body = '';
    for await (const chunk of req) body += chunk;
    const send = (obj, status = 200) => {
      res.writeHead(status, {'Content-Type': 'application/json'}); res.end(JSON.stringify(obj));
    };
    if (pathname === '/' || pathname === '/app.js' || pathname === '/app.css') {
      const file = pathname === '/' ? 'index.html' : pathname.slice(1);
      res.writeHead(200, {'Content-Type': file.endsWith('.js') ? 'text/javascript' : file.endsWith('.css') ? 'text/css' : 'text/html'});
      res.end(fs.readFileSync(path.join(root, file))); return;
    }
    if (pathname === '/api/health') return send({ok: true, version: '0.5.1-opt-in-github-updates'});
    if (pathname === '/api/ping') return send({ok: true});
    if (pathname === '/api/ollama/status') return send({enabled: false, available: false, models: []});
    if (pathname === '/api/dashboard') return dashboardFailure ? send({error: 'Market source offline'}, 503) :
      send({updated_at: '2026-11-20T20:00:00Z', indexes: [
        {name: 'S&P 500', ticker: '^GSPC', price: 6550, change_percent: 0.6},
        {name: 'NASDAQ', ticker: '^IXIC', price: 22050, change_percent: 1.2}],
        sectors: [{name: 'Technology', ticker: 'XLK', change_percent: 1.4}],
        regime: {label: 'NEUTRAL', vix: 18, sp500_momentum_1m: 2, entry_adjust: 0},
        news: [{title: 'Sample market headline (fixture)', publisher: 'QA fixture',
          reliability: 85, impact: 'MEDIUM', url: 'https://example.com'}]});
    if (pathname === '/api/hunter') return send(hunter);
    if (pathname.startsWith('/api/stock/'))
      return send(stock(decodeURIComponent(pathname.split('/').pop())));
    if (pathname.startsWith('/api/research/')) {
      if (deferResearch) await new Promise(resolve => pendingResearch.push(resolve));
      const data = stock(decodeURIComponent(pathname.split('/').pop()));
      if (missingConfidence) delete data.core_research.confidence;
      return send(data);
    }
    if (pathname.startsWith('/api/chart/')) {
      const range = new URL(req.url, 'http://localhost').searchParams.get('range');
      return send({history: range === '1mo' ? Array.from({length: 6}, (_, i) => ({
        date: `2026-11-${String(i + 1).padStart(2, '0')}`,
        open: 145 + i, close: 146 + i, volume: 1000000 + 10000 * i,
      })) : stock('NVDA').history});
    }
    if (pathname.startsWith('/api/news-search/'))
      return send({items: [], resolved_query: decodeURIComponent(pathname.split('/').pop()),
        risk: {score: 0, events: [], confirmed_event_count: 0, event_count: 0}});
    if (pathname === '/api/settings') {
      if (req.method === 'POST') prefs = {...prefs, ...JSON.parse(body)};
      return send(prefs);
    }
    if (pathname === '/api/updates/status') return send(updateState);
    if (pathname === '/api/updates/check') return send(updateState);
    if (pathname === '/api/updates/download') return send(updateState = {status: 'ready', message: 'Fixture verified'});
    if (pathname === '/api/alerts') return send({count: positions.length,
      alerts: positions.map(p => ({ticker: p.ticker, severity: 'WATCH',
        title: 'QA risk', body: 'Fixture alert', risk_score: 55})), updated_at: '2026-11-20T20:00:00Z'});
    if (pathname === '/api/risk') {
      const priced = positions.map(p => ({...p, sector: 'Technology', price: 140,
        pnl_percent: (140 / p.avg_price - 1) * 100,
        exit_risk: {score: 55, label: 'WATCH'},
        position_strategy: {action: 'WATCH', trailing_exit: 120},
        thesis_health: {tracked: false}}));
      const cost = positions.reduce((sum, p) => sum + p.shares * p.avg_price, 0);
      const value = positions.reduce((sum, p) => sum + p.shares * 140, 0);
      return send({positions: priced, grouped: [], sector_exposure: [], valuation_complete: true,
        warnings: [], total_value: value, total_cost: cost, total_pnl: value - cost,
        total_pnl_percent: cost ? (value / cost - 1) * 100 : 0});
    }
    if (pathname === '/api/positions' && req.method === 'POST') {
      const p = {id: nextId++, ...JSON.parse(body)}; positions.push(p); return send(p);
    }
    if (pathname.startsWith('/api/positions/')) {
      const id = Number(pathname.split('/').pop());
      const index = positions.findIndex(p => p.id === id);
      if (index < 0) return send({error: 'Not found'}, 404);
      if (req.method === 'DELETE') {positions.splice(index, 1); return send({ok: true})}
      if (req.method === 'PUT') {positions[index] = {...positions[index], ...JSON.parse(body)}; return send(positions[index])}
    }
    send({error: 'Unknown QA endpoint: ' + pathname}, 404);
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(() => server.close());
  const edge = process.env.SMARTSTOCK_BROWSER || 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
  const browser = await chromium.launch({headless: true, executablePath: edge});
  t.after(() => browser.close());
  const page = await browser.newPage({viewport: {width: 1440, height: 900}});
  const capture = async (name, fullPage = false) => {
    if (!process.env.SMARTSTOCK_SCREENSHOT_DIR) return;
    fs.mkdirSync(process.env.SMARTSTOCK_SCREENSHOT_DIR, {recursive: true});
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({path: path.join(process.env.SMARTSTOCK_SCREENSHOT_DIR, name),
      fullPage, animations: 'disabled'});
  };
  const exceptions = [];
  page.on('pageerror', error => exceptions.push(error.message));
  const base = `http://127.0.0.1:${server.address().port}`;
  await page.goto(base);
  assert.equal(await page.title(), 'SmartStockAZY — Stock Research Terminal');
  await page.getByText('S&P 500').waitFor();
  assert.equal(await page.locator('.nav-link').count(), 5);
  assert.equal(await page.locator('#versionBadge').textContent(), 'v0.5.1');
  assert.equal(await page.locator('.market-indexes.grouped-strip').count(), 1);
  assert.equal(await page.locator('.market-indexes .index-card').count(), 2);
  await capture('market.png');
  await page.locator('#openMarketNews').click();
  await page.locator('.news-feed').waitFor();
  assert.equal(await page.locator('#newsQuery').inputValue(), 'stock market');
  await page.getByRole('button', {name: 'Earnings', exact: true}).click();
  await page.locator('.news-feed h3').getByText('stock earnings', {exact: true}).waitFor();
  await page.locator('#newsQuery').fill('NVDA');
  await page.locator('#newsSearch').getByRole('button', {name:'Search', exact:true}).click();
  await page.locator('.news-feed h3').getByText('NVDA', {exact:true}).waitFor();
  await page.getByRole('button', {name: 'Market', exact: true}).first().click();
  await page.locator('#quickHunter').waitFor();
  await page.locator('#quickHunter').click();
  await page.locator('.hunter-row').first().waitFor();
  assert.equal(await page.locator('#hunterStats .metric-card').count(), 4);
  assert.equal(await page.locator('.hunter-row').count(), 2);
  await page.getByRole('button', {name: 'Low Risk'}).click();
  assert.equal(await page.locator('.hunter-row').count(), 1);
  await page.getByRole('button', {name: 'All', exact: true}).click();
  await page.evaluate(() => {window.__qaHunterSearch = document.querySelector('#hunterSearch')});
  await page.locator('#hunterSearch').fill('MSFT');
  assert.equal(await page.locator('.hunter-row').count(), 1);
  assert.equal(await page.evaluate(() => document.activeElement === window.__qaHunterSearch), true);
  assert.equal(await page.evaluate(() => document.querySelector('#hunterSearch') === window.__qaHunterSearch), true);
  await page.locator('#hunterSearch').fill('');
  await page.locator('#hunterAdvanced summary').click();
  await page.locator('#hunterMinOpp').fill('70');
  await page.locator('#hunterMinOpp').dispatchEvent('change');
  assert.equal(await page.locator('.hunter-row').count(), 1);
  await page.locator('#hunterMinOpp').fill('0');
  await page.locator('#hunterMinOpp').dispatchEvent('change');
  await page.locator('[data-sort="price"]').click();
  assert.match(await page.locator('[data-sort="price"]').locator('xpath=..').getAttribute('aria-sort'), /descending/);
  assert.equal(await page.locator('#hunterAdvanced').getAttribute('open'), '');
  assert.equal(await page.evaluate(() => document.querySelector('#hunterSearch') === window.__qaHunterSearch), true);
  await page.locator('[data-details="NVDA"]').click();
  assert.equal(await page.locator('.hunter-detail').count(), 1);
  await capture('discover.png');
  await page.locator('[data-research="NVDA"]').click();
  await page.locator('.research-tabs').waitFor();
  await page.locator('.chart-wrap').waitFor();
  assert.equal(await page.locator('.decision-summary .metric-card').count(), 4);
  assert.equal(await page.locator('.compact-levels .zone').count(), 3);
  assert.equal(await page.locator('.price-history-slot').locator('xpath=ancestor::section[1]').locator('.compact-levels').count(), 1);
  assert.equal(await page.locator('.evidence-group').count(), 1);
  const reasoning = page.locator('details.compact-fold').filter({has: page.getByText('Research reasoning', {exact: true})});
  assert.equal(await reasoning.getAttribute('open'), null);
  await reasoning.locator('summary').click();
  assert.equal(await reasoning.getAttribute('open'), '');
  await reasoning.locator('summary').click();
  assert.equal(await reasoning.getAttribute('open'), null);
  assert.equal(await page.locator('.score-list:visible').count(), 0);
  await page.locator('.chart-wrap').hover({position: {x: 160, y: 90}});
  assert.notEqual(await page.locator('.js-chart-price').textContent(), '—');
  await page.locator('.range-btn[data-range="1mo"]').click();
  await page.locator('.range-btn.active[data-range="1mo"]').waitFor();
  assert.equal(await page.locator('.chart-hover-meta > div:last-child b').textContent(), '6');
  await page.locator('[data-overlay="sma50"]').click();
  assert.equal(await page.locator('[data-overlay="sma50"]').getAttribute('class').then(x => x.includes('active')), true);
  assert.equal(await page.locator('.chart-hover-meta > div:last-child b').textContent(), '6');
  await capture('research.png');
  if (process.env.SMARTSTOCK_SCREENSHOT_DIR) {
    await page.locator('.chart-wrap').scrollIntoViewIfNeeded();
    await page.screenshot({path: path.join(process.env.SMARTSTOCK_SCREENSHOT_DIR, 'research-chart.png'), animations: 'disabled'});
  }
  // Switching symbols from Research must update the heading and reset the old range.
  await page.locator('#ticker').fill('MSFT');
  await page.locator('#search').getByRole('button').click();
  await page.getByRole('heading', {name: 'MSFT · Research'}).waitFor();
  await page.locator('.range-btn.active[data-range="1y"]').waitFor();
  assert.equal(await page.locator('.chart-hover-meta > div:last-child b').textContent(), '24');
  await page.locator('#ticker').fill('NVDA');
  await page.locator('#search').getByRole('button').click();
  await page.getByRole('heading', {name: 'NVDA · Research'}).waitFor();
  await page.locator('.research-tabs').waitFor();
  await page.locator('.range-btn[data-range="1mo"]').click();
  await page.locator('.range-btn.active[data-range="1mo"]').waitFor();
  await page.getByRole('tab', {name: 'Financials & SEC'}).click();
  await page.getByText('Sample SEC filing').waitFor();
  await page.getByRole('tab', {name: 'Technicals'}).click();
  await page.locator('.score-list').waitFor();
  await page.getByRole('tab', {name: 'News & Events'}).click();
  await page.getByRole('tab', {name: 'History'}).click();
  await page.locator('.history-row').waitFor();
  await page.getByRole('tab', {name: 'Overview'}).click();
  assert.equal(await page.locator('.chart-hover-meta > div:last-child b').textContent(), '6');
  assert.match(await page.locator('[data-overlay="sma50"]').getAttribute('class'), /active/);
  assert.match(await page.locator('.range-btn.active').getAttribute('data-range'), /1mo/);
  await page.locator('#researchReturn').click();
  await page.locator('#hunterStats .metric-card').first().waitFor();
  assert.equal(await page.locator('.hunter-row').count(), 2);
  assert.equal(await page.locator('#hunterAdvanced').getAttribute('open'), '');
  assert.equal(await page.locator('.hunter-detail').count(), 1);
  assert.match(await page.locator('[data-sort="price"]').locator('xpath=..').getAttribute('aria-sort'), /descending/);
  // A missing confidence field must not be displayed as a measured zero.
  missingConfidence = true;
  await page.locator('[data-research="NVDA"]').click();
  await page.getByText('Evidence confidence unavailable').waitFor();
  await page.locator('#researchReturn').click();
  missingConfidence = false;
  // A slow research response must not overwrite another workspace.
  deferResearch = true;
  await page.locator('[data-research="NVDA"]').click();
  await page.locator('#out .price-history-slot').waitFor();
  await page.locator('[data-page="Market"]').click();
  assert.equal(pendingResearch.length, 1);
  deferResearch = false;
  pendingResearch.splice(0).forEach(resolve => resolve());
  await page.getByText('S&P 500').waitFor();
  assert.equal(await page.locator('.research-header').count(), 0);
  await page.locator('[data-page="Portfolio"]').click();
  await page.locator('#positionEditor summary').click();
  await page.locator('#pt').fill('NVDA');
  await page.locator('#ps').fill('2');
  await page.locator('#pa').fill('120');
  await page.locator('#pth').fill('Growth thesis');
  await page.locator('#savePos').click();
  await page.locator('[data-edit]').waitFor();
  assert.equal(await page.locator('#out table thead th').count(), 6);
  assert.equal(await page.locator('.lot-fold').getAttribute('open'), null);
  await page.locator('.lot-fold summary').click();
  await page.locator('.lot-fold').getByText('Trailing exit').waitFor();
  await page.locator('.lot-fold summary').click();
  await page.locator('[data-edit]').click();
  await page.locator('#ps').fill('3');
  await page.locator('#savePos').click();
  await page.locator('.portfolio-summary').getByText('Lots').waitFor();
  await page.locator('[data-tab="Risk Monitor"]').click();
  await page.getByText('Portfolio Risk Defense').waitFor();
  await capture('risk.png');
  await page.locator('[data-tab="Alerts"]').click();
  await page.getByText('Risk Alert Queue').waitFor();
  await capture('alerts.png');
  await page.locator('[data-tab="Holdings"]').click();
  await capture('holdings.png');
  page.once('dialog', dialog => dialog.accept());
  await page.locator('[data-del]').click();
  await page.getByText('No positions stored yet.').waitFor();
  await page.locator('#settingsNav').click();
  await page.locator('#hm').waitFor();
  assert.equal(await page.locator('.setting-group').count(), 3);
  assert.equal(await page.locator('.optional-settings').getAttribute('open'), null);
  await page.locator('.optional-settings summary').click();
  await page.locator('#oe').waitFor({state: 'visible'});
  await page.locator('.optional-settings summary').click();
  await page.locator('#hm').fill('25');
  await page.getByRole('button', {name: 'SAVE SETTINGS'}).click();
  await page.getByText('Saved ✓').waitFor();
  await page.locator('#checkUpdates').click();
  await page.locator('#downloadUpdate').click();
  await page.locator('#applyUpdate').waitFor({state: 'visible'});
  await capture('settings.png');
  await page.reload();
  await page.locator('#settingsNav').click();
  await page.locator('#hm').waitFor();
  assert.equal(await page.locator('#hm').inputValue(), '25');
  for (const [width, height] of [[1920, 1080], [1600, 900], [1366, 768], [1280, 720], [1024, 768], [840, 720], [720, 720], [480, 700]]) {
    await page.setViewportSize({width, height});
    for (const section of ['Market', 'Discover', 'Research', 'News', 'Portfolio', 'Settings']) {
      if (section === 'Settings') await page.locator('#settingsNav').click();
      else await page.locator(`[data-page="${section}"]`).click();
      const size = await page.evaluate(() => ({
        scrollWidth: document.documentElement.scrollWidth, innerWidth: innerWidth,
        searchWidth: document.querySelector('#globalTicker')?.getBoundingClientRect().width,
        overflow: [...document.querySelectorAll('body *')].filter(el => el.getBoundingClientRect().right > innerWidth + 2 && getComputedStyle(el).position !== 'fixed').slice(0, 8).map(el => ({tag: el.tagName, className: String(el.className).slice(0, 70), right: Math.round(el.getBoundingClientRect().right)})),
      }));
      assert.ok(size.scrollWidth <= size.innerWidth + 2, `${section} at ${width}px: ${JSON.stringify(size)}`);
      assert.ok(size.searchWidth > 60, `${section} at ${width}px: ${JSON.stringify(size)}`);
      if (width === 480 && process.env.SMARTSTOCK_SCREENSHOT_DIR && ['Market', 'Discover', 'Research'].includes(section)) {
        if (section === 'Discover') {
          await page.locator('#runHunter').click();
          await page.locator('.hunter-row').first().waitFor();
        } else if (section === 'Research') {
          await page.locator('#ticker').fill('NVDA');
          await page.locator('#search').getByRole('button').click();
          await page.locator('.research-tabs').waitFor();
        }
        await capture(`${section.toLowerCase()}-480.png`);
      }
    }
  }
  await page.locator('[data-page="Market"]').click();
  dashboardFailure = true;
  await page.locator('#refreshDash').click();
  await page.getByText('Market source offline').waitFor();
  assert.deepEqual(exceptions, [], 'Unexpected browser JavaScript errors');
});
