# 🚀 Guia Rápido - Deploy no Dokploy

## 📋 Passo a Passo

### 1. Criar Novo Projeto no Dokploy

```
Nome: memobelc-api
Tipo: Application
Método: Dockerfile (ou Git Repository)
```

### 2. Configuração do Build

#### Se usar Dockerfile (RECOMENDADO):
```yaml
Build Method: Dockerfile
Dockerfile Path: ./Dockerfile
Context: .
Port: 5000
```

#### Se usar Buildpack:
```yaml
Build Command: poetry install --only main
Start Command: gunicorn -c gunicorn.conf.py run:app
Port: 5000
```

### 3. Variáveis de Ambiente (COPIE E COLE)

```bash
# ==========================================
# BANCO DE DADOS
# ==========================================
MONGO_URI=mongodb://seu_usuario:sua_senha@seu_host:27017/nome_banco?authSource=admin

# ==========================================
# GOOGLE AI (Gemini)
# ==========================================
GENAI_API_KEY=sua_chave_aqui
GENAI_MODEL=gemini-pro



# ==========================================
# SEGURANÇA
# ==========================================
SECRET_KEY=gere_uma_chave_super_secreta_aqui_com_pelo_menos_32_caracteres_aleatorios

# ==========================================
# EMAIL (SMTP)
# ==========================================
MAIL_SERVER=smtp.gmail.com
MAIL_PORT=587
MAIL_USERNAME=seu@email.com
MAIL_PASSWORD=sua_senha_app_google
MAIL_DEFAULT_SENDER=seu@email.com

# ==========================================
# FRONTEND
# ==========================================
FRONT_BASE_URL=https://seusite.com

# ==========================================
# SERVIDOR
# ==========================================
PORT=5000

# ==========================================
# SCHEDULER (NOTIFICAÇÕES)
# ==========================================
ENABLE_DAILY_REMINDERS=true

# ==========================================
# GUNICORN (OPCIONAL - TEM DEFAULTS)
# ==========================================
GUNICORN_WORKERS=2
GUNICORN_THREADS=4
```

### 4. Health Check

```yaml
Health Check Path: /doc
Health Check Interval: 30
Health Check Timeout: 10
Health Check Retries: 3
```

### 5. Domínio (Opcional)

```yaml
Domain: api.seusite.com
SSL: Automatic (Let's Encrypt)
```

---

## 🔑 Como Gerar SECRET_KEY

```bash
# No terminal:
python -c "import secrets; print(secrets.token_urlsafe(32))"

# OU
openssl rand -base64 32
```

---

## 📧 Configurar Gmail SMTP

### 1. Ativar 2FA no Gmail:
https://myaccount.google.com/security

### 2. Criar Senha de App:
1. Vá em: https://myaccount.google.com/apppasswords
2. Selecione "Outro (nome personalizado)"
3. Digite: "Memobelc API"
4. Clique em "Gerar"
5. Copie a senha gerada (16 caracteres)
6. Use em `MAIL_PASSWORD`

### 3. Configuração:
```bash
MAIL_SERVER=smtp.gmail.com
MAIL_PORT=587
MAIL_USERNAME=seu@gmail.com
MAIL_PASSWORD=xxxx xxxx xxxx xxxx  # Senha de app gerada
MAIL_DEFAULT_SENDER=seu@gmail.com
```

---

## 🔍 Comandos para Debugging

### Ver logs em tempo real:
```bash
dokploy logs memobelc-api -f
```

### Entrar no container:
```bash
dokploy exec memobelc-api /bin/bash
```

### Verificar variáveis de ambiente:
```bash
dokploy exec memobelc-api env | grep -E "MONGO_URI|PORT|GUNICORN"
```

### Verificar processos:
```bash
dokploy exec memobelc-api ps aux
```

### Testar saúde da API:
```bash
curl https://api.seusite.com/doc
```

---

## 📊 Monitoramento

### Métricas importantes:

```bash
# CPU Usage (deve ficar < 70%)
dokploy stats memobelc-api

# Memory Usage (cada worker ~100-200MB)
dokploy stats memobelc-api

# Logs de erro
dokploy logs memobelc-api --tail 100 | grep ERROR

# Logs do scheduler
dokploy logs memobelc-api | grep "APScheduler"
```

---

## 🐛 Troubleshooting Comum

### Erro: "Connection refused" no MongoDB

**Problema**: MongoDB não aceita conexões do servidor

**Solução**:
1. Verificar se MONGO_URI está correto
2. Adicionar IP do servidor Dokploy no whitelist do MongoDB
3. Se usar MongoDB Atlas: permitir acesso de qualquer IP (0.0.0.0/0) temporariamente

