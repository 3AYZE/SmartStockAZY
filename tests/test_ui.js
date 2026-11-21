// Deterministic UI request-ordering tests. Node built-ins only; no browser or network.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');

function setup() {
  const elements = new Map();
  function element(selector) {
    if (!elements.has(selector)) {
      elements.set(selector, {
        innerHTML: '', textContent: '', value: '', disabled: false,
        classList: {add() {}, remove() {}},
        querySelector: () => null, querySelectorAll: () => [],
      });
    }
    return elements.get(selector);
  }
  const context = vm.createContext({
    document: {querySelector: element, querySelectorAll: () => []},
    window: {scrollY: 0},
    console, setTimeout,
    pending: new Map(),
  });
  const source = fs.readFileSync(path.join(__dirname, '..', 'app.js'), 'utf8');
  const boot = source.lastIndexOf('\nshell();');
  assert(boot > 0);
  vm.runInContext(source.slice(0, boot), context);
  vm.runInContext('api = path => new Promise(resolve => pending.set(path, resolve))', context);
  return {context, element};
}

const settle = () => new Promise(resolve => setImmediate(resolve));

test('market response cannot overwrite a later page', async () => {
  const {context, element} = setup();
  vm.runInContext('renderGeneration=1;Market()', context);
  assert(context.pending.has('/api/dashboard'));
  vm.runInContext('renderGeneration=2;News()', context);
  assert.match(element('#view').innerHTML, /News Search/);
  context.pending.get('/api/dashboard')({});
  await settle();
  assert.match(element('#view').innerHTML, /News Search/);
});

test('newest news search wins when answers arrive out of order', async () => {
  const {context, element} = setup();
  vm.runInContext('renderGeneration=1;News()', context);
  const submit = element('#newsSearch').onsubmit;
  element('#newsQuery').value = 'OLD';
  submit({preventDefault() {}});
  element('#newsQuery').value = 'NEW';
  submit({preventDefault() {}});
  assert(context.pending.has('/api/news-search/OLD'));
  assert(context.pending.has('/api/news-search/NEW'));
  const response = query => ({items: [], resolved_query: query, risk: {score: 0, events: [], confirmed_event_count: 0, event_count: 0}});
  context.pending.get('/api/news-search/NEW')(response('NEW'));
  await settle();
  assert.match(element('#newsOut').innerHTML, /NEW/);
  const latest = element('#newsOut').innerHTML;
  context.pending.get('/api/news-search/OLD')(response('OLD'));
  await settle();
  assert.equal(element('#newsOut').innerHTML, latest);
});

test('risk and settings responses cannot mutate a newer page', async () => {
  const {context, element} = setup();
  vm.runInContext('renderGeneration=1;Risk()', context);
  const riskView = element('#out').innerHTML;
  vm.runInContext('renderGeneration=2;Settings()', context);
  vm.runInContext('renderGeneration=3;News()', context);
  context.pending.get('/api/risk')({positions: []});
  context.pending.get('/api/settings')({hunter_max_symbols: 36});
  await settle();
  assert.equal(element('#out').innerHTML, riskView);
  assert.match(element('#view').innerHTML, /News Search/);
});

test('chart range response is ignored after overlay re-render', async () => {
  const {context} = setup();
  let renders = 0;
  const range = {dataset: {range: '1mo'}};
  const overlay = {dataset: {overlay: 'sma20'}};
  const container = {
    isConnected: true,
    set innerHTML(html) {renders++; this.html=html},
    get innerHTML() {return this.html},
    querySelector() {return null},
    querySelectorAll(q) {return q === '.range-btn' ? [range] : q === '.overlay-btn' ? [overlay] : []},
    classList: {add() {}, remove() {}},
  };
  context.chartContainer = container;
  vm.runInContext("mountPriceHistory(chartContainer,'AAPL',[],'1y')", context);
  range.onclick();
  assert(context.pending.has('/api/chart/AAPL?range=1mo'));
  overlay.onclick();
  assert.equal(renders, 2);
  context.pending.get('/api/chart/AAPL?range=1mo')({history: []});
  await settle();
  assert.equal(renders, 2);
});

test('market partial feeds show a coverage warning', async () => {
  const {context, element} = setup();
  vm.runInContext('renderGeneration=1;Market()', context);
  context.pending.get('/api/dashboard')({
    indexes: [], sectors: [], news: [], regime: {label: 'UNKNOWN'},
    errors: [{ticker: 'SPY', error: 'stale'}], updated_at: '2026-11-21T10:00:00Z',
  });
  await settle();
  assert.match(element('#view').innerHTML, /Partial market data: 1/);
});

test('research hero identifies stale observed prices', () => {
  const {context} = setup();
  context.quote = {
    quote: {ticker: 'TEST', name: 'Fixture', price: 100, stale: true,
      updated_at: '2026-11-01T20:00:00Z'},
    exit_risk: {score: 40, label: 'WATCH'},
  };
  const html = vm.runInContext('stockHero(quote)', context);
  assert.match(html, /STALE PRICE/);
  assert.match(html, /2026/);
});

test('scanner displays unavailable candidates separately from returned candidates', async () => {
  const {context, element} = setup();
  vm.runInContext('renderGeneration=1;Hunter(true)', context);
  context.pending.get('/api/hunter')({
    scanned: 9, successful: 7, results: [], errors: [],
    regime: {label: 'UNKNOWN'}, updated_at: '2026-11-21T10:00:00Z', note: 'Fixture',
  });
  await settle();
  assert.match(element('#hunterStats').innerHTML, /Unavailable/);
  assert.match(element('#hunterStats').innerHTML, />2</);
});

test('risk monitor warns when some positions lack current valuations', async () => {
  const {context, element} = setup();
  vm.runInContext('renderGeneration=1;Risk()', context);
  context.pending.get('/api/risk')({
    positions: [{ticker: 'TEST', error: 'Quote stale', thesis: ''}],
    valuation_complete: false, unpriced_lots: 1, warnings: [],
  });
  await settle();
  assert.match(element('#out').innerHTML, /RISK SCAN INCOMPLETE/);
  assert.match(element('#out').innerHTML, /Quote stale/);
});

test('risk monitor reports unknown news evidence without presenting zero risk', async () => {
  const {context, element} = setup();
  vm.runInContext('renderGeneration=1;Risk()', context);
  context.pending.get('/api/risk')({
    positions: [{ticker: 'TEST', price: 100, news_risk: {available: false},
      scores: {}, exit_risk: {score: 10, label: 'NORMAL'}, thesis_health: {tracked: false}}],
    valuation_complete: true, warnings: [],
  });
  await settle();
  assert.match(element('#out').innerHTML, /News Risk/);
  assert.match(element('#out').innerHTML, /UNAVAILABLE/);
});
