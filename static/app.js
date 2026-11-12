const $ = (selector) => document.querySelector(selector);
const money = (cents) => new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' }).format(cents / 100);
const monthName = (value) => new Intl.DateTimeFormat('pt-BR', { month: 'long', year: 'numeric', timeZone: 'UTC' }).format(new Date(`${value}-01T12:00:00Z`));
const today = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };
let mode = 'login';
let currentUser = null;
let expenses = [];
let accountNames = [];
let activeAccountOption = -1;
let editingExpenseId = null;
let savingOrder = false;
let expenseFilter = 'all';
let expenseSearch = '';
let expenseSort = 'manual';
let expenseRequest = 0;
let comparisonRequest = 0;
let recurringRequest = 0;
let monthlyTotals = null;
let comparisonAccounts = [];
const orderStatus = makeElement('p', 'order-status');
orderStatus.setAttribute('role', 'status');
orderStatus.setAttribute('aria-live', 'polite');
$('.expense-table').before(orderStatus);

function showAuth() {
  expenseRequest++;
  comparisonRequest++;
  recurringRequest++;
  monthlyTotals = null;
  updateComparisonAccounts([]);
  currentUser = null;
  accountNames = [];
  $('#loading').classList.add('hidden');
  $('#dashboard').classList.add('hidden');
  $('#auth').classList.remove('hidden');
}

function showDashboard(user) {
  currentUser = user;
  $('#loading').classList.add('hidden');
  $('#auth').classList.add('hidden');
  $('#dashboard').classList.remove('hidden');
  const firstName = user.name.trim().split(/\s+/)[0];
  $('#greeting-name').textContent = firstName;
  $('#sidebar-name').textContent = user.name;
  $('#avatar').textContent = firstName[0].toUpperCase();
  showPage();
  loadExpenses();
}

function shiftMonth(value, offset) {
  const [year, month] = value.split('-').map(Number);
  const date = new Date(0);
  date.setUTCFullYear(year, month - 1 + offset, 1);
  return `${String(date.getUTCFullYear()).padStart(4, '0')}-${String(date.getUTCMonth() + 1).padStart(2, '0')}`;
}

function defaultComparisonPeriod(date = new Date()) {
  const year = String(date.getFullYear()).padStart(4, '0');
  return { start: `${year}-01`, end: `${year}-${String(date.getMonth() + 1).padStart(2, '0')}` };
}

function showPage() {
  const comparing = location.hash === '#comparador';
  const recurring = location.hash === '#recorrentes';
  $('#inicio').classList.toggle('hidden', comparing || recurring);
  $('#comparador').classList.toggle('hidden', !comparing);
  $('#recorrentes').classList.toggle('hidden', !recurring);
  const active = recurring ? '#recorrentes' : comparing ? '#comparador' : '#inicio';
  document.querySelectorAll('nav a').forEach((link) => {
    link.classList.toggle('nav-active', link.hash === active);
    if (link.hash === active) link.setAttribute('aria-current', 'page');
    else link.removeAttribute('aria-current');
  });
  if (comparing && currentUser) loadComparison();
  if (recurring && currentUser) loadRecurring();
}
window.addEventListener('hashchange', showPage);

// Menu hambúrguer (somente celular): abre a navegação como um painel abaixo da barra superior.
function setMobileMenu(open) {
  $('.topbar').classList.toggle('menu-open', open);
  $('#menu-toggle').setAttribute('aria-expanded', String(open));
  $('#menu-toggle').setAttribute('aria-label', open ? 'Fechar menu' : 'Abrir menu');
}
$('#menu-toggle').addEventListener('click', () => setMobileMenu($('#menu-toggle').getAttribute('aria-expanded') !== 'true'));
$('#mobile-nav').addEventListener('click', (event) => { if (event.target.closest('a, button')) setMobileMenu(false); });
document.addEventListener('click', (event) => { if (!event.target.closest('.topbar')) setMobileMenu(false); });
document.addEventListener('keydown', (event) => {
  if (event.key !== 'Escape' || $('#menu-toggle').getAttribute('aria-expanded') !== 'true') return;
  setMobileMenu(false);
  $('#menu-toggle').focus();
});

