# MemoBelc API

API REST da plataforma MemoBelc: estudo com flashcards (coleções, baralhos e cartas), salas de aula, progresso, streak, livros, chat com IA, pagamentos, convites e notificações.

A aplicação é um serviço Flask com MongoDB, documentação interativa em Swagger e deploy pensado para Gunicorn + Docker.

## Sumário

- [Stack](#stack)
- [Pré-requisitos](#pré-requisitos)
- [Começando](#começando)
- [Variáveis de ambiente](#variáveis-de-ambiente)
- [Rodar localmente (Poetry)](#rodar-localmente-poetry)
- [Rodar com Docker](#rodar-com-docker)
- [Documentação da API](#documentação-da-api)
- [Módulos e rotas](#módulos-e-rotas)
- [Testes](#testes)
- [Protobuf](#protobuf)
- [Produção](#produção)
- [Estrutura do projeto](#estrutura-do-projeto)

## Stack

| Tecnologia | Uso |
| --- | --- |
| Python 3.11 | Runtime |
| Flask 3 | API HTTP |
| Poetry | Dependências e ambiente virtual |
| MongoDB | Banco de dados |
| Gunicorn | Servidor WSGI (produção) |
| Flask-Swagger-UI | Documentação em `/doc` |
| Google Gemini | Chat e geração de cartas |
| APScheduler | Lembretes diários de estudo |
| MailHog (dev) | Captura de e-mails locais |

## Pré-requisitos

- [Python 3.11+](https://www.python.org/downloads/)
- [Poetry](https://python-poetry.org/docs/#installation)
- MongoDB acessível (local, Docker ou Atlas)
- [Docker](https://docs.docker.com/get-docker/) e Docker Compose (opcional, para subir API + Mongo + MailHog juntos)
- `protoc` e o plugin [betterproto](https://github.com/danielgtaylor/python-betterproto) (somente se for regenerar os arquivos `.proto`)

Instalar o Poetry (se ainda não tiver):

```bash
pip install poetry
```

## Começando

1. Clone o repositório e entre na pasta:

```bash
git clone <url-do-repositorio>
cd memobelc-api
```

2. Copie o arquivo de ambiente e preencha os valores:

```bash
cp .env.example .env
```

No Windows (PowerShell):

```powershell
Copy-Item .env.example .env
```

3. Instale as dependências:

```bash
poetry install
```

4. Suba o MongoDB (se ainda não estiver rodando). A forma mais simples é via Compose, só o banco:

```bash
docker compose up -d mongo
```

5. Inicie a API em modo desenvolvimento:

```bash
poetry run python run.py
```

Por padrão a porta vem de `PORT` no `.env` (no exemplo: `3005`). A API fica em `http://localhost:<PORT>`.

## Variáveis de ambiente

Todas as variáveis abaixo são **obrigatórias** para a aplicação subir (`src/app/config.py` lê diretamente do ambiente). Use `.env.example` como base.

| Variável | Descrição |
| --- | --- |
| `MONGO_URI` | URI do MongoDB de desenvolvimento/produção |
| `MONGO_URI_TEST` | URI do MongoDB **somente para testes** (nunca o banco oficial) |
| `SECRET_KEY` | Chave JWT / sessão. Gere com `python -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `PORT` | Porta do servidor Flask local (ex.: `3005`) |
| `FRONT_BASE_URL` | URL do frontend (links de e-mail, convites, etc.) |
| `GENAI_API_KEY` | Chave da API Google Generative AI |
| `GENAI_MODEL` | Modelo Gemini (ex.: `gemin
| `MAIL_SERVER` | Host SMTP (em dev com MailHog: `localhost`) |
| `MAIL_PORT` | Porta SMTP (MailHog: `1025`; Gmail: `587`) |
| `MAIL_USERNAME` | Usuário SMTP |
| `MAIL_PASSWORD` | Senha SMTP (no Gmail, use senha de app) |
| `MAIL_DEFAULT_SENDER` | Remetente padrão |

Opcionais (produção / scheduler):

| Variável | Padrão | Descrição |
| --- | --- | --- |
| `FLASK_DEBUG` | `false` | `true` habilita debug no `run.py` (não use em produção) |
| `FLASK_ENV` | `production` | `development` liga `DEBUG` na config |
| `ENABLE_DAILY_REMINDERS` | `false` | Liga o APScheduler de lembretes às 9h |
| `GUNICORN_WORKERS` | `2` | Número de workers Gunicorn |
| `GUNICORN_THREADS` | `4` | Threads por worker |

Exemplo mínimo para desenvolvimento local com MailHog:

```env
MONGO_URI=mongodb://localhost:27017/memobelc
MONGO_URI_TEST=mongodb://localhost:27017/memobelc_test
SECRET_KEY=troque-esta-chave
PORT=3005
FRONT_BASE_URL=http://localhost:3000
GENAI_API_KEY=
GENAI_MODEL=gemini-pro
MAIL_SERVER=localhost
MAIL_PORT=1025
MAIL_USERNAME=
MAIL_PASSWORD=
MAIL_DEFAULT_SENDER=dev@memobelc.local
```

## Rodar localmente (Poetry)

```bash
poetry install
poetry run python run.py
```

Ou ative o ambiente virtual e rode direto:

```bash
poetry shell
python run.py
```

O servidor de desenvolvimento do Flask processa uma requisição por vez e **não deve ser usado em produção**. Em produção use Gunicorn (veja [Produção](#produção)).

Para testar o mesmo processo de produção na sua máquina:

```bash
poetry run gunicorn -c gunicorn.conf.py run:app
```

O Gunicorn escuta em `0.0.0.0:5000` (definido em `gunicorn.conf.py`), independente do `PORT` do `.env`.

## Rodar com Docker

O `docker-compose.yml` sobe três serviços:

| Serviço | Porta | Função |
| --- | --- | --- |
| `web` | `5000` | API (build do `Dockerfile`) |
| `mongo` | `27017` | MongoDB 4.4 |
| `mailhog` | `8025` (UI) / `1025` (SMTP) | Inbox de e-mails de desenvolvimento |

```bash
docker compose up --build
```

A API fica em `http://localhost:5000`. A interface do MailHog fica em `http://localhost:8025`.

O Compose atual **não injeta** o `.env` automaticamente no serviço `web`. Para a API enxergar as variáveis, passe o arquivo na execução:

```bash
docker compose run --env-file .env --service-ports web
```

Ou rode a imagem isolada (Mongo precisa estar acessível em `MONGO_URI`):

```bash
docker build -t memobelc-api .
docker run -p 5000:5000 --env-file .env memobelc-api
```

Se o Mongo estiver no Compose, use o hostname `mongo` na URI, por exemplo `mongodb://mongo:27017/memobelc`.

## Documentação da API

Com a API no ar, abra o Swagger UI:

- [http://localhost:3005/doc](http://localhost:3005/doc) — se usou `python run.py` com `PORT=3005`
- [http://localhost:5000/doc](http://localhost:5000/doc) — Docker / Gunicorn

Use **Authorize** e informe `Bearer <seu_token>` (token retornado no login/registro) para testar rotas protegidas.

O spec também está em `/doc/swagger.json`.

## Módulos e rotas

Prefixos registrados em `src/app/routes/routes.py`:

| Prefixo | Módulo |
| --- | --- |
| `/auth` | Cadastro, login, JWT, recuperação de senha, logout |
| `/collections` | Coleções de baralhos |
| `/deck` | Baralhos (decks) |
| `/card` | Flashcards |
| `/video` | Vídeos |
| `/progress` | Progresso de estudo |
| `/chat` | Chat e geração de cartas via IA |
| `/classroom` | Salas de aula |
| `/notifications` | Notificações e tokens de push |
| `/streak` | Sequência de estudos |
| `/books` | Livros (fluxo admin e usuário) |
| `/invite` | Convites por e-mail e link |

Rotas protegidas exigem header:

```http
Authorization: Bearer <token>
```

## Testes

Os testes usam **sempre** `MONGO_URI_TEST` (via `TESTING=1` em `src/test/conftest.py`). Não rode a suíte apontando para o banco oficial.

```bash
poetry run pytest
```

Arquivos em `src/test/` (`test_auth.py`, `test_cards.py`, `test_classroom.py`, etc.). Configuração do pytest está em `pyproject.toml`.

Lint (opcional):

```bash
poetry run pylint src
```

Formatação (Black já está nas dependências):

```bash
poetry run black src
```

## Protobuf

Os contratos em `src/app/proto/` geram código Python em `src/app/proto/pb/` com betterproto.

```bash
cd src/app/proto
protoc -I . --python_betterproto_out=./pb/ *.proto
```

Só é necessário quando os arquivos `.proto` mudarem.

## Produção

Em produção **não** use `python run.py`. Use Gunicorn:

```bash
gunicorn -c gunicorn.conf.py run:app
```

O `Dockerfile` já inicia a API assim, com usuário não-root.

Detalhes de workers, scheduler (lembretes diários), health check e checklist de deploy:

- [PRODUCTION.md](PRODUCTION.md) — Gunicorn, APScheduler, monitoramento e troubleshooting
- [DOKPLOY_SETUP.md](DOKPLOY_SETUP.md) — passo a passo no Dokploy (Dockerfile, env, domínio, SSL)

Health check sugerido: `GET /doc` (HTTP 200).

## Estrutura do projeto

```text
memobelc-api/
├── run.py                 # Entrada da aplicação (dev: Flask; prod: gunicorn run:app)
├── gunicorn.conf.py       # Workers, threads, timeout, logs
├── Dockerfile
├── docker-compose.yml     # API + MongoDB + MailHog
├── pyproject.toml         # Poetry + pytest
├── .env.example
├── PRODUCTION.md
├── DOKPLOY_SETUP.md
└── src/
    ├── app/
    │   ├── __init__.py    # Factory create_app(), CORS, Swagger, scheduler
    │   ├── config.py      # Variáveis de ambiente
    │   ├── controllers/   # Handlers HTTP
    │   ├── database/      # Conexão MongoDB
    │   ├── middlewares/   # JWT (token_required)
    │   ├── models/        # Modelos
    │   ├── proto/         # .proto e código gerado (pb/)
    │   ├── routes/        # Blueprints
    │   ├── services/      # Regras de negócio
    │   ├── static/        # swagger.json
    │   └── templates/
    └── test/              # pytest (usa MONGO_URI_TEST)
```

## Comandos úteis

```bash
# Dependências
poetry install

# Dev
poetry run python run.py

# Produção local
poetry run gunicorn -c gunicorn.conf.py run:app
poetry run gunicorn --check-config -c gunicorn.conf.py run:app

# Testes
poetry run pytest

# Docker
docker compose up --build
docker compose up -d mongo mailhog
```
