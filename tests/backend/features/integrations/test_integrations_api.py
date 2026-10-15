"""Testes da arquitetura de integrações: cifra de segredos, permissões, registro de eventos, entrega idempotente com tentativas,
desligamento por falhas e isolamento (sem rede: provedor falso). RLS e gatilhos de verdade: tests/db/integrations.test.mjs."""
import base64
import os
import sys
import unittest
import uuid
from pathlib import Path
from unittest import mock

from aura.features.integrations import crypto as ic  # noqa: E402
from aura.features.integrations import providers
from aura.features.integrations import service as integ  # noqa: E402
from tests.backend.features.orgs.test_orgs import OrgBase, ORG1, ORG2, UA, UB, UC, UD  # noqa: E402

KEY = base64.urlsafe_b64encode(bytes(range(32))).decode()
KEY2 = base64.urlsafe_b64encode(bytes(range(32, 64))).decode()


class FakeProvider:
    """Provedor falso: guarda o que recebeu e devolve o que o teste mandar."""
    name = "webhook"

    def __init__(self):
        self.calls = []
        self.result = providers.DeliveryResult(True, 200)
        self.raises = None

    def validate_config(self, config):
        url = str(config.get("url") or "")
        if not url.startswith("https://"):
            raise ValueError("Informe uma URL https válida.")
        return {"url": url}

    def deliver(self, config, secret, event):
        self.calls.append({"config": config, "secret": secret, "event": event})
        if self.raises:
            raise self.raises
        return self.result


class Base(OrgBase):
    def setUp(self):
        super().setUp()
        self.env = mock.patch.dict(os.environ, {"AURA_INTEGRATIONS_KEY": KEY, "AURA_INTEGRATIONS_KEY_VERSION": "1"})
        self.env.start()
        self.provider = FakeProvider()
        providers.register_provider(self.provider)
        self.addCleanup(providers.unregister_provider, "webhook")
        self.addCleanup(self.env.stop)

    def create(self, tok="tok-a", org=ORG1, **over):
        body = {"org_id": org, "provider": "webhook", "name": "CRM", "config": {"url": "https://example.com/hook"}, "events": ["meeting.analyzed"]}
        body.update(over)
        return self.client.post("/api/integrations", headers=self.h(tok), json=body)

    def new(self, tok="tok-a", org=ORG1, **over):
        r = self.create(tok, org, **over)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def rows(self, table, **where):
        return self.fake.rows(table, **where)

    def emit(self, org=ORG1, owner=UA, type_="meeting.analyzed", key=None, **kw):
        return integ.emit_event(org, owner, type_, "meeting", str(uuid.uuid4()), {"title": "Reunião"}, key)

    def due_now(self):
        for d in self.rows("integration_deliveries"):
            d["next_attempt_at"] = "2000-01-01T00:00:00Z"


class Cifra(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, {"AURA_INTEGRATIONS_KEY": KEY, "AURA_INTEGRATIONS_KEY_VERSION": "1"}, clear=False)
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_ida_e_volta_e_o_texto_cifrado_nao_revela_nada(self):
        ct, v = ic.encrypt("whsec_segredo", "id-1")
        self.assertEqual(v, 1)
        self.assertNotIn("segredo", ct)
        self.assertEqual(ic.decrypt(ct, "id-1", 1), "whsec_segredo")

    def test_cada_cifra_usa_um_nonce_novo(self):
        self.assertNotEqual(ic.encrypt("x", "id")[0], ic.encrypt("x", "id")[0])

    def test_nao_serve_para_outra_integracao(self):
        ct, v = ic.encrypt("s", "id-1")
        with self.assertRaises(ic.CryptoError):
            ic.decrypt(ct, "id-2", v)

    def test_adulterado_falha(self):
        ct, v = ic.encrypt("s", "id-1")
        raw = bytearray(base64.urlsafe_b64decode(ct))
        raw[-1] ^= 1
        with self.assertRaises(ic.CryptoError):
            ic.decrypt(base64.urlsafe_b64encode(bytes(raw)).decode(), "id-1", v)
        with self.assertRaises(ic.CryptoError):
            ic.decrypt("lixo", "id-1", v)

    def test_sem_chave_ou_chave_curta_nao_ha_plano_b(self):
        for value in (None, "", "curta", base64.urlsafe_b64encode(b"x" * 16).decode()):
            env = {"AURA_INTEGRATIONS_KEY": value} if value is not None else {}
            with mock.patch.dict(os.environ, env, clear=False):
                if value is None:
                    os.environ.pop("AURA_INTEGRATIONS_KEY", None)
                self.assertFalse(ic.configured())
                with self.assertRaises(ic.CryptoUnavailable):
                    ic.encrypt("s", "id")

    def test_troca_de_chave_le_o_segredo_antigo(self):
        ct, v = ic.encrypt("s", "id")
        with mock.patch.dict(os.environ, {"AURA_INTEGRATIONS_KEY": KEY2, "AURA_INTEGRATIONS_KEY_VERSION": "2", "AURA_INTEGRATIONS_KEY_PREV": KEY}):
            self.assertEqual(ic.decrypt(ct, "id", v), "s")
            self.assertEqual(ic.encrypt("novo", "id")[1], 2)
        with mock.patch.dict(os.environ, {"AURA_INTEGRATIONS_KEY": KEY2, "AURA_INTEGRATIONS_KEY_VERSION": "2"}):
            os.environ.pop("AURA_INTEGRATIONS_KEY_PREV", None)
            with self.assertRaises(ic.CryptoUnavailable):
                ic.decrypt(ct, "id", v)


