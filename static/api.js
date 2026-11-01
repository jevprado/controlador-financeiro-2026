async function api(path, options = {}) {
  let response;
  try {
    response = await fetch(path, { credentials: 'same-origin', ...options, headers: { 'Content-Type': 'application/json', ...(options.headers || {}) } });
  } catch {
    throw new Error('Não foi possível conectar. Tente novamente.');
  }

  let data;
  try {
    data = await response.json();
  } catch {
    throw new Error(response.ok
      ? 'O servidor enviou uma resposta inválida. Tente novamente.'
      : `Serviço temporariamente indisponível (HTTP ${response.status}). Tente novamente em instantes.`);
  }
  if (!data || typeof data !== 'object' || Array.isArray(data)) {
    throw new Error('O servidor enviou uma resposta inválida. Tente novamente.');
  }
  if (!response.ok) {
    throw new Error(typeof data.error === 'string' && data.error
      ? data.error
      : `Não foi possível concluir a solicitação (HTTP ${response.status}). Tente novamente.`);
  }
  return data;
}
