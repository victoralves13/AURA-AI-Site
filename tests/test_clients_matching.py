"""Testes da regra de correspondência de nomes de clientes (código puro)."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from aura.features.clients import router as c  # noqa: E402


def cl(name, cid=None, aliases=None):
    return {"id": cid or name, "name": name, "normalized_name": c.normalize_name(name), "aliases": aliases or []}


class Nomes(unittest.TestCase):
    def test_normalizacao(self):
        for raw, expected in [("Grupo Atlas Ltda.", "grupo atlas"), ("ACME S.A.", "acme"), ("Acme S/A", "acme"), ("Órbita Saúde", "orbita saude"),
                              ("  Nova   Tech  EIRELI ", "nova tech"), ("Atlas ME", "atlas"), ("Grupo  Atlas", "grupo atlas")]:
            self.assertEqual(c.normalize_name(raw), expected, raw)
        self.assertEqual(c.normalize_name("S.A."), "s a")  # só sufixo: não vira nome vazio

    def test_marcadores_nao_sao_nomes(self):
        for raw in ["", None, "  ", "Cliente não identificado", "CLIENTE NAO IDENTIFICADO", "Não informado", "N/A"]:
            self.assertTrue(c.is_placeholder(raw), raw)
        self.assertFalse(c.is_placeholder("Grupo Atlas"))


class Correspondencia(unittest.TestCase):
    base = [cl("Grupo Atlas"), cl("Órbita Saúde"), cl("Logi Sul", aliases=["LogiSul", "Logística Sul"])]

    def test_igual_ignora_acento_caixa_pontuacao_e_sufixo_societario(self):
        for raw in ["grupo atlas", "GRUPO ATLAS LTDA.", "Grupo  Atlás", "Orbita Saude S.A."]:
            m = c.match_client(raw, self.base)
            self.assertEqual((m["kind"], len(m["matches"])), ("exact", 1), raw)
        self.assertEqual(c.match_client("orbita saude", self.base)["matches"][0][0]["name"], "Órbita Saúde")

    def test_apelido_conta_como_igual(self):
        m = c.match_client("LOGISUL", self.base)
        self.assertEqual((m["kind"], m["matches"][0][0]["name"]), ("exact", "Logi Sul"))
        self.assertEqual(c.match_client("Logística Sul Ltda", self.base)["kind"], "exact")

    def test_apelido_repetido_em_dois_clientes_e_ambiguo(self):
        both = [cl("Atlas Norte", aliases=["Atlas"]), cl("Atlas Sul", aliases=["Atlas"])]
        m = c.match_client("Atlas", both)
        self.assertEqual((m["kind"], len(m["matches"])), ("exact", 2))

    def test_parecido_so_sugere(self):
        m = c.match_client("Atlas", self.base)
        self.assertEqual((m["kind"], m["matches"][0][0]["name"]), ("similar", "Grupo Atlas"))
        self.assertGreaterEqual(m["matches"][0][1], 0.9)
        self.assertEqual(c.match_client("Atlas Sul", self.base)["kind"], "similar")  # palavra em comum: sugere, nunca decide
        self.assertEqual(c.match_client("Grupo Atlsa", self.base)["matches"][0][0]["name"], "Grupo Atlas")  # erro de digitação

    def test_nomes_diferentes_nao_casam(self):
        for raw in ["Grupo Horizonte", "Nova Tech", "Seguro Mais", "Grupo", "Empresa", "Projeto Nexus"]:
            self.assertEqual(c.match_client(raw, self.base)["kind"], "none", raw)

    def test_palavras_genericas_nao_bastam(self):
        both = [cl("Grupo Atlas"), cl("Grupo Horizonte"), cl("Grupo Vale")]
        self.assertEqual(c.match_client("Grupo Delta", both)["kind"], "none")

    def test_marcador_e_vazio_nao_casam(self):
        for raw in ["Cliente não identificado", "", "   "]:
            self.assertEqual(c.match_client(raw, self.base), {"kind": "none", "matches": []})
        self.assertEqual(c.match_client("Grupo Atlas", [])["kind"], "none")

    def test_candidatos_ordenados_e_limitados(self):
        many = [cl("Atlas Sul"), cl("Grupo Atlas"), cl("Atlas Norte"), cl("Atlas Leste"), cl("Atlas")]
        m = c.match_client("Atlas Oeste", many)
        self.assertLessEqual(len(m["matches"]), c.MAX_CANDIDATES)
        scores = [s for _, s in m["matches"]]
        self.assertEqual(scores, sorted(scores, reverse=True))


if __name__ == "__main__":
    unittest.main()
