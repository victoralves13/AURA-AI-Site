"""Testes das reuniões ao vivo (fase 6.1): sessão, consentimento, pedaços, idempotência, interrupção, exclusão e privacidade
(sem rede e sem OpenAI; o bucket de áudio é simulado em memória). As regras de RLS e dos gatilhos são testadas de verdade
em tests/db/live.test.mjs."""
import sys
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from aura.features.live import router as live  # noqa: E402
from aura.core import storage as storage_io  # noqa: E402
from test_orgs import OrgBase, ORG1, ORG2, UA, UB, UC, UD, UE  # noqa: E402

CLOCK = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)


class Base(OrgBase):
    def setUp(self):
        super().setUp()
        self.now = CLOCK
        self.fake.clock = self.now.isoformat()
        self.bucket = {}   # caminho -> tamanho
        self.deleted = []
        self.storage_fail = False
        p = [mock.patch.object(live, "_now", lambda: self.now),
             mock.patch.object(storage_io, "signed_upload", lambda path: (f"https://storage.test/upload/{path}", "tok-" + path[-8:])),
             mock.patch.object(storage_io, "object_size", lambda path: self.bucket.get(path)),
             mock.patch.object(storage_io, "delete_objects", self._delete)]
        for x in p:
            x.start()
            self.addCleanup(x.stop)

    def _delete(self, paths):
        if self.storage_fail:
            raise RuntimeError("falha do bucket")
        self.deleted.extend(paths)
        for path in paths:
            self.bucket.pop(path, None)

    def advance(self, **kw):
        self.now = self.now + timedelta(**kw)
        self.fake.clock = self.now.isoformat()

    def start(self, tok="tok-a", **body):
        body.setdefault("consent", True)
        r = self.client.post("/api/live", headers=self.h(tok), json=body)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()["session"]["id"]

    def upload(self, sid, seq, tok="tok-a", size=120_000, put=True, ext=".webm"):
        r = self.client.post(f"/api/live/{sid}/chunks/upload-url", headers=self.h(tok), json={"seq": seq, "ext": ext})
        self.assertEqual(r.status_code, 200, r.text)
        if put:
            self.bucket[r.json()["path"]] = size
        return r.json()

    def register(self, sid, seq, tok="tok-a", dur=30_000, ext=".webm"):
        return self.client.post(f"/api/live/{sid}/chunks", headers=self.h(tok), json={"seq": seq, "duration_ms": dur, "ext": ext})

    def chunk(self, sid, seq, tok="tok-a"):
        self.upload(sid, seq, tok)
        r = self.register(sid, seq, tok)
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def get(self, sid, tok="tok-a"):
        return self.client.get(f"/api/live/{sid}", headers=self.h(tok))

    def rows(self, table):
        return self.fake.tables[table]


