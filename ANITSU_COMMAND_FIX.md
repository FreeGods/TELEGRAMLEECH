# Análise e Correção do Comando Anitsu

## 🔍 Problemas Identificados

### 1. **Falta de Suporte a Múltiplas Fontes de Cookie**
O comando anitsu tentava carregar o arquivo de cookie apenas de `Config.ANITSU_COOKIE_FILE`, que:
- Pode estar vazio ou não configurado
- Não considerava arquivos salvos via `botset private`
- Não tinha fallback para nomes padrão como `anitsu_cookies.txt`

### 2. **Desconexão entre botset private e Anitsu**
Embora `anitsu_cookies.txt` estivesse na lista de arquivos privados que podem ser salvos via botset:
- O arquivo era armazenado no MongoDB
- Era restaurado durante startup
- **MAS** o comando anitsu nunca tentava usar esse arquivo

### 3. **Sem Suporte a Cookies por Usuário**
Diferentemente de outros comandos (como mirror/leech) que suportam:
- Arquivos privados por usuário via `user_data`
- O comando anitsu usava apenas um arquivo global

## ✅ Soluções Implementadas

### 1. **Refatoração de `anitsu_client.py`**

#### Nova Estratégia de Busca de Cookie:
```python
# Prioridade:
1. Arquivo fornecido como parâmetro (para suporte por usuário)
2. Config.ANITSU_COOKIE_FILE (arquivo global configurado)
3. anitsu_cookies.txt (padrão salvo via botset private)
4. anitsu_cookies (sem extensão)
5. cookies.txt (nome comum alternativo)
```

#### Principais Mudanças:
- `__init__` agora aceita `cookie_file` opcional
- Adicionado método `_find_cookie_file()` para busca inteligente
- Melhorado tratamento de erros com mensagens mais claras
- Adicionado logging detalhado em cada etapa

#### Nova Assinatura:
```python
# Antes
def get_anitsu_client() -> AnitsuClient:
    # Usava apenas Config.ANITSU_COOKIE_FILE

# Depois
def get_anitsu_client(cookie_file: Optional[str] = None) -> AnitsuClient:
    # Tenta arquivo fornecido > Config > arquivos padrão
```

### 2. **Atualização de `anitsuleech.py`**

#### Principal Comando (`/anitsuleech`):
- Obtém arquivo de cookie do `user_data` se disponível
- Passa para `get_anitsu_client(cookie_file=...)`
- Mensagem de erro mais informativa com instruções de setup
- Logging aprimorado para debugging

#### Callbacks de Navegação:
- Nova função helper: `_get_anitsu_client_for_user(user_id)`
- Busca cookie específico do usuário automaticamente
- Fallback para cliente global se necessário
- Aplicada em 4 pontos críticos:
  - `_navigate_folder()` - navegação de pastas
  - `_handle_download_action()` - informações do arquivo
  - Download/Mirror triggers
  - `_handle_search()` - busca de animes

## 🚀 Como Usar (Guia Completo)

### Opção 1: Arquivo Global (Recomendado para Admins)

**1. Exportar cookies:**
- Abra https://nuvem.anitsu.moe no navegador
- Use extensão como "Cookie Editor"
- Exporte no formato **Netscape** (padrão)
- Salve como `anitsu_cookies.txt`

**2. Enviar via botset:**
```
/bsettings
→ Private Files
→ Add/Delete File
→ Envie o arquivo anitsu_cookies.txt
```

**Resultado:** Todos os usuários usarão o mesmo arquivo

### Opção 2: Arquivo por Usuário (Suporte Total)

**Cada usuário pode ter seu próprio cookie:**
```
/userset
→ Upload Cookie
→ Envie seu arquivo de cookies
```

O arquivo será armazenado em `user_data[user_id]["USER_COOKIE_FILE"]`

**Prioridade Automática:**
1. Se usuário tem cookie → usa seu arquivo
2. Senão → usa arquivo global do admin

### Opção 3: Arquivo na Config

Você pode definir explicitamente em `config.py`:
```python
ANITSU_COOKIE_FILE = "anitsu_cookies.txt"
```

## 📋 Fluxo de Carregamento

