"""Regras da arquitetura em camadas (backend/aura). Quebrar uma delas deve falhar aqui, não aparecer só na revisão.

    router.py      camada HTTP: FastAPI, validação do pedido, chama o serviço. Não fala com o banco.
    service.py     regras de negócio: não conhece FastAPI nem PostgREST; usa o repositório.
    repository.py  único lugar que fala com o Supabase/PostgREST (user_rest/service_rest); não tem regra de negócio.
    schemas.py     modelos Pydantic do pedido/resposta.
    core/          base comum (segurança, erros, storage): não depende de nenhuma funcionalidade.
"""
import ast
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend" / "aura"
FEATURES = BACKEND / "features"
# Funcionalidades ainda não separadas em camadas (a lista só diminui; ao terminar a migração fica vazia).
PENDING = {"orgs", "clients", "actions", "chat", "live", "analysis", "meetings"}
DATA_CALLS = ("user_rest", "service_rest", "http_json")


def imports(path):
    tree = ast.parse(path.read_text(encoding="utf8"))
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out += [(a.name, node.lineno) for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            out += [(base, node.lineno)] + [(f"{base}.{a.name}", node.lineno) for a in node.names]
    return out


def layered():
    return sorted(d for d in FEATURES.iterdir() if d.is_dir() and d.name not in PENDING and not d.name.startswith("__"))


class Camadas(unittest.TestCase):
    def test_ha_funcionalidades_em_camadas(self):
        self.assertIn("onboarding", [d.name for d in layered()])

    def test_cada_funcionalidade_tem_as_tres_camadas(self):
        for d in layered():
            for name in ("router.py", "service.py", "repository.py"):
                self.assertTrue((d / name).exists(), f"{d.name}/{name} não existe")

    def test_router_nao_fala_com_o_banco(self):
        for d in layered():
            text = (d / "router.py").read_text(encoding="utf8")
            for call in DATA_CALLS:
                self.assertNotIn(call, text, f"{d.name}/router.py usa {call}: mova para o repository")

    def test_service_e_repository_nao_conhecem_fastapi(self):
        for d in layered():
            for name in ("service.py", "repository.py"):
                for mod, line in imports(d / name):
                    self.assertFalse(mod == "fastapi" or mod.startswith("fastapi."), f"{d.name}/{name}:{line} importa {mod}; use aura.core.errors")

    def test_service_nao_fala_com_o_banco(self):
        for d in layered():
            text = (d / "service.py").read_text(encoding="utf8")
            for call in DATA_CALLS:
                self.assertNotIn(call, text, f"{d.name}/service.py usa {call}: mova para o repository")

    def test_sentido_das_dependencias(self):
        for d in layered():
            for mod, line in imports(d / "repository.py"):
                self.assertFalse(mod.endswith((".service", ".router")), f"{d.name}/repository.py:{line} depende de {mod}")
            for mod, line in imports(d / "service.py"):
                self.assertFalse(mod.endswith(".router"), f"{d.name}/service.py:{line} depende de {mod}")

    def test_core_nao_depende_de_funcionalidades(self):
        for path in (BACKEND / "core").glob("*.py"):
            for mod, line in imports(path):
                self.assertFalse(mod.startswith("aura.features"), f"core/{path.name}:{line} depende de {mod}")

    def test_funcionalidades_so_usam_o_servico_das_outras(self):
        """Entre funcionalidades, só o service (a porta pública) pode ser importado; router e repository são internos."""
        for d in layered():
            for path in d.glob("*.py"):
                for mod, line in imports(path):
                    parts = mod.split(".")
                    if len(parts) >= 4 and parts[:2] == ["aura", "features"] and parts[2] != d.name:
                        self.assertTrue(len(parts) == 4 and parts[3] in ("service", "schemas") or parts[3] not in ("router", "repository"),
                                        f"{d.name}/{path.name}:{line} importa {mod}")


if __name__ == "__main__":
    unittest.main()
