# HelpDesk

Sistema web de gerenciamento de chamados de suporte técnico interno de uma empresa.

Em vez de pedir ajuda de maneira informal, os funcionários abrem chamados pelo
sistema e a equipe de suporte acompanha e resolve cada problema de informática.

> **Status:** Etapa 3 concluída (gerenciamento de chamados).

## Funcionalidades

**Geral (Etapas 1 e 2)**
- Página inicial, cadastro público de funcionários, login e logout
- Dois tipos de usuário (funcionário e técnico), controle de acesso, senhas com hash
  e proteção CSRF em todos os formulários
- Técnicos criados/promovidos somente por comandos administrativos no terminal

**Funcionário**
- Abre chamados informando título, descrição, categoria e prioridade
- Consulta a lista dos **seus** chamados, com filtros por status e prioridade
- Vê detalhes, status, técnico responsável, solução e histórico de atualizações
- Dashboard com a contagem dos seus chamados por status
- Não altera status nem atribui técnicos

**Técnico**
- Vê os chamados disponíveis (abertos e sem técnico), ordenados por prioridade
- Filtra por status e prioridade e alterna entre *Chamados disponíveis*, *Meus atendimentos*
  e *Todos os visíveis*
- Assume manualmente um chamado (o status passa a **Em andamento**)
- Registra comentários e, ao final, a solução, concluindo o chamado
- Consulta os chamados que já atendeu
- Dashboard com disponíveis, em andamento e concluídos por ele

## Regras dos chamados

| Item         | Valores                                    |
|--------------|--------------------------------------------|
| Status       | Aberto → Em andamento → Concluído          |
| Prioridades  | Baixa, Média, Alta                         |
| Categorias   | Hardware, Software, Rede e internet, Impressora, E-mail e contas, Acesso e senhas, Outros |

- Todo chamado pertence ao funcionário que o abriu.
- **Assumir** = atribuir o técnico **e** mudar o status para Em andamento, na mesma operação.
- Chamado concluído não pode ser assumido de novo, nem receber comentários.
- Um técnico não assume um chamado que ele mesmo abriu.
- São registradas as datas de criação, atualização e conclusão.
- Cada alteração importante (abertura, assumir, comentário, conclusão) gera um item no histórico.
- Datas ficam em UTC no banco e são exibidas em horário de Brasília (UTC-3). Para mudar,
  defina `FUSO_HORARIO_HORAS` no `.env`.

## Permissões (verificadas no servidor)

| Situação                                                         | Resposta      |
|------------------------------------------------------------------|---------------|
| Visitante em qualquer página de chamados                         | Redireciona para o login |
| Funcionário em rota exclusiva de técnico (assumir, comentar, concluir, dashboard) | 403 |
| Técnico em rota exclusiva de funcionário (abrir chamado)         | 403           |
| Funcionário abrindo chamado de outro funcionário                 | 404           |
| Técnico abrindo chamado assumido por outro técnico               | 404           |
| Técnico comentando/concluindo chamado disponível (sem assumir)   | 403           |
| Técnico comentando/concluindo chamado de outro técnico           | 404           |

O 404 é usado de propósito: não revela a existência de chamados que o usuário não pode ver.

## Concorrência na atribuição

Assumir, comentar e concluir usam um **UPDATE condicional** (por exemplo, assumir só altera o
chamado se ele ainda estiver `aberto` e sem técnico) e conferem se exatamente uma linha foi
alterada. Como o banco executa cada UPDATE de forma atômica, quando dois técnicos clicam ao
mesmo tempo, um UPDATE altera 1 linha e o outro 0. Quem perde recebe a mensagem
"Este chamado não está mais disponível para ser assumido" e nenhum registro duplicado entra
no histórico.

## Estrutura do projeto

```
HelpDesk/
├── app/
│   ├── __init__.py        # Application Factory
│   ├── extensions.py      # db, login_manager, csrf (+ chaves estrangeiras do SQLite)
│   ├── models.py          # User, Chamado, HistoricoChamado e constantes
│   ├── services.py        # Regras de negócio dos chamados (atribuição atômica)
│   ├── forms.py           # Formulários (cadastro, login, chamado, comentário, solução)
│   ├── decorators.py      # Controle de acesso por tipo de usuário
│   ├── errors.py          # Páginas de erro (403, 404, CSRF)
│   ├── cli.py             # Comandos administrativos
│   ├── utils.py           # Funções auxiliares
│   ├── routes/
│   │   ├── main.py        # Página inicial
│   │   ├── auth.py        # Cadastro, login e logout
│   │   ├── painel.py      # Perfil e dashboards
│   │   └── chamados.py    # Lista, abertura, detalhes, assumir, comentar, concluir
│   ├── templates/
│   │   ├── base.html, home.html, _macros.html
│   │   ├── auth/          # login.html, cadastro.html
│   │   ├── painel/        # index.html, funcionario.html, tecnico.html
│   │   ├── chamados/      # lista.html, novo.html, detalhe.html, _macros.html
│   │   └── errors/        # error.html
│   └── static/            # css/style.css, js/script.js
├── instance/              # Banco SQLite (helpdesk.db) - não versionado
├── tests/
│   ├── base_testes.py     # Base compartilhada (banco temporário, limpeza, auxiliares)
│   ├── test_auth.py       # Testes da Etapa 2
│   └── test_chamados.py   # Testes da Etapa 3
├── config.py
├── run.py
├── requirements.txt
├── .env.example
└── .gitignore
```

