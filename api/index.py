import json
import os
import re
import tempfile
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from openai import OpenAI
from sklearn.ensemble import RandomForestClassifier
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.pipeline import FeatureUnion
from sklearn.preprocessing import FunctionTransformer
from sklearn.pipeline import Pipeline
from sklearn.model_selection import train_test_split

app = FastAPI(title="AURA AI API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

MODEL_NAME = os.getenv("AURA_TRANSCRIPTION_MODEL", "gpt-4o-transcribe")
ANALYSIS_MODEL = os.getenv("AURA_ANALYSIS_MODEL", "gpt-5.6-luna")
_classifier = None
_vectorizer = None


def _dataset_path() -> Path:
    return Path(__file__).resolve().parents[1] / "data" / "DADOS.csv"


def _label_nps(value):
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    if n <= 4:
        return "Negativo"
    if n <= 6:
        return "Neutro"
    return "Positivo"


def _train_sentiment_model():
    global _classifier, _vectorizer
    if _classifier is not None:
        return _classifier, _vectorizer

    path = _dataset_path()
    if not path.exists():
        raise RuntimeError("Base de treinamento não encontrada em data/DADOS.csv")

    df = pd.read_csv(path)
    text_col = "ANON_TRANSCRICAO"
    if text_col not in df.columns or "NOTA_NPS" not in df.columns:
        raise RuntimeError("A base não contém ANON_TRANSCRICAO e NOTA_NPS")

    work = df[[text_col, "NOTA_NPS"]].dropna().copy()
    work["label"] = work["NOTA_NPS"].map(_label_nps)
    work[text_col] = work[text_col].astype(str).str.replace(r"\s+", " ", regex=True).str.strip()
    work = work[work[text_col].str.len() > 3]

    x_train, _, y_train, _ = train_test_split(
        work[text_col],
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
    x_train_tfidf = _vectorizer.fit_transform(x_train)
    _classifier = RandomForestClassifier(
        n_estimators=240,
        random_state=42,
        class_weight="balanced",
        n_jobs=-1,
    )
    _classifier.fit(x_train_tfidf, y_train)
    return _classifier, _vectorizer


def _predict_sentiment(text: str):
    try:
        clf, vec = _train_sentiment_model()
        matrix = vec.transform([text])
        prediction = str(clf.predict(matrix)[0])
        probabilities = clf.predict_proba(matrix)[0]
        confidence = round(float(max(probabilities)) * 100)
        return prediction, confidence
    except Exception:
        return "Neutro", 0


def _extract_json(text: str):
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
    text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.S)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
    return {}


def _llm_analysis(transcript: str, ml_sentiment: str, ml_confidence: int):
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return {
            "summary": "Transcrição recebida. Configure OPENAI_API_KEY para ativar a camada de inteligência comercial.",
            "opportunity": "Em avaliação",
            "risk": "Em avaliação",
            "intent": "Não identificado",
            "objections": [],
            "products": [],
            "evidence": [],
            "next_move": "Revisar a transcrição e definir o próximo contato.",
            "owner": "Comercial",
            "deadline": "72h",
        }

    client = OpenAI(api_key=api_key)
    prompt = f"""
Você é o motor de inteligência comercial do AURA AI.
Analise a transcrição abaixo. O modelo de Machine Learning do AURA classificou o sentimento como {ml_sentiment} com confiança de {ml_confidence}%.
Use essa classificação como sinal, mas não invente fatos.

Retorne SOMENTE um JSON válido com estas chaves:
summary (string), opportunity (string: Detectada|Em avaliação|Não identificada),
risk (string: Alto|Médio|Baixo), intent (string), objections (array de strings),
products (array de strings), evidence (array com até 3 trechos curtos literais da transcrição),
next_move (string), owner (string), deadline (string).

Transcrição:
---
{transcript}
---
"""
    try:
        response = client.responses.create(model=ANALYSIS_MODEL, input=prompt)
        data = _extract_json(getattr(response, "output_text", ""))
        if isinstance(data, dict):
            return data
    except Exception:
        pass

    return {
        "summary": "A transcrição foi processada, mas a camada de inteligência comercial não conseguiu concluir a resposta estruturada.",
        "opportunity": "Em avaliação",
        "risk": "Médio",
        "intent": "Não identificado",
        "objections": [],
        "products": [],
        "evidence": [],
        "next_move": "Revisar a transcrição e definir o próximo contato.",
        "owner": "Comercial",
        "deadline": "72h",
    }


@app.get("/api/health")
def health():
    return {"ok": True, "service": "aura-ai", "version": "0.1.0"}


@app.post("/api/analyze-audio")
async def analyze_audio(file: UploadFile = File(...)):
    allowed = {"audio/mpeg", "audio/wav", "audio/x-wav", "audio/mp4", "audio/x-m4a", "audio/webm", "audio/ogg"}
    if file.content_type not in allowed and not (file.filename or "").lower().endswith((".mp3", ".wav", ".m4a", ".mp4", ".webm", ".ogg")):
        raise HTTPException(status_code=400, detail="Formato de áudio não suportado.")

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=503, detail="OPENAI_API_KEY não configurada no ambiente do AURA.")

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Arquivo de áudio vazio.")
    if len(data) > 25 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Áudio acima de 25 MB. Use um arquivo menor para esta primeira versão.")

    suffix = Path(file.filename or "audio").suffix or ".bin"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp:
        temp.write(data)
        temp_path = temp.name

    try:
        client = OpenAI(api_key=api_key)
        with open(temp_path, "rb") as audio_file:
            transcription = client.audio.transcriptions.create(
                model=MODEL_NAME,
                file=audio_file,
                language="pt",
            )
        transcript = (getattr(transcription, "text", "") or "").strip()
        if not transcript:
            raise HTTPException(status_code=422, detail="Não foi possível obter uma transcrição do áudio.")

        sentiment, confidence = _predict_sentiment(transcript)
        intelligence = _llm_analysis(transcript, sentiment, confidence)

        return {
            "ok": True,
            "source": "audio",
            "transcription_model": MODEL_NAME,
            "analysis_model": ANALYSIS_MODEL,
            "transcript": transcript,
            "sentiment": sentiment,
            "sentiment_confidence": confidence,
            "model": "Random Forest",
            **intelligence,
        }
    finally:
        try:
            os.remove(temp_path)
        except OSError:
            pass
