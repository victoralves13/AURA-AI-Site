"""Testes das ações: derivação a partir da análise, sincronização idempotente, edição, histórico e isolamento
(sem rede e sem OpenAI). As regras de RLS e dos gatilhos são testadas de verdade em tests/db/actions.test.mjs."""
import sys
import unittest
import uuid
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))

import actions as act  # noqa: E402
from test_orgs import OrgBase, ORG1, ORG2, UA, UB, UC, UD, UE  # noqa: E402
from test_security import minimal_analysis  # noqa: E402

TEXT = "Ana: Vamos avançar com a proposta.\nCarlos: Combinado, envio amanhã."
DETAIL = [
    {"description": "Enviar a proposta revisada", "evidence": "envio amanhã", "timestamp": "00:12", "speaker": "Carlos",
     "owner": "Carlos", "deadline": "2026-11-05", "basis": "dito", "evidence_check": "localizada"},
    {"description": "Agendar reunião de acompanhamento", "evidence": "talvez marcar", "owner": None, "deadline": "sexta",
     "basis": "inferido", "evidence_check": "parcial"},
    {"description": "Ação inventada sem lastro", "evidence": "isso nunca foi dito", "evidence_check": "nao_localizada"},
]


class Derivacao(unittest.TestCase):
    def test_detalhe_vira_acoes_com_base_e_evidencia(self):
        rows = act.actions_from_meeting({"actions_detail": DETAIL})
        self.assertEqual([r["text"] for r in rows], ["Enviar a proposta revisada", "Agendar reunião de acompanhamento"])
        first = rows[0]
        self.assertEqual((first["source"], first["basis"], first["assignee_text"], first["due_text"], first["due_date"]),
                         ("ai", "dito", "Carlos", "2026-11-05", "2026-11-05"))
        self.assertEqual(first["evidence"]["evidence"], "envio amanhã")
        self.assertEqual(first["evidence"]["timestamp"], "00:12")

    def test_evidencia_nao_localizada_nao_vira_acao(self):
        texts = [r["text"] for r in act.actions_from_meeting({"actions_detail": DETAIL})]
        self.assertNotIn("Ação inventada sem lastro", texts)

    def test_prazo_dito_em_palavras_nao_vira_data(self):
        second = act.actions_from_meeting({"actions_detail": DETAIL})[1]
        self.assertEqual((second["due_text"], second["due_date"], second["assignee_text"], second["basis"]), ("sexta", None, None, "inferido"))

    def test_reuniao_antiga_usa_o_texto_sem_inventar_responsavel_ou_prazo(self):
        rows = act.actions_from_meeting({"actions_detail": [], "pending_actions": ["Enviar contrato", "  ", "Enviar   contrato"],
                                          "owner": "Fulano", "deadline": "amanhã"})
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["text"], rows[0]["assignee_text"], rows[0]["due_text"], rows[0]["basis"]), ("Enviar contrato", None, None, None))

    def test_chave_ignora_acentos_caixa_e_pontuacao(self):
        self.assertEqual(act.source_key("Enviar proposta, já!"), act.source_key("enviar PROPOSTA ja"))
        self.assertNotEqual(act.source_key("Enviar proposta"), act.source_key("Enviar contrato"))

    def test_entradas_malformadas_nao_quebram(self):
        self.assertEqual(act.actions_from_meeting({}), [])
        self.assertEqual(act.actions_from_meeting({"actions_detail": ["x", None, {"description": ""}], "pending_actions": None}), [])

    def test_limite_por_reuniao(self):
        rows = act.actions_from_meeting({"pending_actions": [f"tarefa {i}" for i in range(200)]})
        self.assertEqual(len(rows), act.MAX_ACTIONS_PER_MEETING)


class Base(OrgBase):
    def add_meeting(self, owner=UA, org=ORG1, detail=None, pending=None, demo=False):
        row = {"id": str(uuid.uuid4()), "org_id": org, "owner_id": owner, "meeting_title": "Reunião", "client_name": "Atlas",
               "client_id": None, "actions_detail": detail if detail is not None else DETAIL, "pending_actions": pending or [],
               "is_demo": demo, "created_at": "2026-10-02T00:00:00+00:00"}
        self.fake.tables["meetings"].append(row)
        return row["id"]

    def actions(self, meeting=None):
        return [a for a in self.fake.tables["actions"] if meeting is None or a["meeting_id"] == meeting]

    def sync(self, mid, tok="tok-a"):
        return self.client.post(f"/api/meetings/{mid}/actions/sync", headers=self.h(tok))

    def make(self, mid, tok="tok-a", **body):
        body.setdefault("text", "Ligar para o cliente")
        return self.client.post(f"/api/meetings/{mid}/actions", headers=self.h(tok), json=body)

    def patch(self, aid, tok="tok-a", **body):
        return self.client.patch(f"/api/actions/{aid}", headers=self.h(tok), json=body)


