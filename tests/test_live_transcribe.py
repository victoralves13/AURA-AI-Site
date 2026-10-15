"""Testes da transcrição contínua ao vivo (fase 6.3): reserva sem corrida, falhas e novas tentativas, ordem e repetição de pedaços,
montagem do texto, limite por hora e estimativa de custo (sem rede e sem OpenAI)."""
import os
import sys
import unittest
from datetime import timedelta
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from aura.features.live import router as live  # noqa: E402
from aura.features.live import transcribe as lt  # noqa: E402
from aura.core import storage as storage_io  # noqa: E402
from test_live_api import Base, CLOCK  # noqa: E402
from test_orgs import ORG1, UA, UB, UC  # noqa: E402


class Texto(unittest.TestCase):
    def test_frases_comuns_de_silencio_sao_descartadas_so_quando_sao_o_pedaco_inteiro(self):
        for text in ("Obrigado.", "  obrigado por assistir! ", "Legendas pela comunidade Amara.org", "Tchau, tchau."):
            self.assertEqual(lt.clean_text(text), "", text)
        self.assertEqual(lt.clean_text("Obrigado pelo retorno, vamos fechar o contrato."), "Obrigado pelo retorno, vamos fechar o contrato.")
        self.assertEqual(lt.clean_text(None), "")
        self.assertEqual(lt.clean_text("  vários   espaços \n e linhas "), "vários espaços e linhas")

    def test_trim_overlap_remove_a_emenda_repetida(self):
        prev = "O prazo de entrega está apertado e preciso renegociar com o fornecedor"
        self.assertEqual(lt.trim_overlap(prev, "com o fornecedor ainda hoje"), "ainda hoje")
        self.assertEqual(lt.trim_overlap(prev, "Com o FORNECEDOR, ainda hoje"), "ainda hoje")  # caixa e pontuação não importam
        self.assertEqual(lt.trim_overlap("a gente combinou de enviar", "de enviar o contrato"), "o contrato")

    def test_uma_palavra_igual_nao_basta(self):
        self.assertEqual(lt.trim_overlap("vamos fechar o contrato", "contrato assinado ontem"), "contrato assinado ontem")

    def test_sem_repeticao_nada_muda(self):
        self.assertEqual(lt.trim_overlap("fim da frase anterior", "começo de outra frase"), "começo de outra frase")
        self.assertEqual(lt.trim_overlap("", "texto"), "texto")
        self.assertEqual(lt.trim_overlap("texto", ""), "")

    def test_limite_de_palavras_da_emenda(self):
        prev = "um dois três quatro cinco seis sete oito"
        # as 8 últimas palavras se repetem, mas só se aparam até 5 (a emenda real é de poucas palavras)
        self.assertEqual(lt.trim_overlap(prev, "um dois três quatro cinco seis sete oito nove"), "um dois três quatro cinco seis sete oito nove")
        self.assertEqual(lt.trim_overlap(prev, "quatro cinco seis sete oito nove"), "nove")

    def test_nao_apara_o_pedaco_inteiro_por_engano(self):
        self.assertEqual(lt.trim_overlap("sim claro", "sim claro"), "")  # tudo era repetição

    def test_estimativa_de_custo(self):
        self.assertEqual(lt.estimate_cost(10), 0.06)
        with mock.patch.dict(os.environ, {"AURA_LIVE_COST_PER_MIN_USD": "0.01"}):
            self.assertEqual(lt.estimate_cost(10), 0.1)
        with mock.patch.dict(os.environ, {"AURA_LIVE_COST_PER_MIN_USD": "lixo"}):
            self.assertEqual(lt.cost_per_minute(), 0.006)

    def test_limite_por_hora_configuravel_e_nunca_zero(self):
        self.assertEqual(lt.hourly_limit_minutes(), 90)
        with mock.patch.dict(os.environ, {"AURA_MAX_LIVE_MINUTES_PER_HOUR": "30"}):
            self.assertEqual(lt.hourly_limit_minutes(), 30)
        with mock.patch.dict(os.environ, {"AURA_MAX_LIVE_MINUTES_PER_HOUR": "0"}):
            self.assertGreaterEqual(lt.hourly_limit_minutes(), 1)


def chunk(seq, text="", status="transcribed", dur=30000, attempts=0):
    return {"seq": seq, "status": status, "text": text, "duration_ms": dur, "attempts": attempts}


