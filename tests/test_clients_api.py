"""Testes de clientes: vínculo ao analisar, edição, troca de vínculo e fusão (sem rede e sem OpenAI)."""
import sys
import unittest
import uuid
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from aura.features.clients import router as c  # noqa: E402
from test_orgs import OrgBase, ORG1, ORG2, UA, UB, UC, UD, UE  # noqa: E402
from test_security import minimal_analysis  # noqa: E402

TEXT = "Ana: Vamos avançar com a proposta.\nCarlos: Combinado, envio amanhã."
NOT_VISIBLE = "88888888-8888-8888-8888-888888888888"


class Base(OrgBase):
    def setUp(self):
        super().setUp()
        self.ai_name = None
        analysis = lambda text, context="Outro": minimal_analysis().model_copy(update={"client_name": self.ai_name})
        p = mock.patch("aura.features.analysis.engine.analyze_transcript", analysis)
        p.start()
        self.addCleanup(p.stop)

    def add_client(self, name, org=ORG1, owner=UA, aliases=None, merged_into=None):
        row = {"id": str(uuid.uuid4()), "org_id": org, "owner_id": owner, "name": name, "normalized_name": c.normalize_name(name),
               "aliases": aliases or [], "created_via": "user", "created_at": "2026-10-01T00:00:00+00:00",
               "merged_into": merged_into, "merged_meeting_ids": []}
        self.fake.tables["clients"].append(row)
        return row["id"]

    def add_meeting(self, org=ORG1, owner=UA, client_id=None, link="unlinked"):
        row = {"id": str(uuid.uuid4()), "org_id": org, "owner_id": owner, "client_id": client_id, "client_link": link,
               "client_suggestion": [], "meeting_title": "Reunião", "created_at": "2026-10-02T00:00:00+00:00"}
        self.fake.tables["meetings"].append(row)
        return row["id"]

    def meeting(self, mid):
        return next(m for m in self.fake.tables["meetings"] if m["id"] == mid)

    def row_client(self, cid):
        return next(x for x in self.fake.tables["clients"] if x["id"] == cid)

    def analyze(self, tok="tok-a", typed=None, ai=None, org=ORG1, **extra):
        self.ai_name = ai
        body = {"transcript": TEXT, "context": "Comercial", **extra}
        if typed is not None:
            body["client_name"] = typed
        if org:
            body["org_id"] = org
        r = self.client.post("/api/analyze-transcript", headers=self.h(tok), json=body)
        self.assertEqual(r.status_code, 200, r.text)
        return self.saved[-1][0]


