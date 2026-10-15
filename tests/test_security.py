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
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi.testclient import TestClient  # noqa: E402

from aura import app as index

from aura.features.meetings import repository as meetings_repo
from aura.features.meetings import service as meetings_mod

from aura.features.analysis import repository as analysis_repo
from aura.features.analysis import service as analysis_mod  # noqa: E402
from aura.core import security as sec  # noqa: E402
from fake_supabase import FakeSupabase  # noqa: E402

UA = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
UB = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
ORG1 = "11111111-1111-1111-1111-111111111111"
ORG2 = "22222222-2222-2222-2222-222222222222"
NEWORG = "33333333-3333-3333-3333-333333333333"
HEX = "0123456789abcdef0123456789abcdef"


def minimal_analysis():
    from aura.features.analysis.engine import AURAAnalysis
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
        self.fake.add_user("tok-a", UA, "a@x.com")
        self.fake.add_user("tok-b", UB, "b@x.com")
        self.fake.add_org(ORG1)
        self.fake.add_org(ORG2)
        self.fake.add_member(ORG1, UA, "member")
        self.fake.add_member(ORG1, UB, "manager")  # o RLS faz UA enxergar também este vínculo
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
        p2 = mock.patch.object(meetings_repo, "request", fake_request)
        p2.start()
        self.addCleanup(p2.stop)
        p3 = mock.patch("aura.features.analysis.engine.analyze_transcript", lambda text, context="Outro": minimal_analysis())
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
        self.assertIn("analysis.transcript", self.fake.actions())

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
        self.fake.tables["membership_permissions"].append(
            {"org_id": ORG1, "user_id": UA, "permission": "meetings.write", "effect": "deny"})
        r = self.client.post("/api/analyze-transcript", headers=self.h(), json={"transcript": "abcd efgh", "org_id": ORG1})
        self.assertEqual(r.status_code, 403)

    def test_conta_pessoal_nao_exige_organizacao(self):
        r = self.client.post("/api/analyze-transcript", headers=self.h(), json={"transcript": "abcd efgh"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIsNone(self.saved[0][0]["org_id"])

    def test_limite_de_uso(self):
        self.fake.tables["audit_log"] += [
            {"id": i, "actor_id": UA, "action": "analysis.transcript", "at": "2999-01-01T00:00:00+00:00"} for i in range(31)]
        r = self.client.post("/api/analyze-transcript", headers=self.h(), json={"transcript": "abcd efgh"})
        self.assertEqual(r.status_code, 429)
        self.assertEqual(self.saved, [])

    def test_limite_de_uso_falha_fechada(self):
        with mock.patch.object(sec, "service_rest", side_effect=RuntimeError("down")):
            r = self.client.post("/api/analyze-transcript", headers=self.h(), json={"transcript": "abcd efgh"})
        self.assertEqual(r.status_code, 503)
        self.assertEqual(self.saved, [])

    def test_caminho_de_audio_pertence_ao_usuario(self):
        with mock.patch.object(analysis_repo, "create_upload_url", return_value=("https://signed", "t")):
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
        with mock.patch.object(analysis_repo, "download_stored_audio"), \
             mock.patch("aura.features.analysis.engine.transcribe_audio", return_value=("Ana: oi", {"segments": []})):
            r = self.client.post("/api/analyze-stored-audio", headers=self.h(), json={"path": f"users/{UA}/{HEX}.mp3", "file_name": "r.mp3"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.saved[0][0]["owner_id"], UA)
        self.assertIn("analysis.audio", self.fake.actions())

    def test_papel_de_outro_membro_nao_vaza_para_mim(self):
        """O RLS mostra a UA também o vínculo de UB (gestor); UA continua sendo apenas membro."""
        access = sec.load_access(sec.AuthUser(id=UA, email="a@x.com", token="tok-a"))
        self.assertEqual(access[ORG1], sec.ROLE_PERMISSIONS["member"])
        me = self.client.get("/api/me", headers=self.h()).json()
        self.assertEqual([o["role"] for o in me["organizations"]], ["member"])
        self.assertNotIn("finance.read", me["organizations"][0]["permissions"])

    def test_filtro_de_espaco_na_listagem(self):
        for query, expected in [("org_id=personal", "org_id=is.null"), (f"org_id={ORG1}", f"org_id=eq.{ORG1}")]:
            paths = []
            with mock.patch.object(meetings_repo, "request", lambda m, p, payload=None, user=None: paths.append(p) or []):
                self.assertEqual(self.client.get("/api/meetings?" + query, headers=self.h()).status_code, 200)
            self.assertIn(expected, paths[0])
        self.assertEqual(self.client.get("/api/meetings?org_id=abc", headers=self.h()).status_code, 400)

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
        org = r.json()["organization"]
        self.assertEqual((org["name"], org["role"]), ("Minha Empresa", "admin"))
        self.assertEqual(self.fake.rows("memberships", org_id=org["id"], user_id=UA)[0]["role"], "admin")
        self.assertEqual(self.fake.rows("organizations", id=org["id"])[0]["created_by"], UA)
        self.assertIn("org.create", self.fake.actions())

    def test_criar_organizacao_desfaz_se_falhar_o_vinculo(self):
        self.fake.fail.add(("POST", "memberships"))
        r = self.client.post("/api/orgs", headers=self.h(), json={"name": "X"})
        self.assertEqual(r.status_code, 502)
        self.assertEqual(len(self.fake.tables["organizations"]), 2)  # só as duas do cenário: a nova foi desfeita
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
        for p in ["/api/index.py", "/backend/aura/app.py", "/backend/aura/core/security.py", "/backend/aura/features/integrations/crypto.py",
                  "/backend/aura/features/analysis/engine.py", "/supabase/schema.sql",
                  "/supabase/migrations/20261014120000_etapa2_identidade_organizacoes.sql", "/.git/config",
                  "/.gitignore", "/.env.example", "/requirements.txt", "/README.md", "/DEPLOY.md", "/equipe.txt",
                  "/tests/test_security.py", "/.venv/pyvenv.cfg", "/package.json", "/vercel.json"]:
            self.assertEqual(self.client.get(p).status_code, 404, p)

    def test_serve_o_front_end(self):
        for p in ["/", "/index.html", "/shell/app.js", "/styles/base/styles.css", "/shell/product-shell.css", "/assets/img/aura-logo.svg",
                  "/assets/img/aura-logo-real.jpeg", "/core/auth.js", "/core/auth.css", "/core/orgs.js", "/core/orgs.css",
                  "/features/analysis/evidence.css", "/features/clients/clients-ui.js", "/features/clients/clients-ui.css",
                  "/vendor/supabase-js-2.117.2.umd.js"]:
            self.assertEqual(self.client.get(p).status_code, 200, p)

    def test_subpastas_nao_abrem_caminho_para_fora_do_front_end(self):
        for p in ["/core/../../backend/aura/app.py", "/features/live/../../../vercel.json", "/%2e%2e/vercel.json", "/core/%2e%2e/%2e%2e/DEPLOY.md",
                  "/core/.hidden.js", "/.git/config", "/core/auth.js.map", "/core/", "/core", "/features", "/vendor/x.py"]:
            r = self.client.get(p)
            self.assertIn(r.status_code, (404, 307, 308), p)
            self.assertNotIn("def ", r.text[:2000], p)
            self.assertNotIn("aura-ai-site", r.text[:2000], p)  # nem o package.json/vercel.json


class TipoDeChave(unittest.TestCase):
    def jwt(self, role):
        import base64
        import json
        enc = lambda o: base64.urlsafe_b64encode(json.dumps(o).encode()).rstrip(b"=").decode()
        return f"{enc({'alg': 'HS256'})}.{enc({'role': role})}.assinatura"

    def test_tipos(self):
        k = sec.key_kind
        self.assertEqual(k(self.jwt("anon")), "publishable")
        self.assertEqual(k(self.jwt("service_role")), "secret")
        self.assertEqual(k("sb_publishable_abc"), "publishable")
        self.assertEqual(k("sb_secret_abc"), "secret")
        self.assertEqual(k(""), "vazia")
        self.assertEqual(k(None), "vazia")
        self.assertEqual(k("sb_secret_abc\n"), "com espaço ou quebra de linha")  # erro comum ao colar a chave
        self.assertEqual(k(" sb_secret_abc"), "com espaço ou quebra de linha")
        self.assertEqual(k("qualquer-coisa"), "desconhecida")
        self.assertEqual(k("a.b.c"), "desconhecida")

    def test_saude_mostra_so_o_tipo_nunca_o_valor(self):
        from aura import app as index
        from aura.features.meetings import repository as meetings_repo
        from aura.features.meetings import service as meetings_mod
        from aura.features.analysis import repository as analysis_repo
        from aura.features.analysis import service as analysis_mod
        from fastapi.testclient import TestClient
        with mock.patch.dict(os.environ, {"SUPABASE_PUBLISHABLE_KEY": "sb_secret_TROCADA", "SUPABASE_SECRET_KEY": "sb_publishable_TROCADA"}):
            body = TestClient(index.app).get("/api/health").json()
        self.assertEqual((body["publishable_key_kind"], body["service_key_kind"]), ("secret", "publishable"))  # chaves trocadas: salta aos olhos
        self.assertNotIn("TROCADA", str(body))


if __name__ == "__main__":
    unittest.main()