class Montagem(unittest.TestCase):
    def test_ordem_de_chegada_nao_importa(self):
        out = lt.assemble([chunk(2, "terceiro trecho"), chunk(0, "primeiro trecho"), chunk(1, "segundo trecho")])
        self.assertEqual([l["seq"] for l in out["lines"]], [0, 1, 2])
        self.assertEqual(out["text"], "primeiro trecho segundo trecho terceiro trecho")

    def test_inicio_de_cada_pedaco_vem_das_duracoes(self):
        out = lt.assemble([chunk(0, "a", dur=30000), chunk(1, "b", dur=28000), chunk(2, "c", dur=30000)])
        self.assertEqual([(l["start_ms"], l["end_ms"]) for l in out["lines"]], [(0, 30000), (30000, 58000), (58000, 88000)])

    def test_pedaco_pendente_ou_falho_ocupa_o_tempo_mas_nao_tem_texto(self):
        out = lt.assemble([chunk(0, "a"), chunk(1, status="uploaded"), chunk(2, "c", status="transcribed")])
        self.assertEqual([(l["seq"], l["text"], l["start_ms"]) for l in out["lines"]], [(0, "a", 0), (1, "", 30000), (2, "c", 60000)])

    def test_lacunas_na_sequencia(self):
        self.assertEqual(lt.assemble([chunk(0, "a"), chunk(3, "d")])["missing"], [1, 2])
        self.assertEqual(lt.assemble([chunk(1, "b")])["missing"], [0])
        self.assertEqual(lt.assemble([])["missing"], [])

    def test_apara_a_emenda_so_entre_pedacos_consecutivos(self):
        a = chunk(0, "preciso renegociar com o fornecedor")
        b = chunk(1, "com o fornecedor ainda hoje")
        out = lt.assemble([a, b])
        self.assertEqual(out["lines"][1]["text"], "ainda hoje")
        gap = lt.assemble([a, chunk(2, "com o fornecedor ainda hoje")])  # o pedaço 1 não chegou: não se pode afirmar que é emenda
        self.assertEqual(gap["lines"][1]["text"], "com o fornecedor ainda hoje")

    def test_nao_apara_depois_de_pedaco_pendente(self):
        out = lt.assemble([chunk(0, "preciso renegociar com o fornecedor"), chunk(1, status="uploaded"), chunk(2, "com o fornecedor ainda hoje")])
        self.assertEqual(out["lines"][2]["text"], "com o fornecedor ainda hoje")

    def test_silencio_alucinado_some_do_texto(self):
        out = lt.assemble([chunk(0, "Obrigado."), chunk(1, "fim")])
        self.assertEqual(out["text"], "fim")

    def test_um_pedaco_ainda_nao_transcrito_nao_vaza_texto(self):
        out = lt.assemble([chunk(0, "rascunho", status="transcribing")])
        self.assertEqual(out["lines"][0]["text"], "")


class Base63(Base):
    def setUp(self):
        super().setUp()
        self.audio = {}
        self.script = {}       # número do pedaço -> texto (ou exceção)
        self.calls = []        # (número, contexto)
        self.download_fail = set()
        self.has_key = True

        def fake_download(path, max_bytes=0):
            if path in self.download_fail:
                raise RuntimeError("falha de download com segredo interno")
            return self.audio.get(path, b"audio")

        def fake_transcribe(data, ext, context=""):
            if not self.has_key:
                raise lt.Unavailable("A transcrição não está configurada neste ambiente.")
            seq = int(self._current)
            self.calls.append((seq, context))
            out = self.script.get(seq, f"texto do pedaço {seq}")
            if isinstance(out, Exception):
                raise out
            return out
        p = [mock.patch.object(storage_io, "download", fake_download), mock.patch.object(lt, "transcribe_audio", fake_transcribe)]
        orig = lt.process_chunk

        def tracking(session_id, ch, now, restore_attempts=0):
            self._current = ch["seq"]
            return orig(session_id, ch, now, restore_attempts)
        p.append(mock.patch.object(lt, "process_chunk", tracking))
        for x in p:
            x.start()
            self.addCleanup(x.stop)
        self.sid = self.start()

    def run_t(self, tok="tok-a", **body):
        return self.client.post(f"/api/live/{self.sid}/transcribe", headers=self.h(tok), json=body)

    def transcript(self, tok="tok-a", sid=None):
        return self.client.get(f"/api/live/{sid or self.sid}/transcript", headers=self.h(tok))

    def row(self, seq):
        return [c for c in self.rows("live_chunks") if c["session_id"] == self.sid and c["seq"] == seq][0]


