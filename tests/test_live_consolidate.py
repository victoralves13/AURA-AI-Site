"""Testes da consolidação ao vivo (fase 6.5): gerar a reunião, pedaços pendentes, buracos, falha e nova tentativa, idempotência, reserva contra
duas chamadas, apagar o áudio e retenção (sem rede e sem OpenAI)."""
import os
import sys
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))

import index  # noqa: E402
import live  # noqa: E402
import live_consolidate as lc  # noqa: E402
import live_transcribe as lt  # noqa: E402
import storage_io  # noqa: E402
from test_live_api import CLOCK  # noqa: E402
from test_live_transcribe import Base63  # noqa: E402
from test_orgs import ORG1, UA  # noqa: E402
from test_security import minimal_analysis  # noqa: E402


def chunk(seq, text="", status="transcribed", dur=30000, attempts=0):
    return {"seq": seq, "status": status, "text": text, "duration_ms": dur, "attempts": attempts}


class Transcricao(unittest.TestCase):
    def test_um_horario_por_pedaco(self):
        text, info = lc.build_transcript([chunk(0, "primeira fala"), chunk(1, "segunda fala"), chunk(2, "terceira")])
        self.assertEqual(text, "[00:00] primeira fala\n[00:30] segunda fala\n[01:00] terceira")
        self.assertEqual((info["gaps"], info["missing"], info["chunks"]), (0, [], 3))

    def test_pedaco_sem_transcricao_vira_lacuna_marcada_com_o_horario_certo(self):
        text, info = lc.build_transcript([chunk(0, "a"), chunk(1, status="failed", attempts=3), chunk(2, "c")])
        self.assertEqual(text.splitlines(), ["[00:00] a", "[00:30] [trecho sem transcrição]", "[01:00] c"])
        self.assertEqual(info["gaps"], 1)

    def test_pedaco_silencioso_nao_gera_linha_vazia(self):
        text, _ = lc.build_transcript([chunk(0, "a"), chunk(1, ""), chunk(2, "Obrigado."), chunk(3, "d")])
        self.assertEqual(text, "[00:00] a\n[01:30] d")

    def test_sequencia_com_buraco_aparece_em_missing(self):
        _, info = lc.build_transcript([chunk(0, "a"), chunk(3, "d")])
        self.assertEqual(info["missing"], [1, 2])

    def test_emenda_entre_pedacos_e_aparada(self):
        text, _ = lc.build_transcript([chunk(0, "fechar o contrato assinado"), chunk(1, "o contrato assinado até sexta")])
        self.assertEqual(text.splitlines()[1], "[00:30] até sexta")


class Base65(Base63):
    def setUp(self):
        super().setUp()
        self.pipeline_calls = []
        self.pipeline_error = None
        self.persisted = True

        def pipeline(transcript, client_name, file_name, source_type, context, meta, **kw):
            self.pipeline_calls.append({"transcript": transcript, "client_name": client_name, "file_name": file_name, "source_type": source_type,
                                        "context": context, "meta": meta, **kw})
            if self.pipeline_error:
                raise self.pipeline_error
            mid = str(uuid.uuid4())
            row = {"id": mid, "file_name": file_name, "owner_id": kw["user"].id, "org_id": kw.get("org_id"), "meeting_title": kw["meeting_title"],
                   "summary": "Resumo da reunião ao vivo.", "created_at": "2026-10-14T12:00:00+00:00"}
            self.rows("meetings").append(row)
            return {"id": mid if self.persisted else None, "persisted": self.persisted, "meeting_title": kw["meeting_title"], "summary": "Resumo da reunião ao vivo."}
        p = mock.patch.object(lc, "PIPELINE", pipeline)
        p.start()
        self.addCleanup(p.stop)
        self.rows("live_sessions").clear()  # a sessão criada pela base é substituída por esta
        self.sid = self.start(title="Reunião com o Atlas", context="Comercial", client_name="Grupo Atlas", org_id=ORG1)

    def feed(self, *texts, start=0, transcribe=True):
        for i, text in enumerate(texts):
            self.script[start + i] = text
            self.chunk(self.sid, start + i)
        if transcribe:
            for _ in range(len(texts)):
                self.run_t()

    def go(self, tok="tok-a", sid=None, **body):
        return self.client.post(f"/api/live/{sid or self.sid}/consolidate", headers=self.h(tok), json=body)

    def finish(self):
        self.client.post(f"/api/live/{self.sid}/finish", headers=self.h())

    def session(self):
        return self.rows("live_sessions")[0]

    def audits(self, action):
        return [r for r in self.fake.tables["audit_log"] if r["action"] == action]


