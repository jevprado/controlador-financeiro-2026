# Clara — controlador financeiro pessoal

Aplicação local para organizar despesas por mês, acompanhar pagamentos e visualizar pendências. Cada usuário possui seus próprios lançamentos, contas e cartões.

O servidor utiliza Python, com SQLite para uso local ou PostgreSQL externo quando `DATABASE_URL` está configurada. A interface utiliza HTML, CSS e JavaScript, sem etapa de compilação. O modo PostgreSQL requer a instalação de `requirements.txt`.

## Funcionalidades

- Cadastro por convite para e-mails autorizados, login e encerramento de sessão.
- Seleção do mês para consultar os lançamentos e o resumo financeiro.
- Criação, edição e exclusão de lançamentos com descrição, tipo, conta ou cartão, valor e data.
- Tipos disponíveis: cartão de crédito, cheque especial, empréstimo e outros.
- Sugestões de contas e cartões já utilizados pelo usuário, permitindo também digitar novos nomes.
- Marcação de pagamento à esquerda do botão **Editar**, alternando entre **Pendente** e **Pago**.
- Reordenação dos lançamentos por arraste ou pelas setas para cima e para baixo quando o botão de mover está em foco. A ordem é salva por usuário e mês.
- Interface adaptada para computadores e celulares.

### Resumo do mês

| Card | Cálculo |
| --- | --- |
| Total de despesas | Soma de todos os lançamentos do mês, pagos ou pendentes. |
| Cartões de crédito | Soma dos lançamentos do tipo cartão de crédito no mês, pagos ou pendentes. |
| Pendências | Soma de todos os lançamentos do mês ainda não marcados como pagos, incluindo cartões de crédito. |

O card de pendências também exibe a quantidade de lançamentos pendentes. Ao marcar ou desmarcar um pagamento, o resumo é atualizado automaticamente. O estado do pagamento fica salvo e é preservado ao editar o lançamento.

## Executar

É necessário ter Python 3.11 ou superior com suporte a SQLite 3.35 ou superior e um navegador atualizado. Antes de iniciar, configure `ALLOWED_EMAILS` e o convite conforme a seção **Acesso restrito a duas pessoas**. Na pasta do projeto, execute:

```bash
python3 server.py
```