```
/anitsuleech chamado
    ↓
Obtém user_id
    ↓
Procura em user_data[user_id]["USER_COOKIE_FILE"]
    ├─ SE ENCONTRADO: passa para get_anitsu_client(cookie_file=...)
    └─ SE NÃO ENCONTRADO: chama get_anitsu_client() sem parâmetros
            ↓
        Procura em ordem:
        1. Config.ANITSU_COOKIE_FILE (se configurado)
        2. anitsu_cookies.txt (botset private)
        3. anitsu_cookies
        4. cookies.txt
            ↓
        SE NENHUM ENCONTRADO:
        → Erro informativo com instruções
        
        SE ENCONTRADO:
        → Carrega cookies
        → Inicializa cliente
        → Processa comando
```

## 🐛 Debugging

### Verificar se o arquivo foi carregado:
Procure nos logs por:
```
[AnitsuClient] Found cookie file: anitsu_cookies.txt
[AnitsuClient] 42 cookies carregados do arquivo
```

### Se receber erro 401 (Sessão Expirada):
```
[AnitsuClient] Status: 401
[AnitsuClient] Sessão expirada (401)
```

**Solução:** Exporte novos cookies e envie via botset

### Se nenhum arquivo for encontrado:
```
[AnitsuClient] Nenhum arquivo de cookies encontrado
```

**Soluções:**
1. Confirme que `anitsu_cookies.txt` existe
2. Ou defina `ANITSU_COOKIE_FILE` em config.py
3. Ou envie via `/bsettings → Private Files`

## 📊 Comparação: Antes vs Depois

| Aspecto | Antes | Depois |
|---------|-------|--------|
| Fontes de cookie | Apenas Config | 5 opções com fallback |
| Suporte per-usuário | ❌ Não | ✅ Sim |
| Integração botset | ❌ Ignorava arquivo | ✅ Prima automática |
| Mensagens de erro | ❌ Genérica | ✅ Informativa |
| Logging | ❌ Mínimo | ✅ Detalhado |
| Tratamento de erros | ❌ Para em erro | ✅ Tenta alternativas |

## 🔧 Mudanças Técnicas

### Arquivos Modifi cados:

#### 1. `bot/helper/ext_utils/anitsu_client.py`
- Classe `AnitsuClient.__init__()` - agora aceita `cookie_file` opcional
- Novo método `_find_cookie_file()` - busca inteligente
- Melhorado `_load_cookies()` - melhor tratamento de erros
- Atualizado `get_anitsu_client()` - suporta parâmetro `cookie_file`
- Atualizado `refresh_anitsu_client()` - suporta novo arquivo

#### 2. `bot/modules/anitsuleech.py`
- Nova função helper `_get_anitsu_client_for_user()` - asyncio-safe, busca por usuário
- Atualizado `anitsuleech()` - integrado com user_data
- Atualizado `_navigate_folder()` - usa client por usuário
- Atualizado `_handle_download_action()` - usa client por usuário
- Atualizado callbacks de download - usam client por usuário
- Atualizado `_handle_search()` - usa client por usuário

### Tecnicamente:
- ✅ Compatível com migrate de código existente
- ✅ Função `get_anitsu_client()` ainda funciona sem parâmetros
- ✅ Não quebra comandos que usam cliente singleton
- ✅ Adiciona novas capacidades sem remover antigas

## ⚠️ Notas Importantes

### 1. **Formato de Arquivo de Cookie**
- DEVE estar no formato **Netscape** (padrão de exportadores)
- Exemplo de primeira linha: `# Netscape HTTP Cookie File`
- **NÃO** funciona com formato JSON

### 2. **Expiração de Cookies**
- Se receber erro 401, cookies expiraram
- Solução: exporte novos cookies
- Pode acontecer após semanas/meses

### 3. **Permissions**
- Arquivo de cookie deve ser leve (<100KB)
- Será armazenado no MongoDB
- Será restaurado em cada startup

## 📞 Troubleshooting

| Erro | Causa | Solução |
|------|-------|---------|
| `Anitsu cookie file not found` | Nenhum arquivo configurado | Ver "Como Usar" acima |
| `Sessão expirada (401)` | Cookie expirado | Exporte novos cookies |
| `Erro de requisição` | Servidor Anitsu offline ou bloqueado | Tente mais tarde |
| `Resposta vazia` | Anime não encontrado | Tente outro nome |

## 🎯 Próximas Melhorias (Sugestões)

- [ ] Comando `/anitsurefresh` para recarregar cookies
- [ ] Dashboard de status do cookie (data de expiração)
- [ ] Suporte a cache de resultados
- [ ] Integração com database para histórico
- [ ] Suporte a múltiplos servidores Anitsu

---

**Última atualização:** 2026-02-22
**Status:** ✅ Funcional e Testado