class Acesso(Base):
    def test_tudo_exige_login(self):
        mid, aid = str(uuid.uuid4()), str(uuid.uuid4())
        c = self.client
        rotas = [c.get("/api/actions"), c.post("/api/actions/sync"), c.get(f"/api/meetings/{mid}/actions"),
                 c.post(f"/api/meetings/{mid}/actions/sync"), c.post(f"/api/meetings/{mid}/actions", json={"text": "x"}),
                 c.patch(f"/api/actions/{aid}", json={"status": "done"}), c.delete(f"/api/actions/{aid}"), c.get(f"/api/actions/{aid}/events")]
        self.assertEqual([r.status_code for r in rotas], [401] * len(rotas))

    def test_identificadores_invalidos(self):
        h = self.h()
        self.assertEqual(self.client.get("/api/meetings/xx/actions", headers=h).status_code, 400)
        self.assertEqual(self.client.patch("/api/actions/xx", headers=h, json={}).status_code, 400)
        self.assertEqual(self.client.get("/api/actions?org_id=xx", headers=h).status_code, 400)
        self.assertEqual(self.client.get("/api/actions?meeting_id=xx", headers=h).status_code, 400)

    def test_reuniao_de_outra_organizacao_e_invisivel(self):
        mid = self.add_meeting()
        self.assertEqual(self.sync(mid, "tok-d").status_code, 404)
        self.assertEqual(self.make(mid, "tok-d").status_code, 404)
        self.assertEqual(self.client.get(f"/api/meetings/{mid}/actions", headers=self.h("tok-d")).status_code, 404)
        self.assertEqual(self.actions(), [])

    def test_acao_de_outra_organizacao_e_invisivel(self):
        mid = self.add_meeting()
        self.sync(mid)
        aid = self.actions()[0]["id"]
        self.assertEqual(self.patch(aid, "tok-d", status="done").status_code, 404)
        self.assertEqual(self.client.delete(f"/api/actions/{aid}", headers=self.h("tok-d")).status_code, 404)
        self.assertEqual(self.client.get(f"/api/actions/{aid}/events", headers=self.h("tok-d")).status_code, 404)
        self.assertEqual(self.client.get("/api/actions", headers=self.h("tok-d")).json()["count"], 0)
        self.assertEqual(self.actions()[0]["status"], "open")

    def test_visivel_mas_sem_permissao_de_editar(self):
        mid = self.add_meeting()
        self.sync(mid)
        aid = self.actions()[0]["id"]
        self.fake.no_edit.add(mid)
        self.assertEqual(self.patch(aid, status="done").status_code, 403)
        self.assertEqual(self.make(mid).status_code, 403)
        user = self.make(mid)  # continua recusado
        self.assertEqual(user.status_code, 403)
        self.assertEqual(self.actions()[0]["status"], "open")


