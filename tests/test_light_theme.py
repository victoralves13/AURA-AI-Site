"""O CSS do tema claro (a11y-light.css) é GERADO a partir dos demais CSS/JS: este teste falha se alguém mudou as cores do tema escuro
sem rodar `python tests/tools/gen_light_theme.py` de novo (o tema claro ficaria desatualizado e com texto ilegível)."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIGHT = ROOT / "web" / "styles" / "theme" / "a11y-light.css"


class TemaClaro(unittest.TestCase):
    def test_arquivo_gerado_esta_em_dia(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "a11y-light.css"
            subprocess.run([sys.executable, str(ROOT / "tests" / "tools" / "gen_light_theme.py"), str(out)], check=True, capture_output=True,
                           env={**__import__("os").environ, "PYTHONUTF8": "1"})
            fresh = out.read_text(encoding="utf8").replace("\r\n", "\n")
        committed = LIGHT.read_text(encoding="utf8").replace("\r\n", "\n")
        self.assertEqual(fresh, committed, "Rode: python tests/tools/gen_light_theme.py")

    def test_regras_do_tema_claro_so_valem_com_a_classe(self):
        for line in LIGHT.read_text(encoding="utf8").splitlines():
            if line and not line.startswith(("/*", "   ")):
                self.assertTrue(line.startswith("body.aura-light"), line[:80])

    def test_nenhum_texto_claro_sobra_sobre_fundo_claro_nas_regras_geradas(self):
        import re
        for color in re.findall(r"(?<![-\w])color:(#[0-9a-f]{6})!important", LIGHT.read_text(encoding="utf8")):
            h = color.lstrip("#")
            r, g, b = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
            f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
            lum = 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)
            self.assertGreaterEqual(1.05 / (lum + 0.05), 4.5, color)


if __name__ == "__main__":
    unittest.main()
