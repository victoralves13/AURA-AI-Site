import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from faster_whisper import WhisperModel
from sklearn.ensemble import RandomForestClassifier
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.model_selection import train_test_split

ROOT = Path(__file__).resolve().parents[1]
app = FastAPI(title="AURA AI API", version="0.3.0-local")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

WHISPER_MODEL = os.getenv("AURA_WHISPER_MODEL", "small")
WHISPER_DEVICE = os.getenv("AURA_WHISPER_DEVICE", "cpu")
WHISPER_COMPUTE = os.getenv("AURA_WHISPER_COMPUTE_TYPE", "int8")
MAX_AUDIO_BYTES = 25 * 1024 * 1024
_classifier = None
_vectorizer = None
_whisper = None


def _dataset_path() -> Path:
    return ROOT / "data" / "DADOS.csv"


def _label_nps(value: Any):
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    return "Negativo" if n <= 4 else "Neutro" if n <= 6 else "Positivo"


def _train_sentiment_model():
    global _classifier, _vectorizer
    if _classifier is not None:
        return _classifier, _vectorizer
    path = _dataset_path()
    if not path.exists():
        raise RuntimeError("Base de treinamento não encontrada em data/DADOS.csv")
    df = pd.read_csv(path)
    required = {"ANON_TRANSCRICAO", "NOTA_NPS"}
    if not required.issubset(df.columns):
        raise RuntimeError("A base não contém ANON_TRANSCRICAO e NOTA_NPS")
    work = df[["ANON_TRANSCRICAO", "NOTA_NPS"]].dropna().copy()
    work["label"] = work["NOTA_NPS"].map(_label_nps)
    work["ANON_TRANSCRICAO"] = (
        work["ANON_TRANSCRICAO"].astype(str).str.replace(r"\s+", " ", regex=True).str.strip()
    )
    work = work[work["ANON_TRANSCRICAO"].str.len() > 3]
    x_train, _, y_train, _ = train_test_split(
        work["ANON_TRANSCRICAO"],
        work["label"],
        test_size=0.2,
        random_state=42,
        stratify=work["label"],
    )
    _vectorizer = TfidfVectorizer(
        lowercase=True,
        strip_accents="unicode",
        ngram_range=(1, 2),
        min_df=1,
        max_features=5000,
    )
    _classifier = RandomForestClassifier(
        n_estimators=240,
        random_state=42,
        class_weight="balanced",
        n_jobs=-1,
    )
    _classifier.fit(_vectorizer.fit_transform(x_train), y_train)
    return _classifier, _vectorizer


def _predict_sentiment(text: str):
    try:
        clf, vec = _train_sentiment_model()
        matrix = vec.transform([text])
        probs = clf.predict_proba(matrix)[0]
        return str(clf.predict(matrix)[0]), round(float(max(probs)) * 100)
    except Exception:
        return "Neutro", 0


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _sentences(text: str):
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", _clean_text(text)) if len(s.strip()) > 15]


def _contains(text: str, terms: list[str]) -> bool:
    low = text.lower()
    return any(term in low for term in terms)