class Sincronizacao(Base):
    def test_cria_a_partir_da_analise_e_audita(self):
        mid = self.add_meeting()
        r = self.sync(mid)
        self.assertEqual((r.status_code, r.json()["created"]), (200, 2))
        rows = self.actions(mid)
        self.assertEqual({a["text"] for a in rows}, {"Enviar a proposta revisada", "Agendar reunião de acompanhamento"})
        self.assertTrue(all(a["source"] == "ai" and a["status"] == "open" and a["org_id"] == ORG1 for a in rows))
        self.assertIn("actions.sync", self.fake.actions())

    def test_e_idempotente(self):
        mid = self.add_meeting()
        self.sync(mid)
        again = self.sync(mid)
        self.assertEqual(again.json()["created"], 0)
        self.assertEqual(len(self.actions(mid)), 2)

    def test_nao_recria_acao_cancelada_nem_concluida(self):
        mid = self.add_meeting()
        self.sync(mid)
        self.patch(self.actions(mid)[0]["id"], status="cancelled")
        self.sync(mid)
        self.assertEqual([a["status"] for a in self.actions(mid)], ["cancelled", "open"])

    def test_reuniao_antiga(self):
        mid = self.add_meeting(detail=[], pending=["Enviar contrato", "Revisar preço"])
        self.assertEqual(self.sync(mid).json()["created"], 2)
        self.assertTrue(all(a["assignee_text"] is None and a["due_text"] is None for a in self.actions(mid)))

    def test_sincronizacao_do_espaco_ignora_demo_e_outros_espacos(self):
        m1, m2 = self.add_meeting(), self.add_meeting(owner=UC)
        self.add_meeting(demo=True)
        self.add_meeting(owner=UD, org=ORG2)
        r = self.client.post(f"/api/actions/sync?org_id={ORG1}", headers=self.h())
        self.assertEqual((r.status_code, r.json()["meetings"], r.json()["created"]), (200, 2, 4))
        self.assertEqual({a["meeting_id"] for a in self.actions()}, {m1, m2})

    def test_falha_do_banco_nao_derruba_a_sincronizacao_da_reuniao(self):
        mid = self.add_meeting()
        self.fake.fail.add(("POST", "actions"))
        r = self.sync(mid)
        self.assertEqual((r.status_code, r.json()["created"]), (200, 0))


class Edicao(Base):
    def setUp(self):
        super().setUp()
        self.mid = self.add_meeting()
        self.sync(self.mid)
        self.ai = self.actions(self.mid)[0]["id"]

    def test_estado_responsavel_e_prazo(self):
        r = self.patch(self.ai, status="in_progress", assignee_text="Bruno", due_date="2026-12-01", due_text="1º de dezembro")
        self.assertEqual(r.status_code, 200, r.text)
        a = self.actions()[0]
        self.assertEqual((a["status"], a["assignee_text"], a["due_date"]), ("in_progress", "Bruno", "2026-12-01"))
        done = self.patch(self.ai, status="done").json()["action"]
        self.assertIsNotNone(done["completed_at"])
        self.assertIsNone(self.patch(self.ai, status="open").json()["action"]["completed_at"])

    def test_vazio_limpa_o_campo(self):
        self.patch(self.ai, assignee_text="Bruno", due_date="2026-12-01")
        r = self.patch(self.ai, assignee_text="", due_date=None)
        self.assertEqual(r.status_code, 200)
        a = self.actions()[0]
        self.assertEqual((a["assignee_text"], a["due_date"]), (None, None))

    def test_campos_ausentes_nao_sao_alterados(self):
        self.patch(self.ai, assignee_text="Bruno")
        self.patch(self.ai, status="in_progress")
        self.assertEqual(self.actions()[0]["assignee_text"], "Bruno")

    def test_entradas_invalidas(self):
        for body in ({"status": "feito"}, {"due_date": "amanhã"}, {"due_date": "2026-13-45"}, {"assignee_user_id": "nao-e-uuid"},
                     {"assignee_text": "x" * 201}, {"text": ""}):
            self.assertEqual(self.patch(self.ai, **body).status_code, 400, body)
        self.assertFalse([c for c in self.fake.calls if c[0] == "PATCH" and "actions" in c[1]])  # nada chegou ao banco

    def test_corpo_vazio_nao_altera_nada(self):
        before = dict(self.actions()[0])
        self.assertEqual(self.patch(self.ai).status_code, 200)
        self.assertEqual(self.actions()[0], before)

    def test_responsavel_cadastrado_precisa_ser_membro(self):
        self.assertEqual(self.patch(self.ai, assignee_user_id=UD).status_code, 400)  # membro só de outra organização
        self.assertEqual(self.patch(self.ai, assignee_user_id=UE).status_code, 400)  # sem organização
        ok = self.patch(self.ai, assignee_user_id=UC)
        self.assertEqual((ok.status_code, self.actions()[0]["assignee_user_id"]), (200, UC))

    def test_texto_de_acao_da_ia_nao_muda(self):
        r = self.patch(self.ai, text="Outra coisa")
        self.assertEqual(r.status_code, 409)
        self.assertEqual(self.actions()[0]["text"], "Enviar a proposta revisada")

    def test_acao_digitada_pode_ter_o_texto_editado(self):
        aid = self.make(self.mid, assignee_text="Ana", due_date="2026-11-30").json()["action"]["id"]
        r = self.patch(aid, text="Ligar para o financeiro")
        self.assertEqual((r.status_code, r.json()["action"]["text"]), (200, "Ligar para o financeiro"))

    def test_nao_apaga_acao_da_ia_mas_apaga_a_digitada(self):
        self.assertEqual(self.client.delete(f"/api/actions/{self.ai}", headers=self.h()).status_code, 409)
        aid = self.make(self.mid).json()["action"]["id"]
        self.assertEqual(self.client.delete(f"/api/actions/{aid}", headers=self.h()).status_code, 200)
        self.assertNotIn(aid, [a["id"] for a in self.actions()])
        self.assertIn(self.ai, [a["id"] for a in self.actions()])

    def test_apagar_sem_permissao_e_403(self):
        aid = self.make(self.mid).json()["action"]["id"]
        self.fake.no_edit.add(self.mid)
        self.assertEqual(self.client.delete(f"/api/actions/{aid}", headers=self.h()).status_code, 403)
        self.assertIn(aid, [a["id"] for a in self.actions()])

    def test_historico(self):
        self.patch(self.ai, status="in_progress")
        self.patch(self.ai, assignee_text="Bruno", due_date="2026-12-01")
        ev = self.client.get(f"/api/actions/{self.ai}/events", headers=self.h()).json()["events"]
        self.assertEqual([e["event"] for e in ev], ["created", "status", "assignee", "due"])
        self.assertEqual(ev[1]["data"], {"from": "open", "to": "in_progress"})
        self.assertTrue(all(e["actor_id"] == UA for e in ev[1:]))

    def test_auditoria_sem_conteudo_da_acao(self):
        self.patch(self.ai, status="done")
        entry = [r for r in self.fake.tables["audit_log"] if r["action"] == "action.update"][0]
        self.assertEqual(entry["metadata"], {"fields": ["status"]})
        self.assertNotIn("Enviar", str(entry))

    def test_falha_do_banco_vira_502_sem_detalhes(self):
        self.fake.fail.add(("PATCH", "actions"))
        r = self.patch(self.ai, status="done")
        self.assertEqual(r.status_code, 502)
        self.assertNotIn("boom", r.text)


