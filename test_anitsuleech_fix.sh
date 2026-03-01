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
# simulate interval selection and ensure no duplicates (regression test)
python3 - <<'PYCODE'
import asyncio
from types import SimpleNamespace

# prepare fake anitsuleech environment
import importlib
anitsuleech = importlib.import_module('bot.modules.anitsuleech')

# monkeypatch client getter to avoid real network
class FakeClient:
    def download_url(self, path):
        return f"url://{path}"
async def fake_get_client(uid):
    return FakeClient()
anitsuleech._get_anitsu_client_for_user = fake_get_client

# capture calls to mirror/leech
called = []
async def fake_mirror(client, message):
    called.append(message.text)
async def fake_leech(client, message):
    called.append(message.text)

# replace original handlers
from bot.modules import mirror_leech
mirror_leech.mirror = fake_mirror
mirror_leech.leech = fake_leech

# build fake query and message
class FakeQuery:
    pass
q = FakeQuery()
msg = SimpleNamespace()
msg.text = ""
msg.chat = SimpleNamespace(id=123)
msg.from_user = SimpleNamespace(id=456)
msg.reply = lambda *a, **k: None
msg._client = None
msg.id = 789
q.message = msg

# prepare state as if 3 files were selected
state = {"selected_files": ["a", "b", "c"], "selected_sizes": [1, 2, 3]}

async def run_test():
    # call action handler simulating mirror
    await anitsuleech._handle_file_action(q, 999, state, "mirror")

asyncio.run(run_test())
print("called texts:", called)
# should be three distinct urls
print("test passed" if len(set(called)) == 3 else "test failed")
PYCODE


# verify that SupabaseTokenManager can rewrite cookie file parts
python3 - <<'PYCODE'
import http.cookiejar, tempfile, os, json
from bot.helper.ext_utils.supabase_token_manager import SupabaseTokenManager

# create temporary cookie file with dummy parts
cookie_path = 'tmp_test_cookie.txt'
with open(cookie_path, 'w') as f:
    f.write('.anitsu.moe\tTRUE\t/\tFALSE\t0\tsb-test-auth-token.0\tbase64-old0\n')
    f.write('.anitsu.moe\tTRUE\t/\tFALSE\t0\tsb-test-auth-token.1\told1\n')

# we don't actually need a proper jar for this test; we'll construct
# manager manually and supply the file path.
#jar = http.cookiejar.MozillaCookieJar(cookie_path)
#jar.load(ignore_discard=True, ignore_expires=True)

mgr = SupabaseTokenManager(None)
mgr.project_id = 'test'
mgr.cookie_file = cookie_path
mgr._auth_data = {'access_token':'newa','refresh_token':'newr','expires_at':456,'expires_in':3600}

mgr.access_token = 'newa'
mgr.refresh_token = 'newr'

# test that client callback is triggered
class DummyClient:
    def __init__(self):
        self.called = False
    def _refresh_cookie_header(self):
        self.called = True

dummy = DummyClient()
mgr._client = dummy
mgr._write_tokens_to_cookie_file()
print('callback invoked on client?', dummy.called)

# ensure config variable exists and can be changed
from bot.core.config_manager import Config
print('anon key before:', Config.ANITSU_SUPABASE_ANON_KEY)
Config.set('ANITSU_SUPABASE_ANON_KEY', 'fakekey123')
print('anon key after:', Config.ANITSU_SUPABASE_ANON_KEY)

print('cookie contents after write:')
with open(cookie_path) as f:
    print(f.read())

os.remove(cookie_path)
PYCODE

echo "✅ Tudo pronto para testes!"
