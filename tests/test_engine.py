"""Testes do motor de análise: contrato dito/inferido, pontuação e salvamento (sem rede e sem OpenAI)."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

from pydantic import ValidationError  # noqa: E402

from aura import app as index

from aura.features.meetings import router as meetings_mod

from aura.features.analysis import router as analysis_mod  # noqa: E402
from aura.features.analysis import engine as eng  # noqa: E402
from aura.core import verification as v  # noqa: E402
from aura.features.analysis.engine import (ActionItem, AURAAnalysis, AURAAnalysisV1, DecisionItem, EvidenceItem, FinancialItem,  # noqa: E402
                           InsightItem, NextAction)

T = (
    "[00:05] [A] Bom dia, a gente precisa conversar sobre o prazo de implantação.\n"
    "[00:12] [B] O prazo de implantação está apertado, se não começarmos até o dia 15 vamos perder a janela.\n"
    "[00:30] [A] Entendi. O orçamento previsto é de R$ 2 milhões para o próximo ano.\n"
    "[00:41] [B] Combinado: eu envio a proposta revisada na terça-feira.\n"
)
Q1 = "O prazo de implantação está apertado, se não começarmos até o dia 15 vamos perder a janela."
Q2 = "O orçamento previsto é de R$ 2 milhões para o próximo ano."
Q3 = "eu envio a proposta revisada na terça-feira"
FAKE = "O diretor ameaçou cancelar o contrato se o preço não caísse trinta por cento"
PARAPHRASE = "O prazo de implantação está apertado, se não começarmos até o dia 15 nós vamos perder a janela"

BASE = dict(summary="Resumo da reunião.", main_topics=["prazo"], objections=[], participants=[], intelligence_type="comercial", sentiment="Neutro")


def ev(quote, strength="alta", basis="dito", **kw):
    return EvidenceItem(description="achado", evidence=quote, evidence_strength=strength, basis=basis, **kw)


def v2(**kw):
    data = dict(BASE, decisions=[], pending_actions=[], risks=[], opportunities=[], important_signals=[], insights=[],
                financial_data=[], next_actions=[])
    data.update(kw)
    return AURAAnalysis(**data)


def fields(analysis, transcript=T):
    return eng.build_product_fields(analysis, transcript)


class Pontuacao(unittest.TestCase):
    def test_evidencia_conferida_pesa_cheia(self):
        f = fields(v2(risks=[ev(Q1), ev(Q2)]))
        self.assertEqual((f["risk_score"], f["risk"], f["priority"]), (68, "Alto", "Crítica"))
        self.assertEqual(f["risk_signals"], ["achado", "achado"])

    def test_evidencia_inventada_nao_gera_risco(self):
        f = fields(v2(risks=[ev(FAKE), ev(FAKE + " e mais")], summary="Só o resumo."))
        self.assertEqual((f["risk_score"], f["risk"], f["priority"]), (0, "Baixo", "Baixa"))
        self.assertEqual(f["risk_signals"], [])
        self.assertEqual(f["why_it_matters"], "Só o resumo.")
        self.assertEqual(f["evidence_summary"]["nao_localizada"], 2)  # continua visível, marcado
        self.assertEqual({e["evidence_check"] for e in f["evidence"]}, {v.NAO_LOCALIZADA})

    def test_mistura_conta_so_o_que_existe(self):
        f = fields(v2(risks=[ev(Q1), ev(FAKE)]))
        self.assertEqual((f["risk_score"], f["risk"]), (34, "Médio"))
        self.assertEqual(len(f["risk_signals"]), 1)

    def test_inferencia_vale_metade_e_parcial_vale_metade(self):
        self.assertEqual(fields(v2(risks=[ev(Q1, basis="inferido", inference_rationale="porque sim")]))["risk_score"], 17)
        self.assertEqual(fields(v2(risks=[ev(Q1, basis="inferido"), ev(Q2, basis="inferido")]))["risk_score"], 34)
        self.assertEqual(fields(v2(risks=[ev(PARAPHRASE)]))["risk_score"], 17)

    def test_teto_de_95_e_pesos_por_forca(self):
        self.assertEqual(fields(v2(risks=[ev(Q1)] * 5))["risk_score"], 95)
        self.assertEqual(fields(v2(risks=[ev(Q1, "média")]))["risk_score"], 22)
        self.assertEqual(fields(v2(risks=[ev(Q1, "baixa")]))["risk_score"], 10)

    def test_oportunidade_usa_a_mesma_regra(self):
        f = fields(v2(opportunities=[ev(Q2), ev(FAKE)]))
        self.assertEqual((f["opportunity_score"], f["opportunity"]), (34, "Detectada"))
        self.assertEqual(len(f["opportunity_signals"]), 1)

    def test_sem_transcricao_mantem_o_comportamento_anterior(self):
        f = eng.build_product_fields(v2(risks=[ev(FAKE), ev(Q1)]))
        self.assertEqual(f["risk_score"], 68)
        self.assertEqual({e["evidence_check"] for e in f["evidence"]}, {v.NAO_VERIFICADA})


class Contrato(unittest.TestCase):
    def test_insight_carrega_base_confianca_e_conferencia(self):
        ins = InsightItem(description="d", evidence=Q1, evidence_strength="alta", category="risco", impact_score=80,
                          basis="inferido", inference_rationale="prazo curto", confidence="baixa", confidence_reason="uma só fala",
                          timestamp="00:30", speaker="A")
        out = fields(v2(insights=[ins]))["insights"][0]
        self.assertEqual((out["basis"], out["confidence"], out["inference_rationale"]), ("inferido", "baixa", "prazo curto"))
        self.assertEqual((out["evidence_check"], out["timestamp"], out["speaker"]), (v.LOCALIZADA, "00:12", "B"))
        self.assertEqual(sorted(out["corrections"]), ["speaker_corrigido", "timestamp_corrigido"])
        self.assertEqual(out["type"], "risco")

    def test_decisoes_e_acoes_com_evidencia(self):
        f = fields(v2(
            decisions=[DecisionItem(description="Enviar a proposta", evidence=Q3), DecisionItem(description="Cancelar tudo", evidence=FAKE)],
            pending_actions=[ActionItem(description="Enviar proposta revisada", evidence=Q3, owner="B", deadline="terça-feira"),
                             ActionItem(description="Ação inventada", evidence=FAKE, owner="Fernanda", deadline="31/12")]))
        self.assertEqual(f["decisions"], ["Enviar a proposta"])  # a não localizada sai da lista exibida...
        self.assertEqual([d["evidence_check"] for d in f["decisions_detail"]], [v.LOCALIZADA, v.NAO_LOCALIZADA])  # ...mas segue salva, marcada
        self.assertEqual(f["pending_actions"], ["Enviar proposta revisada"])
        a0, a1 = f["actions_detail"]
        self.assertEqual((a0["owner"], a0["deadline"], a0["timestamp"], a0["speaker"]), ("B", "terça-feira", "00:41", "B"))
        self.assertEqual((a1["owner"], a1["deadline"]), (None, None))

    def test_proximo_movimento_so_com_evidencia(self):
        good = NextAction(action="Enviar proposta revisada", evidence=Q3, evidence_strength="alta", owner="B", deadline="terça-feira")
        fake = NextAction(action="Fechar com o diretor", evidence=FAKE, evidence_strength="alta", owner="Fernanda")
        f = fields(v2(next_actions=[fake, good]))
        self.assertEqual((f["next_move"], f["owner"], f["deadline"]), ("Enviar proposta revisada", "B", "terça-feira"))
        f = fields(v2(next_actions=[fake]))
        self.assertTrue(f["next_move"].startswith("Definir o próximo movimento"))
        self.assertEqual((f["owner"], f["deadline"]), ("Não identificado", "Não identificado"))

    def test_valores_financeiros_sao_conferidos(self):
        mk = lambda amount, quote: FinancialItem(amount=amount, financial_type="orçamento", nature="mencionado", description="orçamento",
                                                  evidence=quote, evidence_strength="alta")
        f = fields(v2(financial_data=[mk(2_000_000, Q2), mk(5_000_000, Q2), mk(1_000, FAKE)]))["financial_data"]
        self.assertEqual([(x["evidence_check"], x["amount_check"]) for x in f],
                         [(v.LOCALIZADA, "confere"), (v.LOCALIZADA, "nao_confere"), (v.NAO_LOCALIZADA, "nao_verificavel")])

    def test_resumo_das_evidencias(self):
        s = fields(v2(risks=[ev(Q1), ev(FAKE)], opportunities=[ev(PARAPHRASE, basis="inferido")]))["evidence_summary"]
        self.assertEqual((s["total"], s["localizada"], s["parcial"], s["nao_localizada"], s["inferido"]), (3, 1, 1, 1, 1))
        # horário e interlocutor foram derivados da transcrição no achado localizado e no parcial; o inventado não tem o que corrigir
        self.assertEqual(s["corrigidos"], 2)

    def test_contrato_v1_nao_finge_ter_classificado(self):
        v1 = AURAAnalysisV1(**dict(BASE, decisions=["Enviar proposta"], pending_actions=["Revisar contrato"],
                                   risks=[EvidenceItem(description="d", evidence=Q1, evidence_strength="alta")],
                                   opportunities=[], important_signals=[], insights=[
                                       InsightItem(description="i", evidence=Q1, evidence_strength="alta", category="sinal")],
                                   financial_data=[], next_actions=[]))
        f = fields(v1)
        self.assertEqual(f["analysis_version"], 1)
        self.assertIsNone(f["insights"][0]["basis"])
        self.assertIsNone(f["insights"][0]["confidence"])
        self.assertEqual((f["decisions"], f["pending_actions"]), (["Enviar proposta"], ["Revisar contrato"]))
        self.assertEqual(f["decisions_detail"][0]["evidence_check"], v.NAO_VERIFICADA)
        self.assertEqual(f["risk_score"], 34)  # a evidência do risco foi conferida mesmo no contrato v1
        self.assertEqual(fields(v2())["analysis_version"], 2)

    def test_prompts(self):
        self.assertNotIn("inferido", eng.SYSTEM_PROMPT_V1)
        self.assertTrue(eng.SYSTEM_PROMPT.startswith(eng.SYSTEM_PROMPT_V1))
        for rule in ("LITERAL", "inference_rationale", "speaker", "owner"):
            self.assertIn(rule, eng.SYSTEM_PROMPT)


class FallbackDaIA(unittest.TestCase):
    def _client(self, *effects):
        calls = []

        def parse(**kwargs):
            calls.append(kwargs)
            effect = effects[len(calls) - 1]
            if isinstance(effect, Exception):
                raise effect
            return SimpleNamespace(output_parsed=effect)
        return SimpleNamespace(responses=SimpleNamespace(parse=parse)), calls

    def _invalid(self):
        try:
            AURAAnalysis.model_validate({})
        except ValidationError as exc:
            return exc

    def test_resposta_invalida_tenta_uma_vez_o_contrato_v1(self):
        v1 = AURAAnalysisV1(**dict(BASE, decisions=[], pending_actions=[], risks=[], opportunities=[], important_signals=[],
                                   insights=[], financial_data=[], next_actions=[]))
        client, calls = self._client(self._invalid(), v1)
        with mock.patch.object(eng, "_client", return_value=client):
            out = eng.analyze_transcript("uma transcrição qualquer", "Comercial")
        self.assertIs(out, v1)
        self.assertEqual([c["text_format"] for c in calls], [AURAAnalysis, AURAAnalysisV1])
        self.assertEqual([c["input"][0]["content"] for c in calls], [eng.SYSTEM_PROMPT, eng.SYSTEM_PROMPT_V1])
        self.assertEqual(eng.analysis_version(out), 1)
        self.assertIn("uma transcrição qualquer", calls[0]["input"][1]["content"])
        self.assertIn("\n\nTRANSCRIÇÃO:\n", calls[0]["input"][1]["content"])

    def test_sem_analise_estruturada_tambem_tenta_o_v1(self):
        v1 = AURAAnalysisV1(**dict(BASE, decisions=[], pending_actions=[], risks=[], opportunities=[], important_signals=[],
                                   insights=[], financial_data=[], next_actions=[]))
        client, calls = self._client(None, v1)
        with mock.patch.object(eng, "_client", return_value=client):
            self.assertIs(eng.analyze_transcript("uma transcrição qualquer"), v1)
        self.assertEqual(len(calls), 2)

    def test_falha_de_api_nao_dispara_nova_tentativa(self):
        for error in (RuntimeError("Créditos da OpenAI API esgotados."), RuntimeError("OPENAI_API_KEY não configurada no ambiente."),
                      ConnectionError("rede")):
            client, calls = self._client(error, AssertionError("não devia chamar de novo"))
            with mock.patch.object(eng, "_client", return_value=client):
                with self.assertRaises((RuntimeError, ConnectionError)):
                    eng.analyze_transcript("uma transcrição qualquer")
            self.assertEqual(len(calls), 1, error)

    def test_v2_valido_nao_chama_o_v1(self):
        client, calls = self._client(v2())
        with mock.patch.object(eng, "_client", return_value=client):
            self.assertEqual(eng.analysis_version(eng.analyze_transcript("uma transcrição qualquer")), 2)
        self.assertEqual(len(calls), 1)


class Salvamento(unittest.TestCase):
    def build(self, requests):
        analysis = v2(risks=[ev(Q1), ev(FAKE)], decisions=[DecisionItem(description="Enviar a proposta", evidence=Q3)])

        def fake_request(method, path, payload=None, user=None):
            requests.append(dict(payload or {}))
            outcome = self.script.pop(0) if self.script else None
            if isinstance(outcome, Exception):
                raise outcome
            return [{**requests[-1], "id": "m-1", "created_at": "2026-10-14T00:00:00Z"}]

        with mock.patch("aura.features.analysis.engine.analyze_transcript", lambda text, context="Outro": analysis), \
             mock.patch.object(meetings_mod, "_supabase_request", fake_request):
            return analysis_mod._build_result(T, "", "reuniao.mp3", "audio", "Comercial", analysis_transcript=T)

    def test_grava_contrato_v2_completo_e_sem_confianca_falsa(self):
        self.script, reqs = [], []
        result = self.build(reqs)
        p = reqs[0]
        self.assertEqual(p["analysis_version"], 2)
        self.assertEqual(p["evidence_summary"]["nao_localizada"], 1)
        self.assertEqual(p["decisions_detail"][0]["evidence_check"], v.LOCALIZADA)
        self.assertEqual(p["decisions"], ["Enviar a proposta"])
        self.assertIsNone(p["sentiment_confidence"])  # nada de "0%" fingindo medida
        self.assertEqual(result["id"], "m-1")
        self.assertEqual(result["analysis_version"], 2)

    def test_banco_sem_as_colunas_novas_nao_perde_a_reuniao(self):
        self.script = [RuntimeError('Supabase error: HTTP 400: {"code":"PGRST204","message":"Could not find the \'analysis_version\' column"}')]
        reqs = []
        result = self.build(reqs)
        self.assertEqual(len(reqs), 2)
        self.assertTrue(all(k not in reqs[1] for k in meetings_mod.V2_COLUMNS))
        self.assertTrue(result["persisted"])
        self.assertEqual(result["meeting"]["analysis_version"], 2)  # a resposta ainda traz tudo
        self.assertEqual(result["meeting"]["evidence_summary"]["total"], 3)  # 2 riscos + 1 decisão com evidência

    def test_combina_com_o_fallback_antigo_de_insights(self):
        self.script = [RuntimeError("Supabase error: HTTP 400: PGRST204 analysis_version"),
                       RuntimeError("Supabase error: HTTP 400: PGRST204 could not find insights column")]
        reqs = []
        result = self.build(reqs)
        self.assertEqual(len(reqs), 3)
        self.assertNotIn("insights", reqs[2])
        self.assertTrue(result["persisted"])

    def test_outros_erros_nao_sao_engolidos(self):
        self.script = [RuntimeError("Supabase error: HTTP 500: boom")]
        with self.assertRaises(RuntimeError):
            self.build([])

    def test_post_direto_so_envia_colunas_presentes(self):
        sent = []
        with mock.patch.object(meetings_mod, "_supabase_request", lambda m, p, payload=None, user=None: sent.append(payload) or [dict(payload, id="x")]):
            meetings_mod._save_meeting({"transcript": "abcd", "insights": []})
        self.assertTrue(all(k not in sent[0] for k in meetings_mod.V2_COLUMNS))  # null violaria o NOT NULL


if __name__ == "__main__":
    unittest.main()