async function loadRecurring() {
  const request = ++recurringRequest;
  const userId = currentUser?.id;
  const list = $('#recurring-list');
  list.replaceChildren();
  $('#recurring-status').textContent = 'Carregando gastos recorrentes…';
  $('#recurring-retry').classList.add('hidden');
  try {
    const data = await api('/api/recurring-expenses');
    if (request !== recurringRequest || currentUser?.id !== userId) return;
    $('#recurring-status').textContent = data.recurring_expenses.length ? '' : 'Nenhum gasto recorrente cadastrado. Adicione despesas fixas, como plano de saúde, aluguel ou internet.';
    for (const item of data.recurring_expenses) {
      const row = makeElement('div', 'recurring-row');
      const details = makeElement('div', 'expense-details');
      details.append(makeElement('strong', '', item.description), makeElement('span', '', `${item.account} · ${item.kind}`), makeElement('span', '', `Todo dia ${Number(item.first_due_date.slice(8))} · desde ${monthName(item.first_due_date.slice(0, 7))}`));
      const value = makeElement('strong', 'recurring-value', `${money(item.amount_cents)} / mês`);
      const stop = makeElement('button', 'edit-button', 'Encerrar recorrência');
      stop.type = 'button';
      stop.setAttribute('aria-label', `Encerrar recorrência de ${item.description}`);
      stop.addEventListener('click', async () => {
        if (!confirm(`Encerrar a recorrência de "${item.description}"? Os lançamentos já gerados serão mantidos.`)) return;
        stop.disabled = true;
        try {
          await api(`/api/recurring-expenses/${item.id}`, { method: 'DELETE' });
          await loadRecurring();
        } catch (error) {
          alert(error.message);
          stop.disabled = false;
        }
      });
      row.append(makeExpenseIcon(item.kind), details, value, stop);
      list.append(row);
    }
  } catch (error) {
    if (request !== recurringRequest || currentUser?.id !== userId) return;
    if (error.message === 'Faça login para continuar.') showAuth();
    else {
      $('#recurring-status').textContent = error.message;
      $('#recurring-retry').classList.remove('hidden');
    }
  }
}
$('#recurring-retry').addEventListener('click', loadRecurring);
$('#new-recurring').addEventListener('click', () => openDialog(null, true));

function updateComparisonAccounts(accounts) {
  comparisonAccounts = accounts;
  const filter = $('#comparison-account');
  const previous = filter.value;
  const all = makeElement('option', '', 'Todas as contas e cartões');
  all.value = '';
  filter.replaceChildren(all);
  for (const item of accounts) {
    const option = makeElement('option', '', item.account);
    option.value = item.account;
    filter.append(option);
  }
  filter.value = accounts.some((item) => item.account === previous) ? previous : '';
}

function renderComparison() {
  if (!monthlyTotals) return;
  const base = $('#comparison-base').value;
  const target = $('#comparison-target').value;
  if (!base || !target || !$('#comparison-base').validity.valid || !$('#comparison-target').validity.valid) {
    $('#comparison-results').classList.add('hidden');
    $('#comparison-status').textContent = 'Selecione dois meses válidos para comparar.';
    return;
  }
  if (base > target) {
    $('#comparison-results').classList.add('hidden');
    $('#comparison-status').textContent = 'O mês inicial deve ser anterior ou igual ao mês final.';
    return;
  }
  const selectedAccount = comparisonAccounts.find((item) => item.account === $('#comparison-account').value);
  const totals = new Map((selectedAccount ? selectedAccount.months : monthlyTotals).map((item) => [item.month, item]));
  const entry = (month) => totals.get(month) || { total_cents: 0, expense_count: 0 };
  for (const [key, month] of [['base', base], ['target', target]]) {
    const item = entry(month);
    $(`#comparison-${key}-label`).textContent = monthName(month);
    $(`#comparison-${key}-total`).textContent = money(item.total_cents);
    $(`#comparison-${key}-count`).textContent = item.expense_count ? `${item.expense_count} ${item.expense_count === 1 ? 'lançamento' : 'lançamentos'}` : 'Sem lançamentos';
  }
  const initial = entry(base).total_cents;
  const difference = entry(target).total_cents - initial;
  const direction = difference > 0 ? 'Aumento' : difference < 0 ? 'Redução' : 'Sem variação';
  const result = $('#comparison-difference');
  result.textContent = `${difference > 0 ? '+' : difference < 0 ? '−' : ''}${money(Math.abs(difference))}`;
  result.classList.toggle('spending-increase', difference > 0);
  result.classList.toggle('spending-decrease', difference < 0);
  $('#comparison-percentage').textContent = initial === 0 && difference !== 0
    ? 'Aumento · percentual indisponível: referência com total zero.'
    : `${direction}${initial ? ` de ${new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 2 }).format(Math.abs(difference / initial * 100))}%` : ' (0%)'} em relação à referência.`;
  const [startYear, startMonth] = base.split('-').map(Number);
  const [endYear, endMonth] = target.split('-').map(Number);
  const count = (endYear - startYear) * 12 + endMonth - startMonth + 1;
  const months = Array.from({ length: count }, (_, index) => shiftMonth(base, index));
  renderTrendChart(months.map((month) => ({ month, ...entry(month) })));
  $('#comparison-period').textContent = `De ${monthName(base)} a ${monthName(target)} · ${selectedAccount ? selectedAccount.account : 'Todas as contas e cartões'} · totais de despesas por mês.`;
  $('#comparison-status').textContent = '';
  $('#comparison-results').classList.remove('hidden');
}