class Acesso(Base):
    def test_tudo_exige_login(self):
        sid = str(uuid.uuid4())
        c = self.client
        rotas = [c.get("/api/live"), c.post("/api/live", json={"consent": True}), c.get(f"/api/live/{sid}"), c.patch(f"/api/live/{sid}", json={}),
                 c.post(f"/api/live/{sid}/chunks/upload-url", json={"seq": 0}), c.post(f"/api/live/{sid}/chunks", json={"seq": 0, "duration_ms": 1}),
                 c.post(f"/api/live/{sid}/finish"), c.delete(f"/api/live/{sid}")]
        self.assertEqual([r.status_code for r in rotas], [401] * len(rotas))

    def test_identificadores_invalidos(self):
        h = self.h()
        self.assertEqual(self.client.get("/api/live/xx", headers=h).status_code, 400)
        self.assertEqual(self.client.get("/api/live?org_id=xx", headers=h).status_code, 400)
        self.assertEqual(self.client.get("/api/live?status=zzz", headers=h).status_code, 400)

    def test_privacidade_nem_o_administrador_ve_a_gravacao_de_outra_pessoa(self):
        sid = self.start("tok-c", org_id=ORG1)
        self.upload(sid, 0, "tok-c")
        for tok in ("tok-a", "tok-b", "tok-d", "tok-e"):
            self.assertEqual(self.get(sid, tok).status_code, 404, tok)
            self.assertEqual(self.client.patch(f"/api/live/{sid}", headers=self.h(tok), json={"title": "x"}).status_code, 404, tok)
            self.assertEqual(self.client.post(f"/api/live/{sid}/chunks/upload-url", headers=self.h(tok), json={"seq": 1}).status_code, 404, tok)
            self.assertEqual(self.register(sid, 0, tok).status_code, 404, tok)
            self.assertEqual(self.client.post(f"/api/live/{sid}/finish", headers=self.h(tok)).status_code, 404, tok)
            self.assertEqual(self.client.delete(f"/api/live/{sid}", headers=self.h(tok)).status_code, 404, tok)
        self.assertEqual(self.client.get(f"/api/live?org_id={ORG1}", headers=self.h("tok-a")).json()["sessions"], [])
        self.assertEqual(self.deleted, [])

    def test_organizacao_exige_ser_membro_com_permissao_de_gravar(self):
        self.assertEqual(self.client.post("/api/live", headers=self.h("tok-d"), json={"consent": True, "org_id": ORG1}).status_code, 403)
        self.assertEqual(self.client.post("/api/live", headers=self.h("tok-e"), json={"consent": True, "org_id": ORG1}).status_code, 403)
        self.fake.tables["membership_permissions"].append({"org_id": ORG1, "user_id": UC, "permission": "meetings.write", "effect": "deny"})
        self.assertEqual(self.client.post("/api/live", headers=self.h("tok-c"), json={"consent": True, "org_id": ORG1}).status_code, 403)
        self.assertEqual(self.client.post("/api/live", headers=self.h("tok-c"), json={"consent": True}).status_code, 200)  # pessoal continua
        self.assertEqual(self.rows("live_sessions")[0]["org_id"], None)

    def test_permissao_retirada_depois_impede_novos_pedacos(self):
        sid = self.start("tok-c", org_id=ORG1)
        self.fake.tables["membership_permissions"].append({"org_id": ORG1, "user_id": UC, "permission": "meetings.write", "effect": "deny"})
        self.assertEqual(self.client.post(f"/api/live/{sid}/chunks/upload-url", headers=self.h("tok-c"), json={"seq": 0}).status_code, 403)
        self.assertEqual(self.rows("live_chunks"), [])


