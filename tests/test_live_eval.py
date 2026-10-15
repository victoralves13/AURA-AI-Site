"""O roteiro de avaliação ao vivo com a IA real (tests/eval/live_eval.py) precisa calcular certo com modelos falsos."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "eval"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))

import live_alerts as la  # noqa: E402
import live_eval as ev  # noqa: E402

PRAZO = "O prazo de entrega está apertado e preciso renegociar com o fornecedor"


class Avaliacao(unittest.TestCase):
    def pieces(self, n=3):
        return [(b"x", 30000) for _ in range(n)]

    def test_monta_texto_e_confere_alertas(self):
        texts = iter(["Bom dia a todos, vamos começar.", PRAZO, "com o fornecedor ainda hoje. Fechado."])
        batch = la.AlertBatch(alerts=[la.AlertItem(category="risco", statement="Prazo apertado.", quote=PRAZO),
                                      la.AlertItem(category="decisao", statement="Inventado.", quote="o cliente decidiu cancelar tudo hoje mesmo sem avisar")])
        seen = []
        res = ev.evaluate(self.pieces(), lambda d, e, ctx: (seen.append(ctx), next(texts))[1], lambda w: batch)
        self.assertEqual((res["chunks"], res["failed"], res["minutes"]), (3, 0, 1.5))
        self.assertEqual((len(res["alerts"]), res["alerts_proposed"], res["alerts_dropped"]), (1, 2, 1))
        self.assertEqual(res["alerts"][0]["timestamp"], "00:30")
        self.assertIn("ainda hoje. Fechado.", res["text"])
        self.assertEqual(res["text"].count("com o fornecedor"), 1)  # a emenda repetida foi aparada
        self.assertEqual(seen, ["", "Bom dia a todos, vamos começar.", PRAZO])  # o texto anterior vai como contexto
        self.assertEqual(res["estimated_cost_usd"], 0.009)

    def test_pedaco_que_falha_nao_derruba_a_avaliacao(self):
        def flaky(d, e, ctx):
            if not ctx:
                return "primeiro trecho da conversa"
            raise RuntimeError("falha")
        res = ev.evaluate(self.pieces(2), flaky, lambda w: la.AlertBatch(alerts=[]))
        self.assertEqual((res["failed"], res["minutes"]), (1, 0.5))

    def test_sem_texto_nao_chama_a_ia_de_alertas(self):
        called = []
        res = ev.evaluate(self.pieces(1), lambda d, e, c: "Obrigado.", lambda w: called.append(w))
        self.assertEqual((called, res["alerts"], res["text"]), ([], [], ""))

    def test_dry_nao_chama_a_ia(self):
        self.assertEqual(ev.main(["--dry"]), 0)

    def test_exige_arquivo_e_chave(self):
        self.assertEqual(ev.main([]), 2)
        self.assertEqual(ev.main(["nao-existe.mp3"]), 2)


if __name__ == "__main__":
    unittest.main()