class Transcricao(Base63):
    def test_exige_login(self):
        self.assertEqual(self.client.post(f"/api/live/{self.sid}/transcribe").status_code, 401)
        self.assertEqual(self.client.get(f"/api/live/{self.sid}/transcript").status_code, 401)

    def test_privacidade(self):
        self.chunk(self.sid, 0)
        for tok in ("tok-b", "tok-c", "tok-d", "tok-e"):
            self.assertEqual(self.run_t(tok).status_code, 404, tok)
            self.assertEqual(self.transcript(tok).status_code, 404, tok)
        self.assertEqual(self.calls, [])

    def test_transcreve_em_ordem_e_em_lotes_de_dois(self):
        for seq in range(5):
            self.chunk(self.sid, seq)
        r = self.run_t().json()
        self.assertEqual((r["transcribed"], r["failed"], r["remaining"]), ([0, 1], [], 3))
        self.assertEqual(self.run_t().json()["transcribed"], [2, 3])
        last = self.run_t().json()
        self.assertEqual((last["transcribed"], last["remaining"]), ([4], 0))
        self.assertEqual([c["status"] for c in sorted(self.rows("live_chunks"), key=lambda c: c["seq"])], ["transcribed"] * 5)

    def test_grava_texto_hora_e_limpa_a_reserva(self):
        self.chunk(self.sid, 0)
        self.run_t()
        c = self.row(0)
        self.assertEqual((c["status"], c["text"], c["transcribed_at"], c["claimed_at"], c["error"], c["attempts"]),
                         ("transcribed", "texto do pedaço 0", CLOCK.isoformat(), None, None, 1))

    def test_o_pedaco_anterior_vai_como_contexto(self):
        for seq in range(2):
            self.chunk(self.sid, seq)
        self.run_t()
        self.assertEqual(self.calls, [(0, ""), (1, "texto do pedaço 0")])

    def test_chamar_de_novo_nao_transcreve_outra_vez(self):
        self.chunk(self.sid, 0)
        self.run_t()
        again = self.run_t().json()
        self.assertEqual((again["transcribed"], again["remaining"]), ([], 0))
        self.assertEqual(len(self.calls), 1)

    def test_pedacos_chegam_fora_de_ordem_mas_saem_na_ordem(self):
        for seq in (2, 0, 1):
            self.chunk(self.sid, seq)
        self.run_t()
        self.run_t()
        data = self.transcript().json()
        self.assertEqual([l["seq"] for l in data["lines"]], [0, 1, 2])
        self.assertEqual(data["text"], "texto do pedaço 0 texto do pedaço 1 texto do pedaço 2")
        self.assertEqual([c[0] for c in self.calls], [0, 1, 2])  # processados na ordem do número, não da chegada

    def test_registro_repetido_do_mesmo_pedaco_nao_duplica_a_transcricao(self):
        self.chunk(self.sid, 0)
        self.assertEqual(self.register(self.sid, 0).json()["duplicate"], True)
        self.run_t()
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(len(self.rows("live_chunks")), 1)

    def test_reserva_fresca_de_outra_chamada_nao_e_tocada(self):
        self.chunk(self.sid, 0)
        c = self.row(0)
        c.update(status="transcribing", claimed_at=CLOCK.isoformat(), attempts=1)
        r = self.run_t().json()
        self.assertEqual((r["transcribed"], self.calls), ([], []))
        self.assertEqual(self.row(0)["status"], "transcribing")

    def test_reserva_abandonada_e_retomada_depois_de_dois_minutos(self):
        self.chunk(self.sid, 0)
        self.row(0).update(status="transcribing", claimed_at=(CLOCK - timedelta(minutes=3)).isoformat(), attempts=1)
        r = self.run_t().json()
        self.assertEqual(r["transcribed"], [0])
        self.assertEqual(self.row(0)["attempts"], 2)

    def test_perder_a_corrida_pela_reserva_pula_o_pedaco(self):
        self.chunk(self.sid, 0)
        with mock.patch.object(lt, "_claim", return_value=False):
            r = self.run_t().json()
        self.assertEqual((r["transcribed"], r["skipped"], self.calls), ([], 1, []))
        self.assertEqual(self.row(0)["status"], "uploaded")

    def test_a_reserva_e_condicional_no_estado_lido(self):
        """O UPDATE da reserva só vale se o pedaço ainda está no estado lido (duas chamadas nunca pegam o mesmo)."""
        self.chunk(self.sid, 0)
        c = dict(self.row(0))
        self.row(0)["status"] = "transcribing"  # outra chamada reservou entre a leitura e a escrita
        self.assertFalse(lt._claim(c, CLOCK, False))
        self.row(0)["status"] = "uploaded"
        self.assertTrue(lt._claim(c, CLOCK, False))
        self.assertFalse(lt._claim(c, CLOCK, False))  # a segunda já não vence

    def test_silencio_alucinado_vira_texto_vazio_mas_o_pedaco_conta_como_transcrito(self):
        self.script[0] = "Obrigado por assistir!"
        self.chunk(self.sid, 0)
        self.run_t()
        self.assertEqual((self.row(0)["status"], self.row(0)["text"]), ("transcribed", ""))

    def test_audio_apagado_nao_transcreve(self):
        self.chunk(self.sid, 0)
        self.rows("live_sessions")[0]["audio_deleted_at"] = CLOCK.isoformat()
        self.assertEqual(self.run_t().status_code, 409)
        self.assertEqual(self.calls, [])


