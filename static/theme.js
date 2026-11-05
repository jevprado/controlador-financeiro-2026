/*
 * Tema claro/escuro da interface Odarp.
 * Carregado no <head>, sem defer, para aplicar o tema antes da primeira pintura.
 * Sem escolha salva, segue a preferência do sistema operacional.
 */
(() => {
  const STORAGE_KEY = 'odarp-theme';
  const THEME_COLORS = { light: '#f7f8f5', dark: '#111814' };
  const root = document.documentElement;
  const media = typeof window.matchMedia === 'function' ? window.matchMedia('(prefers-color-scheme: dark)') : null;

  function storedTheme() {
    try {
      const value = localStorage.getItem(STORAGE_KEY);
      return value === 'light' || value === 'dark' ? value : null;
    } catch {
      return null;
    }
  }

  function systemTheme() {
    return media && media.matches ? 'dark' : 'light';
  }

  function applyTheme(theme) {
    root.dataset.theme = theme;
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute('content', THEME_COLORS[theme]);
    const dark = theme === 'dark';
    document.querySelectorAll('.theme-toggle').forEach((button) => {
      button.setAttribute('aria-pressed', String(dark));
      button.title = dark ? 'Mudar para o modo claro' : 'Mudar para o modo escuro';
      const icon = button.querySelector('.theme-icon');
      if (icon) icon.textContent = dark ? '☀' : '☾';
    });
  }

  function toggleTheme() {
    const next = root.dataset.theme === 'dark' ? 'light' : 'dark';
    try { localStorage.setItem(STORAGE_KEY, next); } catch { /* preferência vale só para esta visita */ }
    applyTheme(next);
  }

  applyTheme(storedTheme() || systemTheme());

  if (media) {
    const followSystem = () => { if (!storedTheme()) applyTheme(systemTheme()); };
    if (typeof media.addEventListener === 'function') media.addEventListener('change', followSystem);
    else if (typeof media.addListener === 'function') media.addListener(followSystem);
  }

  document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('.theme-toggle').forEach((button) => button.addEventListener('click', toggleTheme));
    applyTheme(root.dataset.theme);
  });
})();