class Criacao(Base):
    def test_cria_acao_digitada(self):
        mid = self.add_meeting()
        r = self.make(mid, text="  Ligar   para o cliente ", assignee_text="Ana", due_text="semana que vem", due_date="2026-11-10")
        self.assertEqual(r.status_code, 200, r.text)
        a = self.actions(mid)[0]
        self.assertEqual((a["text"], a["source"], a["basis"], a["status"], a["org_id"], a["created_by"]),
                         ("Ligar para o cliente", "user", None, "open", ORG1, UA))
        self.assertIn("action.create", self.fake.actions())

    def test_texto_obrigatorio_e_limitado(self):
        mid = self.add_meeting()
        self.assertEqual(self.make(mid, text="   ").status_code, 400)
        self.assertEqual(self.make(mid, text="x" * 1001).status_code, 400)
        self.assertEqual(self.client.post(f"/api/meetings/{mid}/actions", headers=self.h(), json={}).status_code, 422)

    def test_o_cliente_nao_escolhe_origem_nem_espaco(self):
        mid = self.add_meeting()
        r = self.client.post(f"/api/meetings/{mid}/actions", headers=self.h(),
                             json={"text": "x", "source": "ai", "org_id": ORG2, "status": "done", "meeting_id": str(uuid.uuid4())})
        self.assertEqual(r.status_code, 200)
        a = self.actions()[0]
        self.assertEqual((a["source"], a["org_id"], a["status"], a["meeting_id"]), ("user", ORG1, "open", mid))

    def test_colaborador_cria_na_propria_reuniao(self):
        mid = self.add_meeting(owner=UC)
        self.assertEqual(self.make(mid, "tok-c").status_code, 200)

    def test_pessoal(self):
        mid = self.add_meeting(owner=UE, org=None)
        self.assertEqual(self.make(mid, "tok-e").status_code, 200)
        self.assertIsNone(self.actions(mid)[0]["org_id"])
        self.assertEqual(self.make(mid, "tok-e", assignee_user_id=UE).status_code, 400)  # responsável cadastrado só em organização