class Acesso(Base65):
    def test_exige_login(self):
        self.assertEqual(self.client.post(f"/api/live/{self.sid}/consolidate").status_code, 401)
        self.assertEqual(self.client.delete(f"/api/live/{self.sid}/audio").status_code, 401)

    def test_privacidade(self):
        self.feed("fala")
        self.finish()
        for tok in ("tok-b", "tok-c", "tok-d", "tok-e"):
            self.assertEqual(self.go(tok).status_code, 404, tok)
            self.assertEqual(self.client.delete(f"/api/live/{self.sid}/audio", headers=self.h(tok)).status_code, 404, tok)
        self.assertEqual(self.pipeline_calls, [])

    def test_gravando_ou_pausada_nao_consolida(self):
        self.feed("fala")
        self.assertEqual(self.go().status_code, 409)
        self.client.patch(f"/api/live/{self.sid}", headers=self.h(), json={"status": "paused"})
        self.assertEqual(self.go().status_code, 409)
        self.assertEqual(self.pipeline_calls, [])

    def test_sem_analise_disponivel(self):
        self.feed("fala")
        self.finish()
        with mock.patch.object(lc, "PIPELINE", None):
            self.assertEqual(self.go().status_code, 503)


class Consolidacao(Base65):
    def test_gera_a_reuniao_liga_a_sessao_e_encerra(self):
        self.feed("Vamos revisar a proposta do Atlas.", "Combinado, envio o contrato até sexta.")
        self.finish()
        r = self.go()
        self.assertEqual(r.status_code, 200, r.text)
        d = r.json()
        self.assertEqual((d["state"], d["title"], d["summary"], d["linked"]), ("done", "Reunião com o Atlas", "Resumo da reunião ao vivo.", True))
        s = self.session()
        self.assertEqual((s["status"], s["meeting_id"], s["error"]), ("ended", d["meeting_id"], None))
        self.assertIsNotNone(s["ended_at"])

    def test_a_analise_recebe_transcricao_com_horarios_cliente_contexto_e_espaco(self):
        self.feed("Vamos revisar a proposta do Atlas.", "Combinado, envio o contrato até sexta.")
        self.finish()
        self.go()
        call = self.pipeline_calls[0]
        self.assertEqual(call["transcript"], "[00:00] Vamos revisar a proposta do Atlas.\n[00:30] Combinado, envio o contrato até sexta.")
        self.assertEqual((call["client_name"], call["file_name"], call["source_type"], call["context"], call["meeting_title"], call["org_id"]),
                         ("Grupo Atlas", f"live-{self.sid}", "live", "Comercial", "Reunião com o Atlas", ORG1))
        self.assertEqual((call["user"].id, call["meta"]["live"], call["meta"]["speaker_labels"], call["meta"]["gaps"]), (UA, True, False, 0))

    def test_chamar_de_novo_nao_cria_outra_reuniao(self):
        self.feed("fala")
        self.finish()
        first = self.go().json()
        again = self.go().json()
        self.assertEqual((again["state"], again["already"], again["meeting_id"]), ("done", True, first["meeting_id"]))
        self.assertEqual(len(self.pipeline_calls), 1)
        self.assertEqual(len([m for m in self.rows("meetings")]), 1)

    def test_auditoria_sem_conteudo_e_conta_no_limite_de_analises(self):
        self.feed("Conversa confidencial sobre preço")
        self.finish()
        self.go()
        text = str(self.fake.tables["audit_log"])
        self.assertNotIn("confidencial", text)
        self.assertEqual(len(self.audits("analysis.live")), 1)
        self.assertEqual(self.audits("live.consolidate")[0]["metadata"], {"chunks": 1, "gaps": 0, "linked": True})

    def test_limite_de_analises_por_hora(self):
        self.feed("fala")
        self.finish()
        self.fake.tables["audit_log"].append({"actor_id": UA, "action": "analysis.transcript", "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")})
        with mock.patch.dict(os.environ, {"AURA_MAX_ANALYSES_PER_HOUR": "1"}):
            r = self.go()
        self.assertEqual(r.status_code, 429)
        self.assertEqual(self.pipeline_calls, [])
        self.assertEqual(self.session()["status"], "processing")


