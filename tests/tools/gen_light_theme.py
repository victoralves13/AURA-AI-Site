"""Gera a11y-light.css: para cada regra dos CSS do app que define uma COR DE TEXTO clara (feita para fundo escuro), cria a regra
equivalente do tema claro (`body.aura-light <seletor>`) com a mesma matiz, escurecida até ter contraste suficiente sobre branco.

Uso:  python tests/tools/gen_light_theme.py          (reescreve web/styles/theme/a11y-light.css)
Também clareia fundos escuros sólidos/translúcidos e gradientes escuros (viram branco) e troca bordas claras por bordas escuras
translúcidas, para o tema claro ficar coerente: texto escuro sobre fundo claro.
"""
import colorsys
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "web"
OUTPUT = WEB / "styles" / "theme" / "a11y-light.css"
# Todo CSS do front-end (menos o próprio arquivo gerado) e os scripts que injetam CSS; a ordem é fixa para o resultado ser reproduzível.
SOURCES = sorted(p for p in WEB.rglob("*.css") if p.name != "a11y-light.css") + sorted(
    p for p in WEB.rglob("*.js") if "vendor" not in p.parts and p.name not in ("auth.js", "persistence.js", "dynamic-data.js", "cloud-bridge.js", "background.js", "app.js", "real-engine.js"))
TARGET = 5.4  # contraste mínimo desejado sobre branco (o fundo claro mais escuro do tema é #eef4f6)
DECL = re.compile(r"(?<![-\w])color\s*:\s*(#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b|rgba?\(\s*\d+\s*,\s*\d+\s*,\s*\d+\s*(?:,\s*[0-9.]+\s*)?\))")
RULE = re.compile(r"([^{}@]+)\{([^{}]*)\}")


def lum(rgb):
    f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = [f(v / 255) for v in rgb]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def ratio_on_white(rgb):
    return 1.05 / (lum(rgb) + 0.05)


def parse(hexv):
    h = hexv.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def darken(rgb):
    h, l, s = colorsys.rgb_to_hls(*[v / 255 for v in rgb])
    while l > 0.05:
        cand = tuple(round(v * 255) for v in colorsys.hls_to_rgb(h, l, s))
        if ratio_on_white(cand) >= TARGET:
            return "#%02x%02x%02x" % cand
        l -= 0.01
    return "#0c2630"


COLOR = re.compile(r"#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b|rgba?\(\s*\d+\s*,\s*\d+\s*,\s*\d+\s*(?:,\s*[0-9.]+\s*)?\)")
BG = re.compile(r"(?<![-\w])background(?:-color)?\s*:\s*([^;]+)")
BORDER = re.compile(r"(?<![-\w])(border(?:-[a-z]+)*)\s*:\s*([^;]+)")


def color_parts(token):
    token = token.strip()
    if token.startswith("#"):
        return parse(token), 1.0
    nums = [float(x) for x in re.findall(r"[0-9.]+", token)]
    return tuple(int(v) for v in nums[:3]), (nums[3] if len(nums) > 3 else 1.0)


def dark_background(value):
    """True se o fundo é escuro (todas as cores do valor) e relevante (alpha >= .5); sem imagens url()."""
    if "url(" in value or "var(" in value:
        return False
    colors = COLOR.findall(value)
    if not colors:
        return False
    solid = []
    for c in colors:
        rgb, alpha = color_parts(c)
        if alpha >= (0.5 if "gradient(" in value else 0.3):
            solid.append(rgb)
        elif "gradient(" not in value:
            return False  # película translúcida sobre outra coisa: não é "o fundo"
    return bool(solid) and all(lum(rgb) <= 0.08 for rgb in solid)  # em gradientes, os brilhos translúcidos são ignorados


def light_border(value):
    """Troca cores claras da borda por azul-petróleo translúcido (a borda do tema escuro some no branco)."""
    changed = False

    def sub(m):
        nonlocal changed
        rgb, alpha = color_parts(m.group(0))
        if lum(rgb) > 0.5:
            changed = True
            return "rgba(8,45,57,%.2f)" % min(0.3, max(0.12, alpha))
        return m.group(0)
    out = COLOR.sub(sub, value)
    return out if changed else None


PAIR = re.compile(r"^\s*(?:[a-z-]+\s*:[^;{}]+;?\s*)+$", re.I)
SELECTOR = re.compile(r"^[#.\w\[\]=\"'>+~:*,\s()^$|-]+$")


def is_css_rule(selector, body):
    """Filtro para ler CSS escrito dentro de arquivos .js (texto com chaves que não é CSS é descartado)."""
    return bool(selector) and bool(PAIR.match(body)) and bool(SELECTOR.match(selector)) and "function" not in selector and "=>" not in selector


def main():
    out, seen = [], set()
    for path in SOURCES:
        text = re.sub(r"/\*.*?\*/", "", path.read_text(encoding="utf8"), flags=re.S)
        for sel, body in RULE.findall(text):
            sel = " ".join(sel.split())
            if not is_css_rule(sel, body):
                continue
            if not sel or sel[0].isdigit() or sel in ("from", "to") or "keyframes" in sel or ":root" in sel or sel.startswith("html"):
                continue
            if "aura-light" in sel or "forced-colors" in sel:
                continue
            decls = []
            m = DECL.search(body)
            if m:
                rgb, _alpha = color_parts(m.group(1))
                if not (ratio_on_white(rgb) >= 4.5 or lum(rgb) < 0.2):  # senão: já legível no claro, ou escura de propósito
                    decls.append(f"color:{darken(rgb)}")
            b = BG.search(body)
            if b and dark_background(b.group(1)):
                decls.append("background:#fff")
            for bm in BORDER.finditer(body):
                nb = light_border(bm.group(2))
                if nb:
                    decls.append(f"{bm.group(1)}:{nb}")
            if not decls:
                continue
            block = ";".join(d if d.endswith("!important") else d + "!important" for d in decls)  # o tema escuro usa muito !important
            for one in sel.split(","):
                one = one.strip()
                if not one or one.startswith("@"):
                    continue
                key = (one, block)
                if key not in seen:
                    seen.add(key)
                    prefix = "body.aura-light"
                    if one == "body":
                        out.append(f"{prefix}{{{block}}}")
                    elif one.startswith("body "):
                        out.append(f"{prefix}{one[4:]}{{{block}}}")
                    else:
                        out.append(f"{prefix} {one}{{{block}}}")
    header = ("/* AURA AI — tema claro: texto, fundos e bordas. GERADO por tests/tools/gen_light_theme.py (não edite à mão).\n"
              "   Cada regra de texto claro do tema escuro ganha a versão escurecida (mesma matiz) para o tema claro. */\n")
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else OUTPUT
    target.write_text(header + "\n".join(out) + "\n", encoding="utf8", newline="\n")
    print(f"{len(out)} regras geradas")


if __name__ == "__main__":
    sys.exit(main())
