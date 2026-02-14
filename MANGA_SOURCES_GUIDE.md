# 📚 Guia Completo - Fontes de Mangá do Bot

## 📊 Comparativo de Fontes Disponíveis

| Feature | Flower Mangas | Nine Manga | Nexus Toons |
|---------|:-------------:|:----------:|:----------:|
| **Tecnologia** | Web Scraping | Web Scraping | API REST |
| **Proteção** | Sem | ⚠️ Cloudflare | ✅ Aberta |
| **Confiabilidade** | Média | Baixa | **Alta** |
| **Velocidade** | Média | Média | **Rápida** |
| **Cobertura** | Bom | Excelente | Excelente |
| **Status** | Ativo | Ativo | Ativo |

## 🌸 Flower Mangas
**URL Base**: https://flowermangas.net/

### Características
- Web scraping HTML
- Sem proteção especial
- URLs com estrutura `/manga/titulo/capitulo-numero/`
- Bom acervo de mangás em português

### Como Usar
```
Modo Pesquisa: Digitar nome do mangá
Modo Link: 
  - https://flowermangas.net/manga/solo-leveling/
  - flowermangas.net/manga/solo-leveling/
  - www.flowermangas.net/manga/solo-leveling/
```

### Exemplos de Busca
- "Kimetsu no Yaiba"
- "Berserk"
- "Attack on Titan"

---

## 🔥 Nine Manga
**URL Base**: https://br.ninemanga.com/

### Características
- Web scraping HTML
- ⚠️ Protegido por Cloudflare (pode bloquear bots)
- URLs com estrutura `/manga/Titulo.html` e `/chapter/Titulo/ID.html`
- Suporta capítulos com decimais (ex: 205.5)
- Excelente cobertura de mangás

### Como Usar
```
Modo Pesquisa: Digitar nome do mangá
Modo Link:
  - https://br.ninemanga.com/manga/Kimetsu+no+Yaiba.html
  - br.ninemanga.com/manga/Kimetsu+no+Yaiba.html
  - www.br.ninemanga.com/manga/Kimetsu+no+Yaiba.html
```

### Exemplos de Busca
- "Kimetsu no Yaiba"
- "Solo Leveling"
- "Tower of God"

### ⚠️ Limitação
O site usa proteção Cloudflare que pode bloquear:
- IPs de data centers
- IPs de dev containers
- Bots sem limite de taxa

**Funciona melhor em**: Redes residenciais com IP fixo

---

## 🌐 Nexus Toons
**URL Base**: https://nexustoons.com/

### Características
- API REST JSON (muito mais confiável!)
- Sem proteção Cloudflare
- Slugs em formato kebab-case (solo-leveling)
- Acesso direto disponível para todos

### Como Usar
```
Modo Pesquisa: Digitar nome do mangá
Modo Link/Slug:
  - https://nexustoons.com/manga/solo-leveling
  - nexustoons.com/manga/solo-leveling
  - solo-leveling (slug direto)
```

### Exemplos de Busca
- "Solo Leveling"
- "Tower of God"
- "Lookism"

### ✅ Vantagens
- API estruturada
- Resposta JSON padronizada
- Sem bloqueios de IP
- Mais rápido
- Mais confiável em IPs de data centers

---

## 🎯 Dicas de Uso

### Qual fonte usar?

| Situação | Recomendação |
|----------|--------------|
| **IP residencial** | Nine Manga (mais mangas) |
| **Data center/Dev** | Nexus Toons (mais confiável) |
| **Problemas de acesso** | Flower Mangas (alternativa) |
| **Produção** | Nexus Toons (melhor performance) |

### Buscas Comuns

**Isekai/Fantasia:**
- "Solo Leveling"
- "Sword Art Online"
- "Re:Zero"
- "That Time I Got Reincarnated as a Slime"

**Action/Shounen:**
- "Jujutsu Kaisen"
- "Demon Slayer"
- "My Hero Academia"
- "One Piece"

**Drama/Slice of Life:**
- "Kaguya-sama: Love is War"
- "A Place Further Than the Universe"
- "March Comes in Like a Lion"