Abra [http://127.0.0.1:8000](http://127.0.0.1:8000), crie uma conta e adicione seus lançamentos. Para encerrar o servidor, pressione `Ctrl+C` no terminal.

### Configuração

Configuração por variáveis de ambiente:

| Variável | Padrão | Finalidade |
| --- | --- | --- |
| `PORT` | `8000` | Porta do servidor local. |
| `FINANCE_DB` | `data/finance.db` na pasta do projeto | Caminho do arquivo SQLite. |
| `DATABASE_URL` | Não definida | URL PostgreSQL. Quando definida, substitui completamente o SQLite. Obrigatória na Vercel. |
| `ALLOWED_EMAILS` | Não definida: acesso bloqueado | E-mails que podem cadastrar, entrar e usar sessões, separados por vírgula. |
| `REGISTRATION_INVITE_CODE` | Não definida: cadastro fechado | Código privado de 32 a 256 caracteres, exigido apenas no cadastro. |

Exemplo com outra porta:

```bash
PORT=8080 python3 server.py
```

Exemplo com outro arquivo de dados:

```bash
FINANCE_DB=/tmp/clara-demo.db python3 server.py
```

### Acesso restrito a duas pessoas

A autorização é aplicada no backend, inclusive para chamadas diretas à API. Configure os dois e-mails reais no ambiente privado do servidor:

```bash
export ALLOWED_EMAILS='seu-email@exemplo.com,email-da-outra-pessoa@exemplo.com'
```

Os e-mails são comparados por endereço completo, ignorando maiúsculas e espaços externos. Domínios e curingas não são aceitos como regras de acesso. Uma lista ausente, vazia ou com qualquer entrada inválida bloqueia cadastro, login e uso das sessões, tanto localmente quanto na Vercel.

Para permitir os primeiros cadastros, gere um código privado:

```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(32))'
```

Cadastre o valor gerado em `REGISTRATION_INVITE_CODE`. Para digitá-lo sem salvá-lo no histórico do Bash:

```bash
read -rsp 'Código de convite: ' REGISTRATION_INVITE_CODE
export REGISTRATION_INVITE_CODE
```

Compartilhe o código somente com a outra pessoa. Na tela **Criar conta**, cada pessoa informa seu e-mail autorizado, sua própria senha e o código. Um visitante que conhece apenas o e-mail não consegue cadastrar a conta sem o convite. O código não fica no JavaScript nem é retornado pela API. O convite autoriza o cadastro; não há confirmação de propriedade do e-mail por mensagem.

O convite é compartilhado e reutilizável enquanto estiver configurado, mas a unicidade do e-mail impede criar uma segunda conta para o mesmo endereço. Depois que os dois cadastros forem feitos, remova `REGISTRATION_INVITE_CODE` para fechar novos cadastros. Contas autorizadas existentes continuam entrando normalmente com e-mail e senha, sem convite.

Para retirar o acesso de uma pessoa, remova seu e-mail de `ALLOWED_EMAILS`. Contas já existentes também obedecem à lista: o login é recusado e todas as rotas protegidas rejeitam suas sessões. Uma sessão apresentada após a remoção tem seu token excluído do banco; sessões ainda não apresentadas ficam bloqueadas enquanto o e-mail estiver fora da lista. Os cadastros e lançamentos são preservados.

Na Vercel, configure essas duas variáveis no ambiente privado do projeto, junto com `DATABASE_URL`, e aplique a alteração em um novo deployment. Localmente, reinicie o servidor após alterar as variáveis no terminal. O arquivo `.env.example` é apenas um modelo e não é carregado automaticamente.

### PostgreSQL externo e configuração na Vercel

O backend usa PostgreSQL quando `DATABASE_URL` está definida. Nesse modo, usuários, sessões e lançamentos ficam no banco externo; nenhuma pasta ou arquivo SQLite é criado. Falhas de conexão não provocam retorno automático ao SQLite.

1. Crie um banco PostgreSQL no provedor de sua escolha. A Vercel oferece integrações pelo [Marketplace](https://vercel.com/docs/postgres).
2. Copie a URL de conexão do provedor, preferindo o endpoint com pool de conexões para uso em funções. Use TLS (`sslmode=require` ou `verify-full`, conforme o provedor).
3. Instale o driver em um ambiente virtual local:

   ```bash
   python3 -m venv .venv
   .venv/bin/python -m pip install -r requirements.txt
   ```

4. Defina `DATABASE_URL` no ambiente do terminal, sem colocar credenciais no código. Para digitar a URL sem salvá-la no histórico do Bash:

   ```bash
   read -rsp 'DATABASE_URL: ' DATABASE_URL
   export DATABASE_URL
   ```

5. Inicialize a estrutura no banco externo:

   ```bash
   .venv/bin/python database.py
   ```

6. Para testar o backend local usando esse banco:

   ```bash
   .venv/bin/python server.py
   ```

7. Na Vercel, cadastre `DATABASE_URL` nas variáveis de ambiente do projeto para os ambientes necessários. Use um banco separado para Preview e para testes. Não exponha a URL no JavaScript ou em variáveis públicas.

O arquivo [.env.example](.env.example) mostra o formato da configuração. Arquivos `.env` não são carregados automaticamente; configure as variáveis pelo terminal ou pela plataforma. Eles estão ignorados pelo Git.

As conexões são abertas por operação, concluídas com commit ou rollback e fechadas ao final. Prepared statements automáticos estão desativados para compatibilidade com endpoints de pool por transação. TLS é exigido por padrão; `sslmode=disable` serve apenas para um PostgreSQL local de desenvolvimento e é recusado quando `VERCEL` está definida.

**Este ajuste resolve a camada de persistência. A adaptação do servidor HTTP para um ponto de entrada da Vercel continua pendente.** Não basta configurar o banco para publicar o projeto completo.

### Transferir dados existentes do SQLite

Para manter os cadastros e lançamentos já existentes:

1. Encerre o servidor local para evitar alterações durante a transferência e faça uma cópia de segurança do SQLite.
2. Configure `DATABASE_URL` com o banco PostgreSQL de destino.
3. Execute:

   ```bash
   .venv/bin/python migrate_sqlite.py data/finance.db
   ```

O importador abre a origem somente para leitura e preserva IDs, vínculos dos usuários, hashes das senhas, valores em centavos, datas, ordenação e estados de pagamento. Bancos antigos sem as colunas de ordenação ou pagamento também são aceitos.

O destino deve estar vazio: se já houver usuários, sessões ou lançamentos, a importação é recusada. Os registros são inseridos em uma única transação; uma falha desfaz as inserções. A origem não é apagada nem modificada. A criação da estrutura do destino ocorre em uma etapa anterior à importação.

As sessões antigas não são copiadas: cada pessoa deve entrar novamente com seu e-mail e senha atuais. Após validar os dados no PostgreSQL, mantenha `DATABASE_URL` configurada para continuar usando o destino. Sem ela, o modo local volta a usar o SQLite original, que não recebe as alterações feitas no PostgreSQL.

## Dados e autenticação

No modo SQLite, o banco de dados e sua pasta são criados automaticamente na primeira execução. Ao iniciar, o servidor também adiciona as colunas de ordenação e pagamento caso ainda não existam. Lançamentos anteriores à funcionalidade de pagamento começam como pendentes. No modo PostgreSQL, a inicialização cria a estrutura no banco externo.

No modo SQLite, para preservar contas, lançamentos e estados de pagamento, encerre o servidor e faça uma cópia do arquivo configurado. A pasta `data/` está no `.gitignore` e não é versionada. No PostgreSQL, configure backups e restauração no provedor; um banco externo não substitui uma política de backup.

As senhas são armazenadas com PBKDF2-HMAC-SHA256 e salt individual. As sessões usam tokens aleatórios, com hash armazenado no banco e validade de 30 dias; o cookie utiliza `HttpOnly` e `SameSite=Strict`.

O servidor escuta apenas em `127.0.0.1`. Para acesso público, use HTTPS e configure um proxy confiável.

## Estrutura do projeto

```text
server.py           Servidor HTTP, autenticação e API
database.py         Conexões, transações e estrutura SQLite/PostgreSQL
migrate_sqlite.py   Transferência de SQLite para PostgreSQL vazio
requirements.txt    Driver PostgreSQL
.env.example        Modelo de configuração sem credenciais
static/index.html   Estrutura das telas de acesso e painel financeiro
static/styles.css   Estilos e adaptações para diferentes tamanhos de tela
static/app.js       Interações, chamadas à API e cálculo dos cards
tests/test_flow.py  Testes de integração da API
data/finance.db     Banco local criado na execução (não versionado)
```

## Verificação

Execute os testes de integração na pasta do projeto:

```bash
python3 -m unittest discover -s tests -v
```

Por padrão, os testes utilizam SQLite temporário e um servidor HTTP local em uma porta livre. Eles ignoram `DATABASE_URL` do ambiente para não acessar o banco da aplicação e configuram sua própria lista de e-mails e convite fictícios. Cobrem cadastro restrito, configuração ausente ou inválida, bloqueio de contas e sessões removidas da lista, autenticação e isolamento entre usuários, edição de lançamentos, ordenação mensal e marcação reversível e persistente de pagamentos, além da configuração de banco e da migração do esquema SQLite.

Para executar também a migração de dados e os mesmos fluxos da API em um PostgreSQL de testes, configure explicitamente `TEST_DATABASE_URL` e execute a suíte com o Python do ambiente virtual:

```bash
.venv/bin/python -m unittest discover -s tests -v
```

Use um banco descartável e uma conexão direta de teste com permissão de criar schemas. A suíte cria schemas exclusivos e os remove ao final. `TEST_DATABASE_URL` nunca deve apontar para produção. Sem essa variável, os testes específicos de PostgreSQL são indicados como ignorados.

Se tiver Node.js disponível, a sintaxe do JavaScript também pode ser verificada com `node --check static/app.js`. Node.js não é necessário para executar a aplicação.