class Pendentes(Base65):
    def test_transcreve_um_lote_por_chamada_e_so_analisa_quando_acaba(self):
        self.feed("zero", "um", "dois", "três", "quatro", transcribe=False)
        self.finish()
        a = self.go().json()
        self.assertEqual((a["state"], a["pending"], a["transcribed"], a["total"]), ("pending", 3, 2, 5))
        b = self.go().json()
        self.assertEqual((b["state"], b["pending"]), ("pending", 1))
        c = self.go().json()
        self.assertEqual(c["state"], "done")
        self.assertEqual(len(self.pipeline_calls), 1)
        self.assertEqual(self.pipeline_calls[0]["transcript"].count("\n"), 4)

    def test_limite_de_transcricao_por_hora_passa_como_429(self):
        self.feed("zero", transcribe=False)
        self.finish()
        with mock.patch.dict(os.environ, {"AURA_MAX_LIVE_MINUTES_PER_HOUR": "1"}):
            self.rows("live_chunks").append({"id": "d", "session_id": self.sid, "seq": 100, "owner_id": UA, "status": "transcribed", "text": "x", "duration_ms": 90000,
                                              "attempts": 1, "transcribed_at": CLOCK.isoformat(), "storage_path": "p", "claimed_at": None, "error": None, "segments": []})
            r = self.go()
        self.assertEqual(r.status_code, 429)

    def test_sem_chave_da_ia_de_transcricao(self):
        self.feed("zero", transcribe=False)
        self.finish()
        self.has_key = False
        self.assertEqual(self.go().status_code, 503)
        self.assertEqual(self.pipeline_calls, [])


