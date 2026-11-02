const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function dashboard() {
  const elements = new Map();
  function element(tag) {
    const classes = new Set();
    return {
      tag, children: [], attributes: {}, style: {}, textContent: '', value: '',
      validity: { valid: true },
      classList: {
        add(name) { classes.add(name); },
        remove(name) { classes.delete(name); },
        contains(name) { return classes.has(name); },
        toggle(name, enabled) { if (enabled) classes.add(name); else classes.delete(name); },
      },
      setAttribute(name, value) { this.attributes[name] = value; },
      append(...children) { this.children.push(...children); },
      replaceChildren() { this.children = []; },
    };
  }
  const select = (selector) => {
    if (!elements.has(selector)) elements.set(selector, element('div'));
    return elements.get(selector);
  };
  const context = vm.createContext({
    document: { querySelector: select, createElement: element, createElementNS: (_, tag) => element(tag) },
  });
  const source = fs.readFileSync(path.join(__dirname, '../static/app.js'), 'utf8');
  vm.runInContext(source.slice(0, source.indexOf('let mode')), context);
  vm.runInContext('let monthlyTotals = [];', context);
  for (const name of ['shiftMonth', 'defaultComparisonPeriod', 'makeElement', 'renderComparison', 'renderTrendChart']) {
    const definition = source.match(new RegExp(`^function ${name}\\([\\s\\S]*?^}`, 'm'));
    assert.ok(definition, `Missing function ${name}`);
    vm.runInContext(definition[0], context);
  }
  return {
    select,
    evaluate: (code) => vm.runInContext(code, context),
    render(start, end, totals = []) {
      select('#comparison-base').value = start;
      select('#comparison-target').value = end;
      vm.runInContext(`monthlyTotals = ${JSON.stringify(totals)}; renderComparison();`, context);
    },
  };
}

test('default period follows the access year and month, including January and a new year', () => {
  const app = dashboard();
  for (const [year, month, expected] of [[2026, 10, '2026-11'], [2026, 0, '2026-01'], [2027, 2, '2027-03']]) {
    const period = app.evaluate(`defaultComparisonPeriod(new Date(${year}, ${month}, 2))`);
    assert.equal(period.start, `${year}-01`);
    assert.equal(period.end, expected);
  }
});

test('line chart includes every month from January through November and fills gaps with zero', () => {
  const app = dashboard();
  app.render('2026-01', '2026-11', [
    { month: '2026-01', total_cents: 10000, expense_count: 1 },
    { month: '2026-11', total_cents: 20000, expense_count: 2 },
    { month: '2026-12', total_cents: 90000, expense_count: 1 },
  ]);
  const svg = app.select('#comparison-chart').children[0];
  assert.equal(svg.tag, 'svg');
  assert.equal(svg.children.filter((node) => node.tag === 'circle').length, 11);
  assert.equal(svg.children.find((node) => node.tag === 'polyline').attributes.points.split(' ').length, 11);
  const rows = app.select('#comparison-months').children;
  assert.equal(rows.length, 11);
  assert.match(rows[0].children[0].textContent, /janeiro/);
  assert.match(rows[10].children[0].textContent, /novembro/);
  assert.equal(rows[1].children[2].children[1].textContent, 'Sem lançamentos');
  assert.equal(rows[1].children[1].children[0].style.width, '0%');
  assert.equal(rows[10].children[1].children[0].style.width, '100%');
  assert.match(app.select('#comparison-percentage').textContent, /Aumento de 100%/);
});

test('single month, empty period and a range across years render finite points', () => {
  const app = dashboard();
  for (const [start, end, count] of [['2026-01', '2026-01', 1], ['2025-11', '2026-02', 4]]) {
    app.render(start, end);
    const svg = app.select('#comparison-chart').children[0];
    const points = svg.children.find((node) => node.tag === 'polyline').attributes.points;
    assert.equal(points.split(' ').length, count);
    assert.doesNotMatch(points, /NaN|Infinity/);
    assert.equal(app.select('#comparison-months').children.length, count);
  }
});

test('bars use the same monthly totals as the line and scale against the highest total', () => {
  const app = dashboard();
  app.render('2026-01', '2026-04', [10000, 12500, 6250, 6250].map((total_cents, i) => ({
    month: `2026-0${i + 1}`, total_cents, expense_count: 1,
  })));
  const rows = app.select('#comparison-months').children;
  const widths = rows.map((row) => row.children[1].children[0].style.width);
  assert.deepEqual(widths, ['80%', '100%', '50%', '50%']);
  assert.match(rows[0].children[2].children[0].textContent, /100,00/);
  assert.match(rows[1].children[2].children[0].textContent, /125,00/);
  assert.equal(rows[0].attributes.role, 'listitem');
});

test('inverted and missing ranges hide the chart and explain how to correct the range', () => {
  const app = dashboard();
  app.render('2026-11', '2026-01');
  assert.ok(app.select('#comparison-results').classList.contains('hidden'));
  assert.match(app.select('#comparison-status').textContent, /inicial deve ser anterior/);
  app.render('', '2026-11');
  assert.ok(app.select('#comparison-results').classList.contains('hidden'));
  assert.match(app.select('#comparison-status').textContent, /meses válidos/);
});