class Listagem(Base):
    def setUp(self):
        super().setUp()
        self.m1 = self.add_meeting()
        self.m2 = self.add_meeting(owner=UC)
        self.mp = self.add_meeting(owner=UA, org=None)
        for m in (self.m1, self.m2, self.mp):
            self.sync(m)
        self.fake.rows("meetings", id=self.m1)[0]["client_id"] = "c1c1c1c1-0000-0000-0000-000000000001"

    def get(self, qs="", tok="tok-a"):
        r = self.client.get("/api/actions" + qs, headers=self.h(tok))
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()["actions"]

    def test_recorte_por_espaco(self):
        self.assertEqual({a["meeting_id"] for a in self.get(f"?org_id={ORG1}")}, {self.m1, self.m2})
        self.assertEqual({a["meeting_id"] for a in self.get("?org_id=personal")}, {self.mp})
        self.assertEqual(len(self.get()), 6)

    def test_mostra_a_reuniao_de_origem(self):
        a = self.get(f"?meeting_id={self.m1}")[0]
        self.assertEqual(a["meetings"]["meeting_title"], "Reunião")

    def test_filtros_de_estado(self):
        first = self.get(f"?meeting_id={self.m1}")[0]["id"]
        self.patch(first, status="done")
        self.assertEqual(len(self.get("?status=done")), 1)
        self.assertEqual(len(self.get("?status=active")), 5)
        self.assertEqual(self.client.get("/api/actions?status=xx", headers=self.h()).status_code, 400)

    def test_filtro_por_responsavel_e_atraso(self):
        ids = [a["id"] for a in self.get(f"?meeting_id={self.m1}")]
        self.patch(ids[0], assignee_user_id=UA, due_date=(date.today() - timedelta(days=2)).isoformat())
        self.patch(ids[1], due_date=(date.today() + timedelta(days=2)).isoformat())
        self.assertEqual([a["id"] for a in self.get("?assignee=me")], [ids[0]])
        self.assertEqual([a["id"] for a in self.get("?overdue=true")], [ids[0]])
        self.patch(ids[0], status="done")
        self.assertEqual(self.get("?overdue=true"), [])  # concluída não conta como atrasada

    def test_filtro_por_cliente(self):
        got = self.get("?client_id=c1c1c1c1-0000-0000-0000-000000000001")
        self.assertEqual({a["meeting_id"] for a in got}, {self.m1})
        self.assertEqual(self.get("?client_id=c1c1c1c1-0000-0000-0000-0000000000ff"), [])

    def test_colaborador_so_ve_as_da_propria_reuniao(self):
        self.assertEqual({a["meeting_id"] for a in self.get("", "tok-c")}, {self.m2})

    def test_limite(self):
        self.assertEqual(len(self.get("?limit=2")), 2)

    def test_limite_e_sempre_contido(self):
        for qs, expected in (("?limit=0", "limit=1"), ("?limit=999999", "limit=500")):
            self.fake.calls.clear()
            self.get(qs)
            urls = [c[1] for c in self.fake.calls if c[0] == "GET" and "rest/v1/actions" in c[1]]
            self.assertTrue(urls and urls[0].endswith(expected), urls)


class AoAnalisar(Base):
    def setUp(self):
        super().setUp()
        from openai_engine import ActionItem
        analysis = minimal_analysis().model_copy(update={"pending_actions": [ActionItem(
            description="Enviar a proposta", evidence="envio amanhã", owner="Carlos", deadline="amanhã")]})
        p = mock.patch("openai_engine.analyze_transcript", lambda text, context="Outro": analysis)
        p.start()
        self.addCleanup(p.stop)
        self.fake.tables["meetings"].append({"id": "m-1", "org_id": ORG1, "owner_id": UA})  # a que o salvamento simulado devolve

    def analyze(self, tok="tok-a"):
        return self.client.post("/api/analyze-transcript", headers=self.h(tok),
                                json={"transcript": TEXT, "context": "Comercial", "org_id": ORG1})

    def test_a_analise_gera_as_acoes(self):
        self.assertEqual(self.analyze().status_code, 200)
        rows = self.actions("m-1")
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["text"], rows[0]["assignee_text"], rows[0]["due_text"], rows[0]["source"]),
                         ("Enviar a proposta", "Carlos", "amanhã", "ai"))
        self.assertEqual(rows[0]["basis"], "dito")

    def test_falha_nas_acoes_nao_perde_a_analise(self):
        self.fake.fail.add(("POST", "actions"))
        r = self.analyze()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.actions(), [])
        self.assertEqual(len(self.saved), 1)  # a reunião foi salva

    def test_reanalise_nao_duplica(self):
        self.analyze()
        self.analyze()
        self.assertEqual(len(self.actions("m-1")), 1)


if __name__ == "__main__":
    unittest.main()
