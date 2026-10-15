"""Verificação SOMENTE LEITURA de um deploy do AURA (preview ou local). Sem dependências.

Uso:
    python tests/smoke_deploy.py https://SEU-PREVIEW.vercel.app --auth off     # antes de ligar o login
    python tests/smoke_deploy.py https://SEU-PREVIEW.vercel.app --auth on      # depois de ligar AURA_AUTH_REQUIRED=1

Opcional (variáveis de ambiente, nunca argumentos de linha de comando):
    AURA_TEST_TOKEN=<access token de uma conta de teste>  confere também /api/me e o espaço pessoal com login de verdade.
    VERCEL_BYPASS_TOKEN=<token>                           se o preview tiver "Deployment Protection" ligada.

O script NÃO cria dados, NÃO chama a IA e NÃO envia a chave de serviço. Só faz GET/OPTIONS e POSTs
sem corpo válido que precisam ser recusados. Código de saída 0 = tudo passou; 1 = alguma falha.
"""
import base64
import json
import os
import sys
import urllib.error
import urllib.request

SENSITIVE = ["/api/index.py", "/api/security.py", "/api/openai_engine.py", "/api/orgs.py", "/api/clients.py",
             "/.git/config", "/.env", "/.env.example", "/supabase/schema.sql", "/requirements.txt",
             "/DEPLOY.md", "/README.md", "/tests/test_security.py", "/vercel.json", "/package.json"]
ASSETS = ["/", "/index.html", "/auth.js", "/orgs.js", "/clients-ui.js", "/actions-ui.js", "/chat-ui.js", "/live-ui.js", "/product-shell.js", "/auth.css",
          "/evidence.css", "/clients-ui.css", "/actions-ui.css", "/chat-ui.css", "/live-ui.css", "/supabase-js-2.117.2.umd.js"]

results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(("PASS  " if ok else "FAIL  ") + name + ("" if ok or not detail else f"   -> {detail}"))


def call(base, method, path, headers=None, body=None, timeout=25):
    headers = dict(headers or {})
    bypass = os.getenv("VERCEL_BYPASS_TOKEN", "").strip()  # "Protection Bypass for Automation" do projeto, se a proteção de deploy estiver ligada
    if bypass:
        headers["x-vercel-protection-bypass"] = bypass
    req = urllib.request.Request(base + path, method=method, headers=headers, data=body)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, dict((k.lower(), v) for k, v in r.headers.items()), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict((k.lower(), v) for k, v in e.headers.items()), e.read()
    except Exception as e:  # rede
        return 0, {}, str(e).encode()


def jwt_role(token):
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload)).get("role")
    except Exception:
        return None