class Criacao(Base):
    def test_consentimento_e_obrigatorio(self):
        for body in ({}, {"consent": False}):
            self.assertEqual(self.client.post("/api/live", headers=self.h(), json=body).status_code, 400, body)
        self.assertEqual(self.rows("live_sessions"), [])
        self.assertEqual(self.client.post("/api/live", headers=self.h(), json={"consent": "sim"}).status_code, 422)  # só o booleano verdadeiro vale

    def test_cria_com_consentimento_registrado_e_auditoria(self):
        sid = self.start(title="  Reunião   com o Atlas ", context="Comercial", client_name="Grupo Atlas", org_id=ORG1)
        s = self.rows("live_sessions")[0]
        self.assertEqual((s["id"], s["owner_id"], s["org_id"], s["status"], s["title"], s["context"], s["client_name"]),
                         (sid, UA, ORG1, "recording", "Reunião com o Atlas", "Comercial", "Grupo Atlas"))
        self.assertEqual(s["consent_at"], CLOCK.isoformat())
        self.assertEqual(s["alerts_enabled"], True)
        entry = [r for r in self.fake.tables["audit_log"] if r["action"] == "live.start"][0]
        self.assertEqual(entry["metadata"], {"alerts": True})
        self.assertNotIn("Atlas", str(entry))

    def test_dono_e_estado_vem_do_servidor_nunca_do_corpo(self):
        r = self.client.post("/api/live", headers=self.h("tok-c"), json={"consent": True, "owner_id": UA, "status": "ended", "meeting_id": UA, "duration_seconds": 99})
        self.assertEqual(r.status_code, 200)
        s = self.rows("live_sessions")[0]
        self.assertEqual((s["owner_id"], s["status"], s["meeting_id"], s["duration_seconds"]), (UC, "recording", None, 0))

    def test_alertas_podem_comecar_desligados(self):
        self.start(alerts_enabled=False)
        self.assertFalse(self.rows("live_sessions")[0]["alerts_enabled"])

    def test_limite_de_tres_gravacoes_ativas(self):
        for _ in range(3):
            self.start()
        r = self.client.post("/api/live", headers=self.h(), json={"consent": True})
        self.assertEqual(r.status_code, 409)
        self.assertIn("3 gravações ativas", r.json()["detail"])

    def test_lista_so_o_espaco_pedido_e_so_as_proprias(self):
        self.start(title="pessoal")
        self.start(title="org", org_id=ORG1)
        self.start("tok-c", title="do colaborador", org_id=ORG1)
        names = lambda qs, tok="tok-a": [s["title"] for s in self.client.get("/api/live" + qs, headers=self.h(tok)).json()["sessions"]]
        self.assertEqual(sorted(names("")), ["org", "pessoal"])
        self.assertEqual(names("?org_id=personal"), ["pessoal"])
        self.assertEqual(names(f"?org_id={ORG1}"), ["org"])
        self.assertEqual(names("", "tok-c"), ["do colaborador"])

    def test_a_resposta_nao_expoe_o_dono_nem_o_caminho(self):
        sid = self.start()
        self.chunk(sid, 0)
        data = self.get(sid).json()
        self.assertNotIn("owner_id", data["session"])
        self.assertNotIn("storage_path", str(data["chunks"]))


class Edicao(Base):
    def setUp(self):
        super().setUp()
        self.sid = self.start()

    def patch(self, tok="tok-a", **body):
        return self.client.patch(f"/api/live/{self.sid}", headers=self.h(tok), json=body)

    def test_muda_metadados(self):
        r = self.patch(title="  Novo   título ", context="Financeiro", client_name="Beta", alerts_enabled=False)
        self.assertEqual(r.status_code, 200, r.text)
        s = self.rows("live_sessions")[0]
        self.assertEqual((s["title"], s["context"], s["client_name"], s["alerts_enabled"]), ("Novo título", "Financeiro", "Beta", False))

    def test_cliente_pode_ser_limpo_mas_titulo_nao_pode_ficar_vazio(self):
        self.patch(client_name="Beta")
        self.assertEqual(self.patch(client_name="").status_code, 200)
        self.assertIsNone(self.rows("live_sessions")[0]["client_name"])
        self.assertEqual(self.patch(title="   ").status_code, 400)
        self.assertEqual(self.patch(title="x" * 201).status_code, 400)

    def test_pausa_e_retoma(self):
        self.assertEqual(self.patch(status="paused").status_code, 200)
        self.assertEqual(self.rows("live_sessions")[0]["status"], "paused")
        self.assertEqual(self.patch(status="recording").status_code, 200)

    def test_nao_define_estado_final_nem_campos_do_backend(self):
        for body in ({"status": "ended"}, {"status": "failed"}, {"status": "abandoned"}, {"status": "processing"}):
            self.assertEqual(self.patch(**body).status_code, 400, body)
        self.assertEqual(self.rows("live_sessions")[0]["status"], "recording")
        r = self.client.patch(f"/api/live/{self.sid}", headers=self.h(), json={"meeting_id": UA, "duration_seconds": 50, "owner_id": UB, "consent_at": "2020-01-01"})
        self.assertEqual(r.status_code, 200)  # campos desconhecidos são ignorados
        s = self.rows("live_sessions")[0]
        self.assertEqual((s["meeting_id"], s["duration_seconds"], s["owner_id"]), (None, 0, UA))

    def test_corpo_vazio_nao_altera_nada(self):
        before = dict(self.rows("live_sessions")[0])
        self.assertEqual(self.patch().status_code, 200)
        self.assertEqual(self.rows("live_sessions")[0], before)


