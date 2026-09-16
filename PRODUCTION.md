# 🚀 Guia de Deploy em Produção

## ⚠️ AVISOS IMPORTANTES

### 1. NUNCA use `python run.py` em produção!
- O servidor de desenvolvimento do Flask NÃO é adequado para produção
- Consome MUITA CPU/memória
- Processa apenas 1 requisição por vez
- Debug mode expõe código-fonte e variáveis sensíveis

### 2. SEMPRE use Gunicorn em produção!
```bash
gunicorn -c gunicorn.conf.py run:app
```

---

## 📋 Configuração no Dokploy com Railpack

### Método 1: Usando Dockerfile (RECOMENDADO)

```yaml
Build Method: Dockerfile
Port: 5000
Health Check: /doc
```

O Dockerfile já está configurado para produção! ✅

### Método 2: Usando Buildpack

```yaml
Build Command: poetry install --only main
Start Command: gunicorn -c gunicorn.conf.py run:app
Port: 5000
```

---

## 🔧 Variáveis de Ambiente Necessárias

Configure no Dokploy:

```bash
# Banco de dados
MONGO_URI=mongodb://seu_mongo_uri

# API Keys
GENAI_API_KEY=sua_chave_google_ai
GENAI_MODEL=gemini-pro

ASAAS_API_KEY=
ASAAS_API_URL=https://api.asaas.com/v3
ASAAS_WEBHOOK_TOKEN=
GOOGLE_PLAY_PACKAGE_NAME=com.anonymous.memobelc
GOOGLE_PLAY_SERVICE_ACCOUNT_JSON=
GOOGLE_PLAY_RTDN_TOKEN=
SECRET_KEY=sua_chave_secreta_super_segura_aqui

# Email (SMTP)
MAIL_SERVER=smtp.gmail.com
MAIL_PORT=587
MAIL_USERNAME=seu@email.com
MAIL_PASSWORD=sua_senha_app
MAIL_DEFAULT_SENDER=seu@email.com

# Frontend
FRONT_BASE_URL=https://seusite.com

# Porta
PORT=5000

# Scheduler (IMPORTANTE!)
ENABLE_DAILY_REMINDERS=true

# Gunicorn (opcional - tem defaults)
GUNICORN_WORKERS=2
GUNICORN_THREADS=4

# Flask (NÃO definir em produção = fica em production por padrão)
# FLASK_DEBUG=false
```

---

## ⚙️ Configurações do Gunicorn

O arquivo `gunicorn.conf.py` já está configurado com:

- **Workers**: 2 (padrão), configurável via `GUNICORN_WORKERS`
- **Threads**: 4 por worker (padrão), configurável via `GUNICORN_THREADS`
- **Worker Class**: `gthread` (ideal para I/O bound - APIs com DB)
- **Timeout**: 120 segundos
- **Max Requests**: 1000 (previne memory leaks)
- **Preload App**: True (economiza memória)

### Como calcular Workers:

```python
# Fórmula: (2 x CPU cores) + 1
# Exemplos:
# - 1 core: 2-3 workers
# - 2 cores: 4-5 workers
# - 4 cores: 8-9 workers

# NO DOKPLOY, comece com:
GUNICORN_WORKERS=2  # Para máquinas com 1-2 CPUs
GUNICORN_WORKERS=4  # Para máquinas com 2-4 CPUs
```

### Capacidade de Conexões Simultâneas:

```
Total = Workers × Threads
Exemplo: 2 workers × 4 threads = 8 requisições simultâneas
```

---

## 🔄 APScheduler e Múltiplos Workers

### O PROBLEMA:
Com múltiplos workers do gunicorn, cada worker executaria o scheduler, causando **notificações duplicadas**!

### SOLUÇÃO IMPLEMENTADA:
O código verifica se é o worker principal antes de iniciar o scheduler:

```python
is_main_worker = os.environ.get("GUNICORN_WORKER_ID") in (None, "1")
if is_scheduler_enabled and is_main_worker:
    scheduler.start()  # Roda apenas 1 vez!
```