function renderTrendChart(series) {
  const chart = $('#comparison-chart');
  chart.replaceChildren();
  const width = Math.max(660, series.length * 85 + 115);
  const height = 320;
  const left = 110;
  const right = width - 35;
  const top = 30;
  const bottom = height - 55;
  const maximum = Math.max(...series.map((item) => item.total_cents), 100);
  const svgElement = (tag, attributes, content) => {
    const node = document.createElementNS('http://www.w3.org/2000/svg', tag);
    for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, value);
    if (content !== undefined) node.textContent = content;
    return node;
  };
  const svg = svgElement('svg', { viewBox: `0 0 ${width} ${height}`, role: 'img', 'aria-label': 'Gráfico de linha da evolução mensal das despesas. Totais por mês no gráfico de barras abaixo.' });
  svg.style.minWidth = `${width}px`;
  for (let step = 0; step <= 4; step++) {
    const y = bottom - step / 4 * (bottom - top);
    svg.append(svgElement('line', { x1: left, x2: right, y1: y, y2: y, class: 'trend-grid' }));
    svg.append(svgElement('text', { x: left - 12, y: y + 4, 'text-anchor': 'end', class: 'trend-label' }, money(Math.round(maximum * step / 4))));
  }
  const points = series.map((item, index) => ({
    x: series.length === 1 ? (left + right) / 2 : left + index / (series.length - 1) * (right - left),
    y: bottom - item.total_cents / maximum * (bottom - top),
  }));
  svg.append(svgElement('polyline', { points: points.map(({ x, y }) => `${x},${y}`).join(' '), class: 'trend-line' }));
  const rows = $('#comparison-months');
  rows.replaceChildren();
  series.forEach((item, index) => {
    const { x, y } = points[index];
    const point = svgElement('circle', { cx: x, cy: y, r: 5, class: 'trend-point', tabindex: '0', 'aria-label': `${monthName(item.month)}: ${money(item.total_cents)}${item.expense_count ? '' : ', sem lançamentos'}` });
    point.append(svgElement('title', {}, `${monthName(item.month)}: ${money(item.total_cents)}`));
    svg.append(point);
    const label = new Intl.DateTimeFormat('pt-BR', { month: 'short', year: '2-digit', timeZone: 'UTC' }).format(new Date(`${item.month}-01T12:00:00Z`));
    svg.append(svgElement('text', { x, y: bottom + 30, 'text-anchor': 'middle', class: 'trend-label' }, label));
    const row = makeElement('div', 'comparison-chart-row');
    row.setAttribute('role', 'listitem');
    const heading = makeElement('span', 'comparison-chart-label', monthName(item.month));
    const track = makeElement('div', 'comparison-track');
    track.setAttribute('aria-hidden', 'true');
    const bar = makeElement('div', 'comparison-bar');
    bar.style.width = `${item.total_cents / maximum * 100}%`;
    track.append(bar);
    const value = makeElement('div', 'comparison-chart-value');
    value.append(makeElement('strong', '', money(item.total_cents)));
    if (!item.expense_count) value.append(makeElement('small', '', 'Sem lançamentos'));
    row.append(heading, track, value);
    rows.append(row);
  });
  chart.append(svg);
}

async function loadComparison() {
  const request = ++comparisonRequest;
  const userId = currentUser?.id;
  monthlyTotals = null;
  $('#comparison-results').classList.add('hidden');
  $('#comparison-retry').classList.add('hidden');
  $('#comparison-status').textContent = 'Carregando totais mensais…';
  try {
    const data = await api('/api/expenses/monthly-totals');
    if (request !== comparisonRequest || currentUser?.id !== userId) return;
    if (!Array.isArray(data.accounts)) {
      throw new Error('O servidor precisa ser atualizado para carregar o filtro de contas e cartões. Reinicie o servidor local ou publique a versão atualizada.');
    }
    monthlyTotals = data.months;
    updateComparisonAccounts(data.accounts);
    renderComparison();
  } catch (error) {
    if (request !== comparisonRequest || currentUser?.id !== userId) return;
    if (error.message === 'Faça login para continuar.') showAuth();
    else {
      $('#comparison-status').textContent = error.message;
      $('#comparison-retry').classList.remove('hidden');
    }
  }
}
$('#comparison-base').addEventListener('change', renderComparison);
$('#comparison-target').addEventListener('change', renderComparison);
$('#comparison-account').addEventListener('change', renderComparison);
$('#comparison-retry').addEventListener('click', loadComparison);

