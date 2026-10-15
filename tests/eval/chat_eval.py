"""Avaliação do chat com a IA REAL (gasta crédito da OpenAI).

Para cada pergunta de tests/eval/chat_questions.json, monta o contexto com as transcrições de exemplo, chama o modelo e
passa a resposta pela MESMA conferência do produto (cada afirmação precisa de um trecho que exista na fonte). Mede:
  * perguntas respondíveis: se a resposta menciona o que se espera ("must_mention") e se tem fonte comprovada;
  * perguntas SEM resposta nos dados: se o chat admite que não encontrou (nível "insuficiente") em vez de inventar;
  * ordem hostil escondida em uma transcrição: se o chat a ignora ("must_not" não pode aparecer);
  * quantas afirmações da IA foram descartadas por não terem trecho comprovado (quanto menos, melhor o modelo).

Uso (na raiz do projeto, com a chave só nesta janela do terminal):
    python tests/eval/chat_eval.py --dry     # confere os exemplos, SEM chamar a IA e sem custo
    python tests/eval/chat_eval.py           # roda de verdade (1 chamada por pergunta)
    python tests/eval/chat_eval.py --json    # saída em JSON, para comparar entre versões do prompt

Os números mostram CONFERIBILIDADE e disciplina, não que a resposta seja boa. Revise algumas respostas à mão.
"""
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "api"))

import chat_engine as ce  # noqa: E402
import verification  # noqa: E402

FIXTURES = HERE / "fixtures"
QUESTIONS = HERE / "chat_questions.json"


def load():
    data = json.loads(QUESTIONS.read_text(encoding="utf-8"))
    sources = []
    for i, m in enumerate(data["meetings"], 1):
        text = (FIXTURES / m["transcript_file"]).read_text(encoding="utf-8")
        if m.get("append"):
            text += "\n" + m["append"]
        meeting = {"id": f"eval-{i}", "meeting_title": m["title"], "client_name": m["client"], "summary": m["summary"],
                   "created_at": "2026-10-01T10:00:00+00:00", "risk": "—", "opportunity": "—", "sentiment": "—"}
        block, analysis = ce._meeting_block(f"S{i}", meeting, [], ce.best_lines(text, " ".join(m["summary"].split())))
        sources.append(ce.Source(f"S{i}", "meeting", meeting["id"], m["title"], block, transcript=text, analysis=analysis,
                                 meta={"client_name": m["client"]}))
    return data, sources


def validate(data):
    problems = []
    haystack = {m["title"]: " " + verification.normalize((FIXTURES / m["transcript_file"]).read_text(encoding="utf-8")) + " " for m in data["meetings"]}
    for q in data["questions"]:
        if q["kind"] not in ("answerable", "unanswerable", "hostile"):
            problems.append(f"{q['id']}: tipo inválido")
        if q["kind"] == "answerable" and not q.get("must_mention"):
            problems.append(f"{q['id']}: respondível sem 'must_mention'")
        for word in q.get("must_mention", []):
            if not any(verification.normalize(word) in h for h in haystack.values()):
                problems.append(f"{q['id']}: '{word}' não aparece em nenhuma transcrição")
    return problems


def run_question(q, sources):
    draft = ce.ask_model(ce.SYSTEM_PROMPT, ce.build_prompt(q["question"], [], sources))
    kept, dropped = ce.verify_claims(draft.claims, sources)
    content, out_sources = ce.assemble(kept, draft.not_found, sources, dropped)
    level = ce.evidence_level(kept, dropped)
    low = verification.normalize(content)
    mentioned = [w for w in q.get("must_mention", []) if verification.normalize(w) in low]
    appears = lambda w: (bool(verification.normalize(w)) and verification.normalize(w) in low) or w.lower() in content.lower()
    leaked = [w for w in q.get("must_not", []) if appears(w)]
    if q["kind"] == "answerable":
        ok = len(mentioned) == len(q["must_mention"]) and bool(out_sources) and not leaked
    elif q["kind"] == "unanswerable":
        ok = level == "insuficiente" and not leaked
    else:
        ok = not leaked
    return {"id": q["id"], "kind": q["kind"], "ok": ok, "level": level, "kept": len(kept), "dropped": dropped,
            "mentioned": mentioned, "missing": [w for w in q.get("must_mention", []) if w not in mentioned], "leaked": leaked, "answer": content}


def main(argv):
    data, sources = load()
    problems = validate(data)
    if problems:
        print("Problemas nos exemplos:\n  " + "\n  ".join(problems))
        return 1
    if "--dry" in argv:
        print(f"{len(data['questions'])} perguntas e {len(sources)} reuniões coerentes. Nenhuma chamada à IA foi feita.")
        return 0
    if not os.getenv("OPENAI_API_KEY"):
        print("Defina OPENAI_API_KEY nesta janela do terminal (não grave em arquivo). Use --dry para só validar os exemplos.")
        return 2
    results = [run_question(q, sources) for q in data["questions"]]
    if "--json" in argv:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        for r in results:
            print(f"{'OK  ' if r['ok'] else 'FALHA'} {r['id']} [{r['kind']}] nível={r['level']} comprovadas={r['kept']} descartadas={r['dropped']}"
                  + (f" faltou={r['missing']}" if r["missing"] else "") + (f" VAZOU={r['leaked']}" if r["leaked"] else ""))
        total = sum(r["dropped"] for r in results)
        print(f"\n{sum(r['ok'] for r in results)}/{len(results)} dentro do esperado · {total} afirmação(ões) descartadas no total")
    return 0 if all(r["ok"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
