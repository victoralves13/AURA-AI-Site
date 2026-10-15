"""Garante que os exemplos de avaliação continuam coerentes e que o relatório se comporta (sem IA real)."""
import sys
import unittest
from pathlib import Path
from unittest import mock

from tests import ROOT  # noqa: E402
from aura.features.analysis import engine as eng  # noqa: E402
sys.path.insert(0, str(ROOT / "scripts" / "eval"))
import run_eval  # noqa: E402


class Exemplos(unittest.TestCase):
    def test_todos_coerentes(self):
        fixtures = run_eval.load_fixtures()
        self.assertGreaterEqual(len(fixtures), 3)
        for fx in fixtures:
            self.assertEqual(run_eval.validate_fixture(fx), [], fx["name"])

    def test_exemplo_incoerente_e_detectado(self):
        problems = run_eval.validate_fixture({"transcript": "Ana: fechamos o contrato.", "must_find": ["orçamento"], "must_not": ["contrato"]})
        self.assertEqual(len(problems), 2)

    def test_relatorio_conta_inventado_e_esperado(self):
        fx = next(f for f in run_eval.load_fixtures() if f["name"] == "comercial_audio")
        analysis = eng.AURAAnalysis(
            summary="Reunião sobre prazo e orçamento, com risco de cancelamento.", main_topics=[], decisions=[], pending_actions=[],
            risks=[eng.EvidenceItem(description="prazo apertado", evidence="O prazo de implantação é o ponto que mais me preocupa.", evidence_strength="alta"),
                   eng.EvidenceItem(description="cliente vai sair", evidence="Vamos cancelar tudo amanhã.", evidence_strength="alta", basis="inferido")],
            opportunities=[], objections=[], important_signals=[], insights=[], financial_data=[], next_actions=[], participants=[],
            intelligence_type="comercial", sentiment="Neutro")
        with mock.patch.object(eng, "analyze_transcript", lambda text, context="Outro": analysis):
            r = run_eval.evaluate(fx)
        self.assertEqual((r["evidencias"], r["localizadas"], r["nao_localizadas"], r["inferidos"]), (2, 1, 1, 1))
        self.assertEqual(r["pct_conferidas"], 50.0)
        self.assertIn("cancelamento", r["afirmacoes_sem_base_na_transcricao"])
        self.assertEqual(r["fatos_esperados_encontrados"], "2/6")  # o resumo cita "prazo" e "orçamento"
        self.assertEqual(sorted(r["fatos_esperados_faltando"]), sorted(["piloto", "terça-feira", "quinta", "2 milhões"]))

    def test_sem_chave_o_script_nao_chama_a_ia(self):
        with mock.patch.dict("os.environ", {"OPENAI_API_KEY": ""}), mock.patch.object(eng, "analyze_transcript", side_effect=AssertionError("chamou a IA")):
            self.assertEqual(run_eval.main([]), 2)
        self.assertEqual(run_eval.main(["--dry"]), 0)


if __name__ == "__main__":
    unittest.main()