function setMode(next) {
  mode = next;
  const register = mode === 'register';
  $('#name-field').classList.toggle('hidden', !register);
  $('#name').required = register;
  $('#invite-field').classList.toggle('hidden', !register);
  $('#invite-code').required = register;
  $('#invite-code').disabled = !register;
  $('#invite-code').value = '';
  $('#password').autocomplete = register ? 'new-password' : 'current-password';
  $('#password-hint').classList.toggle('hidden', !register);
  $('#auth-title').innerHTML = register ? 'Comece com clareza<span>.</span>' : 'Bem-vindo de volta<span>.</span>';
  $('#auth-subtitle').textContent = register ? 'Use seu e-mail autorizado e o código de convite para criar sua conta.' : 'Entre na sua conta para continuar de onde parou.';
  $('#auth-submit').innerHTML = register ? 'Criar minha conta <span>→</span>' : 'Entrar na minha conta <span>→</span>';
  $('#switch-prompt').textContent = register ? 'Já tem uma conta?' : 'Ainda não tem uma conta?';
  $('#switch-mode').textContent = register ? 'Entrar' : 'Criar conta';
  $('#auth-error').textContent = '';
}

$('#switch-mode').addEventListener('click', () => setMode(mode === 'login' ? 'register' : 'login'));
$('#toggle-password').addEventListener('click', () => {
  const input = $('#password');
  input.type = input.type === 'password' ? 'text' : 'password';
  $('#toggle-password').textContent = input.type === 'password' ? 'Mostrar' : 'Ocultar';
  $('#toggle-password').setAttribute('aria-label', input.type === 'password' ? 'Mostrar senha' : 'Ocultar senha');
});

$('#auth-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const email = $('#email').value.trim();
  const password = $('#password').value;
  const name = $('#name').value.trim();
  const inviteCode = $('#invite-code').value;
  if ((mode === 'register' && (name.length < 2 || !inviteCode)) || !$('#email').validity.valid || password.length < (mode === 'register' ? 8 : 1)) {
    $('#auth-error').textContent = mode === 'register' ? 'Informe nome, e-mail válido, senha com pelo menos 8 caracteres e código de convite.' : 'Informe seu e-mail e senha.';
    return;
  }
  const button = $('#auth-submit');
  button.disabled = true;
  $('#auth-error').textContent = '';
  try {
    const body = { name, email, password };
    if (mode === 'register') body.invite_code = inviteCode;
    const data = await api(mode === 'register' ? '/api/register' : '/api/login', { method: 'POST', body: JSON.stringify(body) });
    $('#auth-form').reset();
    showDashboard(data.user);
  } catch (error) {
    $('#auth-error').textContent = error.message;
  } finally {
    button.disabled = false;
  }
});

async function logout() {
  try { await api('/api/logout', { method: 'POST', body: '{}' }); }
  catch (error) { alert(error.message); return; }
  showAuth();
  setMode('login');
}
$('#logout').addEventListener('click', logout);
$('#mobile-logout').addEventListener('click', logout);

function makeElement(tag, className, content) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (content !== undefined) element.textContent = content;
  return element;
}

function makeExpenseIcon(kind) {
  const paths = {
    'Cartão de crédito': 'M4 4h16a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2Z M2 9h20 M6 15h3 M13 15h2',
    'Cheque especial': 'M13 4H4a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-7 M6 9h3 M6 15h5 M15 15l2-5 4-4a1.4 1.4 0 0 0-2-2l-4 4-2 5Z',
    'Empréstimo': 'M3 9h18L12 3 3 9Z M5 9v9 M10 9v9 M14 9v9 M19 9v9 M3 18h18 M2 21h20',
    'Outros': 'M5 3l2 2 2-2 3 2 3-2 2 2 2-2v18l-2-2-2 2-3-2-3 2-2-2-2 2V3Z M9 9h6 M9 13h6 M9 17h3',
  };
  const icon = makeElement('div', 'expense-icon');
  icon.title = kind;
  icon.setAttribute('aria-hidden', 'true');
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('fill', 'none');
  svg.setAttribute('stroke', 'currentColor');
  svg.setAttribute('stroke-width', '1.7');
  svg.setAttribute('stroke-linecap', 'round');
  svg.setAttribute('stroke-linejoin', 'round');
  svg.setAttribute('focusable', 'false');
  const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  path.setAttribute('d', paths[kind] || paths.Outros);
  svg.append(path);
  icon.append(svg);
  return icon;
}

const plural = (count, one, many) => `${count} ${count === 1 ? one : many}`;
const normalizeText = (text) => text.normalize('NFD').replace(/[̀-ͯ]/g, '').toLocaleLowerCase('pt-BR');

