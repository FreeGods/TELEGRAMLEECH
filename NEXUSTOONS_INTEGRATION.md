# Integração Nexus Toons - Documentação

## 📋 Alterações Realizadas

### 1. **Novo módulo: `nexustoons_utils.py`**
   - **Localização**: [bot/helper/ext_utils/nexustoons_utils.py](bot/helper/ext_utils/nexustoons_utils.py)
   - **Classe**: `NexusToonsDownloader`
   - **Funcionalidades**:
     - ✅ Busca de mangás por termo via API JSON
     - ✅ Listagem de capítulos com números
     - ✅ Extração de informações do mangá
     - ✅ Download de capítulos em formato CBZ
     - ✅ Suporte a múltiplas páginas por capítulo

### 2. **Modificações em `mangaleech.py`**
   - **Localização**: [bot/modules/mangaleech.py](bot/modules/mangaleech.py)
   - **Alterações**:
     - Adicionado import de `NexusToonsDownloader`
     - Adicionado botão "🌐 Nexus Toons" na seleção de fontes
     - Modificada função `manga_source_callback()` para criar downloader apropriado
     - Adaptada função `manga_mode_callback()` para mostrar exemplo de URL/slug correto
     - Modificada função `_handle_search_link_input()` para:
       - Aceitar URLs do Nexus Toons (nexustoons.com/manga/...)
       - Aceitar slug direto (solo-leveling)
       - Extrair slug de URLs completas
     - Modificada função `_handle_chapter_input()` para:
       - Extrair números de capítulos corretamente do Nexus Toons (dictos)
       - Passar dados de capítulos apropriadamente para download

## 📊 Comparação de Fontes

| Característica | Flower | Nine Manga | Nexus Toons |
|---|---|---|---|
| **URL Base** | flowermangas.net | br.ninemanga.com | nexustoons.com |
| **API** | HTML Scraping | HTML Scraping | JSON REST |
| **Chapters** | Array de strings | Array de dicts | Array de dicts |
| **Identificador** | URL completa | URL completa | Slug |
| **Confiabilidade** | Média | Baixa (Cloudflare) | **Alta (API)** |

### Estruturas de Dados

**Flower Mangas:**
```python
chapters = [
    "https://flowermangas.net/manga/solo-leveling/capitulo-1/",
    "https://flowermangas.net/manga/solo-leveling/capitulo-2/",
]
```

**Nine Manga:**
```python
chapters = [
    {"url": "https://br.ninemanga.com/chapter/...", "id": "123", "number": 1.0},
    {"url": "https://br.ninemanga.com/chapter/...", "id": "124", "number": 2.0},
]
```

**Nexus Toons:**
```python
chapters = [
    {"id": "abc123", "number": 1.0, "title": "Chapter 1"},
    {"id": "abc124", "number": 2.0, "title": "Chapter 2"},
]
```

## 🚀 Como Usar

### Via Telegram Bot
```
/mangaleech             # Inicia o comando
↓
Escolha a fonte → "🌐 Nexus Toons"
↓
Escolha modo → "🔍 Pesquisar" ou "🔗 Link direto"
↓
Digite nome ou link/slug
↓
Digite intervalo de capítulos (ex: 1-5, 10, 15-20 ou "todos")
```

### Exemplos de Entrada

**Modo Pesquisa:**
- Digitar: "Solo Leveling"
- Bot busca e mostra resultados
- Você seleciona o resultado

**Modo Link Direto:**
- URL completa: `https://nexustoons.com/manga/solo-leveling`
- URL sem protocolo: `nexustoons.com/manga/solo-leveling`
- Apenas slug: `solo-leveling`

### Intervalo de Capítulos
- `1` - Apenas capítulo 1
- `1-5` - Capítulos 1 a 5
- `10` - Apenas capítulo 10
- `todos` - Todos os capítulos disponíveis

## 🔧 Detalhes Técnicos

### Headers HTTP
```python
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36...",
    "Accept": "application/json",  # JSON API
    "Accept-Language": "pt-BR,pt;q=0.9",
    "Referer": "https://nexustoons.com/",
}
```

### Endpoints da API