---

## 📥 Intervalo de Capítulos

Todas as fontes suportam os mesmos formatos:

```
1            → Apenas capítulo 1
5-10         → Capítulos 5 a 10
1-5, 20-25   → Capítulos 1-5 e 20-25
todos        → Todos os capítulos disponíveis
```

**Nota**: Capítulos decimais funcionam em todas as fontes (ex: 205.5)

---

## 🔄 Fluxo Completo

```
/mangaleech
    ↓
[Selecionar Fonte]
    • 🌸 Flower Mangas
    • 🔥 Nine Manga
    • 🌐 Nexus Toons
    ↓
[Selecionar Modo]
    • 🔍 Pesquisar
    • 🔗 Link direto
    ↓
[Entrada do Usuário]
    Pesquisa: Nome do mangá
    Link: URL ou slug
    ↓
[Se pesquisa]
    Bot busca e mostra 5-10 resultados
    Usuário seleciona um
    ↓
[Carregar Informações]
    • Título
    • Total de capítulos
    • Descrição
    • Primeiro e último capítulo
    ↓
[Digitar Intervalo]
    ex: 1-5, 10, todos
    ↓
[Download]
    • Processa capítulos no intervalo
    • Baixa imagens
    • Cria arquivos CBZ
    • Mostra progresso em %
    ↓
[Upload Telegram]
    • Envia cada capítulo
    • Mostra progresso final
    ↓
[Limpeza]
    • Remove arquivos temporários
    • Finaliza com ✅
```

---

## 💾 Formatos de Saída

Todos os capítulos são salvos como **CBZ** (Compressed Comic Book):
- Arquivo ZIP com imagens numeradas
- Compatível com leitores de mangá
- Redução de tamanho

### Estrutura do CBZ
```
capitulo-001.0.cbz
├── 001.jpg
├── 002.jpg
├── 003.jpg
├── 004.jpg
└── 005.jpg
```

**Compatível com:**
- Tachiyomi (Android)
- ComiXology (iOS/Android)
- Archaea (iOS)
- Perfect Viewer (Android)
- E muitos outros leitores

---

## 🐛 Troubleshooting

### "Protegido por Cloudflare"
**Problema**: Nine Manga retorna erro 403
**Solução**: Use Nexus Toons ou Flower Mangas

### "Nenhum resultado encontrado"
**Problema**: Busca não retorna resultados
**Solução**: 
- Tente outro nome/autor
- Verifique ortografia
- Use outra fonte

### "Erro ao baixar imagens"
**Problema**: Arquivo CBZ vazio ou incompleto
**Solução**:
- Verifique conexão
- Tente outro capítulo
- Mude de fonte

### "Link inválido"
**Problema**: URL não é reconhecida
**Solução**: Use URL completa do site (ex: https://...)

---

## 📊 Cobertura de Títulos

### Recomendações por Título

| Título | Flower | Nine | Nexus | Recomendado |
|--------|:------:|:----:|:-----:|:-----------:|
| Solo Leveling | ✅ | ✅ | ✅ | Nexus (API) |
| Demon Slayer | ✅ | ✅ | ✅ | Qualquer |
| Berserk | ✅ | ✅ | ✅ | Qualquer |
| Tower of God | ❌ | ✅ | ✅ | Nine/Nexus |
| Lookism | ❌ | ✅ | ✅ | Nine/Nexus |

---

## 🔐 Privacidade & Segurança

- ✅ Sem armazenamento de dados pessoais
- ✅ Sem tracking externo
- ✅ Headers padrão de navegador
- ✅ Requisições com delay para não sobrecarregar servidores
- ✅ Sem manipulação de conteúdo

---

## 📞 Suporte

Se você tiver dúvidas:
1. Tente outra fonte
2. Verifique o nome exato do mangá
3. Confirme se há capítulos publicados
4. Use slugs em Nexus Toons

---

**Última atualização**: 14 de Fevereiro de 2026
**Versão**: 1.0 (Todas as 3 fontes integradas)
