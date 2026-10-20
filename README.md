# Clara — controlador financeiro pessoal

Aplicação local para organizar despesas por mês, acompanhar pagamentos e visualizar pendências. Cada usuário possui seus próprios lançamentos, contas e cartões.

O servidor utiliza Python e SQLite, apenas com a biblioteca padrão. A interface utiliza HTML, CSS e JavaScript, sem etapa de compilação ou instalação de dependências.

## Funcionalidades

- Cadastro, login e encerramento de sessão.
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

É necessário ter Python 3 com suporte a SQLite e um navegador atualizado. Na pasta do projeto, execute:

```bash
python3 server.py
```

Abra [http://127.0.0.1:8000](http://127.0.0.1:8000), crie uma conta e adicione seus lançamentos. Para encerrar o servidor, pressione `Ctrl+C` no terminal.

### Configuração

As variáveis de ambiente abaixo são opcionais:

| Variável | Padrão | Finalidade |
| --- | --- | --- |
| `PORT` | `8000` | Porta do servidor local. |
| `FINANCE_DB` | `data/finance.db` na pasta do projeto | Caminho do arquivo SQLite. |

Exemplo com outra porta:

```bash
PORT=8080 python3 server.py
```

Exemplo com outro arquivo de dados:

```bash
FINANCE_DB=/tmp/clara-demo.db python3 server.py
```

## Dados e autenticação

O banco de dados e sua pasta são criados automaticamente na primeira execução. Ao iniciar, o servidor também adiciona as colunas de ordenação e pagamento caso ainda não existam. Lançamentos anteriores à funcionalidade de pagamento começam como pendentes.

Para preservar contas, lançamentos e estados de pagamento, encerre o servidor e faça uma cópia do arquivo SQLite configurado. A pasta `data/` está no `.gitignore` e não é versionada.

As senhas são armazenadas com PBKDF2-HMAC-SHA256 e salt individual. As sessões usam tokens aleatórios, com hash armazenado no banco e validade de 30 dias; o cookie utiliza `HttpOnly` e `SameSite=Strict`.

O servidor escuta apenas em `127.0.0.1`. Para acesso público, use HTTPS e configure um proxy confiável.

## Estrutura do projeto

```text
server.py           Servidor HTTP, autenticação, API e persistência SQLite
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

Os testes utilizam um banco temporário e um servidor HTTP local em uma porta livre. Cobrem autenticação e isolamento entre usuários, edição de lançamentos, ordenação mensal e marcação reversível e persistente de pagamentos.

Se tiver Node.js disponível, a sintaxe do JavaScript também pode ser verificada com `node --check static/app.js`. Node.js não é necessário para executar a aplicação.