1. **Buscar** (GET):
   ```
   /api/mangas?search=termo
   
   Resposta:
   {
       "data": [
           {
               "id": "123",
               "title": "Solo Leveling",
               "slug": "solo-leveling",
               "chapterCount": 200,
               "cover": "https://..."
           }
       ]
   }
   ```

2. **Listar Capítulos** (GET):
   ```
   /api/mangas/{slug}
   
   Resposta:
   {
       "title": "Solo Leveling",
       "chapters": [
           {
               "id": "ch1",
               "number": 1.0,
               "title": "Chapter 1"
           }
       ]
   }
   ```

3. **Obter Capítulo** (GET):
   ```
   /api/chapter/{chapter_id}
   
   Resposta:
   {
       "id": "ch1",
       "number": 1.0,
       "pages": [
           {
               "pageNumber": 1,
               "imageUrl": "https://..."
           }
       ]
   }
   ```

### Extração de Imagens
- Acessa cada página via `imageUrl` do JSON
- Respeita os headers de referer e Accept-Type
- Detecta extensão automaticamente da URL
- Compacta em arquivo CBZ com índice numérico

### Nomeação de Arquivos CBZ
```
cap_001234.5.cbz  (para capítulo 1234.5)
cap_000001.0.cbz  (para capítulo 1)
```

## 📝 Arquivos Modificados

| Arquivo | Tipo | Descrição |
|---------|------|-----------|
| bot/helper/ext_utils/nexustoons_utils.py | ✨ Novo | Implementação completa do downloader Nexus Toons |
| bot/modules/mangaleech.py | 📝 Modificado | Integração com UI e handlers |
| exemplo_nexustoons.py | 📚 Novo | Exemplos de uso do NexusToonsDownloader |

## ⚙️ Dependências

Utiliza as mesmas dependências do projeto:
- `httpx` - Requisições HTTP async (suporta JSON)
- `aiofiles` - Operações de arquivos async
- `zipfile` - Criação de arquivos CBZ
- `pyrogram` - API do Telegram

## 🎯 Vantagens do Nexus Toons

✅ **API JSON** - Mais rápido que scraping HTML
✅ **Sem Proteção Cloudflare** - Acesso direto e confiável
✅ **Estrutura Consistente** - Resposta JSON padronizada
✅ **Melhor Performance** - Menos processamento de dados
✅ **Mais Confiável** - Menos sujeito a mudanças de layout

## ⚠️ Considerações

- **Delay**: 0.3s entre requisições (menor que alternativas pois é API)
- **Timeout**: 30 segundos por requisição
- **Compatibilidade**: Mesmo rating de capítulos que Nine Manga (formato dict)
- **Slugs**: Geralmente em formato kebab-case (solo-leveling)

## 📢 Mensagens ao Usuário

O bot informa:
- 🔍 Resultados da busca com título e slug
- 📊 Total de capítulos disponíveis
- 📍 Capítulo inicial e final
- 📝 Descrição do mangá
- ⏳ Progresso do download em tempo real (%)
- 📥 Capítulo sendo baixado
- ✅ Lista final com:
  - Nome do capítulo
  - Número de páginas
  - Tamanho em MB
  - Total agregado
- 📤 Progresso do upload para Telegram

## 🧪 Teste Rápido

```bash
python3 exemplo_nexustoons.py
```

## 🔄 Fluxo de Download

```
1. Usuário digita "/mangaleech"
2. Escolhe "🌐 Nexus Toons"
3. Escolhe "🔍 Pesquisar"
4. Digita "Solo Leveling"
5. Bot busca em /api/mangas?search=Solo%20Leveling
6. Mostra resultados com slugs
7. Usuário seleciona um resultado
8. Bot chama /api/mangas/{slug} para listar capítulos
9. Mostra primeiro, último e total de capítulos
10. Usuário digita "1-5"
11. Bot filtra capítulos 1 a 5
12. Para cada capítulo:
    - Chama /api/chapter/{id}
    - Baixa todas as imagens
    - Cria arquivo CBZ
13. Envia arquivos para Telegram
14. Limpa diretório temp
```

---

**Status**: ✅ Integração Completa e Funcional

**Vantagem**: Suporte a API JSON garante maior confiabilidade

**Data**: 14 de Fevereiro de 2026