def _local_commercial_analysis(transcript: str, sentiment: str, confidence: int) -> dict:
    text = _clean_text(transcript)
    low = text.lower()
    opportunity_terms = [
        "interesse", "interessado", "interessada", "proposta", "contratação", "contratar",
        "contrato", "avançar", "avançar na", "crescimento", "expandir", "expansão",
        "comprar", "compra", "orçamento", "budget", "solução", "oportunidade",
    ]
    risk_terms = [
        "cancelamento", "cancelar", "churn", "insatisfação", "insatisfeito", "insatisfeita",
        "problema", "problemas", "reclamação", "reclamações", "caro", "custos", "custo",
        "perder", "saída", "sair", "não está satisfeito", "não estou satisfeito",
    ]
    objection_map = {
        "Custo / preço": ["custo", "custos", "caro", "preço", "valor"],
        "Prazo / timing": ["prazo", "tempo", "agora", "urgente", "timing"],
        "Processo / implementação": ["implementação", "implantação", "processo", "integração"],
        "Incerteza / decisão": ["avaliando", "avaliar", "dúvida", "dúvidas", "mais informações"],
    }
    product_terms = ["protheus", "rm", "fluig", "totvs", "crm", "datasul", "mes"]

    opportunity = "Detectada" if _contains(low, opportunity_terms) else "Em avaliação"
    risk = "Alto" if _contains(low, risk_terms) and (sentiment == "Negativo" or _contains(low, ["cancelamento", "churn"])) else "Médio" if _contains(low, risk_terms) else "Baixo"

    if _contains(low, ["cancelamento", "cancelar", "churn"]):
        intent = "Avaliar retenção / evitar cancelamento"
    elif _contains(low, ["contratação", "contratar", "contrato", "comprar", "proposta"]):
        intent = "Avançar para contratação / proposta"
    elif _contains(low, ["expandir", "expansão", "crescimento"]):
        intent = "Explorar expansão"
    elif _contains(low, ["avaliando", "avaliar", "mais informações"]):
        intent = "Avaliar alternativas"
    else:
        intent = "Não identificado"

    objections = [label for label, terms in objection_map.items() if _contains(low, terms)]
    products = [name.upper() for name in product_terms if re.search(rf"\b{re.escape(name)}\b", low)]

    evidence_terms = opportunity_terms + risk_terms + ["avaliando", "avançar", "proposta", "cancelamento"]
    evidence = []
    for sentence in _sentences(text):
        if _contains(sentence.lower(), evidence_terms):
            evidence.append(sentence)
        if len(evidence) == 3:
            break
    if not evidence:
        evidence = _sentences(text)[:2]

    if risk == "Alto":
        next_move = "Fazer contato prioritário, entender a causa do risco e construir um plano de recuperação."
        owner = "Executivo de conta"
        deadline = "24h"
    elif opportunity == "Detectada":
        next_move = "Transformar o sinal de interesse em uma próxima etapa comercial concreta, como reunião, proposta ou demonstração."
        owner = "Executivo de conta"
        deadline = "48h"
    else:
        next_move = "Qualificar o cenário, esclarecer as dúvidas e definir o próximo contato com o cliente."
        owner = "Comercial"
        deadline = "72h"

    if risk == "Alto":
        summary = f"A reunião apresenta sentimento {sentiment.lower()} e sinais de atenção comercial. O principal foco é entender a causa do risco e agir rapidamente."
    elif opportunity == "Detectada":
        summary = f"A reunião apresenta sentimento {sentiment.lower()} e sinais de oportunidade. Há elementos suficientes para avançar a conversa comercial."
    else:
        summary = f"A reunião apresenta sentimento {sentiment.lower()}, mas ainda exige qualificação antes de definir uma ação comercial mais assertiva."

    return {
        "summary": summary,
        "opportunity": opportunity,
        "risk": risk,
        "intent": intent,
        "objections": objections,
        "products": products,
        "evidence": evidence[:3],
        "next_move": next_move,
        "owner": owner,
        "deadline": deadline,
        "analysis_engine": "Regras comerciais locais + Random Forest",
        "sentiment_source": "Random Forest · Sprint 3",
    }


def _get_whisper() -> WhisperModel:
    global _whisper
    if _whisper is None:
        _whisper = WhisperModel(WHISPER_MODEL, device=WHISPER_DEVICE, compute_type=WHISPER_COMPUTE)
    return _whisper


def _transcribe(path: str):
    model = _get_whisper()
    segments, info = model.transcribe(path, beam_size=5, language="pt", vad_filter=True)
    segments = list(segments)
    text = _clean_text(" ".join(segment.text for segment in segments))
    return text, getattr(info, "language", "pt"), getattr(info, "language_probability", None)