## Atualizando do banco da Etapa 2 (preservar os dados)

**Não é necessária migração.** A Etapa 3 só **cria duas tabelas novas** (`chamados` e
`historico_chamados`). A tabela `usuarios` não é alterada. Ao iniciar, o sistema executa
`db.create_all()`, que cria apenas as tabelas que ainda não existem e nunca apaga nem
modifica as existentes.

Mesmo assim, faça uma cópia de segurança antes de rodar a nova versão pela primeira vez
(Prompt de Comando, na pasta do projeto, com o servidor parado):

```bat
copy instance\helpdesk.db instance\helpdesk_backup_etapa2.db
```

Para conferir que os usuários continuam lá, antes e depois de atualizar:

```bat
.venv\Scripts\activate.bat
flask --app run listar-usuarios
```

Se algo der errado, pare o servidor e restaure a cópia:

```bat
copy /Y instance\helpdesk_backup_etapa2.db instance\helpdesk.db
```

> **Importante:** **não** apague `instance\helpdesk.db` para "atualizar". Isso só é necessário
> em desenvolvimento, caso você mude manualmente as colunas de uma tabela existente (o projeto
> ainda não usa migrações). Isso não se aplica à Etapa 3.

## Como executar (Windows, Prompt de Comando - CMD)

```bat
:: 1. Entrar na pasta do projeto (ajuste o caminho)
cd C:\caminho\para\HelpDesk

:: 2. Ativar o ambiente virtual
.venv\Scripts\activate.bat

:: 3. Instalar as dependências (se ainda não estiverem instaladas)
pip install -r requirements.txt

:: 4. Criar o arquivo .env a partir do modelo (apenas na primeira vez)
copy .env.example .env

:: 5. Iniciar a aplicação
python run.py
```

Acesse <http://127.0.0.1:5000>. Para parar o servidor: `Ctrl + C`.

Para gerar uma `SECRET_KEY` própria (coloque no `.env`):

```bat
python -c "import secrets; print(secrets.token_hex(32))"
```

## Técnicos

O cadastro público cria apenas **funcionários**. Técnicos são criados ou promovidos por
comandos que exigem acesso ao terminal (nenhuma página web altera o tipo de usuário):

```bat
flask --app run criar-tecnico
flask --app run promover-tecnico email@empresa.com
flask --app run rebaixar-tecnico email@empresa.com
flask --app run listar-usuarios
```

Quem foi promovido precisa sair e entrar de novo para ver a mudança.

## Rotas

| Rota                              | Acesso                  | Descrição                         |
|-----------------------------------|-------------------------|-----------------------------------|
| `/`                               | Público                 | Página inicial                    |
| `/cadastro`, `/login`             | Público                 | Cadastro de funcionário e login   |
| `/logout` (POST)                  | Autenticado             | Logout (com token CSRF)           |
| `/painel`                         | Qualquer usuário logado | Perfil                            |
| `/painel/funcionario`             | Funcionários            | Dashboard do funcionário          |
| `/painel/tecnico`                 | Técnicos                | Dashboard do técnico              |
| `/chamados/`                      | Qualquer usuário logado | Lista com filtros (`status`, `prioridade`, `escopo` para técnicos) |
| `/chamados/novo`                  | Funcionários            | Abrir chamado                     |
| `/chamados/<id>`                  | Dono ou técnico com acesso | Detalhes e histórico           |
| `/chamados/<id>/assumir` (POST)   | Técnicos                | Assumir atendimento               |
| `/chamados/<id>/comentarios` (POST) | Técnico responsável   | Registrar comentário              |
| `/chamados/<id>/concluir` (POST)  | Técnico responsável     | Registrar solução e concluir      |

## Testes

Os testes usam um banco SQLite temporário (não alteram `instance\helpdesk.db`) e conferem as
linhas gravadas diretamente no arquivo `.db`. Na raiz do projeto, com o ambiente virtual ativado:

```bat
python -m unittest discover -s tests -v
```

Para exibir avisos como `ResourceWarning`, rode com o modo de desenvolvimento do Python:

```bat
python -X dev -m unittest discover -s tests -v
```

Cobertura da Etapa 3: estrutura e relacionamentos do banco, preservação dos usuários ao criar as
tabelas novas, abertura de chamados, validações, permissões de funcionários e técnicos,
visibilidade, filtros, atribuição, comentários, conclusão, histórico, datas, CSRF e
concorrência (várias threads tentando assumir o mesmo chamado, por serviço e por HTTP).

## Limitações conhecidas

- Sem migrações de banco (o projeto usa `db.create_all()`); mudanças futuras em tabelas
  existentes exigirão uma ferramenta como Flask-Migrate/Alembic.
- Listas sem paginação.
- Sem edição ou cancelamento de chamados, reabertura, anexos ou notificações.
- Sem limite de tentativas de login, recuperação de senha ou confirmação de e-mail.
- Produção: use HTTPS, `SECRET_KEY` própria, `SESSION_COOKIE_SECURE`/`REMEMBER_COOKIE_SECURE`
  e um servidor WSGI. Com vários processos ou servidores, prefira um banco como PostgreSQL;
  o SQLite serializa as escritas.
- O Bootstrap vem de CDN, então a página precisa de internet para ficar estilizada.

## Roadmap

- [x] Etapa 1: estrutura inicial e página inicial
- [x] Etapa 2: banco de dados, usuários, login e controle de acesso
- [x] Etapa 3: gerenciamento de chamados