class Acesso(Base):
    def test_tudo_exige_login(self):
        iid = str(uuid.uuid4())
        c = self.client
        rotas = [c.get("/api/integrations"), c.post("/api/integrations", json={}), c.patch(f"/api/integrations/{iid}", json={"name": "x"}),
                 c.delete(f"/api/integrations/{iid}"), c.post(f"/api/integrations/{iid}/rotate-secret"), c.post(f"/api/integrations/{iid}/test"),
                 c.get(f"/api/integrations/{iid}/deliveries")]
        self.assertEqual([r.status_code for r in rotas], [401] * len(rotas))

    def test_so_administrador_gerencia_na_organizacao(self):
        self.assertEqual(self.create("tok-a").status_code, 200)
        for tok in ("tok-b", "tok-c"):  # gestor e colaborador
            self.assertEqual(self.create(tok).status_code, 403, tok)
            self.assertEqual(self.client.get(f"/api/integrations?org_id={ORG1}", headers=self.h(tok)).status_code, 403, tok)
        self.assertEqual(self.client.get(f"/api/integrations?org_id={ORG1}", headers=self.h("tok-d")).status_code, 403)  # admin de outra org

    def test_conta_pessoal_e_do_dono(self):
        r = self.create("tok-c", org=None)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(len(self.client.get("/api/integrations", headers=self.h("tok-c")).json()["integrations"]), 1)
        self.assertEqual(self.client.get("/api/integrations", headers=self.h("tok-e")).json()["integrations"], [])

    def test_item_de_outro_espaco_vira_404(self):
        iid = self.new()["integration"]["id"]
        for call in (lambda t: self.client.patch(f"/api/integrations/{iid}", headers=self.h(t), json={"name": "x"}),
                     lambda t: self.client.delete(f"/api/integrations/{iid}", headers=self.h(t)),
                     lambda t: self.client.post(f"/api/integrations/{iid}/test", headers=self.h(t)),
                     lambda t: self.client.post(f"/api/integrations/{iid}/rotate-secret", headers=self.h(t)),
                     lambda t: self.client.get(f"/api/integrations/{iid}/deliveries", headers=self.h(t))):
            self.assertEqual(call("tok-d").status_code, 404)
            self.assertEqual(call("tok-c").status_code, 404)
        self.assertEqual(len(self.rows("integrations")), 1)

    def test_identificadores_invalidos(self):
        h = self.h()
        self.assertEqual(self.client.delete("/api/integrations/xx", headers=h).status_code, 400)
        self.assertEqual(self.client.get("/api/integrations?org_id=xx", headers=h).status_code, 400)