function renderSummary() {
  const total = expenses.reduce((sum, item) => sum + item.amount_cents, 0);
  const cards = expenses.filter((item) => item.kind === 'Cartão de crédito');
  const cardsTotal = cards.reduce((sum, item) => sum + item.amount_cents, 0);
  const pending = expenses.filter((item) => !item.is_paid);
  const pendingTotal = pending.reduce((sum, item) => sum + item.amount_cents, 0);
  $('#total-amount').textContent = money(total);
  $('#cards-amount').textContent = money(cardsTotal);
  $('#pending-amount').textContent = money(pendingTotal);
  $('#total-count').textContent = expenses.length ? `${plural(expenses.length, 'compromisso', 'compromissos')} neste mês` : 'Nenhum compromisso neste mês';
  $('#cards-count').textContent = plural(cards.length, 'lançamento', 'lançamentos');
  $('#pending-count').textContent = pending.length ? plural(pending.length, 'pagamento pendente', 'pagamentos pendentes') : 'Nenhum pagamento pendente';
  $('#filter-count-all').textContent = expenses.length;
  $('#filter-count-pending').textContent = pending.length;
  $('#filter-count-paid').textContent = expenses.length - pending.length;
}

function visibleExpenses() {
  const query = normalizeText(expenseSearch.trim());
  const items = expenses.filter((item) => (expenseFilter === 'all' || (expenseFilter === 'paid') === item.is_paid)
    && (!query || normalizeText(`${item.account} ${item.description} ${item.kind}`).includes(query)));
  if (expenseSort === 'due') items.sort((a, b) => a.due_date.localeCompare(b.due_date));
  else if (expenseSort === 'amount') items.sort((a, b) => b.amount_cents - a.amount_cents);
  return items;
}

function closeRowMenus() {
  document.querySelectorAll('.row-menu-list:not(.hidden)').forEach((list) => {
    list.classList.add('hidden');
    list.previousElementSibling.setAttribute('aria-expanded', 'false');
  });
}
document.addEventListener('click', (event) => { if (!event.target.closest('.row-menu')) closeRowMenus(); });
document.addEventListener('keydown', (event) => {
  if (event.key !== 'Escape') return;
  const open = document.querySelector('.row-menu-list:not(.hidden)');
  if (!open) return;
  closeRowMenus();
  open.previousElementSibling.focus();
});

function makeRowMenu(item) {
  const menu = makeElement('div', 'row-menu');
  const more = makeElement('button', 'row-menu-button', '⋯');
  more.type = 'button';
  more.title = 'Mais ações';
  more.setAttribute('aria-label', `Mais ações de ${item.account} · ${item.description}`);
  more.setAttribute('aria-haspopup', 'menu');
  more.setAttribute('aria-expanded', 'false');
  const options = makeElement('div', 'row-menu-list hidden');
  options.setAttribute('role', 'menu');
  const edit = makeElement('button', '', 'Editar lançamento');
  const remove = makeElement('button', 'danger', 'Excluir lançamento');
  for (const option of [edit, remove]) {
    option.type = 'button';
    option.setAttribute('role', 'menuitem');
  }
  edit.addEventListener('click', () => { closeRowMenus(); openDialog(item); });
  remove.addEventListener('click', async () => {
    closeRowMenus();
    if (!confirm(`Excluir "${item.description}"?`)) return;
    try { await api(`/api/expenses/${item.id}`, { method: 'DELETE' }); await loadExpenses(); }
    catch (error) { alert(error.message); }
  });
  more.addEventListener('click', () => {
    const opening = options.classList.contains('hidden');
    closeRowMenus();
    if (!opening) return;
    menu.classList.toggle('menu-up', more.getBoundingClientRect().bottom + 120 > window.innerHeight);
    options.classList.remove('hidden');
    more.setAttribute('aria-expanded', 'true');
    edit.focus();
  });
  options.addEventListener('keydown', (event) => {
    if (!['ArrowDown', 'ArrowUp'].includes(event.key)) return;
    event.preventDefault();
    (document.activeElement === edit ? remove : edit).focus();
  });
  options.append(edit, remove);
  menu.append(more, options);
  return menu;
}

