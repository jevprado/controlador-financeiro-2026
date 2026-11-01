const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function client(fetch) {
  const context = vm.createContext({ fetch });
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../static/api.js'), 'utf8'), context);
  return context.api;
}

test('platform error text becomes a readable HTTP error', async () => {
  const api = client(async () => new Response('A server error has occurred', { status: 500 }));
  await assert.rejects(api('/api/register'), /indisponível \(HTTP 500\)/);
});

test('HTML and malformed success responses do not leak parse errors', async () => {
  for (const body of ['<html>Error</html>', '', 'null', '[]', '"unexpected"']) {
    const api = client(async () => new Response(body));
    await assert.rejects(api('/api/register'), /resposta inválida/);
  }
});

test('API permission errors retain their message', async () => {
  const api = client(async () => Response.json({ error: 'Cadastro restrito.' }, { status: 403 }));
  await assert.rejects(api('/api/register'), /Cadastro restrito\./);
});

test('registration sends credentials and returns the user', async () => {
  const api = client(async (url, options) => {
    assert.equal(url, '/api/register');
    assert.equal(options.method, 'POST');
    assert.equal(options.credentials, 'same-origin');
    assert.equal(options.headers['Content-Type'], 'application/json');
    assert.equal(JSON.parse(options.body).invite_code, 'private-invite');
    return Response.json({ user: { id: 1 } }, { status: 201 });
  });
  const result = await api('/api/register', { method: 'POST', body: JSON.stringify({ invite_code: 'private-invite' }) });
  assert.equal(result.user.id, 1);
});

test('network failures keep a readable message', async () => {
  const api = client(async () => { throw new TypeError('fetch failed'); });
  await assert.rejects(api('/api/register'), /Não foi possível conectar/);
});