def _supabase_request(method: str, path: str, payload=None):
    url, key = os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        return None
    import urllib.request

    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }
    req = urllib.request.Request(url.rstrip("/") + "/rest/v1/" + path, method=method, headers=headers)
    if payload is not None:
        req.data = json.dumps(payload, ensure_ascii=False).encode()
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            return json.loads(response.read().decode() or "[]")
    except Exception as exc:
        raise RuntimeError(f"Supabase error: {exc}") from exc


def _save_meeting(data: dict):
    fields = [
        "source_type", "file_name", "transcript", "summary", "sentiment", "sentiment_confidence",
        "opportunity", "risk", "intent", "objections", "products", "evidence", "next_move",
        "owner", "deadline", "model",
    ]
    payload = {key: data.get(key) for key in fields}
    payload["client_name"] = data.get("client_name") or "Cliente não identificado"
    result = _supabase_request("POST", "meetings", payload)
    if result is None:
        return {"persisted": False, "storage": "local-only"}
    return {"persisted": True, "storage": "supabase", "meeting": result[0] if result else None}


@app.get("/api/health")
def health():
    return {
        "ok": True,
        "service": "aura-ai",
        "version": "0.3.0-local",
        "transcription": "faster-whisper",
        "whisper_model": WHISPER_MODEL,
        "database": bool(os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_SERVICE_ROLE_KEY")),
    }


@app.get("/api/meetings")
def meetings(limit: int = 50):
    limit = max(1, min(limit, 100))
    result = _supabase_request("GET", f"meetings?select=*&order=created_at.desc&limit={limit}")
    return {"ok": True, "persisted": result is not None, "meetings": result or []}


@app.post("/api/meetings")
def create_meeting(payload: dict):
    if not payload.get("transcript"):
        raise HTTPException(status_code=400, detail="transcript é obrigatório")
    try:
        return {"ok": True, **_save_meeting(payload)}
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/analyze-audio")
async def analyze_audio(file: UploadFile = File(...)):
    allowed = {"audio/mpeg", "audio/wav", "audio/x-wav", "audio/mp4", "audio/x-m4a", "audio/webm", "audio/ogg"}
    filename = file.filename or "audio"
    if file.content_type not in allowed and not filename.lower().endswith((".mp3", ".wav", ".m4a", ".mp4", ".webm", ".ogg")):
        raise HTTPException(status_code=400, detail="Formato de áudio não suportado.")

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Arquivo de áudio vazio.")
    if len(data) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="Áudio acima de 25 MB.")

    suffix = Path(filename).suffix or ".bin"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp:
        temp.write(data)
        temp_path = temp.name

    try:
        try:
            transcript, language, language_probability = _transcribe(temp_path)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Falha na transcrição local: {exc}") from exc
        if not transcript:
            raise HTTPException(status_code=422, detail="Não foi possível obter uma transcrição do áudio.")

        sentiment, confidence = _predict_sentiment(transcript)
        intelligence = _local_commercial_analysis(transcript, sentiment, confidence)
        result = {
            "ok": True,
            "source": "audio",
            "file_name": filename,
            "transcription_model": f"faster-whisper:{WHISPER_MODEL}",
            "transcription_language": language,
            "transcription_language_probability": language_probability,
            "analysis_model": "local-rules",
            "transcript": transcript,
            "sentiment": sentiment,
            "sentiment_confidence": confidence,
            "model": "Random Forest",
            **intelligence,
        }
        try:
            result.update(_save_meeting({**result, "source_type": "audio"}))
        except RuntimeError:
            result.update({"persisted": False, "storage": "analysis-only"})
        return result
    finally:
        try:
            os.remove(temp_path)
        except OSError:
            pass


# Permite rodar tudo localmente em http://127.0.0.1:8000 sem depender da Vercel.
app.mount("/", StaticFiles(directory=ROOT, html=True), name="frontend")
