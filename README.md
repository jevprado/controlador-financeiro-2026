# Clara — controlador financeiro pessoal

Aplicação local com cadastro, login e lançamentos mensais separados por usuário. Não requer instalação de dependências.

## Executar

```bash
python3 server.py
```

Abra [http://127.0.0.1:8000](http://127.0.0.1:8000). Para mudar a porta, use `PORT=8080 python3 server.py`.

Os dados são salvos em `data/finance.db` (SQLite). Faça backup desse arquivo para preservar as contas e os lançamentos. As senhas são armazenadas com PBKDF2 e as sessões com tokens aleatórios. O servidor escuta apenas em `127.0.0.1`; para acesso público, use HTTPS e configure um proxy confiável.