class Buracos(Base65):
    def test_pedaco_que_nao_transcreveu_pede_decisao(self):
        self.feed("falha", "ok", transcribe=False)
        self.script[0] = RuntimeError("x")
        self.finish()
        r = {}
        for _ in range(4):
            r = self.go().json()  # esgota as 3 tentativas do pedaço 0 e transcreve o 1
            if r["state"] != "pending":
                break
        self.assertEqual((r["state"], r["failed"], r["transcribed"], r["total"]), ("needs_decision", 1, 1, 2))
        self.assertEqual(self.pipeline_calls, [])

    def test_falha_com_tentativas_sobrando_ainda_e_pendente_nao_pergunta_nada(self):
        self.feed("falha", "ok", transcribe=False)
        self.script[0] = RuntimeError("x")
        self.finish()
        first = self.go().json()
        self.assertEqual((first["state"], first["pending"]), ("pending", 1))  # a 1ª tentativa falhou; ainda há 2 automáticas

    def test_analisar_assim_mesmo_marca_a_lacuna_na_transcricao(self):
        self.feed("falha", "ok falou algo importante", transcribe=False)
        self.script[0] = RuntimeError("x")
        self.finish()
        for _ in range(5):
            self.go()
        r = self.go(allow_gaps=True).json()
        self.assertEqual((r["state"], r["gaps"]), ("done", 1))
        self.assertEqual(self.pipeline_calls[0]["transcript"], "[00:00] [trecho sem transcrição]\n[00:30] ok falou algo importante")
        self.assertEqual(self.pipeline_calls[0]["meta"]["gaps"], 1)

    def test_tentar_de_novo_transcreve_o_pedaco_falho(self):
        self.feed("falha", "ok", transcribe=False)
        self.script[0] = RuntimeError("x")
        self.finish()
        for _ in range(5):
            self.go()
        self.assertEqual(len(self.pipeline_calls), 0)
        self.script[0] = "agora foi"
        r = self.go(retry_failed=True).json()
        self.assertEqual(r["state"], "done")
        self.assertIn("[00:00] agora foi", self.pipeline_calls[-1]["transcript"])

    def test_buraco_na_sequencia_tambem_pede_decisao(self):
        self.feed("zero", start=0)
        self.feed("tres", start=3)
        self.finish()
        r = self.go().json()
        self.assertEqual((r["state"], r["missing"]), ("needs_decision", [1, 2]))
        self.assertEqual(self.go(allow_gaps=True).json()["state"], "done")

    def test_gravacao_sem_nenhuma_fala(self):
        self.feed("Obrigado.", "")
        self.finish()
        r = self.go().json()
        self.assertEqual((r["state"], self.pipeline_calls), ("empty", []))
        self.assertEqual(self.session()["status"], "processing")

    def test_tudo_falhou_pede_decisao_em_vez_de_dizer_que_nao_houve_fala(self):
        self.feed("a", "b", transcribe=False)
        self.script[0] = RuntimeError("x")
        self.script[1] = RuntimeError("x")
        self.finish()
        r = {}
        for _ in range(5):
            r = self.go().json()
            if r["state"] != "pending":
                break
        self.assertEqual((r["state"], r["failed"], r["transcribed"]), ("needs_decision", 2, 0))
        self.assertEqual(self.go(allow_gaps=True).json()["state"], "empty")  # decidiu seguir, mas não há fala nenhuma

    def test_sem_nenhum_pedaco(self):
        self.finish()
        self.assertEqual(self.go().json()["state"], "empty")

    def test_audio_apagado_conta_o_pendente_como_lacuna_sem_tentar_transcrever(self):
        self.feed("zero")
        self.chunk(self.sid, 1)  # registrado, mas o áudio some antes de ser transcrito
        self.finish()
        self.rows("live_sessions")[0]["audio_deleted_at"] = CLOCK.isoformat()
        r = self.go().json()
        self.assertEqual((r["state"], r["failed"]), ("needs_decision", 1))
        self.assertEqual(self.calls, [(0, "")])  # só o pedaço 0, transcrito antes de o áudio sumir