```bash
# Testar conexão manualmente:
dokploy exec memobelc-api python -c "from pymongo import MongoClient; MongoClient('$MONGO_URI').admin.command('ping')"
```

### Erro: CPU a 100%

**Problema**: Muitos workers para a CPU disponível

**Solução**: Reduzir workers
```bash
GUNICORN_WORKERS=1
GUNICORN_THREADS=2
```

### Erro: Memory limit exceeded

**Problema**: Muitos workers consumindo memória

**Solução**: Reduzir workers ou aumentar limite
```bash
GUNICORN_WORKERS=2
# OU aumentar limite de memória no Dokploy
```

### Erro: 502 Bad Gateway

**Problema**: Timeout nas requisições

**Solução**: Aumentar timeout no `gunicorn.conf.py`:
```python
timeout = 300  # 5 minutos
```

### Notificações duplicadas

**Problema**: Scheduler rodando em múltiplos workers

**Solução 1**: Verificar logs
```bash
dokploy logs memobelc-api | grep "APScheduler"
# Deve aparecer apenas 1x: "✅ APScheduler iniciado no worker principal"
```

**Solução 2**: Forçar 1 worker para scheduler
```bash
# Criar serviço separado ou definir:
GUNICORN_WORKERS=1  # Temporariamente
```

### Erro: "Module not found"

**Problema**: Dependências não instaladas

**Solução**: Verificar se está usando `--only main`
```bash
# No Dockerfile ou build command:
poetry install --only main --no-interaction --no-ansi
```

---

## ✅ Checklist Pré-Deploy

Antes de fazer o deploy, verifique:

- [ ] Dockerfile existe e está correto
- [ ] gunicorn.conf.py existe
- [ ] Todas as variáveis de ambiente configuradas
- [ ] MONGO_URI aponta para banco de produção (não dev!)
- [ ] SECRET_KEY é diferente do desenvolvimento
- [ ] Email SMTP configurado com senha de app
- [ ] FRONT_BASE_URL aponta para domínio correto
- [ ] Health check configurado
- [ ] Domínio e SSL configurados (opcional)
- [ ] Backup do MongoDB configurado

---

## 🚦 Checklist Pós-Deploy

Após deploy, verifique:

- [ ] API está respondendo: `curl https://api.seusite.com/doc`
- [ ] Swagger está funcionando no navegador
- [ ] Logs não mostram erros: `dokploy logs memobelc-api`
- [ ] MongoDB conectado (sem erros de conexão nos logs)
- [ ] Scheduler iniciou apenas 1x (ver nos logs)
- [ ] CPU usage normal (< 70%)
- [ ] Memory usage normal (< 80% do limite)
- [ ] Testar endpoint de login/cadastro
- [ ] Receber email de teste

---

## 📞 Comandos Úteis

### Reiniciar aplicação:
```bash
dokploy restart memobelc-api
```

### Ver última build:
```bash
dokploy builds memobelc-api --last
```

### Rollback para versão anterior:
```bash
dokploy rollback memobelc-api
```

### Escalar workers (se suportado):
```bash
dokploy scale memobelc-api --replicas 2
```

### Backup de variáveis de ambiente:
```bash
dokploy env export memobelc-api > memobelc-api.env
```

---

## 🎯 Configurações Recomendadas por Tamanho

### Pequeno (< 1000 usuários):
```bash
GUNICORN_WORKERS=2
GUNICORN_THREADS=4
# Total: 8 conexões simultâneas
# Memória: ~200-400MB
```

### Médio (1000-10000 usuários):
```bash
GUNICORN_WORKERS=4
GUNICORN_THREADS=4
# Total: 16 conexões simultâneas
# Memória: ~400-800MB
```

### Grande (> 10000 usuários):
```bash
GUNICORN_WORKERS=8
GUNICORN_THREADS=2
# Total: 16 conexões simultâneas
# Memória: ~800MB-1.6GB
# Considerar múltiplas instâncias com load balancer
```

---

## 📚 Links Úteis

- **Dokploy Docs**: https://docs.dokploy.com
- **Gunicorn Docs**: https://docs.gunicorn.org
- **Flask Docs**: https://flask.palletsprojects.com
- **MongoDB Atlas**: https://www.mongodb.com/cloud/atlas

---

## 🆘 Suporte

Se tiver problemas:

1. Verifique os logs: `dokploy logs memobelc-api -f`
2. Verifique as variáveis: `dokploy env list memobelc-api`
3. Consulte o `PRODUCTION.md` para detalhes
4. Consulte o `EXPLICACAO_DEBUG_SCHEDULER.md` para entender conceitos
