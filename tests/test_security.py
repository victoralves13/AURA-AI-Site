"""Testes de autenticação, autorização, auditoria e arquivos estáticos (sem rede, sem OpenAI).

Rodar:  python -m unittest discover -s tests -v
"""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "api"))

from fastapi.testclient import TestClient  # noqa: E402

import index  # noqa: E402
import security as sec  # noqa: E402

UA = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
UB = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
ORG1 = "11111111-1111-1111-1111-111111111111"
ORG2 = "22222222-2222-2222-2222-222222222222"
NEWORG = "33333333-3333-3333-3333-333333333333"
HEX = "0123456789abcdef0123456789abcdef"


class FakeSupabase:
    """Substitui sec.http_json: Auth + PostgREST mínimos."""

    def __init__(self):
        self.users = {"tok-a": {"id": UA, "email": "a@x.com"}, "tok-b": {"id": UB, "email": "b@x.com"}}
        self.memberships = {UA: [{"org_id": ORG1, "role": "member"}], UB: [{"org_id": ORG1, "role": "manager"}]}
        self.overrides = {}
        self.audit_rows = []
        self.audit_recent = []
        self.fail_membership = False
        self.calls = []

    def _user(self, headers):
        return self.users.get(headers.get("Authorization", "").split(" ")[-1])

    def __call__(self, method, url, headers, payload=None, timeout=15):
        self.calls.append((method, url, payload))
        if "/auth/v1/user" in url:
            u = self._user(headers)
            return (200, u) if u else (401, {"msg": "invalid"})
        path = url.split("/rest/v1/")[1]
        table = path.split("?")[0]
        if method == "GET" and table == "memberships":
            u = self._user(headers)
            rows = self.memberships.get(u["id"], []) if u else []
            if "organizations" in path:
                rows = [{**r, "organizations": {"id": r["org_id"], "name": "Org " + r["org_id"][:2]}} for r in rows]
            return 200, rows
        if method == "GET" and table == "membership_permissions":
            u = self._user(headers)
            return 200, self.overrides.get(u["id"], []) if u else []
        if method == "GET" and table == "audit_log":
            return 200, self.audit_recent
        if method == "POST" and table == "audit_log":
            self.audit_rows.append(payload)
            return 201, [payload]
        if method == "POST" and table == "organizations":
            return 201, [{"id": NEWORG, **payload}]
        if method == "POST" and table == "memberships":
            return (500, {}) if self.fail_membership else (201, [payload])
        if method == "DELETE" and table == "organizations":
            return 204, None
        return 404, {}


def minimal_analysis():
    from openai_engine import AURAAnalysis
    return AURAAnalysis(summary="ok", main_topics=[], decisions=[], pending_actions=[], risks=[], opportunities=[],
                        objections=[], important_signals=[], insights=[], financial_data=[], next_actions=[],
                        participants=[], intelligence_type="comercial", sentiment="Neutro")


class Base(unittest.TestCase):
    auth = True

    def setUp(self):
        env = {"SUPABASE_URL": "https://x.supabase.co", "SUPABASE_PUBLISHABLE_KEY": "pk", "SUPABASE_SECRET_KEY": "sk",
               "AURA_AUTH_REQUIRED": "1" if self.auth else ""}
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        sec._token_cache.clear()
        self.fake = FakeSupabase()
        p = mock.patch.object(sec, "http_json", self.fake)
        p.start()
        self.addCleanup(p.stop)
        self.saved = []
        self.meetings_rows = []

        def fake_request(method, path, payload=None, user=None):
            if method == "POST":
                self.saved.append((payload, user))
                return [{**payload, "id": "m-1", "created_at": "2026-10-14T00:00:00Z"}]
            return self.meetings_rows
        p2 = mock.patch.object(index, "_supabase_request", fake_request)
        p2.start()
        self.addCleanup(p2.stop)
        p3 = mock.patch("openai_engine.analyze_transcript", lambda text, context="Outro": minimal_analysis())
        p3.start()
        self.addCleanup(p3.stop)
        self.client = TestClient(index.app)

    def h(self, tok="tok-a"):
        return {"Authorization": f"Bearer {tok}"}