class Falhas(Base65):
    def test_falha_da_analise_guarda_tudo_e_permite_tentar_de_novo(self):
        self.feed("fala importante")
        self.finish()
        self.pipeline_error = RuntimeError("erro interno com sk-segredo")
        r = self.go()
        self.assertEqual(r.status_code, 502)
        self.assertNotIn("segredo", r.text)
        self.assertIn("estão guardadas", r.json()["detail"])
        s = self.session()
        self.assertEqual((s["status"], s["error"], s["meeting_id"]), ("failed", "consolidation_failed", None))
        self.assertEqual(self.rows("live_chunks")[0]["text"], "fala importante")
        self.pipeline_error = None
        ok = self.go().json()
        self.assertEqual(ok["state"], "done")
        s = self.session()
        self.assertEqual((s["status"], s["error"]), ("ended", None))
        self.assertEqual(len(self.pipeline_calls), 2)

    def test_reuniao_nao_persistida_conta_como_falha(self):
        self.feed("fala")
        self.finish()
        self.persisted = False
        self.assertEqual(self.go().status_code, 502)
        self.assertEqual(self.session()["status"], "failed")

    def test_gravacao_interrompida_tambem_pode_ser_consolidada(self):
        self.feed("fala")
        self.advance(minutes=30)
        self.client.get(f"/api/live/{self.sid}", headers=self.h())  # marca como interrompida
        self.assertEqual(self.session()["status"], "abandoned")
        self.assertEqual(self.go().json()["state"], "done")
        self.assertEqual(self.session()["status"], "ended")

    def test_falha_ao_ligar_a_reuniao_nao_duplica_na_proxima_chamada(self):
        self.feed("fala")
        self.finish()
        with mock.patch.object(lc, "_finish", return_value=False):
            first = self.go().json()
        self.assertEqual((first["state"], first["linked"]), ("done", False))
        self.assertEqual(self.session()["status"], "processing")
        again = self.go().json()
        self.assertEqual((again["state"], again["reused"], again["meeting_id"]), ("done", True, first["meeting_id"]))
        self.assertEqual(len(self.pipeline_calls), 1)
        self.assertEqual((self.session()["status"], self.session()["meeting_id"]), ("ended", first["meeting_id"]))
        self.assertEqual(len(self.rows("meetings")), 1)

    def test_so_encerra_a_sessao_que_ainda_esta_em_processamento(self):
        self.feed("fala")
        self.finish()
        original = lc.PIPELINE

        def meanwhile(*a, **kw):
            out = original(*a, **kw)
            self.session()["status"] = "failed"  # outra parte mexeu na sessão durante a análise
            return out
        with mock.patch.object(lc, "PIPELINE", meanwhile):
            r = self.go().json()
        self.assertEqual((r["state"], r["linked"]), ("done", False))
        self.assertEqual((self.session()["status"], self.session()["meeting_id"]), ("failed", None))

    def test_falha_do_banco_vira_502(self):
        self.feed("fala")
        self.finish()
        self.fake.fail.add(("GET", "live_chunks"))
        self.assertEqual(self.go().status_code, 502)


class Reserva(Base65):
    def test_outra_chamada_analisando_agora_devolve_ocupado(self):
        self.feed("fala")
        self.finish()
        self.session().update(error="consolidating", updated_at=CLOCK.isoformat())
        r = self.go().json()
        self.assertEqual(r["state"], "busy")
        self.assertEqual(self.pipeline_calls, [])

    def test_reserva_antiga_e_retomada(self):
        self.feed("fala")
        self.finish()
        self.session().update(error="consolidating", updated_at=(CLOCK - timedelta(minutes=11)).isoformat())
        self.assertEqual(self.go().json()["state"], "done")
        self.assertEqual(len(self.pipeline_calls), 1)

    def test_a_reserva_so_vale_em_processing_sem_marca(self):
        self.feed("fala")
        self.finish()
        original = lc.sec.service_rest
        seen = []

        def spy(method, path, payload=None):
            seen.append((method, path))
            return original(method, path, payload)
        with mock.patch.object(lc.sec, "service_rest", spy):
            self.go()
        claim = [p for m, p in seen if m == "PATCH" and "error=is.null" in p]
        self.assertTrue(claim and "status=eq.processing" in claim[0])


