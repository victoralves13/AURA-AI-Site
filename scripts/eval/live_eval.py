"""Avaliação da transcrição contínua e dos alertas ao vivo com a IA REAL (gasta crédito da OpenAI).

Pega um arquivo de áudio SEU (uma conversa em português, de 1 a 5 minutos), corta em pedaços de 30 s como a gravação ao vivo faz, transcreve cada
pedaço com o mesmo motor do produto (com o pedaço anterior como contexto), monta o texto (aparando a emenda), roda UMA varredura de alertas e
confere cada alerta contra o texto. Mostra o que importa para a confiança: texto montado, alertas comprovados e descartados, minutos e custo estimado.

Uso (na raiz do projeto, com a chave só nesta janela do terminal):
    python tests/eval/live_eval.py --dry                         # confere o ambiente, SEM chamar a IA e sem custo
    python tests/eval/live_eval.py caminho\\da\\conversa.mp3      # roda de verdade (1 chamada por pedaço + 1 de alertas)
    python tests/eval/live_eval.py conversa.mp3 --json           # saída em JSON
    python tests/eval/live_eval.py conversa.mp3 --seconds 20     # tamanho do pedaço (padrão 30)

Não envia nada para o Supabase e não grava arquivos. O áudio vai à OpenAI para ser transcrito (use só conteúdo que você pode enviar).
Os números mostram conferibilidade; leia o texto e os alertas à mão para julgar a qualidade (nomes, números e termos do seu negócio).
"""
import io
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "backend"))

from aura.features.live import alerts as la  # noqa: E402
from aura.features.live import transcription as lt  # noqa: E402

DEFAULT_SECONDS = 30


def _ffmpeg() -> str:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        import shutil
        found = shutil.which("ffmpeg")
        if not found:
            raise RuntimeError("ffmpeg não encontrado. Rode `pip install -r requirements.txt` no ambiente do projeto.")
        return found


def split_audio(path: str, seconds: int) -> list[tuple[bytes, int]]:
    """Corta o áudio em pedaços de `seconds` s (mp3 mono, em memória) com o ffmpeg do projeto. Retorna [(bytes, duração em ms)]."""
    import re
    import subprocess
    import tempfile
    exe = _ffmpeg()
    probe = subprocess.run([exe, "-i", path], capture_output=True, text=True)
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", probe.stderr or "")
    if not m:
        raise RuntimeError("Não foi possível ler o áudio (formato não reconhecido).")
    total_ms = int((int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))) * 1000)
    with tempfile.TemporaryDirectory() as tmp:
        run = subprocess.run([exe, "-y", "-i", path, "-vn", "-ac", "1", "-ar", "16000", "-c:a", "libmp3lame", "-b:a", "48k", "-f", "segment",
                              "-segment_time", str(seconds), "-reset_timestamps", "1", str(Path(tmp) / "p%04d.mp3")], capture_output=True, text=True)
        files = sorted(Path(tmp).glob("p*.mp3"))
        if run.returncode != 0 or not files:
            raise RuntimeError("O ffmpeg não conseguiu cortar o áudio.")
        out = []
        for i, f in enumerate(files):
            dur = min(seconds * 1000, total_ms - i * seconds * 1000)
            if dur >= 1000:
                out.append((f.read_bytes(), dur))
        return out


def evaluate(pieces: list[tuple[bytes, int]], transcribe, ask) -> dict:
    """Roda o fluxo ao vivo sobre pedaços já cortados. `transcribe(bytes, ext, contexto)` e `ask(janela)` são injetáveis (testes usam falsos)."""
    chunks, previous = [], ""
    for seq, (data, dur) in enumerate(pieces):
        try:
            text = lt.clean_text(transcribe(data, ".mp3", previous))
            status = "transcribed"
        except Exception as exc:  # um pedaço que falha não derruba a avaliação
            text, status = "", "failed"
            print(f"  pedaço {seq} falhou: {type(exc).__name__}", file=sys.stderr)
        chunks.append({"seq": seq, "status": status, "text": text, "duration_ms": dur, "attempts": 1})
        if text:
            previous = text
    built = lt.assemble(chunks)
    window, _ = la.build_window(built["lines"], 0)
    window = la.lt_neutralize(window)
    alerts, dropped, proposed = [], 0, 0
    if window.strip():
        batch = ask(window)
        proposed = len(batch.alerts)
        alerts, dropped = la.verify_alerts(batch.alerts, window)
    minutes = sum(c["duration_ms"] for c in chunks if c["status"] == "transcribed") / 60000
    return {"chunks": len(chunks), "failed": sum(1 for c in chunks if c["status"] == "failed"), "minutes": round(minutes, 2),
            "estimated_cost_usd": lt.estimate_cost(minutes), "text": built["text"], "lines": built["lines"], "alerts": alerts,
            "alerts_proposed": proposed, "alerts_dropped": dropped}


def show(res: dict) -> None:
    print(f"\nPedaços: {res['chunks']} · falhos: {res['failed']} · áudio transcrito: {res['minutes']} min · custo estimado ≈ US$ {res['estimated_cost_usd']} (ESTIMATIVA)\n")
    print("== Texto montado ==")
    for l in res["lines"]:
        print(f"[{la.clock(l['start_ms'])}] {l['text'] or ('(' + l['status'] + ')')}")
    print(f"\n== Alertas: {len(res['alerts'])} comprovados de {res['alerts_proposed']} propostos ({res['alerts_dropped']} descartados por falta de trecho) ==")
    for a in res["alerts"]:
        print(f"- [{a.get('timestamp')}] {a['category'].upper()} ({a['kind']}, trecho {a['check']}): {a['statement']}\n    “{a['quote']}”")
    print("\nLeia o texto e os alertas: confira nomes, valores e prazos. Muitos descartados indicam um modelo que cita trechos inexistentes.")


def main(argv):
    if "--dry" in argv:
        try:
            ok = "ffmpeg ok (" + Path(_ffmpeg()).name + ")"
        except Exception as exc:
            ok = f"ffmpeg indisponível: {exc}"
        print(f"Ambiente: {ok} · modelo de transcrição: {lt.LIVE_MODEL} · modelo de alertas: {la.ALERT_MODEL} · chave definida: {bool(os.getenv('OPENAI_API_KEY'))}")
        print("Nenhuma chamada à IA foi feita.")
        return 0
    paths = [a for a in argv if not a.startswith("--") and not a.isdigit()]
    if not paths or not Path(paths[0]).is_file():
        print("Informe o caminho de um arquivo de áudio. Veja o uso com: python tests/eval/live_eval.py --help")
        return 2
    if not os.getenv("OPENAI_API_KEY"):
        print("Defina OPENAI_API_KEY nesta janela do terminal (não grave em arquivo). Use --dry para só conferir o ambiente.")
        return 2
    seconds = int(argv[argv.index("--seconds") + 1]) if "--seconds" in argv else DEFAULT_SECONDS
    pieces = split_audio(paths[0], seconds)
    print(f"{len(pieces)} pedaços de até {seconds} s. Transcrevendo…")
    res = evaluate(pieces, lt.transcribe_audio, la.ask_model)
    if "--json" in argv:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        show(res)
    return 0 if res["failed"] == 0 else 1


if __name__ == "__main__":
    if "--help" in sys.argv or "-h" in sys.argv:
        print(__doc__)
        sys.exit(0)
    sys.exit(main(sys.argv[1:]))