function renderExpenses() {
  renderSummary();
  const label = monthName($('#month').value);
  $('#month-label').textContent = label[0].toUpperCase() + label.slice(1);
  const list = $('#expense-list');
  const items = visibleExpenses();
  list.replaceChildren();
  $('#expense-head').classList.toggle('hidden', !items.length);
  $('#expense-footer').classList.toggle('hidden', !items.length);
  if (!items.length) {
    const empty = makeElement('div', 'empty-state');
    if (expenses.length) {
      empty.append(makeElement('h3', '', 'Nenhum lançamento encontrado'), makeElement('p', '', 'Ajuste o filtro ou a busca para ver outros lançamentos deste mês.'));
    } else {
      empty.append(makeElement('div', 'empty-icon', '✳'), makeElement('h3', '', 'Tudo em ordem por aqui'), makeElement('p', '', 'Adicione seu primeiro lançamento para começar a acompanhar este mês.'));
      const button = makeElement('button', 'secondary-button', '+ Adicionar lançamento');
      button.type = 'button';
      button.addEventListener('click', () => openDialog());
      empty.append(button);
    }
    list.append(empty);
    return;
  }
  const filtered = items.length !== expenses.length;
  const manualOrder = expenseSort === 'manual' && !filtered;
  for (const item of items) {
    const row = makeElement('div', 'expense-row');
    row.dataset.id = item.id;
    const handle = makeElement('button', 'drag-handle', '⠿');
    handle.type = 'button';
    handle.setAttribute('aria-label', `Mover ${item.account}. Use as setas para cima ou para baixo para reordenar.`);
    handle.title = manualOrder ? 'Arraste para reordenar ou use as setas ↑ e ↓' : 'Para reordenar, mostre todos os lançamentos em ordem manual';
    handle.disabled = !manualOrder || expenses.length < 2;
    enableExpenseDrag(handle, row);
    const icon = makeExpenseIcon(item.kind);
    const details = makeElement('div', 'expense-details');
    details.append(makeElement('strong', '', item.account), makeElement('span', '', `${item.kind} · ${item.description}`));
    const formattedDate = new Intl.DateTimeFormat('pt-BR', { day: '2-digit', month: 'short', timeZone: 'UTC' }).format(new Date(`${item.due_date}T12:00:00Z`));
    const due = makeElement('span', 'expense-due', formattedDate);
    const value = makeElement('strong', 'expense-value', money(item.amount_cents));
    const payment = makeElement('label', 'payment-toggle');
    const paid = makeElement('input');
    paid.type = 'checkbox';
    paid.setAttribute('role', 'switch');
    paid.checked = item.is_paid;
    paid.setAttribute('aria-label', `Pago: ${item.account} · ${item.description}`);
    payment.classList.toggle('is-paid', item.is_paid);
    payment.append(paid, makeElement('span', 'toggle-track'), makeElement('span', 'toggle-label', item.is_paid ? 'Pago' : 'Pendente'));
    paid.addEventListener('change', async () => {
      const isPaid = paid.checked;
      paid.disabled = true;
      try {
        const data = await api(`/api/expenses/${item.id}/payment`, {
          method: 'PUT', body: JSON.stringify({ is_paid: isPaid }),
        });
        item.is_paid = data.is_paid;
        renderExpenses();
        $(`.expense-row[data-id="${item.id}"] .payment-toggle input`)?.focus({ preventScroll: true });
      } catch (error) {
        paid.checked = item.is_paid;
        paid.disabled = false;
        alert(error.message);
      }
    });
    row.append(handle, icon, details, due, value, payment, makeRowMenu(item));
    list.append(row);
  }
  const paidCount = items.filter((item) => item.is_paid).length;
  $('#footer-count').textContent = filtered
    ? `${items.length} de ${plural(expenses.length, 'lançamento', 'lançamentos')}`
    : `${plural(items.length, 'lançamento', 'lançamentos')} neste mês`;
  $('#footer-total').textContent = money(items.reduce((sum, item) => sum + item.amount_cents, 0));
  $('#footer-status').textContent = paidCount === items.length ? (items.length === 1 ? 'Pago' : 'Todos pagos') : `${paidCount} de ${plural(items.length, 'pago', 'pagos')}`;
  $('#footer-status').classList.toggle('is-paid', paidCount === items.length);
}

$('#expense-filters').addEventListener('click', (event) => {
  const button = event.target.closest('button[data-filter]');
  if (!button) return;
  expenseFilter = button.dataset.filter;
  for (const item of $('#expense-filters').children) item.setAttribute('aria-pressed', String(item === button));
  renderExpenses();
});
$('#expense-search').addEventListener('input', (event) => { expenseSearch = event.target.value; renderExpenses(); });
$('#expense-sort').addEventListener('change', (event) => { expenseSort = event.target.value; renderExpenses(); });

async function saveExpenseOrder(focusId) {
  const ids = [...$('#expense-list').children].map((row) => Number(row.dataset.id));
  if (ids.every((id, index) => id === expenses[index].id)) return;
  savingOrder = true;
  $('#expense-list').inert = true;
  $('#month').disabled = true;
  $('#new-expense').disabled = true;
  orderStatus.textContent = 'Salvando ordem…';
  try {
    await api('/api/expenses/order', { method: 'PUT', body: JSON.stringify({ month: $('#month').value, ids }) });
    const byId = new Map(expenses.map((item) => [item.id, item]));
    expenses = ids.map((id) => byId.get(id));
    orderStatus.textContent = 'Ordem salva.';
  } catch (error) {
    await loadExpenses();
    orderStatus.textContent = `Não foi possível salvar a ordem. ${error.message}`;
  } finally {
    savingOrder = false;
    $('#expense-list').inert = false;
    $('#month').disabled = false;
    $('#new-expense').disabled = false;
    $(`.expense-row[data-id="${focusId}"] .drag-handle`)?.focus({ preventScroll: true });
  }
}