class Pedacos(Base):
    def setUp(self):
        super().setUp()
        self.sid = self.start(org_id=ORG1)

    def test_fluxo_completo_url_envio_e_registro(self):
        up = self.upload(self.sid, 0)
        self.assertEqual(up["path"], f"orgs/{ORG1}/live/{self.sid}/0000.webm")
        self.assertTrue(up["signed_url"].startswith("https://storage.test/upload/"))
        r = self.register(self.sid, 0)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((r.json()["duplicate"], r.json()["chunk"]), (False, {"seq": 0, "status": "uploaded", "duration_ms": 30000, "size_bytes": 120000}))
        c = self.rows("live_chunks")[0]
        self.assertEqual((c["storage_path"], c["owner_id"]), (f"orgs/{ORG1}/live/{self.sid}/0000.webm", UA))

    def test_conta_pessoal_usa_a_pasta_do_usuario(self):
        sid = self.start()
        self.assertEqual(self.upload(sid, 3)["path"], f"users/{UA}/live/{sid}/0003.webm")

    def test_o_cliente_nao_escolhe_o_caminho(self):
        r = self.client.post(f"/api/live/{self.sid}/chunks", headers=self.h(),
                             json={"seq": 0, "duration_ms": 1000, "storage_path": "users/outra-pessoa/x.webm", "path": "../../x"})
        self.assertEqual(r.status_code, 409)  # nenhum arquivo chegou ao caminho certo
        self.assertEqual(self.rows("live_chunks"), [])

    def test_so_registra_se_o_audio_chegou_ao_bucket(self):
        self.upload(self.sid, 0, put=False)
        r = self.register(self.sid, 0)
        self.assertEqual(r.status_code, 409)
        self.assertIn("ainda não chegou", r.json()["detail"])
        self.assertEqual(self.rows("live_chunks"), [])

    def test_arquivo_vazio_ou_grande_demais(self):
        self.upload(self.sid, 0, size=0)
        self.assertEqual(self.register(self.sid, 0).status_code, 400)
        self.upload(self.sid, 1, size=live.MAX_CHUNK_BYTES + 1)
        self.assertEqual(self.register(self.sid, 1).status_code, 400)
        self.assertEqual(self.rows("live_chunks"), [])

    def test_registrar_duas_vezes_e_seguro(self):
        self.chunk(self.sid, 0)
        with mock.patch.object(storage_io, "object_size", mock.Mock(return_value=5)) as size:
            again = self.register(self.sid, 0)
            self.assertFalse(size.called)  # o duplicado é reconhecido sem consultar o bucket de novo
        self.assertEqual((again.status_code, again.json()["duplicate"]), (200, True))
        self.assertEqual(len(self.rows("live_chunks")), 1)

    def test_corrida_na_gravacao_do_mesmo_pedaco_vira_duplicado(self):
        self.upload(self.sid, 0)
        original = live._db
        calls = {"n": 0}

        def racing(call):  # na primeira vez, "outra chamada" grava o pedaço antes
            calls["n"] += 1
            if calls["n"] == 3:
                self.rows("live_chunks").append({"id": "x", "session_id": self.sid, "seq": 0, "owner_id": UA, "status": "uploaded", "duration_ms": 30000, "size_bytes": 5})
            return original(call)
        with mock.patch.object(live, "_db", racing):
            r = self.register(self.sid, 0)
        self.assertEqual((r.status_code, r.json()["duplicate"]), (200, True))

    def test_numero_e_duracao_validos(self):
        h = self.h()
        for seq in (-1, 400, 10**6):
            self.assertEqual(self.client.post(f"/api/live/{self.sid}/chunks/upload-url", headers=h, json={"seq": seq}).status_code, 400, seq)
        self.assertEqual(self.client.post(f"/api/live/{self.sid}/chunks/upload-url", headers=h, json={"seq": [3]}).status_code, 422)
        self.upload(self.sid, 0)
        with mock.patch.object(storage_io, "object_size", mock.Mock(return_value=5)) as size:
            for dur in (-1, 120_001):
                self.assertEqual(self.register(self.sid, 0, dur=dur).status_code, 400, dur)
            self.assertFalse(size.called)  # recusado antes de olhar o bucket
        self.assertEqual(self.rows("live_chunks"), [])
        self.assertEqual(self.upload(self.sid, 399)["seq"], 399)

    def test_formato_de_audio(self):
        h = self.h()
        self.assertEqual(self.client.post(f"/api/live/{self.sid}/chunks/upload-url", headers=h, json={"seq": 0, "ext": ".exe"}).status_code, 400)
        self.assertEqual(self.client.post(f"/api/live/{self.sid}/chunks/upload-url", headers=h, json={"seq": 0, "ext": "../x"}).status_code, 400)
        self.assertEqual(self.upload(self.sid, 0, ext="mp4")["path"].endswith("/0000.mp4"), True)

    def test_ordem_qualquer_e_lacunas_aparecem_no_encerramento(self):
        for seq in (2, 0, 5):  # chegam fora de ordem; 1, 3 e 4 faltam
            self.chunk(self.sid, seq)
        r = self.client.post(f"/api/live/{self.sid}/finish", headers=self.h())
        self.assertEqual((r.json()["chunks"], r.json()["missing"]), (3, [1, 3, 4]))
        self.assertEqual([c["seq"] for c in self.get(self.sid).json()["chunks"]], [0, 2, 5])

    def test_duracao_e_ultimo_sinal_da_sessao(self):
        self.advance(minutes=1)
        self.chunk(self.sid, 0)
        self.chunk(self.sid, 1)
        s = self.rows("live_sessions")[0]
        self.assertEqual((s["duration_seconds"], s["last_chunk_at"]), (60, self.now.isoformat()))

    def test_sessao_pausada_ou_em_processamento_ainda_aceita_pedacos(self):
        self.client.patch(f"/api/live/{self.sid}", headers=self.h(), json={"status": "paused"})
        self.chunk(self.sid, 0)
        self.client.post(f"/api/live/{self.sid}/finish", headers=self.h())
        self.chunk(self.sid, 1)  # o último pedaço pode chegar depois de pedir o encerramento
        self.assertEqual(len(self.rows("live_chunks")), 2)

    def test_sessao_encerrada_ou_interrompida_nao_aceita_pedacos(self):
        self.rows("live_sessions")[0]["status"] = "ended"
        r = self.client.post(f"/api/live/{self.sid}/chunks/upload-url", headers=self.h(), json={"seq": 0})
        self.assertEqual(r.status_code, 409)
        self.bucket[f"orgs/{ORG1}/live/{self.sid}/0000.webm"] = 5
        self.assertEqual(self.register(self.sid, 0).status_code, 409)
        self.assertEqual(self.rows("live_chunks"), [])

    def test_sessao_com_audio_apagado_nao_aceita_pedacos(self):
        self.rows("live_sessions")[0]["audio_deleted_at"] = CLOCK.isoformat()
        self.assertEqual(self.client.post(f"/api/live/{self.sid}/chunks/upload-url", headers=self.h(), json={"seq": 0}).status_code, 409)

    def test_falha_do_bucket_vira_erro_amigavel(self):
        with mock.patch.object(storage_io, "signed_upload", mock.Mock(side_effect=RuntimeError("segredo interno"))):
            r = self.client.post(f"/api/live/{self.sid}/chunks/upload-url", headers=self.h(), json={"seq": 0})
        self.assertEqual(r.status_code, 502)
        self.assertNotIn("segredo", r.text)
        self.upload(self.sid, 0)
        with mock.patch.object(storage_io, "object_size", mock.Mock(side_effect=RuntimeError("segredo interno"))):
            r = self.register(self.sid, 0)
        self.assertEqual(r.status_code, 502)
        self.assertNotIn("segredo", r.text)

    def test_falha_ao_atualizar_a_sessao_nao_perde_o_pedaco(self):
        self.upload(self.sid, 0)
        self.fake.fail.add(("PATCH", "live_sessions"))
        r = self.register(self.sid, 0)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(self.rows("live_chunks")), 1)