### Alternativa (se tiver problemas):
Desabilitar em todos os workers e usar um processo separado:

```bash
# No Dokploy, criar 2 serviços:

# Serviço 1: API (sem scheduler)
ENABLE_DAILY_REMINDERS=false
gunicorn -c gunicorn.conf.py run:app

# Serviço 2: Scheduler (1 worker apenas)
ENABLE_DAILY_REMINDERS=true
gunicorn -w 1 -c gunicorn.conf.py run:app
```

---

## 📊 Monitoramento

### Logs
O gunicorn já está configurado para enviar logs para stdout/stderr:
```bash
# No Dokploy, veja logs em tempo real
docker logs -f <container_id>
```

### Métricas importantes:
1. **CPU Usage**: Se passar de 70%, aumente workers
2. **Memory Usage**: Cada worker consome ~100-200MB
3. **Response Time**: Se aumentar, considere mais threads
4. **Error Rate**: Monitore erros 500

### Health Check:
```bash
curl https://sua-api.com/doc
# Deve retornar 200 OK
```

---

## 🐛 Troubleshooting

### CPU estourando:
```bash
# Reduza workers:
GUNICORN_WORKERS=2
```

### Memória estourando:
```bash
# Reduza workers OU threads:
GUNICORN_WORKERS=2
GUNICORN_THREADS=2
```

### Timeout em requisições longas:
```bash
# Aumente timeout no gunicorn.conf.py:
timeout = 300  # 5 minutos
```

### Notificações duplicadas:
```bash
# Verifique logs:
# Deve aparecer apenas 1x: "✅ APScheduler iniciado no worker principal"
# Se aparecer 2x ou mais, o scheduler está rodando em múltiplos workers!

# Solução: Usar processo separado (ver seção "APScheduler")
```

### Erro de conexão com MongoDB:
```bash
# Verifique se o MONGO_URI está correto
# Verifique se o MongoDB aceita conexões da sua VPC/IP do Dokploy
```

---

## 🔒 Segurança

### ✅ Já implementado:
- [x] Usuário não-root no Docker (appuser)
- [x] Debug mode desabilitado em produção
- [x] Secrets via variáveis de ambiente
- [x] CORS configurado
- [x] Timeout para prevenir DoS

### 🔐 Recomendações adicionais:
- [ ] Use HTTPS (configure no Dokploy/Nginx)
- [ ] Configure rate limiting (nginx ou Flask-Limiter)
- [ ] Monitore logs de acesso
- [ ] Use MongoDB com autenticação forte
- [ ] Rotate secrets regularmente
- [ ] Configure firewall para MongoDB (apenas IP do servidor)

---

## 📦 Checklist de Deploy

Antes de fazer deploy:

- [ ] Todas as variáveis de ambiente configuradas
- [ ] MONGO_URI aponta para banco de PRODUÇÃO
- [ ] SECRET_KEY é diferente do desenvolvimento
- [ ] ASAAS_API_KEY e ASAAS_WEBHOOK_TOKEN de produção
- [ ] Webhook Asaas apontando para /billing/asaas/webhook
- [ ] ENABLE_DAILY_REMINDERS=false OU configuração de worker único
- [ ] Health check configurado no Dokploy
- [ ] Logs sendo monitorados
- [ ] Backup do MongoDB configurado

---

## 🚀 Comandos Úteis

### Desenvolvimento local:
```bash
# Com Poetry
poetry install
poetry run python run.py

# Ou ativar venv
poetry shell
python run.py
```

### Testar gunicorn localmente:
```bash
gunicorn -c gunicorn.conf.py run:app
```

### Verificar configuração:
```bash
gunicorn --check-config -c gunicorn.conf.py run:app
```

### Build Docker localmente:
```bash
docker build -t memobelc-api .
docker run -p 5000:5000 --env-file .env memobelc-api
```

---

## 📚 Referências

- [Gunicorn Documentation](https://docs.gunicorn.org/)
- [Flask Production Best Practices](https://flask.palletsprojects.com/en/stable/deploying/)
- [APScheduler Documentation](https://apscheduler.readthedocs.io/)
