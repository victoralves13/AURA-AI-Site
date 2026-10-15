"""Testes das conversas do chat: criação, escopo, privacidade, mensagens e resposta gravada só pelo backend
(sem rede e sem OpenAI). As regras de RLS e dos gatilhos são testadas de verdade em tests/db/chat.test.mjs."""
import sys
import unittest
import uuid
from pathlib import Path

from aura.features.chat import service as conv  # noqa: E402
from aura.core import security as sec  # noqa: E402
from tests.backend.features.orgs.test_orgs import OrgBase, ORG1, ORG2, UA, UB, UC, UD, UE  # noqa: E402


class Base(OrgBase):
    def add_meeting(self, owner=UA, org=ORG1):
        row = {"id": str(uuid.uuid4()), "org_id": org, "owner_id": owner, "meeting_title": "Reunião"}
        self.fake.tables["meetings"].append(row)
        return row["id"]

    def create(self, tok="tok-a", **body):
        return self.client.post("/api/conversations", headers=self.h(tok), json=body)

    def new(self, tok="tok-a", **body):
        r = self.create(tok, **body)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()["conversation"]["id"]

    def say(self, cid, text="Qual o risco do Atlas?", tok="tok-a"):
        return self.client.post(f"/api/conversations/{cid}/messages", headers=self.h(tok), json={"content": text})

    def rows(self, table):
        return self.fake.tables[table]


class Acesso(Base):
    def test_tudo_exige_login(self):
        cid = str(uuid.uuid4())
        c = self.client
        rotas = [c.get("/api/conversations"), c.post("/api/conversations", json={}), c.get(f"/api/conversations/{cid}"),
                 c.patch(f"/api/conversations/{cid}", json={"title": "x"}), c.delete(f"/api/conversations/{cid}"),
                 c.post(f"/api/conversations/{cid}/messages", json={"content": "x"})]
        self.assertEqual([r.status_code for r in rotas], [401] * len(rotas))

    def test_identificadores_invalidos(self):
        h = self.h()
        self.assertEqual(self.client.get("/api/conversations/xx", headers=h).status_code, 400)
        self.assertEqual(self.client.get("/api/conversations?org_id=xx", headers=h).status_code, 400)
        self.assertEqual(self.client.post("/api/conversations/xx/messages", headers=h, json={"content": "x"}).status_code, 400)

    def test_privacidade_nem_o_administrador_le(self):
        cid = self.new("tok-c", org_id=ORG1)  # colaborador
        for tok in ("tok-a", "tok-b", "tok-d", "tok-e"):  # administrador, gestor, outra org, sem org
            self.assertEqual(self.client.get(f"/api/conversations/{cid}", headers=self.h(tok)).status_code, 404, tok)
            self.assertEqual(self.client.patch(f"/api/conversations/{cid}", headers=self.h(tok), json={"title": "x"}).status_code, 404, tok)
            self.assertEqual(self.client.delete(f"/api/conversations/{cid}", headers=self.h(tok)).status_code, 404, tok)
            self.assertEqual(self.say(cid, tok=tok).status_code, 404, tok)
        self.assertEqual(self.client.get(f"/api/conversations?org_id={ORG1}", headers=self.h("tok-a")).json()["conversations"], [])
        self.assertEqual(len(self.rows("conversations")), 1)
        self.assertEqual(self.rows("messages"), [])

    def test_so_a_pessoa_grava_pergunta_na_propria_conversa(self):
        cid = self.new("tok-c", org_id=ORG1)
        self.assertEqual(self.say(cid, tok="tok-c").status_code, 200)

    def test_organizacao_exige_ser_membro_com_permissao(self):
        self.assertEqual(self.create("tok-d", org_id=ORG1).status_code, 403)  # admin de OUTRA organização
        self.assertEqual(self.create("tok-e", org_id=ORG1).status_code, 403)  # sem organização
        self.assertEqual(self.client.get(f"/api/conversations?org_id={ORG1}", headers=self.h("tok-e")).status_code, 403)
        self.fake.tables["membership_permissions"].append({"org_id": ORG1, "user_id": UC, "permission": "chat.use", "effect": "deny"})
        self.assertEqual(self.create("tok-c", org_id=ORG1).status_code, 403)  # 'chat.use' negado
        self.assertEqual(self.create("tok-c").status_code, 200)  # o espaço pessoal continua
        self.assertEqual(self.rows("conversations")[0]["org_id"], None)

    def test_permissao_retirada_depois_impede_novas_perguntas(self):
        cid = self.new("tok-c", org_id=ORG1)
        self.fake.tables["membership_permissions"].append({"org_id": ORG1, "user_id": UC, "permission": "chat.use", "effect": "deny"})
        self.assertEqual(self.say(cid, tok="tok-c").status_code, 403)
        self.assertEqual(self.rows("messages"), [])