class Interrupcao(Base):
    def test_gravando_sem_sinal_por_10_minutos_vira_interrompida(self):
        sid = self.start()
        self.advance(minutes=9)
        self.assertEqual(self.get(sid).json()["session"]["status"], "recording")
        self.advance(minutes=2)
        data = self.get(sid).json()
        self.assertEqual(data["session"]["status"], "abandoned")
        self.assertEqual(self.rows("live_sessions")[0]["status"], "abandoned")

    def test_pedaco_novo_renova_o_sinal_de_vida(self):
        sid = self.start()
        for _ in range(4):
            self.advance(minutes=8)
            self.chunk(sid, _)
        self.assertEqual(self.get(sid).json()["session"]["status"], "recording")

    def test_pausada_so_vira_interrompida_depois_de_6_horas(self):
        sid = self.start()
        self.client.patch(f"/api/live/{sid}", headers=self.h(), json={"status": "paused"})
        self.advance(hours=5, minutes=50)
        self.assertEqual(self.get(sid).json()["session"]["status"], "paused")
        self.advance(minutes=20)
        self.assertEqual(self.get(sid).json()["session"]["status"], "abandoned")

    def test_lista_tambem_marca_as_interrompidas(self):
        sid = self.start()
        self.advance(minutes=30)
        listed = self.client.get("/api/live", headers=self.h()).json()["sessions"]
        self.assertEqual(listed[0]["status"], "abandoned")

    def test_interrompida_pode_ser_finalizada_e_nada_se_perde(self):
        sid = self.start()
        self.chunk(sid, 0)
        self.advance(minutes=30)
        self.assertEqual(self.get(sid).json()["session"]["status"], "abandoned")
        r = self.client.post(f"/api/live/{sid}/finish", headers=self.h())
        self.assertEqual((r.status_code, r.json()["session"]["status"], r.json()["chunks"]), (200, "processing", 1))

    def test_nao_mexe_em_sessao_que_nao_esta_ativa(self):
        sid = self.start()
        self.client.post(f"/api/live/{sid}/finish", headers=self.h())
        self.advance(hours=3)
        self.assertEqual(self.get(sid).json()["session"]["status"], "processing")

    def test_nao_sobrescreve_uma_sessao_que_mudou_no_meio(self):
        sid = self.start()
        self.advance(minutes=30)
        original = live._sweep

        def racing(sessions):  # entre ler e marcar, o dono pediu o encerramento
            self.rows("live_sessions")[0]["status"] = "processing"
            return original(sessions)
        with mock.patch.object(live, "_sweep", racing):
            data = self.get(sid).json()
        self.assertEqual(self.rows("live_sessions")[0]["status"], "processing")
        self.assertEqual(data["session"]["status"], "recording")  # a resposta não afirma algo que não aconteceu

    def test_falha_ao_marcar_nao_derruba_a_leitura(self):
        sid = self.start()
        self.advance(minutes=30)
        self.fake.fail.add(("PATCH", "live_sessions"))
        r = self.get(sid)
        self.assertEqual((r.status_code, r.json()["session"]["status"]), (200, "recording"))


