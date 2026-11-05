const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../static/theme.js'), 'utf8');

function page({ stored = null, systemDark = false, storageFails = false } = {}) {
  const storage = new Map(stored ? [['odarp-theme', stored]] : []);
  const listeners = {};
  const mediaListeners = [];
  const media = { matches: systemDark, addEventListener: (_, fn) => mediaListeners.push(fn) };
  const icon = { textContent: '☾' };
  const button = {
    attributes: {}, title: '', clicks: [],
    setAttribute(name, value) { this.attributes[name] = value; },
    querySelector: () => icon,
    addEventListener(_, fn) { this.clicks.push(fn); },
  };
  const meta = { attributes: {}, setAttribute(name, value) { this.attributes[name] = value; } };
  const root = { dataset: {} };
  const localStorage = {
    getItem(key) { if (storageFails) throw new Error('blocked'); return storage.has(key) ? storage.get(key) : null; },
    setItem(key, value) { if (storageFails) throw new Error('blocked'); storage.set(key, value); },
  };
  const context = vm.createContext({
    window: { matchMedia: () => media },
    localStorage,
    document: {
      documentElement: root,
      querySelector: () => meta,
      querySelectorAll: () => [button],
      addEventListener: (name, fn) => { listeners[name] = fn; },
    },
  });
  vm.runInContext(source, context);
  listeners.DOMContentLoaded();
  return {
    root, meta, button, icon, storage,
    click: () => button.clicks.forEach((fn) => fn()),
    systemChange(dark) { media.matches = dark; mediaListeners.forEach((fn) => fn()); },
  };
}

test('segue o tema do sistema quando não há escolha salva', () => {
  assert.equal(page({ systemDark: true }).root.dataset.theme, 'dark');
  const light = page({ systemDark: false });
  assert.equal(light.root.dataset.theme, 'light');
  assert.equal(light.button.attributes['aria-pressed'], 'false');
  assert.equal(light.meta.attributes.content, '#f7f8f5');
});

test('a escolha salva tem prioridade sobre o sistema', () => {
  const view = page({ stored: 'light', systemDark: true });
  assert.equal(view.root.dataset.theme, 'light');
  view.systemChange(true);
  assert.equal(view.root.dataset.theme, 'light');
});

test('alternar troca o tema, salva a escolha e atualiza o botão', () => {
  const view = page();
  view.click();
  assert.equal(view.root.dataset.theme, 'dark');
  assert.equal(view.storage.get('odarp-theme'), 'dark');
  assert.equal(view.button.attributes['aria-pressed'], 'true');
  assert.equal(view.icon.textContent, '☀');
  assert.equal(view.meta.attributes.content, '#111814');
  view.click();
  assert.equal(view.root.dataset.theme, 'light');
  assert.equal(view.storage.get('odarp-theme'), 'light');
});

test('acompanha mudanças do sistema até o usuário escolher', () => {
  const view = page();
  view.systemChange(true);
  assert.equal(view.root.dataset.theme, 'dark');
});

test('funciona sem acesso ao armazenamento local', () => {
  const view = page({ storageFails: true, systemDark: true });
  assert.equal(view.root.dataset.theme, 'dark');
  view.click();
  assert.equal(view.root.dataset.theme, 'light');
});
