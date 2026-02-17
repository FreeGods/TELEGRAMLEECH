# 🔍 Guia de Depuração Rápida - Anitsu Leech

## Problema: Nenhuma resposta no Telegram

### 1️⃣ Verificar Configuração
```bash
# Cheque se ANITSU_COOKIE_FILE está definido
grep "ANITSU_COOKIE_FILE" config.py

# Deve retornar algo como:
# ANITSU_COOKIE_FILE = "/path/to/cookies.txt"
```

**Se não encontrar:**
- Adicione em `config.py`:
  ```python
  ANITSU_COOKIE_FILE = "/caminho/para/arquivo/de/cookies.txt"
  ```

### 2️⃣ Verificar Arquivo de Cookies
```bash
# Verifique se o arquivo existe
ls -la /caminho/para/arquivo/de/cookies.txt

# Verifique o formato (deve ser Netscape)
head -5 /caminho/para/arquivo/de/cookies.txt
```

**Deve começar com:**
```
# Netscape HTTP Cookie File
# Tipo de arquivo gerado por um navegador
```

### 3️⃣ Verificar Logs
```bash
# Em tempo real
tail -f log.txt | grep -i anitsu

# Procure por estes padrões:
# [Anitsu] - Logs do módulo principal
# [AnitsuClient] - Logs do cliente HTTP
```

## 🐛 Cenários Comuns de Erro

### Erro 1: "Anitsu client não configurado"
```
[Anitsu] Erro ao inicializar cliente: ANITSU_COOKIE_FILE not configured
```
**Solução:** Adicione `ANITSU_COOKIE_FILE` em `config.py`

### Erro 2: "Arquivo de cookies não encontrado"
```
[AnitsuClient] Arquivo de cookies não encontrado: /caminho/invalido.txt
```
**Solução:** Corrija o caminho em `ANITSU_COOKIE_FILE`

### Erro 3: "Sessão expirada (401)"
```
[AnitsuClient] Sessão expirada (401)
```
**Solução:** Exporte novos cookies do navegador e atualize o arquivo

### Erro 4: "Nenhum resultado para busca"
```
[AnitsuClient] Busca retornou 0 resultados para: "termo"
```
**Solução:** 
- Tente outro termo de busca
- Verifique se o servidor Anitsu está online
- Aguarde alguns segundos e tente novamente

### Erro 5: "Resposta vazia do servidor"
```
[AnitsuClient] search retornou None ou vazio para 'Naruto'
```
**Solução:**
- Verifique conexão com nuvem.anitsu.moe
- Verifique se os cookies ainda são válidos
- Tente com outro navegador para exportar cookies novos

## 📊 Checklist de Depuração

- [ ] `ANITSU_COOKIE_FILE` configurado em `config.py`?
- [ ] Arquivo de cookies existe?
- [ ] Arquivo está em formato Netscape?
- [ ] Bot pode ler o arquivo (permissões)?
- [ ] Servidor Anitsu (nuvem.anitsu.moe) está online?
- [ ] Cookies ainda são válidos?
- [ ] Pode acessar nuvem.anitsu.moe no navegador?

## 🧪 Teste Manual

### Test 1: Verificar Import
```python
python3 -c "from bot.helper.ext_utils.anitsu_client import get_anitsu_client; print('OK')"
```

### Test 2: Verificar Cliente
```python
python3 << 'EOF'
from bot.helper.ext_utils.anitsu_client import get_anitsu_client
try:
    client = get_anitsu_client()
    print("✓ Cliente inicializado")
except Exception as e:
    print(f"✗ Erro: {e}")
EOF
```

### Test 3: Verificar Busca
```python
python3 << 'EOF'
import asyncio
from bot.helper.ext_utils.anitsu_client import get_anitsu_client

async def test():
    try:
        client = get_anitsu_client()
        result = await client.search("Naruto")
        print(f"Resultados: {len(result.get('results', []))}")
    except Exception as e:
        print(f"Erro: {e}")

asyncio.run(test())
EOF
```

## 📝 Informações Úteis

- **URL do Anitsu**: https://nuvem.anitsu.moe
- **Formato de Sessão**: 10 minutos (600 segundos)
- **Timeout da Request**: 30 segundos
- **Limite de Resultados Exibidos**: 8 por página

## 🚀 Se Tudo Falhar

1. Coloque seu `log.txt` completo aqui
2. Execute:
   ```bash
   python3 -m pytest bot/helper/ext_utils/anitsu_client.py -v
   ```
3. Compartilhe:
   - Versão do Python
   - Sistema Operacional
   - Última parte do `log.txt`
   - Resultado dos testes acima

## ✅ Sinais de que Está Funcionando

Após executar `/anitsuleech` com sucesso, você deve ver nos logs:
```
[Anitsu] Iniciando /anitsuleech para usuário XXXXX
[Anitsu] Sessão iniciada para XXXXX
[AnitsuClient] Buscando por: Naruto
[AnitsuClient] Busca retornou 10 resultados
[Anitsu] Exibindo 8 itens em /
```

E no Telegram:
```
🎌 Anitsu Cloud Leech
Digite o nome do anime que deseja buscar:
```