class Criacao(Base):
    def test_cria_pessoal_e_em_organizacao(self):
        a = self.create(title="  Riscos   do trimestre ")
        self.assertEqual(a.status_code, 200)
        self.assertEqual(a.json()["conversation"]["title"], "Riscos do trimestre")
        self.assertIsNone(a.json()["conversation"]["org_id"])
        b = self.create(org_id=ORG1)
        self.assertEqual((b.json()["conversation"]["org_id"], b.json()["conversation"]["title"]), (ORG1, conv.DEFAULT_TITLE))
        self.assertEqual({c["owner_id"] for c in self.rows("conversations")}, {UA})
        self.assertEqual([r["action"] for r in self.fake.tables["audit_log"]].count("conversation.create"), 2)

    def test_dono_vem_do_token_nunca_do_corpo(self):
        r = self.client.post("/api/conversations", headers=self.h("tok-c"), json={"title": "x", "owner_id": UA})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.rows("conversations")[0]["owner_id"], UC)

    def test_titulo_longo_e_cortado(self):
        self.create(title="x" * 500)
        self.assertEqual(len(self.rows("conversations")[0]["title"]), 200)

    def test_lista_so_o_espaco_pedido_e_so_as_proprias(self):
        self.new(title="pessoal")
        self.new(org_id=ORG1, title="org")
        self.new("tok-c", org_id=ORG1, title="do colaborador")
        names = lambda qs, tok="tok-a": [c["title"] for c in self.client.get("/api/conversations" + qs, headers=self.h(tok)).json()["conversations"]]
        self.assertEqual(names("?org_id=personal"), ["pessoal"])
        self.assertEqual(names(f"?org_id={ORG1}"), ["org"])
        self.assertEqual(names(f"?org_id={ORG1}", "tok-c"), ["do colaborador"])

    def test_limite_de_conversas_vira_409(self):
        for _ in range(500):
            self.rows("conversations").append({"id": str(uuid.uuid4()), "owner_id": UA, "org_id": None, "title": "x", "scope": {}, "created_at": "", "last_message_at": ""})
        self.assertEqual(self.create().status_code, 409)


class Escopo(Base):
    def test_escopo_de_reuniao_do_mesmo_espaco(self):
        mid = self.add_meeting()
        cid = self.new(org_id=ORG1, scope={"meeting_id": mid})
        self.assertEqual(self.rows("conversations")[0]["scope"], {"meeting_id": mid})
        self.assertEqual(self.client.get(f"/api/conversations/{cid}", headers=self.h()).json()["conversation"]["scope"], {"meeting_id": mid})

    def test_escopo_de_item_inexistente_ou_invisivel(self):
        other = self.add_meeting(owner=UD, org=ORG2)  # reunião de outra organização
        self.assertEqual(self.create(org_id=ORG1, scope={"meeting_id": other}).status_code, 404)
        self.assertEqual(self.create(org_id=ORG1, scope={"meeting_id": str(uuid.uuid4())}).status_code, 404)
        self.assertEqual(self.rows("conversations"), [])

    def test_escopo_de_outro_espaco_e_recusado(self):
        pessoal = self.add_meeting(org=None)
        self.assertEqual(self.create(org_id=ORG1, scope={"meeting_id": pessoal}).status_code, 409)  # reunião pessoal em conversa da org
        org_meeting = self.add_meeting()
        self.assertEqual(self.create(scope={"meeting_id": org_meeting}).status_code, 409)  # reunião da org em conversa pessoal

    def test_escopo_so_aceita_chaves_conhecidas_e_ids_validos(self):
        for scope in ({"qualquer": "x"}, {"qualquer": str(uuid.uuid4())}, {"meeting_id": "nao-e-uuid"}, ["a"], {"meeting_id": 5}):
            self.assertIn(self.create(scope=scope).status_code, (400, 422), scope)
        self.assertEqual(self.rows("conversations"), [])

    def test_escopo_nao_muda_depois(self):
        cid = self.new()
        r = self.client.patch(f"/api/conversations/{cid}", headers=self.h(), json={"title": "ok", "scope": {"meeting_id": str(uuid.uuid4())}})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.rows("conversations")[0]["scope"], {})