class Falhas63(Base63):
    def test_falha_do_modelo_marca_falho_e_segue_com_os_outros(self):
        self.script[0] = RuntimeError("erro com chave sk-secreta")
        for seq in range(2):
            self.chunk(self.sid, seq)
        r = self.run_t()
        self.assertEqual(r.status_code, 200)
        self.assertEqual((r.json()["transcribed"], r.json()["failed"]), ([1], [0]))
        self.assertNotIn("secret", r.text)
        c = self.row(0)
        self.assertEqual((c["status"], c["attempts"], c["error"], c["claimed_at"]), ("failed", 1, "transcription_failed", None))
        self.assertNotIn("secreta", str(self.rows("live_chunks")))  # o motivo detalhado não vai para o banco

    def test_falha_de_download(self):
        self.chunk(self.sid, 0)
        self.download_fail.add(self.row(0)["storage_path"])
        r = self.run_t().json()
        self.assertEqual(r["failed"], [0])
        self.assertNotIn("segredo", str(r))

    def test_ate_tres_tentativas_automaticas(self):
        self.script[0] = RuntimeError("x")
        self.chunk(self.sid, 0)
        for expected in (1, 2, 3):
            self.run_t()
            self.assertEqual(self.row(0)["attempts"], expected)
        self.run_t()  # a quarta nem é tentada
        self.assertEqual((self.row(0)["attempts"], len(self.calls)), (3, 3))
        self.assertEqual(self.transcript().json()["counts"]["failed"], 1)

    def test_nova_tentativa_pedida_pela_pessoa_zera_o_contador(self):
        self.script[0] = RuntimeError("x")
        self.chunk(self.sid, 0)
        for _ in range(3):
            self.run_t()
        self.script[0] = "agora foi"
        r = self.run_t(retry_failed=True).json()
        self.assertEqual(r["transcribed"], [0])
        self.assertEqual((self.row(0)["status"], self.row(0)["attempts"], self.row(0)["text"]), ("transcribed", 1, "agora foi"))

    def test_sem_chave_da_ia_devolve_o_pedaco_a_fila_sem_gastar_tentativa(self):
        self.chunk(self.sid, 0)
        self.has_key = False
        r = self.run_t()
        self.assertEqual(r.status_code, 503)
        self.assertIn("não está configurada", r.json()["detail"])
        self.assertEqual((self.row(0)["status"], self.row(0)["attempts"], self.row(0)["claimed_at"]), ("uploaded", 0, None))
        self.has_key = True
        self.assertEqual(self.run_t().json()["transcribed"], [0])

    def test_falha_do_banco_vira_502_sem_detalhes(self):
        self.chunk(self.sid, 0)
        self.fake.fail.add(("PATCH", "live_chunks"))
        r = self.run_t()
        self.assertIn(r.status_code, (502, 200))
        self.assertNotIn("boom", r.text)


class Limites63(Base63):
    def done(self, seq, minutes_ago=1, user=UA, sid=None, dur=30000):
        self.rows("live_chunks").append({"id": f"d{seq}{minutes_ago}{user[-1]}", "session_id": sid or self.sid, "seq": 100 + seq, "owner_id": user, "status": "transcribed",
                                         "text": "x", "duration_ms": dur, "attempts": 1, "transcribed_at": (CLOCK - timedelta(minutes=minutes_ago)).isoformat(),
                                         "storage_path": "p", "claimed_at": None, "error": None, "segments": []})

    def test_passou_do_limite_por_hora_barra_sem_perder_o_audio(self):
        self.chunk(self.sid, 0)
        for i in range(2):
            self.done(i)  # 1 minuto transcrito na última hora
        with mock.patch.dict(os.environ, {"AURA_MAX_LIVE_MINUTES_PER_HOUR": "1"}):
            r = self.run_t()
        self.assertEqual(r.status_code, 429)
        self.assertIn("áudio continua guardado", r.json()["detail"])
        self.assertEqual((self.row(0)["status"], self.calls), ("uploaded", []))

    def test_so_conta_a_ultima_hora(self):
        self.chunk(self.sid, 0)
        for i in range(10):
            self.done(i, minutes_ago=90)
        with mock.patch.dict(os.environ, {"AURA_MAX_LIVE_MINUTES_PER_HOUR": "1"}):
            self.assertEqual(self.run_t().status_code, 200)

    def test_o_limite_e_por_pessoa(self):
        self.chunk(self.sid, 0)
        for i in range(4):
            self.done(i, user=UB)
        with mock.patch.dict(os.environ, {"AURA_MAX_LIVE_MINUTES_PER_HOUR": "1"}):
            self.assertEqual(self.run_t().status_code, 200)

    def test_falha_ao_verificar_o_limite_bloqueia(self):
        self.chunk(self.sid, 0)
        self.fake.fail.add(("GET", "live_chunks"))
        self.assertEqual(self.run_t().status_code, 503)
        self.assertEqual(self.calls, [])


