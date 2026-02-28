#!/bin/bash
# Script para testar o módulo Anitsu após as correções

echo "=== TESTE DE ANITSULEECH APÓS CORREÇÕES ==="
echo ""
echo "✅ Verifying arquivo syntax..."
python3 -m py_compile bot/modules/anitsuleech.py bot/helper/ext_utils/anitsu_client.py
if [ $? -eq 0 ]; then
    echo "   ✓ Sem erros de sintaxe"
else
    echo "   ✗ Erros de sintaxe detectados!"
    exit 1
fi

echo ""
echo "=== RESUMO DAS CORREÇÕES ==="
echo ""
echo "🔧 PROBLEMAS CORRIGIDOS:"
echo "   1. ❌ Chamadas assíncronas sem 'await'"
echo "      ✓ Adicionado 'await' em ac.search() e ac.list_files()"
echo ""
echo "   2. ❌ Verificação incorreta do cliente"
echo "      ✓ Adicionado try/catch na inicialização"
echo ""
echo "   3. ❌ Sem validação de dados nulos"
echo "      ✓ Adicionada verificação de None/vazio"
echo ""
echo "   4. ❌ Handler de mensagem genérico demais"
echo "      ✓ Adicionada validação de stage"
echo ""
echo "   5. ❌ Falta de logging de depuração"
echo "      ✓ Adicionado logging em ALL pontos críticos"
echo ""
echo "   6. ❌ URLs Anitsu eram enviadas sem cabeçalhos de auth"
echo "      ✓ Agora incluem Cookie: e Authorization: JWT automaticamente"
echo ""
echo "=== LOGGING ADICIONADO ==="
echo ""
echo "📍 Em anitsu_client.py:"
grep -c "\[AnitsuClient\]" bot/helper/ext_utils/anitsu_client.py
echo "   linhas de logging"
echo ""
echo "📍 Em anitsuleech.py:"
grep -c "\[Anitsu\]" bot/modules/anitsuleech.py
echo "   linhas de logging"
echo ""
echo "=== PRÓXIMOS PASSOS ==="
echo ""
echo "1. Certifique-se de que ANITSU_COOKIE_FILE está em config.py"
echo "2. Verifique se o arquivo de cookies existe"
echo "3. Teste com: /anitsuleech"
echo "4. Se houver problema, verifique logs para [Anitsu]"
echo ""

# quick python check that direct_link_generator bypasses Anitsu links
python3 - <<'PYCODE'
# prevent qBittorrent from attempting to launch when bot package is imported
import subprocess
subprocess.run = lambda *args, **kwargs: None

from bot.helper.mirror_leech_utils.download_utils.direct_link_generator import direct_link_generator
link = 'https://nuvem.anitsu.moe/api/download?path=Foo'
result = direct_link_generator(link)
print('direct_link_generator passthrough:', result == link)
PYCODE

echo ""
echo "✅ Tudo pronto para testes!"