function enableExpenseDrag(handle, row) {
  const list = $('#expense-list');
  let pointerId = null;
  let startY = 0;
  let dragging = false;
  handle.addEventListener('pointerdown', (event) => {
    if (savingOrder || !event.isPrimary || event.button !== 0 || handle.disabled) return;
    pointerId = event.pointerId;
    startY = event.clientY;
    list.addEventListener('pointermove', move);
    list.addEventListener('pointerup', finish);
    list.addEventListener('pointercancel', finish);
    list.addEventListener('lostpointercapture', finish);
    list.setPointerCapture(pointerId);
  });
  const move = (event) => {
    if (pointerId !== event.pointerId) return;
    if (!dragging && Math.abs(event.clientY - startY) < 5) return;
    dragging = true;
    row.classList.add('dragging');
    const otherRows = [...$('#expense-list').children].filter((item) => item !== row);
    const before = otherRows.find((item) => {
      const rect = item.getBoundingClientRect();
      return event.clientY < rect.top + rect.height / 2;
    });
    $('#expense-list').insertBefore(row, before || null);
    if (event.clientY < 70) window.scrollBy(0, -18);
    else if (event.clientY > window.innerHeight - 70) window.scrollBy(0, 18);
  };
  const finish = (event) => {
    if (pointerId !== event.pointerId) return;
    const moved = dragging;
    pointerId = null;
    dragging = false;
    row.classList.remove('dragging');
    list.removeEventListener('pointermove', move);
    list.removeEventListener('pointerup', finish);
    list.removeEventListener('pointercancel', finish);
    list.removeEventListener('lostpointercapture', finish);
    if (list.hasPointerCapture(event.pointerId)) list.releasePointerCapture(event.pointerId);
    if (event.type !== 'pointerup') {
      if (moved) renderExpenses();
      return;
    }
    if (moved) saveExpenseOrder(row.dataset.id);
  };
  handle.addEventListener('keydown', (event) => {
    if (savingOrder || !['ArrowUp', 'ArrowDown'].includes(event.key)) return;
    event.preventDefault();
    if (event.key === 'ArrowUp' && row.previousElementSibling) row.previousElementSibling.before(row);
    else if (event.key === 'ArrowDown' && row.nextElementSibling) row.nextElementSibling.after(row);
    else return;
    saveExpenseOrder(row.dataset.id);
  });
}

async function loadExpenses() {
  const request = ++expenseRequest;
  const month = $('#month').value;
  orderStatus.textContent = '';
  try {
    const data = await api(`/api/expenses?month=${encodeURIComponent(month)}`);
    if (request !== expenseRequest) return;
    expenses = data.expenses;
    renderExpenses();
  } catch (error) {
    if (error.message === 'Faça login para continuar.') showAuth();
    else $('#expense-list').textContent = error.message;
  }
}
$('#month').addEventListener('change', loadExpenses);
$('.month-picker').addEventListener('click', (event) => {
  const monthInput = $('#month');
  if (monthInput.disabled || typeof monthInput.showPicker !== 'function') return;
  event.preventDefault();
  monthInput.focus();
  try { monthInput.showPicker(); } catch { /* o campo continua editável pelo teclado */ }
});
// Navegadores sem seletor de mês nativo mostram o campo de texto no lugar do rótulo.
if ($('#month').type !== 'month') $('.month-picker').classList.add('month-picker-fallback');

function closeAccountOptions() {
  $('#account-options').classList.add('hidden');
  $('#account').setAttribute('aria-expanded', 'false');
  $('#account').removeAttribute('aria-activedescendant');
  activeAccountOption = -1;
}

function setActiveAccountOption(index) {
  const options = [...$('#account-options').children];
  activeAccountOption = index;
  options.forEach((option, position) => option.setAttribute('aria-selected', String(position === index)));
  if (index >= 0) {
    $('#account').setAttribute('aria-activedescendant', options[index].id);
    options[index].scrollIntoView({ block: 'nearest' });
  } else {
    $('#account').removeAttribute('aria-activedescendant');
  }
}

function renderAccountOptions() {
  const query = $('#account').value.trim().toLocaleLowerCase('pt-BR');
  const matches = accountNames.filter((name) => name.toLocaleLowerCase('pt-BR').includes(query));
  const list = $('#account-options');
  list.replaceChildren();
  for (const [index, name] of matches.entries()) {
    const option = makeElement('button', 'account-option', name);
    option.type = 'button';
    option.id = `account-option-${index}`;
    option.setAttribute('role', 'option');
    option.setAttribute('aria-selected', 'false');
    option.addEventListener('click', () => {
      $('#account').value = name;
      $('#account').focus();
      closeAccountOptions();
    });
    list.append(option);
  }
  activeAccountOption = -1;
  $('#account').removeAttribute('aria-activedescendant');
  list.classList.toggle('hidden', !matches.length);
  $('#account').setAttribute('aria-expanded', String(matches.length > 0));
}

