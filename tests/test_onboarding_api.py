"""Testes do onboarding no servidor: progresso calculado a partir dos dados reais, passos pulados, dispensar, recomeçar
e isolamento entre pessoas (sem rede). RLS e gatilho de verdade: tests/db/onboarding.test.mjs."""
import sys
import unittest
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from aura.features.onboarding import router as ob  # noqa: E402
from test_orgs import OrgBase, ORG1, UA, UB, UC  # noqa: E402


class Base(OrgBase):
    def state(self, tok="tok-a"):
        r = self.client.get("/api/onboarding", headers=self.h(tok))
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def step(self, state, key):
        return next(s for s in state["steps"] if s["key"] == key)

    def add(self, table, **row):
        self.fake.tables[table].append({"id": str(uuid.uuid4()), **row})

    def progress(self, uid=UA):
        return self.fake.rows("onboarding_progress", user_id=uid)


class Acesso(Base):
    def test_tudo_exige_login(self):
        c = self.client
        rotas = [c.get("/api/onboarding"), c.post("/api/onboarding/dismiss"), c.post("/api/onboarding/reset"), c.post("/api/onboarding/steps/chat/skip")]
        self.assertEqual([r.status_code for r in rotas], [401] * 4)

    def test_passo_desconhecido(self):
        r = self.client.post("/api/onboarding/steps/hack/skip", headers=self.h())
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.progress(), [])

    def test_lista_de_passos_igual_a_do_banco(self):
        migration = (Path(__file__).resolve().parents[1] / "supabase" / "migrations" / "20261014230000_etapa7_onboarding.sql").read_text(encoding="utf8")
        for key in ob.KEYS:
            self.assertIn(f"'{key}'", migration)
        self.assertEqual(tuple(ob.KEYS), self.fake.ONBOARDING_STEPS)


class Progresso(Base):
    def test_conta_nova_comeca_do_zero_e_nao_grava_nada(self):
        s = self.state()
        self.assertEqual((s["finished"], s["total"], s["visible"], s["completed"]), (0, 5, True, False))
        self.assertTrue(all(not x["done"] and not x["skipped"] for x in s["steps"]))
        self.assertEqual(self.progress(), [])

    def test_passos_vem_dos_dados_reais_da_pessoa(self):
        self.add("meetings", owner_id=UA, org_id=None)
        self.add("conversations", owner_id=UA, org_id=None, title="x")
        s = self.state()
        self.assertTrue(self.step(s, "first_meeting")["done"])
        self.assertTrue(self.step(s, "chat")["done"])
        self.assertFalse(self.step(s, "client")["done"])
        self.assertEqual(s["done_count"], 2)

    def test_dados_de_outra_pessoa_nao_contam(self):
        self.add("meetings", owner_id=UB, org_id=ORG1)  # gestor: UA (admin) enxerga, mas não é dela
        self.add("clients", owner_id=UB, org_id=ORG1, normalized_name="x", name="X")
        s = self.state()
        self.assertEqual(s["done_count"], 0)

    def test_acao_conta_so_para_quem_criou(self):
        mid = str(uuid.uuid4())
        self.fake.tables["meetings"].append({"id": mid, "owner_id": UA, "org_id": None})
        self.add("actions", meeting_id=mid, org_id=None, text="t", created_by=UB)
        self.assertFalse(self.step(self.state(), "action")["done"])
        self.add("actions", meeting_id=mid, org_id=None, text="t2", created_by=UA)
        self.assertTrue(self.step(self.state(), "action")["done"])

    def test_pular_passo_grava_e_conta_como_encerrado(self):
        r = self.client.post("/api/onboarding/steps/live/skip", headers=self.h())
        self.assertEqual(r.status_code, 200, r.text)
        s = r.json()
        self.assertTrue(self.step(s, "live")["skipped"])
        self.assertEqual((s["finished"], s["done_count"]), (1, 0))
        self.assertEqual(list(self.progress()[0]["skipped"]), ["live"])
        self.client.post("/api/onboarding/steps/chat/skip", headers=self.h())
        self.assertEqual(sorted(self.progress()[0]["skipped"]), ["chat", "live"])
        self.assertEqual(len(self.progress()), 1)  # uma linha só por pessoa

    def test_passo_feito_nao_aparece_como_pulado(self):
        self.client.post("/api/onboarding/steps/chat/skip", headers=self.h())
        self.add("conversations", owner_id=UA, org_id=None, title="x")
        step = self.step(self.state(), "chat")
        self.assertTrue(step["done"])
        self.assertFalse(step["skipped"])

    def test_dispensar_esconde_e_recomecar_mostra(self):
        s = self.client.post("/api/onboarding/dismiss", headers=self.h()).json()
        self.assertTrue(s["dismissed"])
        self.assertFalse(s["visible"])
        self.assertTrue(self.state()["dismissed"])  # vale em outra sessão: está no servidor
        s = self.client.post("/api/onboarding/reset", headers=self.h()).json()
        self.assertTrue(s["visible"])
        self.assertEqual(self.progress()[0]["skipped"], {})

    def test_concluir_registra_uma_vez_e_audita(self):
        mid = str(uuid.uuid4())
        self.fake.tables["meetings"].append({"id": mid, "owner_id": UA, "org_id": None})
        self.add("actions", meeting_id=mid, org_id=None, text="t", created_by=UA)
        for table in ("clients", "conversations", "live_sessions"):
            self.add(table, owner_id=UA, org_id=None)
        s = self.state()
        self.assertEqual((s["finished"], s["completed"], s["visible"]), (5, True, False))
        first = self.progress()[0]["completed_at"]
        self.assertTrue(first)
        self.state()
        self.assertEqual(self.progress()[0]["completed_at"], first)
        self.assertEqual(len(self.fake.rows("audit_log", action="onboarding.complete")), 1)

    def test_tudo_pulado_tambem_conclui(self):
        for key in ob.KEYS:
            self.client.post(f"/api/onboarding/steps/{key}/skip", headers=self.h())
        s = self.state()
        self.assertTrue(s["completed"])
        self.assertEqual(s["done_count"], 0)


class Isolamento(Base):
    def test_cada_pessoa_tem_o_seu_progresso(self):
        self.client.post("/api/onboarding/dismiss", headers=self.h("tok-a"))
        self.client.post("/api/onboarding/steps/chat/skip", headers=self.h("tok-a"))
        s = self.state("tok-c")
        self.assertFalse(s["dismissed"])
        self.assertFalse(self.step(s, "chat")["skipped"])
        self.assertEqual(self.progress(UC), [])

    def test_nao_ha_como_gravar_progresso_de_outra_pessoa(self):
        with self.assertRaises(Exception):
            ob.sec.user_rest(ob.sec.AuthUser(id=UA, email="a@x.com", token="tok-a"), "POST", "onboarding_progress", {"user_id": UB})

    def test_auditoria_nao_guarda_conteudo(self):
        self.client.post("/api/onboarding/steps/chat/skip", headers=self.h())
        rows = self.fake.rows("audit_log", action="onboarding.skip")
        self.assertEqual(rows[0]["metadata"], {"step": "chat"})


class Falhas(Base):
    def test_erro_do_banco_vira_502_generico(self):
        self.fake.fail.add(("GET", "onboarding_progress"))
        r = self.client.get("/api/onboarding", headers=self.h())
        self.assertEqual(r.status_code, 502)
        self.assertNotIn("onboarding_progress", r.text)


if __name__ == "__main__":
    unittest.main()