class Cadastro(Base):
    def test_cria_cifrado_e_mostra_o_segredo_uma_vez(self):
        out = self.new()
        secret, row = out["secret"], self.rows("integrations")[0]
        self.assertTrue(secret.startswith("whsec_"))
        self.assertNotIn(secret, str(row))  # nada em texto aberto no banco
        self.assertEqual(ic.decrypt(row["secret_ct"], row["id"], row["key_version"]), secret)
        self.assertEqual(row["secret_hint"], secret[-4:])
        self.assertNotIn("secret_ct", out["integration"])
        listing = self.client.get(f"/api/integrations?org_id={ORG1}", headers=self.h()).json()
        self.assertNotIn(secret, str(listing))
        self.assertNotIn("secret_ct", str(listing))
        self.assertEqual(listing["integrations"][0]["secret_hint"], secret[-4:])

    def test_sem_chave_do_servidor_nao_cria(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("AURA_INTEGRATIONS_KEY", None)
            r = self.create()
        self.assertEqual(r.status_code, 503)
        self.assertEqual(self.rows("integrations"), [])

    def test_provedor_indisponivel(self):
        providers.unregister_provider("webhook")
        self.assertEqual(self.create().status_code, 501)

    def test_validacoes(self):
        self.assertEqual(self.create(name="   ").status_code, 400)
        self.assertEqual(self.create(name="x" * 101).status_code, 400)
        self.assertEqual(self.create(events=["meeting.deleted"]).status_code, 400)
        self.assertEqual(self.create(events=["integration.test"]).status_code, 400)
        self.assertEqual(self.create(config={"url": "http://x.com"}).status_code, 400)
        self.assertEqual(self.create(provider="slack").status_code, 501)
        self.assertEqual(self.rows("integrations"), [])

    def test_limite_por_espaco(self):
        for _ in range(20):
            self.new()
        r = self.create()
        self.assertEqual(r.status_code, 409)
        self.assertEqual(len(self.rows("integrations")), 20)

    def test_pausar_e_reativar_zera_falhas(self):
        iid = self.new()["integration"]["id"]
        self.rows("integrations")[0].update(status="disabled", consecutive_failures=10, disabled_reason="x")
        self.assertEqual(self.client.patch(f"/api/integrations/{iid}", headers=self.h(), json={"status": "disabled"}).status_code, 400)
        r = self.client.patch(f"/api/integrations/{iid}", headers=self.h(), json={"status": "active"})
        self.assertEqual(r.status_code, 200, r.text)
        row = self.rows("integrations")[0]
        self.assertEqual((row["status"], row["consecutive_failures"], row["disabled_reason"]), ("active", 0, None))
        self.assertEqual(self.client.patch(f"/api/integrations/{iid}", headers=self.h(), json={}).status_code, 400)

    def test_editar_nome_eventos_e_destino(self):
        iid = self.new()["integration"]["id"]
        r = self.client.patch(f"/api/integrations/{iid}", headers=self.h(),
                              json={"name": "Novo", "events": ["action.completed"], "config": {"url": "https://other.example/x"}})
        self.assertEqual(r.status_code, 200, r.text)
        row = self.rows("integrations")[0]
        self.assertEqual((row["name"], row["events"], row["config"]["url"]), ("Novo", ["action.completed"], "https://other.example/x"))
        bad = self.client.patch(f"/api/integrations/{iid}", headers=self.h(), json={"config": {"url": "ftp://x"}})
        self.assertEqual(bad.status_code, 400)

    def test_girar_segredo_troca_o_cifrado_e_mostra_o_novo_uma_vez(self):
        out = self.new()
        iid, before = out["integration"]["id"], self.rows("integrations")[0]["secret_ct"]
        r = self.client.post(f"/api/integrations/{iid}/rotate-secret", headers=self.h())
        self.assertEqual(r.status_code, 200, r.text)
        row = self.rows("integrations")[0]
        self.assertNotEqual(row["secret_ct"], before)
        self.assertNotEqual(r.json()["secret"], out["secret"])
        self.assertEqual(ic.decrypt(row["secret_ct"], iid, row["key_version"]), r.json()["secret"])

    def test_apagar_leva_as_entregas(self):
        iid = self.new()["integration"]["id"]
        self.emit()
        self.assertEqual(len(self.rows("integration_deliveries")), 1)
        self.assertEqual(self.client.delete(f"/api/integrations/{iid}", headers=self.h()).status_code, 200)
        self.assertEqual((self.rows("integrations"), self.rows("integration_deliveries")), ([], []))

    def test_auditoria_nao_guarda_segredo_nem_url(self):
        out = self.new()
        self.client.post(f"/api/integrations/{out['integration']['id']}/rotate-secret", headers=self.h())
        text = str(self.rows("audit_log"))
        self.assertIn("integration.create", text)
        self.assertNotIn(out["secret"], text)
        self.assertNotIn("example.com", text)
        self.assertNotIn("whsec_", text)

    def test_erro_do_banco_vira_502_generico(self):
        self.fake.fail.add(("GET", "integrations"))
        r = self.client.get(f"/api/integrations?org_id={ORG1}", headers=self.h())
        self.assertEqual(r.status_code, 502)
        self.assertNotIn("integrations", r.text.replace("integra", ""))  # sem nome de tabela na mensagem


class Eventos(Base):
    def test_gera_uma_entrega_por_integracao_ativa_que_assina(self):
        a = self.new(name="A")["integration"]["id"]
        self.new(name="B", events=["action.completed"])  # não assina este tipo
        c = self.new(name="C")["integration"]["id"]
        self.client.patch(f"/api/integrations/{c}", headers=self.h(), json={"status": "paused"})
        self.new(tok="tok-d", org=ORG2, name="Outra org")
        self.emit()
        self.assertEqual([d["integration_id"] for d in self.rows("integration_deliveries")], [a])

    def test_conta_pessoal_nao_vaza_para_organizacao_nem_para_outra_pessoa(self):
        mine = self.new(tok="tok-c", org=None)["integration"]["id"]
        self.new(tok="tok-e", org=None, name="De outra pessoa")
        integ.emit_event(None, UC, "meeting.analyzed", "meeting", str(uuid.uuid4()), {}, None)
        self.assertEqual([d["integration_id"] for d in self.rows("integration_deliveries")], [mine])

    def test_mesmo_evento_de_origem_nao_duplica(self):
        self.new()
        first = self.emit(key="meeting.analyzed:m1")
        again = self.emit(key="meeting.analyzed:m1")
        self.assertTrue(first)
        self.assertIsNone(again)
        self.assertEqual((len(self.rows("integration_events")), len(self.rows("integration_deliveries"))), (1, 1))
        self.assertTrue(self.emit(key="meeting.analyzed:m2"))

    def test_tipo_invalido_nao_registra(self):
        with self.assertRaises(ValueError):
            integ.emit_event(ORG1, UA, "meeting.deleted")
        with self.assertRaises(ValueError):
            integ.emit_event(ORG1, UA, "integration.test")  # o teste só nasce pelo botão
        self.assertEqual(self.rows("integration_events"), [])

    def test_emit_safe_nunca_levanta(self):
        self.fake.fail.add(("POST", "integration_events"))
        self.assertIsNone(integ.emit_safe(ORG1, UA, "meeting.analyzed", "meeting", str(uuid.uuid4()), {}, None))
        self.assertIsNone(integ.emit_safe(ORG1, UA, "tipo.invalido"))


class Entrega(Base):
    def setUp(self):
        super().setUp()
        out = self.new()
        self.iid, self.secret = out["integration"]["id"], out["secret"]
        self.emit()

    def dispatch(self):
        return integ.dispatch_due()

    def delivery(self):
        return self.rows("integration_deliveries")[0]

    def test_entrega_uma_vez_com_o_segredo_decifrado_e_sem_vazar(self):
        s = self.dispatch()
        self.assertEqual((s["found"], s["succeeded"]), (1, 1))
        call = self.provider.calls[0]
        self.assertEqual(call["secret"], self.secret)
        self.assertEqual(call["config"]["url"], "https://example.com/hook")
        self.assertEqual(call["event"]["type"], "meeting.analyzed")
        self.assertNotIn("secret_ct", str(call["event"]))
        d = self.delivery()
        self.assertEqual((d["status"], d["attempts"], d["last_status"]), ("succeeded", 1, 200))
        self.assertTrue(d["delivered_at"])
        self.assertEqual(self.dispatch()["found"], 0)  # nada a repetir
        self.assertEqual(len(self.provider.calls), 1)

    def test_sucesso_zera_falhas_seguidas(self):
        self.rows("integrations")[0]["consecutive_failures"] = 4
        self.dispatch()
        row = self.rows("integrations")[0]
        self.assertEqual(row["consecutive_failures"], 0)
        self.assertTrue(row["last_success_at"])

    def test_falha_agenda_nova_tentativa_e_nao_repete_antes_da_hora(self):
        self.provider.result = providers.DeliveryResult(False, 500, "HTTP 500")
        self.dispatch()
        d = self.delivery()
        self.assertEqual((d["status"], d["attempts"], d["last_status"], d["last_error"]), ("failed", 1, 500, "HTTP 500"))
        self.assertGreater(d["next_attempt_at"], integ._iso(integ._now()))  # só daqui a pouco
        self.assertEqual(self.dispatch()["found"], 0)
        self.assertEqual(len(self.provider.calls), 1)
        self.due_now()
        self.provider.result = providers.DeliveryResult(True, 200)
        self.assertEqual(self.dispatch()["succeeded"], 1)
        self.assertEqual((self.delivery()["status"], self.delivery()["attempts"]), ("succeeded", 2))

    def test_espera_cresce_a_cada_falha(self):
        self.provider.result = providers.DeliveryResult(False, 503)
        waits = []
        from datetime import datetime, timezone
        for _ in range(3):
            self.due_now()
            self.dispatch()
            when = datetime.strptime(self.delivery()["next_attempt_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            waits.append(round((when - datetime.now(timezone.utc)).total_seconds() / 60))
        self.assertEqual(waits, [1, 5, 30])

    def test_depois_das_tentativas_vira_morta(self):
        self.provider.result = providers.DeliveryResult(False, 500)
        for _ in range(integ.MAX_ATTEMPTS):
            self.due_now()
            self.dispatch()
        d = self.delivery()
        self.assertEqual((d["status"], d["attempts"]), ("dead", integ.MAX_ATTEMPTS))
        self.due_now()
        self.assertEqual(self.dispatch()["found"], 0)
        self.assertEqual(len(self.provider.calls), integ.MAX_ATTEMPTS)

    def test_erro_sem_nova_tentativa_encerra_na_hora(self):
        self.provider.result = providers.DeliveryResult(False, 410, "Destino removido", retryable=False)
        self.dispatch()
        self.assertEqual(self.delivery()["status"], "dead")

    def test_excecao_do_provedor_nao_derruba_e_nao_vaza_a_mensagem(self):
        self.provider.raises = RuntimeError("senha=hunter2 em http://interno")
        s = self.dispatch()
        self.assertEqual(s["failed"], 1)
        d = self.delivery()
        self.assertEqual(d["status"], "failed")
        self.assertNotIn("hunter2", d["last_error"])
        self.assertNotIn("interno", d["last_error"])

    def test_falhas_seguidas_desligam_a_integracao(self):
        self.provider.result = providers.DeliveryResult(False, 500)
        self.rows("integrations")[0]["consecutive_failures"] = integ.DISABLE_AFTER - 1
        self.dispatch()
        row = self.rows("integrations")[0]
        self.assertEqual(row["status"], "disabled")
        self.assertTrue(row["disabled_reason"])
        self.emit()  # desligada: não nasce entrega nova
        self.assertEqual(len(self.rows("integration_deliveries")), 1)

    def test_outra_execucao_ja_reservou_a_entrega(self):
        d = dict(self.delivery())
        self.delivery()["attempts"] = 1  # outra execução reservou entre a leitura e a reserva
        self.assertIsNone(integ.deliver_one(d))
        self.assertEqual(self.provider.calls, [])

    def test_duas_execucoes_seguidas_entregam_uma_vez(self):
        d = dict(self.delivery())
        self.assertEqual(integ.deliver_one(dict(d)), "succeeded")
        self.assertIsNone(integ.deliver_one(dict(d)))
        self.assertEqual(len(self.provider.calls), 1)

    def test_pausada_nao_entrega_nem_gasta_tentativa(self):
        self.client.patch(f"/api/integrations/{self.iid}", headers=self.h(), json={"status": "paused"})
        self.assertEqual(self.dispatch()["skipped"], 1)
        self.assertEqual(self.provider.calls, [])
        self.assertEqual((self.delivery()["status"], self.delivery()["attempts"]), ("pending", 0))
        self.client.patch(f"/api/integrations/{self.iid}", headers=self.h(), json={"status": "active"})
        self.due_now()
        self.assertEqual(self.dispatch()["succeeded"], 1)

    def test_desligada_encerra_a_entrega(self):
        self.rows("integrations")[0]["status"] = "disabled"
        self.dispatch()
        self.assertEqual(self.delivery()["status"], "dead")
        self.assertEqual(self.provider.calls, [])

    def test_segredo_ilegivel_nao_tenta_de_novo(self):
        self.rows("integrations")[0]["secret_ct"] = "lixo"
        self.dispatch()
        self.assertEqual(self.delivery()["status"], "dead")
        self.assertEqual(self.provider.calls, [])

    def test_provedor_removido_tenta_depois(self):
        providers.unregister_provider("webhook")
        self.dispatch()
        self.assertEqual(self.delivery()["status"], "failed")

    def test_segredo_continua_lendo_depois_da_troca_de_chave(self):
        with mock.patch.dict(os.environ, {"AURA_INTEGRATIONS_KEY": KEY2, "AURA_INTEGRATIONS_KEY_VERSION": "2", "AURA_INTEGRATIONS_KEY_PREV": KEY}):
            self.dispatch()
            self.assertEqual(self.provider.calls[0]["secret"], self.secret)


class LigadoAosFluxos(Base):
    def setUp(self):
        super().setUp()
        self.iid = self.new(events=["meeting.analyzed", "action.completed"])["integration"]["id"]

    def make_action(self):
        mid = str(uuid.uuid4())
        self.fake.tables["meetings"].append({"id": mid, "org_id": ORG1, "owner_id": UA, "meeting_title": "R", "client_name": "X", "client_id": None,
                                             "actions_detail": [], "pending_actions": [], "is_demo": False, "created_at": "2026-10-02T00:00:00+00:00"})
        r = self.client.post(f"/api/meetings/{mid}/actions", headers=self.h(), json={"text": "Ligar para o cliente"})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()["action"]["id"]

    def test_concluir_acao_emite_uma_vez(self):
        aid = self.make_action()
        self.assertEqual(self.rows("integration_events"), [])
        self.client.patch(f"/api/actions/{aid}", headers=self.h(), json={"status": "in_progress"})
        self.assertEqual(self.rows("integration_events"), [])
        self.client.patch(f"/api/actions/{aid}", headers=self.h(), json={"status": "done"})
        events = self.rows("integration_events")
        self.assertEqual([e["type"] for e in events], ["action.completed"])
        self.assertEqual(events[0]["org_id"], ORG1)
        self.assertEqual(events[0]["data"]["action_id"], aid)
        self.assertEqual(len(self.rows("integration_deliveries")), 1)
        self.client.patch(f"/api/actions/{aid}", headers=self.h(), json={"status": "done"})  # já estava concluída
        self.assertEqual(len(self.rows("integration_events")), 1)

    def test_falha_nas_integracoes_nao_afeta_a_acao(self):
        aid = self.make_action()
        self.fake.fail.add(("POST", "integration_events"))
        r = self.client.patch(f"/api/actions/{aid}", headers=self.h(), json={"status": "done"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["action"]["status"], "done")

    def test_reuniao_salva_emite_sem_transcricao(self):
        from aura import app as index
        from aura.features.meetings import repository as meetings_repo
        from aura.features.meetings import service as meetings_mod
        from aura.features.analysis import repository as analysis_repo
        from aura.features.analysis import service as analysis_mod
        user = integ.sec.AuthUser(id=UA, email="a@x.com", token="tok-a")
        saved = {"id": str(uuid.uuid4())}
        with mock.patch.object(meetings_repo, "request", return_value=[saved]):
            meetings_mod.save_meeting({"meeting_title": "Plano 2027", "transcript": "TEXTO SECRETO DA REUNIAO", "org_id": ORG1, "risk": "Alto"}, user=user)
        events = self.rows("integration_events")
        self.assertEqual([e["type"] for e in events], ["meeting.analyzed"])
        self.assertEqual(events[0]["data"]["title"], "Plano 2027")
        self.assertNotIn("SECRETO", str(events))
        with mock.patch.object(meetings_repo, "request", return_value=[saved]):  # salvar de novo a mesma reunião não duplica
            meetings_mod.save_meeting({"meeting_title": "Plano 2027", "org_id": ORG1}, user=user)
        self.assertEqual(len(self.rows("integration_events")), 1)

    def test_demonstracao_e_sem_login_nao_emitem(self):
        from aura import app as index
        from aura.features.meetings import repository as meetings_repo
        from aura.features.meetings import service as meetings_mod
        from aura.features.analysis import repository as analysis_repo
        from aura.features.analysis import service as analysis_mod
        user = integ.sec.AuthUser(id=UA, email="a@x.com", token="tok-a")
        with mock.patch.object(meetings_repo, "request", return_value=[{"id": str(uuid.uuid4())}]):
            meetings_mod.save_meeting({"meeting_title": "Demo", "is_demo": True, "org_id": ORG1}, user=user)
            meetings_mod.save_meeting({"meeting_title": "Anônima"}, user=None)
        self.assertEqual(self.rows("integration_events"), [])


class Teste(Base):
    def test_botao_de_teste_entrega_so_para_a_integracao(self):
        a = self.new(name="A")["integration"]["id"]
        self.new(name="B")
        r = self.client.post(f"/api/integrations/{a}/test", headers=self.h())
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["delivery"]["status"], "succeeded")
        self.assertEqual(len(self.provider.calls), 1)
        self.assertEqual(self.provider.calls[0]["event"]["type"], "integration.test")
        self.assertEqual([d["integration_id"] for d in self.rows("integration_deliveries")], [a])

    def test_resultado_de_falha_aparece_na_hora(self):
        a = self.new()["integration"]["id"]
        self.provider.result = providers.DeliveryResult(False, 502, "HTTP 502")
        out = self.client.post(f"/api/integrations/{a}/test", headers=self.h()).json()
        self.assertEqual((out["delivery"]["status"], out["delivery"]["last_status"]), ("failed", 502))

    def test_exige_integracao_ativa(self):
        a = self.new()["integration"]["id"]
        self.client.patch(f"/api/integrations/{a}", headers=self.h(), json={"status": "paused"})
        self.assertEqual(self.client.post(f"/api/integrations/{a}/test", headers=self.h()).status_code, 409)
        self.assertEqual(self.provider.calls, [])

    def test_lista_de_entregas(self):
        a = self.new()["integration"]["id"]
        self.client.post(f"/api/integrations/{a}/test", headers=self.h())
        rows = self.client.get(f"/api/integrations/{a}/deliveries", headers=self.h()).json()["deliveries"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "succeeded")


class Limites(Base):
    def test_botao_de_teste_tem_limite_por_hora(self):
        a = self.new()["integration"]["id"]
        for _ in range(integ.MAX_TESTS_PER_HOUR):
            self.assertEqual(self.client.post(f"/api/integrations/{a}/test", headers=self.h()).status_code, 200)
        for e in self.rows("integration_events"):  # o relógio do banco simulado é fixo: põe os eventos "agora"
            e["created_at"] = integ._iso(integ._now())
        r = self.client.post(f"/api/integrations/{a}/test", headers=self.h())
        self.assertEqual(r.status_code, 429)
        other = self.new(name="Outra")["integration"]["id"]  # o limite é por integração
        self.assertEqual(self.client.post(f"/api/integrations/{other}/test", headers=self.h()).status_code, 200)

    def test_rodada_de_entregas_respeita_o_tempo(self):
        self.new()
        for k in range(5):
            self.emit(key=f"k{k}")
        with mock.patch.object(integ, "BUDGET_SECONDS", 0):
            s = integ._run(self.rows("integration_deliveries"), budget=-1)
        self.assertEqual((s["deferred"], s["succeeded"]), (5, 0))
        self.assertEqual(len(self.provider.calls), 0)
        self.assertEqual(integ.dispatch_due()["succeeded"], 5)  # o que ficou para depois sai na rodada seguinte


class Agendador(Base):
    def test_sem_segredo_configurado(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("AURA_CRON_SECRET", None)
            self.assertEqual(self.client.post("/api/integrations/dispatch", headers={"X-Cron-Secret": "x"}).status_code, 503)

    def test_segredo_errado_ou_ausente(self):
        with mock.patch.dict(os.environ, {"AURA_CRON_SECRET": "abc123"}):
            self.assertEqual(self.client.post("/api/integrations/dispatch").status_code, 401)
            self.assertEqual(self.client.post("/api/integrations/dispatch", headers={"X-Cron-Secret": "errado"}).status_code, 401)
            self.assertEqual(self.client.post("/api/integrations/dispatch", headers=self.h()).status_code, 401)  # login comum não basta

    def test_segredo_certo_entrega(self):
        self.new()
        self.emit()
        with mock.patch.dict(os.environ, {"AURA_CRON_SECRET": "abc123"}):
            r = self.client.post("/api/integrations/dispatch", headers={"X-Cron-Secret": "abc123"})
        self.assertEqual((r.status_code, r.json()["succeeded"]), (200, 1))


if __name__ == "__main__":
    unittest.main()