async function loadAccountNames() {
  const userId = currentUser?.id;
  try {
    const { accounts } = await api('/api/accounts');
    if (currentUser?.id !== userId) return;
    accountNames = accounts;
    if ($('#expense-dialog').open && document.activeElement === $('#account')) renderAccountOptions();
  } catch {
    // Suggestions are optional; typing a new name remains available.
  }
}

$('#account').addEventListener('focus', renderAccountOptions);
$('#account').addEventListener('click', renderAccountOptions);
$('#account').addEventListener('input', renderAccountOptions);
$('#account').addEventListener('keydown', (event) => {
  const list = $('#account-options');
  const count = list.children.length;
  if (event.key === 'Escape' && !list.classList.contains('hidden')) {
    event.preventDefault();
    event.stopPropagation();
    closeAccountOptions();
  } else if ((event.key === 'ArrowDown' || event.key === 'ArrowUp') && count) {
    event.preventDefault();
    if (list.classList.contains('hidden')) renderAccountOptions();
    const next = event.key === 'ArrowDown'
      ? (activeAccountOption + 1) % count
      : (activeAccountOption - 1 + count) % count;
    setActiveAccountOption(next);
  } else if (event.key === 'Enter' && !list.classList.contains('hidden') && activeAccountOption >= 0) {
    event.preventDefault();
    list.children[activeAccountOption].click();
  }
});
$('.account-combobox').addEventListener('focusout', (event) => {
  if (!event.currentTarget.contains(event.relatedTarget)) closeAccountOptions();
});

function openDialog(item = null, recurring = false) {
  editingExpenseId = item ? item.id : null;
  $('#expense-form').reset();
  $('#recurring-field').classList.toggle('hidden', Boolean(item));
  $('#repeat-monthly').disabled = Boolean(item);
  $('#repeat-monthly').checked = recurring;
  closeAccountOptions();
  $('#expense-error').textContent = '';
  $('.dialog-head .eyebrow').textContent = item ? 'EDITAR COMPROMISSO' : 'NOVO COMPROMISSO';
  $('.dialog-head h2').textContent = item ? 'Editar lançamento' : recurring ? 'Adicionar gasto recorrente' : 'Adicionar lançamento';
  $('#save-expense').textContent = item ? 'Salvar alterações' : 'Salvar lançamento →';
  $('#due-date').value = item ? item.due_date : today();
  if (item) {
    $('#description').value = item.description;
    $('#kind').value = item.kind;
    $('#account').value = item.account;
    $('#amount').value = (item.amount_cents / 100).toFixed(2);
  }
  $('#expense-dialog').showModal();
  $('#description').focus();
  loadAccountNames();
}
$('#new-expense').addEventListener('click', () => openDialog());
$('#close-dialog').addEventListener('click', () => $('#expense-dialog').close());
$('#expense-dialog').addEventListener('click', (event) => { if (event.target === $('#expense-dialog')) $('#expense-dialog').close(); });
$('#expense-dialog').addEventListener('close', closeAccountOptions);
$('#expense-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const amount = Number($('#amount').value);
  const body = {
    description: $('#description').value.trim(), kind: $('#kind').value, account: $('#account').value.trim(),
    amount_cents: Math.round(amount * 100), due_date: $('#due-date').value,
  };
  if (body.description.length < 2 || body.account.length < 2 || !Number.isFinite(amount) || amount <= 0 || !body.due_date) {
    $('#expense-error').textContent = 'Preencha todos os campos com valores válidos.';
    return;
  }
  const button = $('#save-expense');
  if (button.disabled) return;
  button.disabled = true;
  const recurring = editingExpenseId === null && $('#repeat-monthly').checked;
  try {
    await api(recurring ? '/api/recurring-expenses' : editingExpenseId === null ? '/api/expenses' : `/api/expenses/${editingExpenseId}`, {
      method: editingExpenseId === null ? 'POST' : 'PUT', body: JSON.stringify(body),
    });
    $('#expense-dialog').close();
    $('#month').value = body.due_date.slice(0, 7);
    await loadExpenses();
    if (location.hash === '#recorrentes') await loadRecurring();
  } catch (error) {
    $('#expense-error').textContent = error.message;
  } finally {
    button.disabled = false;
  }
});

$('#month').value = today().slice(0, 7);
const comparisonPeriod = defaultComparisonPeriod();
$('#comparison-target').value = comparisonPeriod.end;
$('#comparison-base').value = comparisonPeriod.start;
api('/api/me').then(({ user }) => user ? showDashboard(user) : showAuth()).catch(showAuth);