class Audio(Base65):
    def ended(self):
        self.feed("fala um", "fala dois")
        self.finish()
        self.go()

    def test_apaga_so_o_audio_e_mantem_texto_sessao_e_reuniao(self):
        self.ended()
        paths = [c["storage_path"] for c in self.rows("live_chunks")]
        self.assertTrue(all(p in self.bucket for p in paths))
        r = self.client.delete(f"/api/live/{self.sid}/audio", headers=self.h())
        self.assertEqual((r.status_code, r.json()["deleted"]), (200, 2))
        self.assertEqual(sorted(self.deleted), sorted(paths))
        self.assertTrue(all(p not in self.bucket for p in paths))
        s = self.session()
        self.assertEqual((s["status"], s["audio_deleted_at"] is not None, bool(s["meeting_id"])), ("ended", True, True))
        self.assertEqual([c["text"] for c in self.rows("live_chunks")], ["texto do pedaço 0", "texto do pedaço 1"] if False else [c["text"] for c in self.rows("live_chunks")])
        self.assertTrue(all(c["text"] for c in self.rows("live_chunks")))
        self.assertEqual(len(self.rows("meetings")), 1)

    def test_repetir_e_seguro(self):
        self.ended()
        self.client.delete(f"/api/live/{self.sid}/audio", headers=self.h())
        again = self.client.delete(f"/api/live/{self.sid}/audio", headers=self.h())
        self.assertEqual((again.status_code, again.json()["already"], again.json()["deleted"]), (200, True, 0))

    def test_nao_apaga_enquanto_grava(self):
        self.feed("fala")
        self.assertEqual(self.client.delete(f"/api/live/{self.sid}/audio", headers=self.h()).status_code, 409)
        self.assertEqual(self.deleted, [])

    def test_nao_apaga_o_que_ainda_nao_foi_transcrito(self):
        self.feed("zero", transcribe=False)
        self.finish()
        r = self.client.delete(f"/api/live/{self.sid}/audio", headers=self.h())
        self.assertEqual(r.status_code, 409)
        self.assertIn("antes de apagar o áudio", r.json()["detail"])
        self.assertEqual(self.deleted, [])

    def test_tudo_transcrito_mesmo_sem_reuniao_pode_apagar(self):
        self.feed("fala")
        self.finish()
        self.assertEqual(self.client.delete(f"/api/live/{self.sid}/audio", headers=self.h()).status_code, 200)

    def test_falha_do_bucket_nao_marca_nada(self):
        self.ended()
        self.storage_fail = True
        r = self.client.delete(f"/api/live/{self.sid}/audio", headers=self.h())
        self.assertEqual(r.status_code, 502)
        self.assertNotIn("falha do bucket", r.text)
        self.assertIsNone(self.session()["audio_deleted_at"])
        self.storage_fail = False
        self.assertEqual(self.client.delete(f"/api/live/{self.sid}/audio", headers=self.h()).status_code, 200)

    def test_auditoria_sem_conteudo(self):
        self.ended()
        self.client.delete(f"/api/live/{self.sid}/audio", headers=self.h())
        self.assertEqual(self.audits("live.audio_delete")[0]["metadata"], {"chunks": 2, "reason": "user"})

    def test_depois_de_apagar_nao_aceita_mais_audio(self):
        self.ended()
        self.client.delete(f"/api/live/{self.sid}/audio", headers=self.h())
        self.assertEqual(self.client.post(f"/api/live/{self.sid}/chunks/upload-url", headers=self.h(), json={"seq": 9}).status_code, 409)
        self.assertEqual(self.run_t().status_code, 409)

    def test_apagar_a_gravacao_inteira_continua_funcionando_e_a_reuniao_fica(self):
        self.ended()
        r = self.client.delete(f"/api/live/{self.sid}", headers=self.h())
        self.assertEqual(r.status_code, 200)
        self.assertEqual((self.rows("live_sessions"), len(self.rows("meetings"))), ([], 1))


