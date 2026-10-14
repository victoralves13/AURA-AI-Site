"""Avaliação da qualidade da análise com a IA REAL (gasta crédito da OpenAI).

Mede, em transcrições de exemplo com fatos conhecidos, o que importa para a confiança:
  * quantas evidências a IA citou e quantas existem de fato na transcrição (localizadas / parciais / inventadas);
  * quantos achados ela marcou como "inferido";
  * se ela encontrou os fatos esperados ("must_find") e se afirmou coisas que ninguém disse ("must_not");
  * quantos horários, interlocutores, responsáveis e prazos ela errou ou inventou (corrigidos pela conferência).

Uso (na raiz do projeto, com a chave só nesta janela do terminal):
    python tests/eval/run_eval.py --dry     # confere os exemplos, SEM chamar a IA e sem custo
    python tests/eval/run_eval.py           # roda de verdade (3 chamadas à análise)
    python tests/eval/run_eval.py --json    # saída em JSON, para comparar entre versões do prompt

Não substitui uma avaliação humana: os números mostram CONFERIBILIDADE, não que a análise seja boa.
"""
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "api"))

FIXTURES = HERE / "fixtures"


def load_fixtures():
    out = []
    for txt in sorted(FIXTURES.glob("*.txt")):
        meta = json.loads(txt.with_suffix(".json").read_text(encoding="utf-8"))
        out.append({"name": txt.stem, "transcript": txt.read_text(encoding="utf-8"), **meta})
    return out


def validate_fixture(fx):
    """Problemas nos próprios exemplos (devolve lista vazia se estiver tudo coerente)."""
    from verification import normalize
    haystack = " " + normalize(fx["transcript"]) + " "
    problems = []
    for word in fx.get("must_find", []):
        if " " + normalize(word) + " " not in haystack:
            problems.append(f"must_find '{word}' não aparece na transcrição")
    for word in fx.get("must_not", []):
        if " " + normalize(word) + " " in haystack:
            problems.append(f"must_not '{word}' aparece na transcrição (não seria invenção)")
    return problems


def evaluate(fx):
    import openai_engine as eng
    analysis = eng.analyze_transcript(fx["transcript"], fx.get("context", "Outro"))
    fields = eng.build_product_fields(analysis, fx["transcript"])
    summary = fields["evidence_summary"]
    asserted = " ".join([fields["summary"], *[i["description"] + " " + (i["evidence"] or "") for i in fields["insights"]],
                         *fields["decisions"], *fields["pending_actions"]])
    from verification import normalize
    text = " " + normalize(asserted) + " "
    found = [w for w in fx.get("must_find", []) if " " + normalize(w) + " " in text]
    invented = [w for w in fx.get("must_not", []) if " " + normalize(w) + " " in text]
    total = max(1, summary["total"])
    return {
        "arquivo": fx["name"],
        "versao_do_contrato": fields["analysis_version"],
        "evidencias": summary["total"],
        "localizadas": summary["localizada"],
        "parciais": summary["parcial"],
        "nao_localizadas": summary["nao_localizada"],
        "pct_conferidas": round(100 * (summary["localizada"] + summary["parcial"]) / total, 1),
        "inferidos": summary["inferido"],
        "itens_corrigidos_pela_conferencia": summary["corrigidos"],
        "fatos_esperados_encontrados": f"{len(found)}/{len(fx.get('must_find', []))}",
        "fatos_esperados_faltando": [w for w in fx.get("must_find", []) if w not in found],
        "afirmacoes_sem_base_na_transcricao": invented,
        "riscos": fields["risk"],
        "oportunidade": fields["opportunity"],
    }


def main(argv):
    fixtures = load_fixtures()
    bad = {fx["name"]: validate_fixture(fx) for fx in fixtures}
    if any(bad.values()):
        print("Exemplos incoerentes:", json.dumps(bad, ensure_ascii=False, indent=2))
        return 2
    if "--dry" in argv:
        print(f"{len(fixtures)} exemplos coerentes. Nenhuma chamada à IA foi feita.")
        return 0
    if not os.getenv("OPENAI_API_KEY"):
        print("Defina OPENAI_API_KEY nesta janela do terminal (não grave em arquivo). Use --dry para só validar os exemplos.")
        return 2
    results = [evaluate(fx) for fx in fixtures]
    if "--json" in argv:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        for r in results:
            print(f"\n== {r['arquivo']} (contrato v{r['versao_do_contrato']})")
            for k, v in r.items():
                if k not in ("arquivo", "versao_do_contrato"):
                    print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