class Encerramento(Base):
    def test_finish_vai_para_processamento_e_e_repetivel(self):
        sid = self.start()
        self.chunk(sid, 0)
        a = self.client.post(f"/api/live/{sid}/finish", headers=self.h())
        self.assertEqual((a.status_code, a.json()["session"]["status"], a.json()["missing"]), (200, "processing", []))
        b = self.client.post(f"/api/live/{sid}/finish", headers=self.h())
        self.assertEqual((b.status_code, b.json()["session"]["status"]), (200, "processing"))
        self.assertEqual([r["action"] for r in self.fake.tables["audit_log"]].count("live.finish"), 1)

    def test_encerrada_nao_pode_ser_encerrada_de_novo(self):
        sid = self.start()
        self.rows("live_sessions")[0]["status"] = "ended"
        self.assertEqual(self.client.post(f"/api/live/{sid}/finish", headers=self.h()).status_code, 409)

    def test_sem_pedacos_nao_ha_lacunas(self):
        sid = self.start()
        self.assertEqual(self.client.post(f"/api/live/{sid}/finish", headers=self.h()).json()["missing"], [])


class Exclusao(Base):
    def test_apaga_o_audio_primeiro_e_depois_os_registros(self):
        sid = self.start(org_id=ORG1)
        for seq in range(3):
            self.chunk(sid, seq)
        order = []
        original = storage_io.delete_objects
        self.fake.calls.clear()
        r = self.client.delete(f"/api/live/{sid}", headers=self.h())
        self.assertEqual((r.status_code, r.json()["deleted_audio"]), (200, 3))
        self.assertEqual(sorted(self.deleted), [f"orgs/{ORG1}/live/{sid}/000{i}.webm" for i in range(3)])
        self.assertEqual((self.rows("live_sessions"), self.rows("live_chunks")), ([], []))
        self.assertEqual(self.bucket, {})

    def test_se_o_bucket_falhar_nada_e_apagado_do_banco(self):
        sid = self.start()
        self.chunk(sid, 0)
        self.storage_fail = True
        r = self.client.delete(f"/api/live/{sid}", headers=self.h())
        self.assertEqual(r.status_code, 502)
        self.assertNotIn("falha do bucket", r.text)
        self.assertEqual(len(self.rows("live_sessions")), 1)
        self.assertEqual(len(self.rows("live_chunks")), 1)
        self.storage_fail = False
        self.assertEqual(self.client.delete(f"/api/live/{sid}", headers=self.h()).status_code, 200)  # tentar de novo funciona

    def test_apagar_sessao_sem_pedacos(self):
        sid = self.start()
        self.assertEqual(self.client.delete(f"/api/live/{sid}", headers=self.h()).status_code, 200)
        self.assertEqual(self.deleted, [])

    def test_auditoria_sem_conteudo(self):
        sid = self.start(title="Título confidencial do cliente")
        self.chunk(sid, 0)
        self.client.delete(f"/api/live/{sid}", headers=self.h())
        text = str(self.fake.tables["audit_log"])
        self.assertNotIn("confidencial", text)
        self.assertEqual([r["action"] for r in self.fake.tables["audit_log"]], ["live.start", "live.delete"])


class Banco(Base):
    def test_falha_do_banco_vira_502_sem_detalhes(self):
        self.fake.fail.add(("POST", "live_sessions"))
        r = self.client.post("/api/live", headers=self.h(), json={"consent": True})
        self.assertEqual(r.status_code, 502)
        self.assertNotIn("boom", r.text)


class CaminhoDoAudio(unittest.TestCase):
    def test_montagem_do_caminho(self):
        sid = "11111111-1111-4111-8111-111111111111"
        self.assertEqual(live.chunk_path("u1", None, sid, 7, ".webm"), f"users/u1/live/{sid}/0007.webm")
        self.assertEqual(live.chunk_path("u1", "o1", sid, 123, ".ogg"), f"orgs/o1/live/{sid}/0123.ogg")


if __name__ == "__main__":
    unittest.main()
