# Clara — controlador financeiro pessoal

Aplicação local para organizar despesas por mês, acompanhar pagamentos e visualizar pendências. Cada usuário possui seus próprios lançamentos, contas e cartões.

O servidor utiliza Python, com SQLite para uso local ou PostgreSQL externo quando `DATABASE_URL` está configurada. A interface utiliza HTML, CSS e JavaScript, sem etapa de compilação. O modo PostgreSQL requer a instalação de `requirements.txt`.

## Funcionalidades

- Cadastro por convite para e-mails autorizados, login e encerramento de sessão.
- Seleção do mês para consultar os lançamentos e o resumo financeiro.
- Submenu **Dashboard**, abaixo de **Visão geral**, com período padrão de janeiro até o mês atual do ano do acesso, usando a data local do navegador. Os filtros permitem escolher outro período. O gráfico de linha mostra o total de despesas de todos os meses do intervalo, acompanhado do gráfico de barras **Evolução das despesas**, com os totais de cada mês do mesmo intervalo. Os cards comparam o primeiro e o último mês. Inclui despesas pagas e pendentes; meses sem lançamentos têm total zero. Quando a referência tem total zero e há aumento, o percentual é indicado como indisponível.
- Criação, edição e exclusão de lançamentos com descrição, tipo, conta ou cartão, valor e data.
- Gastos recorrentes mensais com valor fixo: cadastre em **Recorrentes → Novo gasto recorrente**, ou marque **Repetir todos os meses** ao adicionar um lançamento.
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

### Gastos recorrentes

Informe a descrição (por exemplo, plano de saúde), conta, tipo, valor e data da primeira cobrança. A data define o mês inicial e o dia das próximas cobranças. Nos meses que não têm esse dia, a cobrança fica no último dia disponível; uma cobrança do dia 31 vence em 28 ou 29 de fevereiro e volta ao dia 31 em março.

Ao consultar os lançamentos, o Dashboard ou a área **Recorrentes**, o servidor gera automaticamente as cobranças desde o mês inicial até o mês atual, no fuso de São Paulo. Os meses entre acessos também são preenchidos. Ao cadastrar uma recorrência com início futuro ou consultar um mês futuro nos lançamentos, a cobrança daquele mês também é gerada. Não é necessário agendador em segundo plano.

Cada mês gera um único lançamento pendente e entra nos totais e gráficos normalmente. Marcar como pago, editar ou excluir uma cobrança afeta apenas aquela ocorrência. Uma cobrança excluída não reaparece nos próximos acessos. Cadastros duplicados da mesma despesa são tratados como recorrências independentes; evite cadastrar novamente uma despesa já ativa.

Em **Recorrentes**, use **Encerrar recorrência** para impedir novas cobranças. Os lançamentos já gerados, inclusive de meses futuros consultados, são mantidos e podem ser editados ou excluídos individualmente. Para alterar o valor fixo das próximas cobranças, encerre a recorrência e cadastre outra com a nova data inicial, cuidando para não duplicar cobranças já geradas.

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

### Transferir dados existentes do SQLite

Para manter os cadastros e lançamentos já existentes:

1. Encerre o servidor local para evitar alterações durante a transferência e faça uma cópia de segurança do SQLite.
2. Configure `DATABASE_URL` com o banco PostgreSQL de destino.
3. Execute:

   ```bash
   .venv/bin/python migrate_sqlite.py data/finance.db
   ```

O importador abre a origem somente para leitura e preserva IDs, vínculos dos usuários, hashes das senhas, valores em centavos, datas, ordenação, estados de pagamento e recorrências com seu histórico de geração. Bancos antigos sem as colunas de ordenação ou pagamento ou sem recorrências também são aceitos.

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
api/index.py        Entrada da Vercel e inicialização automática do banco
vercel.json         Publicação dos arquivos estáticos e rotas da API
database.py         Conexões, transações e estrutura SQLite/PostgreSQL
migrate_sqlite.py   Transferência de SQLite para PostgreSQL vazio
requirements.txt    Driver PostgreSQL
.env.example        Modelo de configuração sem credenciais
static/index.html   Estrutura das telas de acesso e painel financeiro
static/styles.css   Estilos e adaptações para diferentes tamanhos de tela
static/app.js       Interações, chamadas à API e cálculo dos cards
static/api.js       Cliente HTTP e tratamento de respostas inválidas
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

Para testar os fluxos HTTP pelo ponto de entrada da Vercel, inicialização do banco e tratamento de falhas:

```bash
TEST_VERCEL_HANDLER=1 python3 -m unittest discover -s tests -v
node --test tests/test_api_client.cjs tests/test_dashboard.cjs
```

Os testes locais não executam um deployment real. A validação final deve ser feita no endereço publicado, verificando cadastro e login e os logs da Vercel.