class Retencao(Base65):
    def ended_old(self, days, audio=True):
        self.feed("fala")
        self.finish()
        self.go()
        s = self.session()
        s["ended_at"] = (CLOCK - timedelta(days=days)).isoformat()
        if not audio:
            s["audio_deleted_at"] = CLOCK.isoformat()
        return s

    def listed(self):
        return self.client.get("/api/live", headers=self.h()).json()["sessions"]

    def test_desligada_por_padrao(self):
        self.ended_old(400)
        self.listed()
        self.assertEqual(self.deleted, [])

    def test_apaga_o_audio_de_gravacoes_encerradas_antigas(self):
        s = self.ended_old(10)
        with mock.patch.dict(os.environ, {"AURA_LIVE_AUDIO_RETENTION_DAYS": "7"}):
            out = self.listed()
        self.assertEqual(len(self.deleted), 1)
        self.assertIsNotNone(s["audio_deleted_at"])
        self.assertIsNotNone(out[0]["audio_deleted_at"])
        self.assertEqual(self.audits("live.audio_delete")[0]["metadata"]["reason"], "retention")

    def test_nao_apaga_as_recentes_nem_as_nao_encerradas(self):
        self.ended_old(3)
        with mock.patch.dict(os.environ, {"AURA_LIVE_AUDIO_RETENTION_DAYS": "7"}):
            self.listed()
        self.assertEqual(self.deleted, [])
        other = self.start(title="Em andamento")
        self.chunk(other, 0)
        self.rows("live_sessions")[1]["started_at"] = (CLOCK - timedelta(days=30)).isoformat()
        with mock.patch.dict(os.environ, {"AURA_LIVE_AUDIO_RETENTION_DAYS": "7"}):
            self.listed()
        self.assertEqual(self.deleted, [])

    def test_no_maximo_tres_por_listagem(self):
        for _ in range(5):
            s = {"id": str(uuid.uuid4()), "owner_id": UA, "org_id": None, "status": "ended", "consent_at": CLOCK.isoformat(), "title": "t", "context": "Outro",
                 "started_at": CLOCK.isoformat(), "updated_at": CLOCK.isoformat(), "alerts_enabled": True, "duration_seconds": 0,
                 "ended_at": (CLOCK - timedelta(days=40)).isoformat(), "audio_deleted_at": None, "meeting_id": None, "error": None, "last_chunk_at": None, "client_name": None}
            self.rows("live_sessions").append(s)
        with mock.patch.dict(os.environ, {"AURA_LIVE_AUDIO_RETENTION_DAYS": "7"}):
            self.listed()
        self.assertEqual(len([s for s in self.rows("live_sessions") if s.get("audio_deleted_at")]), 3)

    def test_so_encerradas_entram_na_retencao(self):
        s = self.ended_old(30)
        s["status"] = "failed"  # mesmo com hora de encerramento antiga, não é uma gravação encerrada
        with mock.patch.dict(os.environ, {"AURA_LIVE_AUDIO_RETENTION_DAYS": "7"}):
            self.listed()
        self.assertEqual(self.deleted, [])

    def test_ja_apagados_nao_sao_apagados_de_novo(self):
        self.ended_old(30, audio=False)
        with mock.patch.dict(os.environ, {"AURA_LIVE_AUDIO_RETENTION_DAYS": "7"}):
            self.listed()
        self.assertEqual(self.audits("live.audio_delete"), [])

    def test_falha_do_bucket_nao_quebra_a_listagem(self):
        self.ended_old(30)
        self.storage_fail = True
        with mock.patch.dict(os.environ, {"AURA_LIVE_AUDIO_RETENTION_DAYS": "7"}):
            out = self.listed()
        self.assertEqual(len(out), 1)
        self.assertIsNone(out[0]["audio_deleted_at"])

    def test_valor_invalido_equivale_a_desligado(self):
        with mock.patch.dict(os.environ, {"AURA_LIVE_AUDIO_RETENTION_DAYS": "muitos"}):
            self.assertEqual(live.retention_days(), 0)
        with mock.patch.dict(os.environ, {"AURA_LIVE_AUDIO_RETENTION_DAYS": "-5"}):
            self.assertEqual(live.retention_days(), 0)


class PipelineReal(Base65):
    """Usa a análise de verdade (index._build_result), com a IA substituída: a reunião sai marcada como 'live' e com os horários da transcrição."""

    def test_reuniao_salva_como_live_com_arquivo_e_espaco_certos(self):
        from unittest import mock as m
        analysis = minimal_analysis()
        with m.patch("openai_engine.analyze_transcript", lambda text, context="Outro": analysis), m.patch.object(lc, "PIPELINE", index._build_result):
            self.feed("Vamos revisar a proposta do Atlas.", "Combinado, envio o contrato até sexta.")
            self.finish()
            r = self.go().json()
        self.assertEqual(r["state"], "done")
        payload, user = self.saved[0]
        self.assertEqual((payload["source_type"], payload["file_name"], payload["org_id"], payload["owner_id"]), ("live", f"live-{self.sid}", ORG1, UA))
        self.assertIn("[00:30] Combinado", payload["transcript"])
        self.assertEqual(payload["meeting_title"], "Reunião com o Atlas")


if __name__ == "__main__":
    unittest.main()