class Leitura(Base63):
    def test_estado_contagens_uso_e_custo_estimado(self):
        for seq in range(3):
            self.chunk(self.sid, seq)
        self.run_t()  # 0 e 1
        d = self.transcript().json()
        self.assertEqual(d["counts"], {"chunks": 3, "transcribed": 2, "pending": 1, "failed": 0})
        self.assertEqual(d["usage"]["minutes_transcribed"], 1.0)
        self.assertEqual((d["usage"]["estimated_cost_usd"], d["usage"]["cost_is_estimate"]), (0.006, True))
        self.assertEqual(d["usage"]["hourly_limit_minutes"], 90)
        self.assertEqual(d["usage"]["minutes_last_hour"], 1.0)
        self.assertEqual(d["session_status"], "recording")

    def test_texto_cresce_e_a_emenda_e_aparada(self):
        self.script[0] = "preciso renegociar com o fornecedor"
        self.script[1] = "com o fornecedor ainda hoje"
        for seq in range(2):
            self.chunk(self.sid, seq)
        self.run_t()
        d = self.transcript().json()
        self.assertEqual(d["text"], "preciso renegociar com o fornecedor ainda hoje")
        self.assertEqual([l["text"] for l in d["lines"]], ["preciso renegociar com o fornecedor", "ainda hoje"])

    def test_pedaco_em_transcricao_conta_como_pendente(self):
        self.chunk(self.sid, 0)
        self.row(0).update(status="transcribing", claimed_at=CLOCK.isoformat(), attempts=1)
        d = self.transcript().json()
        self.assertEqual((d["counts"]["pending"], d["counts"]["transcribed"], d["lines"][0]["text"]), (1, 0, ""))

    def test_lacunas_aparecem(self):
        for seq in (0, 3):
            self.chunk(self.sid, seq)
        self.assertEqual(self.transcript().json()["missing"], [1, 2])

    def test_sessao_vazia(self):
        d = self.transcript().json()
        self.assertEqual((d["lines"], d["text"], d["counts"]["chunks"]), ([], "", 0))

    def test_a_resposta_nao_expoe_caminho_nem_dono(self):
        self.chunk(self.sid, 0)
        self.run_t()
        text = self.transcript().text
        self.assertNotIn("storage_path", text)
        self.assertNotIn("owner_id", text)
        self.assertNotIn("users/", text)

    def test_continua_funcionando_depois_de_encerrar(self):
        self.chunk(self.sid, 0)
        self.client.post(f"/api/live/{self.sid}/finish", headers=self.h())
        self.assertEqual(self.run_t().json()["transcribed"], [0])
        self.assertEqual(self.transcript().json()["session_status"], "processing")


class Servico(unittest.TestCase):
    def test_sem_chave_da_openai_levanta_indisponivel(self):
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
            with self.assertRaises(lt.Unavailable):
                lt.transcribe_audio(b"x", ".webm")

    def test_o_pedaco_so_e_pego_por_quem_esta_na_fila(self):
        now = CLOCK
        chunks = [{"seq": 0, "status": "transcribed"}, {"seq": 1, "status": "uploaded"}, {"seq": 2, "status": "failed", "attempts": 3},
                  {"seq": 3, "status": "failed", "attempts": 1}, {"seq": 4, "status": "transcribing", "claimed_at": now.isoformat()},
                  {"seq": 5, "status": "transcribing", "claimed_at": (now - timedelta(minutes=5)).isoformat()}]
        self.assertEqual([c["seq"] for c in lt.pick_pending(chunks, now, False)], [1, 3, 5])
        self.assertEqual([c["seq"] for c in lt.pick_pending(chunks, now, True)], [1, 2, 3, 5])


if __name__ == "__main__":
    unittest.main()
