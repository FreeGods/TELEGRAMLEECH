## 🔐 Renovação Automática de Tokens Supabase - Guia Técnico

### 📝 Resumo da Implementação

O sistema Anitsu agora implementa **renovação automática de tokens Supabase** sem necessidade de reenviar manualmente os cookies. Isso resolve o problema onde usuários recebiam erro `401 - Sessão Expirada` após 1 hora de inatividade.

---

## 🏗️ Arquitetura

### Componentes Principais

1. **SupabaseTokenManager** (`bot/helper/ext_utils/supabase_token_manager.py`)
   - Responsável por extrair, validar e renovar tokens Supabase
   - Gerencia ciclo de vida dos tokens (access + refresh)

2. **AnitsuClient** (atualizado em `bot/helper/ext_utils/anitsu_client.py`)
   - Integração do token manager
   - Chamada automática de `ensure_valid_token()` antes de requisições

---

## 🔄 Fluxo de Renovação de Token

```
Usuário faz requisição (ex: /anitsuleech)
         ↓
   AnitsuClient._get()
         ↓
   Verifica: token_manager.is_token_valid()
         ↓
   ┌──────────────────────────┐
   │   Token é válido?        │
   └──────────────────────────┘
   Sim ↓          Não ↓
      │           token_manager.refresh_access_token()
      │                ↓
      │           POST {backend}/auth/v1/token
      │           Body: { "refresh_token": "..." }
      │                ↓
      │           Supabase retorna:
      │           {
      │             "access_token": "novo_...",
      │             "refresh_token": "novo_...",
      │             "expires_at": 1771...,
      │             "expires_in": 3600
      │           }
      │                ↓
      │           Salva novos tokens em memória
      │                ↓
   Usa token        ↓
   válido ◄─────────┘
      ↓
   headers["Authorization"] = "Bearer {access_token}"
      ↓
   Requisição GET → nuvem.anitsu.moe/api/...
      ↓
   Resposta com sucesso
```

---

## 🔍 Extração de Tokens dos Cookies

### Formato Esperado

Supabase armazena tokens em cookies divididos em partes:

```
sb-{PROJECT_ID}-auth-token.0 = "{"access_token":"eyJ..."
sb-{PROJECT_ID}-auth-token.1 = "...","refresh_token":"huiwbche62qj"..."
```

### Processo de Reconstrução

1. Token Manager busca cookies com padrão `sb-*-auth-token.*`
2. Encontra o PROJECT_ID do padrão
3. Ordena as partes (0, 1, 2...) e concatena
4. Faz parse como JSON
5. Extrai `access_token`, `refresh_token`, `expires_at`

---

## 🚀 Como Funciona na Prática

### Antes (Sistema Antigo)
```
Usuário exporta cookies → envia arquivo → ... (1 hora) ...
→ Acesso expira → Erro 401 → Precisa reexportar cookies
```

### Depois (Sistema Novo)
```
Usuário exporta cookies → Envia arquivo → ... (qualquer tempo) ...
→ Token vai expirar? → Renovação automática com refresh_token
→ Acesso continua funcionando indefinidamente ✅
```

---

## 📋 Métodos do SupabaseTokenManager

### `is_token_valid(buffer_seconds=300)`
- **O que faz**: Verifica se access token ainda é válido
- **Parâmetro**: buffer_seconds = segundos antes da expiração real para começar refresh
- **Retorna**: `bool`

```python
# Exemplo
if token_manager.is_token_valid():
    print("Token é válido")
else:
    print("Token expirado, precisa renovar")
```

### `async ensure_valid_token()`
- **O que faz**: Garante token válido (renovando se necessário)
- **Retorna**: `bool` - True se token é válido (original ou renovado)

```python
# Exemplo (em função async)
if await token_manager.ensure_valid_token():
    # Fazer requisição com token seguro
    headers["Authorization"] = token_manager.get_authorization_header()
```

### `async refresh_access_token()`
- **O que faz**: Renova access token usando refresh token
- **Faz**: POST para `{backend}/auth/v1/token?grant_type=refresh_token`
- **Retorna**: `bool` - True se renovação foi bem-sucedida

```python
# Exemplo
success = await token_manager.refresh_access_token()
if success:
    print("Token renovado! Novos tokens em memory")
```

### `get_authorization_header()`
- **O que faz**: Retorna header pronto para usar
- **Retorna**: `"Bearer {access_token}"` ou None

```python
# Exemplo
header_value = token_manager.get_authorization_header()
headers["Authorization"] = header_value
```

---

## 📊 Integração com AnitsuClient

### Método `.get_token_status()`

Novo método para obter status dos tokens:

```python
client = get_anitsu_client()
status = client.get_token_status()

# Retorna:
{
    "has_tokens": True,
    "token_valid": True,
    "access_token": "eyJ0eXAiOiJKV1QiLCJhbG...",
    "refresh_token": "huiwbche62q...",
    "project_id": "qzrxxwizigfdcpmwkztq",
    "expires_at": 1771812360,   # Unix timestamp
    "expires_in_hours": 0.95    # Horas até expiração
}
```

### Método `_get()` (atualizado)

Agora chamado de forma automática em toda requisição:

```python
async def _get(self, endpoint: str, params: Dict) -> Dict:
    # 1. Chama ensure_valid_token() automaticamente
    if self._token_manager:
        await self._token_manager.ensure_valid_token()
    
    # 2. Se token foi renovado, usa novo Authorization header
    auth_header = self._token_manager.get_authorization_header()
    headers["Authorization"] = auth_header
    
    # 3. Faz requisição com token válido
    resp = await client.get(...)
```

---

## 🔧 Tratamento de Erros

### Erro 401 - Sessão Expirada

**Caso 1**: Token expirado e refresh falhou
- **Causa**: Refresh token também expirou ou foi revogado
- **Solução**: Usuário deve reexportar cookies

**Caso 2**: Cookies não contêm tokens Supabase
- **Causa**: Cookie foi exportado de conta não-autenticada
- **Solução**: Fazer login em nuvem.anitsu.moe antes de exportar

---

## 📝 Logging e Debug

### O que verificar nos logs

```log
# ✅ Sucesso
[SupabaseTokenManager] ✅ Tokens extraídos com sucesso
[SupabaseTokenManager] Project ID Supabase: qzrxxwizigfdcpmwkztq
[SupabaseTokenManager] Access Token: eyJ0eXAiOiJKV1Qi...
[SupabaseTokenManager] Token valid for 0.95 hours

# Durante renovação
[SupabaseTokenManager] 🔄 Renovando access token...
[SupabaseTokenManager] ✅ Tokens renovados com sucesso!
[SupabaseTokenManager] Novo Access Token: eyJ0eXAiOiJKV1Qi...

# ❌ Problemas
[SupabaseTokenManager] Nenhum cookie de autenticação encontrado
[SupabaseTokenManager] Access token expirado ou prestes a expirar
```

---

## 🧪 Testando o Sistema

### Teste 1: Verificar Extração de Tokens

```python
from bot.helper.ext_utils.anitsu_client import get_anitsu_client

client = get_anitsu_client()
status = client.get_token_status()

print(status)
# Deve mostrar tokens extraídos com sucesso
```

### Teste 2: Verificar Renovação Automática

```python
import asyncio
from bot.helper.ext_utils.anitsu_client import get_anitsu_client

async def test_refresh():
    client = get_anitsu_client()
    
    # Simular múltiplas requisições
    for i in range(3):
        result = await client.search("naruto")
        print(f"Requisição {i}: OK")
        await asyncio.sleep(1)

asyncio.run(test_refresh())
# Deve completar sem erros 401
```

### Teste 3: Verificar Token Válido

```python
async def test_token_validity():
    client = get_anitsu_client()
    
    # Antes de renovação
    before = client.get_token_status()
    print(f"Token válido antes: {before['token_valid']}")
    
    # Força refresh
    await client._token_manager.ensure_valid_token()
    
    # Depois de renovação
    after = client.get_token_status()
    print(f"Token válido depois: {after['token_valid']}")
```

---

## 📋 Comparação: Antes vs. Depois

| Aspecto | Antes | Depois |
|---------|-------|--------|
| **Expiração de Token** | Erro 401 depois de 1h | Renovação automática |
| **Intervenção do Usuário** | Reexportar cookies | Nenhuma |
| **Tipo de Autenticação** | Apenas cookies | Cookies + Authorization header |
| **Tratamento de Erro** | Falha completa | Tenta renovar automaticamente |
| **Status de Token** | Desconhecido | Visível via `get_token_status()` |
| **Logs** | Mínimos | Detalhados |

---

## 🎯 Fluxo Completo de Uso

1. **Setup**
   ```bash
   # Usuario exporta cookies de nuvem.anitsu.moe
   # Envia arquivo via /bsettings → Private Files
   ```

2. **Primeira Requisição**
   ```
   /anitsuleech search "naruto"
        ↓
   AnitsuClient carrega cookies
        ↓
   SupabaseTokenManager extrai tokens
        ↓
   busca é executada
   ```

3. **Próximas Requisições (mesma sessão)**
   ```
   Qualquer comando anitsu
        ↓
   Token manager verifica validade
        ↓
   Token é renovado? (Se expirando)
        ↓
   Requisição é feita com token válido
   ```

4. **Sem Reenvio de Arquivo**
   ```
   A menos que refresh_token expire (muito tempo depois)
   Sistema continua funcionando indefinidamente
   ```

---

## 🔐 Segurança

### O que é protegido?

✅ Access Token (curta duração)
✅ Refresh Token (renovado automaticamente)
✅ Project ID (extraído automaticamente dos cookies)

### O que o usuário precisa confiar?

✅ O arquivo de cookies foi exportado corretamente
✅ Cookies contêm tokens válidos

### Nota sobre armazenamento

⚠️ Os tokens são mantidos **em memória apenas**
⚠️ Não são salvos em arquivo ou banco de dados
⚠️ Expiram quando o bot reinicia

---

## 📞 Troubleshooting

| Problema | Causa | Solução |
|----------|-------|---------|
| "Sessão expirada (401)" | Tokens não foram extraídos | Verificar se cookies contêm `sb-*-auth-token` |
| "Nenhum cookie Supabase encontrado" | Cookie sem autenticação | Fazer login antes de exportar |
| Renovação continua falhando | Refresh token revogado | Reexportar cookies |
| Token sempre "inválido" | Erro na estrutura do cookie | Exportar novamente em formato Netscape |

---

**Última atualização**: 2026-02-23  
**Status**: ✅ Implementado e Testado
