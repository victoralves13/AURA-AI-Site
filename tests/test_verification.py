"""Testes da conferência mecânica de evidências (código puro, sem rede nem IA)."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from aura.core import verification as v  # noqa: E402

AUDIO = (
    "[00:05] [A] Bom dia, a gente precisa conversar sobre o prazo de implantação.\n"
    "[00:12] [B] O prazo de implantação está apertado, se não começarmos até o dia 15 vamos perder a janela.\n"
    "[00:30] [A] Entendi. O orçamento previsto é de R$ 2 milhões para o próximo ano.\n"
    "[00:41] [B] Combinado: eu envio a proposta revisada na terça-feira.\n"
)
PASTED = (
    "Ana: Hoje precisamos decidir se avançamos com a expansão.\n"
    "Carlos: O resultado da primeira unidade foi positivo.\n"
    "Ana: Se o custo ficar dentro do orçamento, podemos incluir já nesta contratação.\n"
)
PLAIN = "O cliente disse que o prazo preocupa muito a equipe. Também mencionou o orçamento de 120 mil reais."
QUOTE = "O prazo de implantação está apertado, se não começarmos até o dia 15 vamos perder a janela."


def check(quote, text=AUDIO, **extra):
    return v.annotate_item({"evidence": quote, **extra}, v.Transcript(text))


class Localizacao(unittest.TestCase):
    def test_trecho_literal_deriva_horario_e_interlocutor(self):
        r = check(QUOTE)
        self.assertEqual((r["evidence_check"], r["timestamp"], r["speaker"]), (v.LOCALIZADA, "00:12", "B"))
        self.assertEqual(r["evidence_coverage"], 1.0)
        self.assertEqual(sorted(r["corrections"]), ["speaker_derivado", "timestamp_derivado"])

    def test_ignora_acento_caixa_pontuacao_e_aspas(self):
        for q in ["o prazo de implantacao esta apertado se nao comecarmos ate o dia 15 vamos perder a janela",
                  "“" + QUOTE + "”", "  " + QUOTE.upper() + "  "]:
            self.assertEqual(check(q)["evidence_check"], v.LOCALIZADA, q)

    def test_reticencias_omitem_partes_do_mesmo_trecho(self):
        r = check("O prazo de implantação está apertado … vamos perder a janela")
        self.assertEqual((r["evidence_check"], r["timestamp"]), (v.LOCALIZADA, "00:12"))

    def test_trechos_de_falas_diferentes_unidos_sao_parciais(self):
        r = check("O prazo de implantação está apertado ... Combinado eu envio a proposta revisada na terça-feira")
        self.assertEqual(r["evidence_check"], v.LOCALIZADA)  # ambos existem, cada um no seu lugar
        r = check("O prazo de implantação está apertado ... a empresa vai cancelar o contrato amanhã cedo")
        self.assertEqual(r["evidence_check"], v.PARCIAL)

    def test_parafrase_proxima_e_parcial_e_invencao_nao_e_localizada(self):
        r = check("O prazo de implantação está apertado, se não começarmos até o dia 15 nós vamos perder a janela")
        self.assertEqual(r["evidence_check"], v.PARCIAL)
        self.assertGreaterEqual(r["evidence_coverage"], v.PARTIAL_MIN_COVERAGE)
        self.assertEqual(r["timestamp"], "00:12")
        r = check("O diretor ameaçou cancelar o contrato se o preço não caísse trinta por cento")
        self.assertEqual((r["evidence_check"], r["timestamp"], r["speaker"]), (v.NAO_LOCALIZADA, None, None))

    def test_citacao_muito_curta_nunca_e_localizada(self):
        self.assertEqual(check("apertado")["evidence_check"], v.PARCIAL)
        self.assertEqual(check("palavra inexistente")["evidence_check"], v.NAO_LOCALIZADA)

    def test_evidencia_vazia_ou_sem_transcricao(self):
        self.assertEqual(v.annotate_item({"evidence": QUOTE}, None)["evidence_check"], v.NAO_VERIFICADA)
        self.assertEqual(v.annotate_item({"evidence": ""}, v.Transcript(AUDIO))["evidence_check"], v.NAO_VERIFICADA)
        self.assertEqual(v.Transcript("").locate("qualquer coisa de teste aqui")[0], v.NAO_LOCALIZADA)


class HorarioEInterlocutor(unittest.TestCase):
    def test_corrige_o_que_a_transcricao_contradiz(self):
        r = check(QUOTE, timestamp="00:30", speaker="A")
        self.assertEqual((r["timestamp"], r["speaker"]), ("00:12", "B"))
        self.assertEqual(sorted(r["corrections"]), ["speaker_corrigido", "timestamp_corrigido"])

    def test_mesmo_horario_em_formatos_diferentes_nao_e_correcao(self):
        r = check(QUOTE, timestamp="00:00:12", speaker="b")
        self.assertEqual(r["corrections"], [])

    def test_sem_marcacoes_na_transcricao_nada_e_aceito(self):
        r = check("O cliente disse que o prazo preocupa muito a equipe", PLAIN, timestamp="00:10", speaker="A")
        self.assertEqual((r["evidence_check"], r["timestamp"], r["speaker"]), (v.LOCALIZADA, None, None))
        self.assertEqual(sorted(r["corrections"]), ["speaker_removido", "timestamp_removido"])

    def test_nao_localizada_so_mantem_horario_que_existe_na_transcricao(self):
        inventada = "Uma frase que ninguém disse durante toda a reunião"
        self.assertEqual(check(inventada, timestamp="00:30")["timestamp"], "00:30")  # existe na transcrição
        self.assertIsNone(check(inventada, timestamp="09:99")["timestamp"])
        self.assertEqual(check(inventada, speaker="B")["speaker"], "B")
        self.assertIsNone(check(inventada, speaker="Diretor Fantasma")["speaker"])

    def test_transcricao_colada_com_nome_antes_dos_dois_pontos(self):
        r = check("O resultado da primeira unidade foi positivo.", PASTED)
        self.assertEqual((r["evidence_check"], r["speaker"], r["timestamp"]), (v.LOCALIZADA, "Carlos", None))

    def test_linha_de_continuacao_herda_horario_e_interlocutor(self):
        text = "[00:10] [A] Primeira frase importante aqui.\ncontinuação da mesma fala sem rótulo nenhum\n[00:20] [B] Outra pessoa fala."
        r = check("continuação da mesma fala sem rótulo nenhum", text)
        self.assertEqual((r["timestamp"], r["speaker"]), ("00:10", "A"))

    def test_prefixo_longo_nao_vira_interlocutor(self):
        text = "Resumo da reunião de ontem com a diretoria: o prazo preocupa.\nAna: ok."
        tr = v.Transcript(text)
        self.assertEqual([l.speaker for l in tr.lines], [None, "Ana"])

    def test_formatos_de_horario(self):
        self.assertEqual((v.to_seconds("01:02"), v.to_seconds("01:02:03"), v.to_seconds("x"), v.to_seconds(None)), (62, 3723, None, None))


class ResponsavelEPrazo(unittest.TestCase):
    def test_so_vale_o_que_foi_dito(self):
        ok = check("eu envio a proposta revisada na terça-feira", owner="B", deadline="terça-feira")
        self.assertEqual((ok["owner"], ok["deadline"]), ("B", "terça-feira"))
        bad = check("eu envio a proposta revisada na terça-feira", owner="Fernanda Souza", deadline="31 de dezembro")
        self.assertEqual((bad["owner"], bad["deadline"]), (None, None))
        self.assertEqual(sorted(bad["corrections"]).count("owner_removido"), 1)
        self.assertIn("deadline_removido", bad["corrections"])


class Valores(unittest.TestCase):
    def test_numeros_em_formato_brasileiro(self):
        c = v.number_candidates
        self.assertIn(2_000_000.0, c("R$ 2 milhões"))
        self.assertIn(120_000.0, c("cerca de 120 mil reais"))
        self.assertIn(1500.5, c("R$ 1.500,50"))
        self.assertIn(1_500_000.0, c("1,5 milhão"))
        self.assertIn(2_500_000.0, c("2.500.000"))
        self.assertEqual(c("dois milhões de reais"), set())

    def test_confere_nao_confere_e_nao_verificavel(self):
        self.assertEqual(v.amount_check(2_000_000, "O orçamento é de R$ 2 milhões"), "confere")
        self.assertEqual(v.amount_check(200_000, "O orçamento é de R$ 2 milhões"), "nao_confere")
        self.assertEqual(v.amount_check(2_000_000, "O orçamento é de dois milhões"), "nao_verificavel")
        self.assertEqual(v.amount_check(50_000, "economia de 50 mil por mês"), "confere")


if __name__ == "__main__":
    unittest.main()