class VinculoAoAnalisar(Base):
    def test_nome_da_ia_igual_vincula_automaticamente(self):
        atlas = self.add_client("Grupo Atlas")
        p = self.analyze(ai="Grupo Atlas Ltda.")
        self.assertEqual((p["client_id"], p["client_link"]), (atlas, "auto"))

    def test_nome_da_ia_parecido_so_sugere(self):
        atlas = self.add_client("Grupo Atlas")
        p = self.analyze(ai="Atlas")
        self.assertNotIn("client_id", p)
        self.assertEqual(p["client_link"], "suggested")
        kinds = [(s["kind"], s.get("client_id")) for s in p["client_suggestion"]]
        self.assertEqual(kinds, [("existing", atlas), ("new", None)])
        self.assertEqual(len(self.fake.tables["clients"]), 1)  # nada foi criado

    def test_nome_da_ia_sem_correspondencia_propoe_e_espera(self):
        self.add_client("Grupo Atlas")
        p = self.analyze(ai="Nova Empresa SA")
        self.assertEqual((p["client_link"], p["client_suggestion"]), ("suggested", [{"kind": "new", "name": "Nova Empresa SA"}]))
        self.assertEqual(len(self.fake.tables["clients"]), 1)

    def test_nome_ambiguo_nunca_e_decidido_sozinho(self):
        self.add_client("Atlas Norte", aliases=["Atlas"])
        self.add_client("Atlas Sul", aliases=["Atlas"])
        p = self.analyze(ai="Atlas")
        self.assertEqual(p["client_link"], "suggested")
        self.assertEqual(len([s for s in p["client_suggestion"] if s["kind"] == "existing"]), 2)

    def test_sem_nome_ou_marcador_fica_sem_vinculo(self):
        self.add_client("Grupo Atlas")
        for typed, ai in [(None, None), ("Cliente não identificado", None), ("Cliente não identificado", "Cliente não identificado")]:
            p = self.analyze(typed=typed, ai=ai)
            self.assertNotIn("client_link", p)  # padrão do banco: unlinked
            self.assertNotIn("client_id", p)

    def test_marcador_enviado_pela_interface_nao_apaga_o_cliente_da_ia(self):
        """Correção do bug: antes "Cliente não identificado" sobrescrevia o nome extraído pela IA."""
        atlas = self.add_client("Grupo Atlas")
        p = self.analyze(typed="Cliente não identificado", ai="Grupo Atlas")
        self.assertEqual(p["client_name"], "Grupo Atlas")
        self.assertEqual((p["client_id"], p["client_link"]), (atlas, "auto"))

    def test_nome_digitado_igual_confirma_parecido_sugere_novo_cria(self):
        atlas = self.add_client("Grupo Atlas")
        p = self.analyze(typed="GRUPO ATLAS")
        self.assertEqual((p["client_id"], p["client_link"]), (atlas, "confirmed"))
        p = self.analyze(typed="Atlas")
        self.assertEqual(p["client_link"], "suggested")
        self.assertEqual(len(self.fake.tables["clients"]), 1)  # parecido não cria duplicado
        p = self.analyze(typed="Horizonte Digital")
        self.assertEqual(p["client_link"], "confirmed")
        created = self.row_client(p["client_id"])
        self.assertEqual((created["name"], created["created_via"], created["org_id"], created["owner_id"]), ("Horizonte Digital", "user", ORG1, UA))
        self.assertIn("client.create", self.fake.actions())

    def test_nome_digitado_vence_o_da_ia(self):
        atlas = self.add_client("Grupo Atlas")
        self.add_client("Grupo Horizonte")
        p = self.analyze(typed="Grupo Atlas", ai="Grupo Horizonte")
        self.assertEqual(p["client_id"], atlas)

    def test_reuniao_demo_nao_cria_nem_vincula(self):
        p = self.analyze(typed="Grupo Atlas", is_demo=True)
        self.assertNotIn("client_id", p)
        self.assertEqual(self.fake.tables["clients"], [])

    def test_sem_login_nada_de_clientes(self):
        with mock.patch.dict("os.environ", {"AURA_AUTH_REQUIRED": ""}):
            r = self.client.post("/api/analyze-transcript", json={"transcript": TEXT, "client_name": "Grupo Atlas"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertFalse(any("/clients" in call[1] for call in self.fake.calls))
        self.assertNotIn("client_id", self.saved[-1][0])

    def test_isolamento_entre_espacos(self):
        self.add_client("Grupo Atlas", org=ORG2, owner=UD)               # outra organização
        self.add_client("Grupo Atlas", org=None, owner=UC)               # conta pessoal de outra pessoa
        p = self.analyze(ai="Grupo Atlas")                                # UA na ORG1: nenhum dos dois pode casar
        self.assertEqual((p["client_link"], p["client_suggestion"]), ("suggested", [{"kind": "new", "name": "Grupo Atlas"}]))
        p = self.analyze(ai="Grupo Atlas", org=None)                      # UA no espaço pessoal
        self.assertEqual(p["client_link"], "suggested")
        self.assertEqual(len(self.fake.tables["clients"]), 2)

    def test_mesmo_usuario_nao_mistura_organizacao_e_espaco_pessoal(self):
        """UA é membro da ORG1 e enxerga o cliente dela; ainda assim a análise pessoal não pode casar com ele."""
        org_client = self.add_client("Grupo Atlas", org=ORG1, owner=UA)
        p = self.analyze(ai="Grupo Atlas", org=None)
        self.assertNotIn("client_id", p)
        self.assertEqual((p["client_link"], p["client_suggestion"]), ("suggested", [{"kind": "new", "name": "Grupo Atlas"}]))
        p = self.analyze(typed="Grupo Atlas", org=None)  # digitado no espaço pessoal: cria o cliente pessoal, não usa o da organização
        self.assertNotEqual(p["client_id"], org_client)
        self.assertIsNone(self.row_client(p["client_id"])["org_id"])

    def test_cliente_pessoal_nao_casa_na_organizacao_e_vice_versa(self):
        mine = self.add_client("Grupo Atlas", org=None, owner=UA)
        p = self.analyze(ai="Grupo Atlas", org=None)
        self.assertEqual((p["client_id"], p["client_link"]), (mine, "auto"))
        p = self.analyze(ai="Grupo Atlas", org=ORG1)
        self.assertEqual(p["client_link"], "suggested")

    def test_clientes_fundidos_nao_participam(self):
        target = self.add_client("Grupo Atlas")
        self.add_client("Atlas Antigo", merged_into=target)
        p = self.analyze(ai="Atlas Antigo")
        self.assertNotIn("client_id", p)  # o cliente fundido não casa nem automaticamente
        self.assertEqual(p["client_link"], "suggested")  # só é parecido com o cliente ativo
        self.assertEqual([s.get("client_id") for s in p["client_suggestion"] if s["kind"] == "existing"], [target])

    def test_falha_no_banco_de_clientes_nao_perde_a_analise(self):
        self.add_client("Grupo Atlas")
        self.fake.fail.add(("GET", "clients"))
        p = self.analyze(ai="Grupo Atlas")
        self.assertNotIn("client_id", p)
        self.assertEqual(p["client_name"], "Grupo Atlas")


class Listagem(Base):
    def test_lista_clientes_ativos_com_contagem_e_pendencias(self):
        a = self.add_client("Grupo Atlas")
        self.add_client("Antigo", merged_into=a)
        self.add_client("Outra Org", org=ORG2, owner=UD)
        self.add_meeting(client_id=a, link="confirmed")
        self.add_meeting(client_id=a, link="auto")
        self.add_meeting(link="suggested")
        r = self.client.get(f"/api/clients?org_id={ORG1}", headers=self.h("tok-c")).json()
        # UC é colaborador: não enxerga as reuniões dos outros, então não conta nenhuma
        self.assertEqual([(x["name"], x["meetings"]) for x in r["clients"]], [("Grupo Atlas", 0)])
        self.assertEqual(r["pending_suggestions"], 0)
        r = self.client.get(f"/api/clients?org_id={ORG1}", headers=self.h("tok-b")).json()  # gestor vê todas
        self.assertEqual((r["clients"][0]["meetings"], r["pending_suggestions"]), (2, 1))

    def test_espacos_e_permissoes(self):
        self.add_client("Pessoal", org=None, owner=UA)
        self.assertEqual([x["name"] for x in self.client.get("/api/clients?org_id=personal", headers=self.h()).json()["clients"]], ["Pessoal"])
        self.assertEqual(self.client.get("/api/clients", headers=self.h("tok-b")).json()["clients"], [])  # espaço pessoal de UB
        self.assertEqual(self.client.get(f"/api/clients?org_id={ORG2}", headers=self.h()).status_code, 403)
        self.assertEqual(self.client.get("/api/clients?org_id=xx", headers=self.h()).status_code, 400)
        self.assertEqual(self.client.get("/api/clients").status_code, 401)


class Edicao(Base):
    def test_criar(self):
        r = self.client.post("/api/clients", headers=self.h("tok-c"), json={"name": "  Nova   Tech Ltda ", "aliases": ["NovaTech", "novatech", "Nova Tech", ""], "org_id": ORG1})
        self.assertEqual(r.status_code, 200, r.text)
        row = r.json()["client"]
        self.assertEqual((row["name"], row["normalized_name"], row["created_via"]), ("Nova Tech Ltda", "nova tech", "user"))
        self.assertEqual(row["aliases"], ["NovaTech"])  # sem repetidos nem o próprio nome
        self.assertIn("client.create", self.fake.actions())

    def test_validacoes_e_duplicado(self):
        self.assertEqual(self.client.post("/api/clients", headers=self.h(), json={"name": "  ", "org_id": ORG1}).status_code, 400)
        self.assertEqual(self.client.post("/api/clients", headers=self.h(), json={"name": "x" * 201, "org_id": ORG1}).status_code, 400)
        self.assertEqual(self.client.post("/api/clients", headers=self.h(), json={"name": "Atlas", "org_id": ORG1}).status_code, 200)
        r = self.client.post("/api/clients", headers=self.h("tok-b"), json={"name": "ATLAS Ltda", "org_id": ORG1})
        self.assertEqual(r.status_code, 409)
        self.assertEqual(self.client.post("/api/clients", headers=self.h("tok-e"), json={"name": "Atlas", "org_id": ORG1}).status_code, 403)
        self.assertEqual(self.client.post("/api/clients", headers=self.h("tok-e"), json={"name": "Atlas"}).status_code, 200)  # espaço pessoal de UE

    def test_renomear_e_apelidos(self):
        cid = self.add_client("Atlas")
        r = self.client.patch(f"/api/clients/{cid}", headers=self.h("tok-c"), json={"name": "Grupo Atlas", "aliases": ["Atlas", "Atlas Corp", "Grupo Atlas"]})
        self.assertEqual(r.status_code, 200, r.text)
        row = self.row_client(cid)
        self.assertEqual((row["name"], row["normalized_name"], row["aliases"]), ("Grupo Atlas", "grupo atlas", ["Atlas", "Atlas Corp"]))
        self.assertIn("client.update", self.fake.actions())
        self.assertEqual(self.client.patch(f"/api/clients/{cid}", headers=self.h(), json={"name": " "}).status_code, 400)

    def test_quem_nao_ve_o_cliente_nao_edita_nem_le(self):
        cid = self.add_client("Atlas")
        self.assertEqual(self.client.patch(f"/api/clients/{cid}", headers=self.h("tok-d"), json={"name": "X"}).status_code, 404)
        self.assertEqual(self.client.get(f"/api/clients/{cid}", headers=self.h("tok-d")).status_code, 404)
        self.assertEqual(self.row_client(cid)["name"], "Atlas")

    def test_detalhe_traz_reunioes_visiveis(self):
        cid = self.add_client("Atlas")
        mine = self.add_meeting(owner=UC, client_id=cid, link="confirmed")
        self.add_meeting(owner=UB, client_id=cid, link="auto")
        ids = [m["id"] for m in self.client.get(f"/api/clients/{cid}", headers=self.h("tok-c")).json()["meetings"]]
        self.assertEqual(ids, [mine])  # colaborador só vê as próprias
        self.assertEqual(len(self.client.get(f"/api/clients/{cid}", headers=self.h("tok-b")).json()["meetings"]), 2)

    def test_exige_login(self):
        cid = self.add_client("Atlas")
        for r in [self.client.post("/api/clients", json={"name": "x"}), self.client.patch(f"/api/clients/{cid}", json={}),
                  self.client.get(f"/api/clients/{cid}"), self.client.post(f"/api/clients/{cid}/merge", json={"into": cid}),
                  self.client.post(f"/api/clients/{cid}/unmerge"), self.client.patch(f"/api/meetings/{cid}/client", json={"action": "unlink"})]:
            self.assertEqual(r.status_code, 401)


class TrocaDeVinculo(Base):
    def test_confirmar_sugestao_e_desvincular(self):
        atlas = self.add_client("Grupo Atlas")
        mid = self.add_meeting(link="suggested")
        r = self.client.patch(f"/api/meetings/{mid}/client", headers=self.h(), json={"action": "confirm", "client_id": atlas})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((self.meeting(mid)["client_id"], self.meeting(mid)["client_link"]), (atlas, "confirmed"))
        self.assertEqual(self.meeting(mid)["client_suggestion"], [])
        r = self.client.patch(f"/api/meetings/{mid}/client", headers=self.h(), json={"action": "unlink"})
        self.assertEqual((self.meeting(mid)["client_id"], self.meeting(mid)["client_link"]), (None, "unlinked"))
        self.assertIn("meeting.client_link", self.fake.actions())

    def test_criar_cliente_proposto(self):
        mid = self.add_meeting(link="suggested")
        r = self.client.patch(f"/api/meetings/{mid}/client", headers=self.h(), json={"action": "create", "name": "Horizonte Digital"})
        self.assertEqual(r.status_code, 200, r.text)
        new = self.row_client(self.meeting(mid)["client_id"])
        self.assertEqual((new["name"], new["org_id"], new["created_via"]), ("Horizonte Digital", ORG1, "user"))
        dup = self.client.patch(f"/api/meetings/{mid}/client", headers=self.h(), json={"action": "create", "name": "horizonte digital"})
        self.assertEqual(dup.status_code, 409)

    def test_cliente_de_outro_espaco_e_recusado(self):
        personal = self.add_client("Pessoal", org=None, owner=UA)
        mid = self.add_meeting()
        r = self.client.patch(f"/api/meetings/{mid}/client", headers=self.h(), json={"action": "set", "client_id": personal})
        self.assertEqual(r.status_code, 409)
        self.assertIsNone(self.meeting(mid)["client_id"])
        theirs = self.add_client("De outra org", org=ORG2, owner=UD)
        r = self.client.patch(f"/api/meetings/{mid}/client", headers=self.h(), json={"action": "set", "client_id": theirs})
        self.assertEqual(r.status_code, 404)  # nem enxerga

    def test_cliente_fundido_e_recusado(self):
        target = self.add_client("Grupo Atlas")
        merged = self.add_client("Atlas Antigo", merged_into=target)
        mid = self.add_meeting()
        r = self.client.patch(f"/api/meetings/{mid}/client", headers=self.h(), json={"action": "set", "client_id": merged})
        self.assertEqual(r.status_code, 409)

    def test_a_api_confere_espaco_e_fusao_mesmo_sem_o_gatilho_do_banco(self):
        """Defesa em profundidade: a API recusa sozinha; o gatilho do banco é a segunda barreira."""
        self.fake._scope_error = lambda meeting, client: None  # simula um banco sem o gatilho
        personal = self.add_client("Pessoal", org=None, owner=UA)
        merged = self.add_client("Atlas Antigo", merged_into=self.add_client("Grupo Atlas"))
        mid = self.add_meeting()
        for cid in (personal, merged):
            r = self.client.patch(f"/api/meetings/{mid}/client", headers=self.h(), json={"action": "set", "client_id": cid})
            self.assertEqual(r.status_code, 409)
        self.assertIsNone(self.meeting(mid)["client_id"])

    def test_so_quem_pode_alterar_a_reuniao(self):
        atlas = self.add_client("Grupo Atlas")
        alheia = self.add_meeting(owner=UA)
        self.assertEqual(self.client.patch(f"/api/meetings/{alheia}/client", headers=self.h("tok-c"), json={"action": "unlink"}).status_code, 404)  # colaborador nem vê
        self.assertEqual(self.client.patch(f"/api/meetings/{alheia}/client", headers=self.h("tok-b"), json={"action": "set", "client_id": atlas}).status_code, 200)  # gestor gerencia
        self.assertEqual(self.client.patch(f"/api/meetings/{alheia}/client", headers=self.h("tok-d"), json={"action": "unlink"}).status_code, 404)  # outra org
        self.assertEqual(self.meeting(alheia)["client_id"], atlas)

    def test_entradas_invalidas(self):
        mid = self.add_meeting()
        for body in [{"action": "apagar"}, {"action": "set"}, {"action": "set", "client_id": "xx"}, {"action": "create", "name": " "}]:
            self.assertEqual(self.client.patch(f"/api/meetings/{mid}/client", headers=self.h(), json=body).status_code, 400, body)
        self.assertEqual(self.client.patch("/api/meetings/xx/client", headers=self.h(), json={"action": "unlink"}).status_code, 400)
        self.assertEqual(self.client.patch(f"/api/meetings/{NOT_VISIBLE}/client", headers=self.h(), json={"action": "unlink"}).status_code, 404)


class Fusao(Base):
    def setUp(self):
        super().setUp()
        self.src = self.add_client("Atlas Sul", aliases=["AtlasSul"])
        self.dst = self.add_client("Grupo Atlas")
        self.m1 = self.add_meeting(client_id=self.src, link="auto")
        self.m2 = self.add_meeting(owner=UB, client_id=self.src, link="confirmed")

    def merge(self, tok="tok-b", src=None, into=None):
        return self.client.post(f"/api/clients/{src or self.src}/merge", headers=self.h(tok), json={"into": into or self.dst})

    def test_gestor_funde_e_move_as_reunioes(self):
        r = self.merge()
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["moved"], 2)
        self.assertTrue(all(self.meeting(m)["client_id"] == self.dst and self.meeting(m)["client_link"] == "confirmed" for m in (self.m1, self.m2)))
        self.assertEqual(self.row_client(self.src)["merged_into"], self.dst)
        self.assertEqual(set(self.row_client(self.dst)["aliases"]), {"Atlas Sul", "AtlasSul"})
        self.assertIn("client.merge", self.fake.actions())
        # o cliente fundido some da lista e deixa de casar na análise
        names = [x["name"] for x in self.client.get(f"/api/clients?org_id={ORG1}", headers=self.h()).json()["clients"]]
        self.assertEqual(names, ["Grupo Atlas"])
        self.assertEqual(self.analyze(ai="Atlas Sul")["client_link"], "auto")  # agora é apelido do destino

    def test_quem_nao_gerencia_nao_funde(self):
        self.assertEqual(self.merge("tok-c").status_code, 403)       # colaborador
        self.assertEqual(self.merge("tok-d").status_code, 404)       # admin de outra organização: nem enxerga
        self.assertEqual(self.merge("tok-e").status_code, 404)
        self.assertIsNone(self.row_client(self.src)["merged_into"])
        self.assertEqual(self.meeting(self.m1)["client_id"], self.src)

    def test_casos_invalidos(self):
        self.assertEqual(self.merge(into=self.src).status_code, 400)
        self.assertEqual(self.merge(into="xx").status_code, 400)
        self.assertEqual(self.merge(into=NOT_VISIBLE).status_code, 404)
        personal = self.add_client("Pessoal", org=None, owner=UA)
        self.assertEqual(self.merge(into=personal, tok="tok-a").status_code, 409)  # espaços diferentes
        self.assertEqual(self.merge().status_code, 200)
        self.assertEqual(self.merge().status_code, 409)             # já fundido

    def test_desfazer(self):
        self.merge()
        self.assertEqual(self.client.post(f"/api/clients/{self.src}/unmerge", headers=self.h("tok-c")).status_code, 403)
        r = self.client.post(f"/api/clients/{self.src}/unmerge", headers=self.h("tok-b"))
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["restored"], 2)
        self.assertTrue(all(self.meeting(m)["client_id"] == self.src for m in (self.m1, self.m2)))
        self.assertIsNone(self.row_client(self.src)["merged_into"])
        self.assertEqual(self.row_client(self.dst)["aliases"], [])
        self.assertEqual(self.client.post(f"/api/clients/{self.src}/unmerge", headers=self.h("tok-b")).status_code, 409)
        self.assertIn("client.unmerge", self.fake.actions())

    def test_personal_o_dono_funde_os_proprios(self):
        a, b = self.add_client("Pessoal A", org=None, owner=UE), self.add_client("Pessoal B", org=None, owner=UE)
        self.assertEqual(self.merge("tok-e", a, b).status_code, 200)
        self.assertEqual(self.merge("tok-a", a, b).status_code, 404)


if __name__ == "__main__":
    unittest.main()