def main(argv):
    if not argv or argv[0].startswith("--"):
        print(__doc__)
        return 2
    base = argv[0].rstrip("/")
    expect = argv[argv.index("--auth") + 1] if "--auth" in argv else "off"
    if expect not in ("on", "off"):
        print("--auth deve ser on ou off")
        return 2
    print(f"Verificando {base} (login esperado: {expect})\n")

    print("== Publicação do front-end")
    for path in ASSETS:
        status, headers, body = call(base, "GET", path)
        check(f"GET {path} = 200", status == 200, f"status {status}")
    status, _, body = call(base, "GET", "/")
    check("a página inicial é o AURA", b"AURA" in body)

    print("\n== Nada de código, git ou configuração publicado")
    for path in SENSITIVE:
        status, _, body = call(base, "GET", path)
        leaked = status == 200 and any(m in body for m in (b"import ", b"[core]", b"SUPABASE", b"create table", b"fastapi"))
        check(f"GET {path} não vaza conteúdo", status in (401, 403, 404) or not leaked, f"status {status}")

    print("\n== Saúde e configuração")
    status, _, body = call(base, "GET", "/api/health")
    health = {}
    try:
        health = json.loads(body)
    except ValueError:
        pass
    check("/api/health responde 200 com JSON", status == 200 and health.get("ok") is True, f"status {status}")
    print(f"      openai_configured={health.get('openai_configured')}  supabase_configured={health.get('supabase_configured')}  "
          f"auth_configured={health.get('auth_configured')}  auth_required={health.get('auth_required')}")
    check(f"auth_required = {expect == 'on'} como esperado", bool(health.get("auth_required")) == (expect == "on"), f"veio {health.get('auth_required')}")
    if expect == "on":
        check("auth_configured = true (URL e chave pública presentes)", health.get("auth_configured") is True)
    status, _, body = call(base, "GET", "/api/config")
    cfg = {}
    try:
        cfg = json.loads(body)
    except ValueError:
        pass
    check("/api/config coerente com /api/health", status == 200 and bool(cfg.get("auth_required")) == bool(health.get("auth_required")))
    key = str(cfg.get("supabase_publishable_key") or "")
    check("a chave exposta ao navegador NÃO é de serviço", not key.startswith("sb_secret") and jwt_role(key) != "service_role",
          "chave secreta/serviço aparecendo em /api/config!")
    if expect == "on":
        check("a chave pública está presente e é publishable/anon", key.startswith("sb_publishable_") or jwt_role(key) == "anon",
              "defina SUPABASE_PUBLISHABLE_KEY")
        check("supabase_url presente", str(cfg.get("supabase_url") or "").startswith("https://"))

    print("\n== CORS fechado")
    status, headers, _ = call(base, "OPTIONS", "/api/meetings", {"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"})
    check("origem estranha não recebe Access-Control-Allow-Origin", "access-control-allow-origin" not in headers, headers.get("access-control-allow-origin", ""))

    print("\n== Rotas de dados " + ("(login exigido)" if expect == "on" else "(login desligado: só informativo)"))
    protected = [("GET", "/api/meetings", None), ("GET", "/api/me", None), ("GET", "/api/clients", None),
                 ("POST", "/api/analyze-transcript", b'{"transcript":"x"}'), ("POST", "/api/audio-upload-url", b'{"file_name":"a.mp3","size_bytes":10}'),
                 ("POST", "/api/orgs", b'{"name":"x"}'), ("POST", "/api/invitations/accept", b'{"token":"x"}'),
                 ("GET", "/api/actions", None), ("GET", "/api/actions/stats", None), ("POST", "/api/actions/sync", None),
                 ("GET", "/api/conversations", None), ("POST", "/api/conversations", b'{}')]
    for method, path, body in protected:
        hdr = {"Content-Type": "application/json"} if body else {}
        status, _, _ = call(base, method, path, hdr, body)
        if expect == "on":
            check(f"{method} {path} sem login = 401", status == 401, f"status {status}")
        else:
            print(f"INFO  {method} {path} sem login = {status}")
    if expect == "on":
        status, _, _ = call(base, "GET", "/api/meetings", {"Authorization": "Bearer token-invalido"})
        check("token inválido = 401 (não 500)", status == 401, f"status {status}")
        status, _, _ = call(base, "GET", "/api/meetings", {"Authorization": "Basic abc"})
        check("esquema de autorização errado = 401", status == 401, f"status {status}")

    token = os.getenv("AURA_TEST_TOKEN", "").strip()
    if token:
        print("\n== Com a conta de teste (AURA_TEST_TOKEN)")
        auth = {"Authorization": f"Bearer {token}"}
        status, _, body = call(base, "GET", "/api/me", auth)
        me = {}
        try:
            me = json.loads(body)
        except ValueError:
            pass
        check("/api/me = 200 com o usuário", status == 200 and bool((me.get("user") or {}).get("id")), f"status {status}")
        status, _, body = call(base, "GET", "/api/meetings?org_id=personal&limit=5", auth)
        check("/api/meetings do espaço pessoal = 200", status == 200, f"status {status}")
        status, _, _ = call(base, "GET", "/api/orgs/00000000-0000-0000-0000-000000000000/members", auth)
        check("membros de organização alheia = 403 (nunca 200)", status in (403, 404), f"status {status}")
    else:
        print("\n(sem AURA_TEST_TOKEN: pulando as checagens com login de verdade)")

    failed = results.count(False)
    print(f"\n{results.count(True)} ok, {failed} falha(s).")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