class Mensagens(Base):
    def test_grava_pergunta_e_nomeia_a_conversa(self):
        cid = self.new()
        r = self.say(cid, "  Qual   o risco\ndo cliente Atlas neste trimestre?  ")
        self.assertEqual(r.status_code, 200, r.text)
        msg = self.rows("messages")[0]
        self.assertEqual((msg["role"], msg["owner_id"], msg["sources"]), ("user", UA, []))
        self.assertTrue(msg["content"].startswith("Qual   o risco\ndo cliente"))  # a pergunta é guardada como escrita
        self.assertEqual(self.rows("conversations")[0]["title"], "Qual o risco do cliente Atlas neste trimestre?")
        self.say(cid, "Segunda pergunta")
        self.assertEqual(self.rows("conversations")[0]["title"], "Qual o risco do cliente Atlas neste trimestre?")  # só a primeira nomeia

    def test_titulo_dado_pela_pessoa_nao_e_sobrescrito(self):
        cid = self.new(title="Minha conversa")
        self.say(cid)
        self.assertEqual(self.rows("conversations")[0]["title"], "Minha conversa")

    def test_mensagem_vazia_ou_longa_demais(self):
        cid = self.new()
        for text in ("", "   \n ", "x" * 4001):
            self.assertEqual(self.say(cid, text).status_code, 400, len(text))
        self.assertEqual(self.rows("messages"), [])
        self.assertFalse([c for c in self.fake.calls if c[0] == "POST" and c[1].endswith("/messages")])  # nada chegou ao banco

    def test_o_corpo_nao_escolhe_papel_nem_fontes(self):
        cid = self.new()
        r = self.client.post(f"/api/conversations/{cid}/messages", headers=self.h(),
                             json={"content": "oi", "role": "assistant", "sources": [{"type": "meeting"}], "evidence_level": "forte"})
        self.assertEqual(r.status_code, 200)
        msg = self.rows("messages")[0]
        self.assertEqual((msg["role"], msg["sources"], msg["evidence_level"]), ("user", [], None))

    def test_conversa_cheia_vira_409(self):
        cid = self.new()
        for _ in range(400):
            self.rows("messages").append({"id": str(uuid.uuid4()), "conversation_id": cid, "owner_id": UA, "role": "user", "content": "m", "sources": [], "evidence_level": None, "created_at": ""})
        self.assertEqual(self.say(cid).status_code, 409)

    def test_historico_na_ordem(self):
        cid = self.new()
        self.say(cid, "primeira")
        conv.append_assistant(sec.AuthUser(id=UA, email="a@x.com", token="tok-a", email_confirmed=True), cid, "resposta", [], "insuficiente")
        self.say(cid, "segunda")
        data = self.client.get(f"/api/conversations/{cid}", headers=self.h()).json()
        self.assertEqual([m["role"] for m in data["messages"]], ["user", "assistant", "user"])
        self.assertEqual(data["conversation"]["id"], cid)


class RespostaDoAura(Base):
    def user(self, tok="tok-a", uid=UA):
        return sec.AuthUser(id=uid, email="x@x.com", token=tok, email_confirmed=True)

    def test_so_o_backend_grava_a_resposta_com_fontes(self):
        cid = self.new()
        src = [{"type": "meeting", "id": "m1", "quote": "prazo apertado"}]
        row = conv.append_assistant(self.user(), cid, "O risco é médio.", src, "forte")
        self.assertEqual((row["role"], row["owner_id"], row["sources"], row["evidence_level"]), ("assistant", UA, src, "forte"))
        service_calls = [c for c in self.fake.calls if c[0] == "POST" and c[1].endswith("/rest/v1/messages")]
        self.assertTrue(service_calls)

    def test_nao_grava_resposta_em_conversa_de_outra_pessoa(self):
        cid = self.new("tok-c", org_id=ORG1)
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as ctx:
            conv.append_assistant(self.user(), cid, "x", [], None)  # administrador tentando
        self.assertEqual(ctx.exception.status_code, 404)
        self.assertEqual(self.rows("messages"), [])

    def test_nivel_de_evidencia_invalido(self):
        cid = self.new()
        with self.assertRaises(ValueError):
            conv.append_assistant(self.user(), cid, "x", [], "otimo")


class Edicao(Base):
    def test_renomeia_e_apaga(self):
        cid = self.new()
        self.say(cid)
        self.assertEqual(self.client.patch(f"/api/conversations/{cid}", headers=self.h(), json={"title": "  Novo   nome "}).json()["conversation"]["title"], "Novo nome")
        self.assertEqual(self.client.patch(f"/api/conversations/{cid}", headers=self.h(), json={"title": "  "}).status_code, 400)
        self.assertEqual(self.client.patch(f"/api/conversations/{cid}", headers=self.h(), json={"title": "x" * 201}).status_code, 400)
        self.assertEqual(self.client.delete(f"/api/conversations/{cid}", headers=self.h()).status_code, 200)
        self.assertEqual((self.rows("conversations"), self.rows("messages")), ([], []))
        self.assertEqual(self.client.get(f"/api/conversations/{cid}", headers=self.h()).status_code, 404)

    def test_auditoria_sem_conteudo(self):
        cid = self.new()
        self.say(cid, "Conteúdo confidencial da pergunta")
        self.client.patch(f"/api/conversations/{cid}", headers=self.h(), json={"title": "Título confidencial"})
        self.client.delete(f"/api/conversations/{cid}", headers=self.h())
        text = str(self.fake.tables["audit_log"])
        self.assertNotIn("confidencial", text)
        self.assertEqual([r["action"] for r in self.fake.tables["audit_log"]], ["conversation.create", "conversation.rename", "conversation.delete"])

    def test_falha_do_banco_vira_502_sem_detalhes(self):
        self.fake.fail.add(("POST", "conversations"))
        r = self.create()
        self.assertEqual(r.status_code, 502)
        self.assertNotIn("boom", r.text)


if __name__ == "__main__":
    unittest.main()
