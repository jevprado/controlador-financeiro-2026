const $ = (selector) => document.querySelector(selector);
const money = (cents) => new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' }).format(cents / 100);
const monthName = (value) => new Intl.DateTimeFormat('pt-BR', { month: 'long', year: 'numeric', timeZone: 'UTC' }).format(new Date(`${value}-01T12:00:00Z`));
const today = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };
let mode = 'login';
let currentUser = null;
let expenses = [];
let accountNames = [];
let activeAccountOption = -1;

async function api(path, options = {}) {
  let response;
  try {
    response = await fetch(path, { credentials: 'same-origin', ...options, headers: { 'Content-Type': 'application/json', ...(options.headers || {}) } });
  } catch {
    throw new Error('Não foi possível conectar. Tente novamente.');
  }
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Algo deu errado. Tente novamente.');
  return data;
}

function showAuth() {
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
  loadExpenses();
}

function setMode(next) {
  mode = next;
  const register = mode === 'register';
  $('#name-field').classList.toggle('hidden', !register);
  $('#name').required = register;
  $('#password').autocomplete = register ? 'new-password' : 'current-password';
  $('#password-hint').classList.toggle('hidden', !register);
  $('#auth-title').innerHTML = register ? 'Comece com clareza<span>.</span>' : 'Bem-vindo de volta<span>.</span>';
  $('#auth-subtitle').textContent = register ? 'Crie sua conta e organize suas finanças no seu ritmo.' : 'Entre na sua conta para continuar de onde parou.';
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
  if ((mode === 'register' && name.length < 2) || !$('#email').validity.valid || password.length < (mode === 'register' ? 8 : 1)) {
    $('#auth-error').textContent = mode === 'register' ? 'Informe nome, e-mail válido e senha com pelo menos 8 caracteres.' : 'Informe seu e-mail e senha.';
    return;
  }
  const button = $('#auth-submit');
  button.disabled = true;
  $('#auth-error').textContent = '';
  try {
    const data = await api(mode === 'register' ? '/api/register' : '/api/login', { method: 'POST', body: JSON.stringify({ name, email, password }) });
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

function renderExpenses() {
  const total = expenses.reduce((sum, item) => sum + item.amount_cents, 0);
  const cards = expenses.filter((item) => item.kind === 'Cartão de crédito');
  const cardsTotal = cards.reduce((sum, item) => sum + item.amount_cents, 0);
  $('#total-amount').textContent = money(total);
  $('#cards-amount').textContent = money(cardsTotal);
  $('#other-amount').textContent = money(total - cardsTotal);
  $('#cards-count').textContent = `${cards.length} ${cards.length === 1 ? 'lançamento' : 'lançamentos'}`;
  $('#other-count').textContent = `${expenses.length - cards.length} ${expenses.length - cards.length === 1 ? 'lançamento' : 'lançamentos'}`;
  $('#expense-count').textContent = `${expenses.length} ${expenses.length === 1 ? 'lançamento' : 'lançamentos'}`;
  $('#month-label').textContent = monthName($('#month').value);
  const list = $('#expense-list');
  list.replaceChildren();
  if (!expenses.length) {
    const empty = makeElement('div', 'empty-state');
    empty.append(makeElement('div', 'empty-icon', '✳'), makeElement('h3', '', 'Tudo em ordem por aqui'), makeElement('p', '', 'Adicione seu primeiro lançamento para começar a acompanhar este mês.'));
    const button = makeElement('button', 'secondary-button', '+ Adicionar lançamento');
    button.type = 'button';
    button.addEventListener('click', openDialog);
    empty.append(button);
    list.append(empty);
    return;
  }
  for (const item of expenses) {
    const row = makeElement('div', 'expense-row');
    const icon = makeElement('div', 'expense-icon', item.kind === 'Cartão de crédito' ? '▤' : item.kind === 'Empréstimo' ? '◇' : '◎');
    const details = makeElement('div', 'expense-details');
    details.append(makeElement('strong', '', item.description), makeElement('span', '', `${item.kind} · ${item.account}`));
    const value = makeElement('div', 'expense-value');
    const formattedDate = new Intl.DateTimeFormat('pt-BR', { day: '2-digit', month: 'short', timeZone: 'UTC' }).format(new Date(`${item.due_date}T12:00:00Z`));
    value.append(makeElement('strong', '', money(item.amount_cents)), makeElement('span', '', formattedDate));
    const remove = makeElement('button', 'remove-button', '×');
    remove.type = 'button';
    remove.setAttribute('aria-label', `Excluir ${item.description}`);
    remove.title = 'Excluir lançamento';
    remove.addEventListener('click', async () => {
      if (!confirm(`Excluir "${item.description}"?`)) return;
      try { await api(`/api/expenses/${item.id}`, { method: 'DELETE' }); await loadExpenses(); }
      catch (error) { alert(error.message); }
    });
    row.append(icon, details, value, remove);
    list.append(row);
  }
}

async function loadExpenses() {
  try {
    expenses = (await api(`/api/expenses?month=${encodeURIComponent($('#month').value)}`)).expenses;
    renderExpenses();
  } catch (error) {
    if (error.message === 'Faça login para continuar.') showAuth();
    else $('#expense-list').textContent = error.message;
  }
}
$('#month').addEventListener('change', loadExpenses);

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

function openDialog() {
  $('#expense-form').reset();
  closeAccountOptions();
  $('#expense-error').textContent = '';
  $('#due-date').value = today();
  $('#expense-dialog').showModal();
  $('#description').focus();
  loadAccountNames();
}
$('#new-expense').addEventListener('click', openDialog);
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
  button.disabled = true;
  try {
    await api('/api/expenses', { method: 'POST', body: JSON.stringify(body) });
    $('#expense-dialog').close();
    $('#month').value = body.due_date.slice(0, 7);
    await loadExpenses();
  } catch (error) {
    $('#expense-error').textContent = error.message;
  } finally {
    button.disabled = false;
  }
});

$('#month').value = today().slice(0, 7);
api('/api/me').then(({ user }) => user ? showDashboard(user) : showAuth()).catch(showAuth);