class AuthRequired(Base):
    def test_endpoints_exigem_login(self):
        c = self.client
        casos = [
            c.get("/api/meetings"), c.get("/api/me"),
            c.post("/api/meetings", json={"transcript": "abcd"}),
            c.post("/api/analyze-transcript", json={"transcript": "abcd efgh"}),
            c.post("/api/audio-upload-url", json={"file_name": "a.mp3", "size_bytes": 10}),
            c.post("/api/analyze-stored-audio", json={"path": f"users/{UA}/{HEX}.mp3"}),
            c.post("/api/orgs", json={"name": "X"}),
        ]
        self.assertEqual([r.status_code for r in casos], [401] * len(casos))
        self.assertEqual(self.saved, [])

    def test_token_invalido_e_formato_errado(self):
        self.assertEqual(self.client.get("/api/meetings", headers=self.h("tok-falso")).status_code, 401)
        self.assertEqual(self.client.get("/api/meetings", headers={"Authorization": "Basic abc"}).status_code, 401)

    def test_servidor_sem_configuracao_de_auth_responde_503(self):
        with mock.patch.dict(os.environ, {"SUPABASE_PUBLISHABLE_KEY": ""}):
            self.assertEqual(self.client.get("/api/meetings", headers=self.h()).status_code, 503)

    def test_publicos(self):
        self.assertEqual(self.client.get("/api/health").status_code, 200)
        cfg = self.client.get("/api/config").json()
        self.assertTrue(cfg["auth_required"])
        self.assertNotIn("sk", str(cfg.values()))  # chave de serviço nunca sai

    def test_me_lista_organizacoes(self):
        r = self.client.get("/api/me", headers=self.h())
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["user"]["id"], UA)
        self.assertEqual(r.json()["organizations"][0]["id"], ORG1)

    def test_analise_grava_com_dono_do_token_e_ignora_dono_do_corpo(self):
        r = self.client.post("/api/analyze-transcript", headers=self.h(),
                             json={"transcript": "Ana: oi\nBia: olá", "owner_id": UB, "org_id": ORG1})
        self.assertEqual(r.status_code, 200, r.text)
        payload, user = self.saved[0]
        self.assertEqual(payload["owner_id"], UA)
        self.assertEqual(payload["org_id"], ORG1)
        self.assertEqual(payload["visibility"], "private")
        self.assertEqual(user.id, UA)
        self.assertIn("\n", payload["transcript"])  # quebras de linha preservadas
        acts = [a["action"] for a in self.fake.audit_rows]
        self.assertIn("analysis.transcript", acts)

    def test_organizacao_alheia_e_negada(self):
        r = self.client.post("/api/analyze-transcript", headers=self.h(), json={"transcript": "abcd efgh", "org_id": ORG2})
        self.assertEqual(r.status_code, 403)
        self.assertEqual(self.saved, [])
        r = self.client.post("/api/meetings", headers=self.h(), json={"transcript": "abcd", "org_id": ORG2})
        self.assertEqual(r.status_code, 403)

    def test_organizacao_invalida(self):
        r = self.client.post("/api/analyze-transcript", headers=self.h(), json={"transcript": "abcd efgh", "org_id": "../x"})
        self.assertEqual(r.status_code, 400)

    def test_deny_remove_permissao_do_papel(self):
        self.fake.overrides[UA] = [{"org_id": ORG1, "permission": "meetings.write", "effect": "deny"}]
        r = self.client.post("/api/analyze-transcript", headers=self.h(), json={"transcript": "abcd efgh", "org_id": ORG1})
        self.assertEqual(r.status_code, 403)

    def test_conta_pessoal_nao_exige_organizacao(self):
        r = self.client.post("/api/analyze-transcript", headers=self.h(), json={"transcript": "abcd efgh"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIsNone(self.saved[0][0]["org_id"])

    def test_limite_de_uso(self):
        self.fake.audit_recent = [{"id": i} for i in range(31)]
        r = self.client.post("/api/analyze-transcript", headers=self.h(), json={"transcript": "abcd efgh"})
        self.assertEqual(r.status_code, 429)
        self.assertEqual(self.saved, [])

    def test_limite_de_uso_falha_fechada(self):
        with mock.patch.object(sec, "service_rest", side_effect=RuntimeError("down")):
            r = self.client.post("/api/analyze-transcript", headers=self.h(), json={"transcript": "abcd efgh"})
        self.assertEqual(r.status_code, 503)
        self.assertEqual(self.saved, [])

    def test_caminho_de_audio_pertence_ao_usuario(self):
        with mock.patch.object(index, "_create_upload_url", return_value=("https://signed", "t")):
            pessoal = self.client.post("/api/audio-upload-url", headers=self.h(), json={"file_name": "a.mp3", "size_bytes": 10}).json()
            org = self.client.post("/api/audio-upload-url", headers=self.h(), json={"file_name": "a.MP3", "size_bytes": 10, "org_id": ORG1}).json()
            negada = self.client.post("/api/audio-upload-url", headers=self.h(), json={"file_name": "a.mp3", "size_bytes": 10, "org_id": ORG2})
            estranho = self.client.post("/api/audio-upload-url", headers=self.h(), json={"file_name": "a.exe.py", "size_bytes": 10, "content_type": "audio/mpeg"}).json()
        self.assertTrue(pessoal["path"].startswith(f"users/{UA}/"))
        self.assertTrue(org["path"].startswith(f"orgs/{ORG1}/"))
        self.assertEqual(negada.status_code, 403)
        self.assertTrue(estranho["path"].endswith(".mp3"))  # extensão fora da lista vira .mp3

    def test_analisar_audio_de_outro_usuario_e_negado(self):
        for path, status in [(f"users/{UB}/{HEX}.mp3", 403), (f"orgs/{ORG2}/{HEX}.mp3", 403),
                             ("meetings/" + HEX + ".mp3", 400), (f"users/{UA}/../{HEX}.mp3", 400)]:
            r = self.client.post("/api/analyze-stored-audio", headers=self.h(), json={"path": path})
            self.assertEqual(r.status_code, status, path)

    def test_analisar_audio_proprio(self):
        with mock.patch.object(index, "_download_stored_audio"), \
             mock.patch("openai_engine.transcribe_audio", return_value=("Ana: oi", {"segments": []})):
            r = self.client.post("/api/analyze-stored-audio", headers=self.h(), json={"path": f"users/{UA}/{HEX}.mp3", "file_name": "r.mp3"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.saved[0][0]["owner_id"], UA)
        self.assertIn("analysis.audio", [a["action"] for a in self.fake.audit_rows])

    def test_dados_financeiros_so_para_quem_pode(self):
        rows = [{"id": "1", "owner_id": UA, "org_id": ORG1, "financial_data": [{"amount": 1}]},
                {"id": "2", "owner_id": UB, "org_id": ORG1, "financial_data": [{"amount": 2}]}]
        self.meetings_rows = rows
        membro = self.client.get("/api/meetings", headers=self.h("tok-a")).json()["meetings"]
        self.assertEqual(membro[0]["financial_data"], [{"amount": 1}])  # próprio
        self.assertEqual(membro[1]["financial_data"], [])  # de outro, sem finance.read
        gestor = self.client.get("/api/meetings", headers=self.h("tok-b")).json()["meetings"]
        self.assertEqual(gestor[0]["financial_data"], [{"amount": 1}])  # manager tem finance.read

    def test_criar_organizacao(self):
        r = self.client.post("/api/orgs", headers=self.h(), json={"name": "  Minha   Empresa "})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["organization"], {"id": NEWORG, "name": "Minha Empresa", "role": "admin"})
        posted = [c for c in self.fake.calls if c[0] == "POST" and c[1].endswith("/memberships")][0][2]
        self.assertEqual((posted["user_id"], posted["role"]), (UA, "admin"))
        self.assertIn("org.create", [a["action"] for a in self.fake.audit_rows])

    def test_criar_organizacao_desfaz_se_falhar_o_vinculo(self):
        self.fake.fail_membership = True
        r = self.client.post("/api/orgs", headers=self.h(), json={"name": "X"})
        self.assertEqual(r.status_code, 502)
        self.assertTrue(any(c[0] == "DELETE" and "organizations" in c[1] for c in self.fake.calls))
        self.assertEqual(self.client.post("/api/orgs", headers=self.h(), json={"name": " "}).status_code, 400)


class LegacyMode(Base):
    auth = False

    def test_sem_login_continua_funcionando_enquanto_desligado(self):
        self.assertEqual(self.client.get("/api/meetings").status_code, 200)
        r = self.client.post("/api/analyze-transcript", json={"transcript": "abcd efgh"})
        self.assertEqual(r.status_code, 200, r.text)
        payload, user = self.saved[0]
        self.assertIsNone(user)
        self.assertNotIn("owner_id", payload)
        self.assertFalse(self.client.get("/api/health").json()["auth_required"])

    def test_audio_legado_mantem_prefixo_antigo(self):
        r = self.client.post("/api/analyze-stored-audio", json={"path": "users/x/y.mp3"})
        self.assertEqual(r.status_code, 400)


class Publico(Base):
    def test_cors_fechado_por_padrao(self):
        r = self.client.options("/api/meetings", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"})
        self.assertNotIn("access-control-allow-origin", {k.lower() for k in r.headers})

    def test_nao_serve_codigo_nem_configuracao(self):
        for p in ["/api/index.py", "/api/security.py", "/api/openai_engine.py", "/supabase/schema.sql",
                  "/supabase/migrations/20261014120000_etapa2_identidade_organizacoes.sql", "/.git/config",
                  "/.gitignore", "/.env.example", "/requirements.txt", "/README.md", "/DEPLOY.md", "/equipe.txt",
                  "/tests/test_security.py", "/.venv/pyvenv.cfg", "/package.json", "/vercel.json"]:
            self.assertEqual(self.client.get(p).status_code, 404, p)

    def test_serve_o_front_end(self):
        for p in ["/", "/index.html", "/app.js", "/product-shell.css", "/aura-logo.svg", "/aura-logo-real.jpeg"]:
            self.assertEqual(self.client.get(p).status_code, 200, p)


if __name__ == "__main__":
    unittest.main()
