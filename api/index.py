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
from sklearn.model_selection import train_test_split

app = FastAPI(title="AURA AI API", version="0.2.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
MODEL_NAME = os.getenv("AURA_TRANSCRIPTION_MODEL", "gpt-4o-transcribe")
ANALYSIS_MODEL = os.getenv("AURA_ANALYSIS_MODEL", "gpt-5.6-luna")
_classifier = None
_vectorizer = None

def _dataset_path(): return Path(__file__).resolve().parents[1] / "data" / "DADOS.csv"
def _label_nps(value):
    try: n=float(value)
    except (TypeError,ValueError): return None
    return "Negativo" if n<=4 else "Neutro" if n<=6 else "Positivo"

def _train_sentiment_model():
    global _classifier,_vectorizer
    if _classifier is not None: return _classifier,_vectorizer
    path=_dataset_path()
    if not path.exists(): raise RuntimeError("Base de treinamento não encontrada em data/DADOS.csv")
    df=pd.read_csv(path)
    if "ANON_TRANSCRICAO" not in df.columns or "NOTA_NPS" not in df.columns: raise RuntimeError("A base não contém ANON_TRANSCRICAO e NOTA_NPS")
    work=df[["ANON_TRANSCRICAO","NOTA_NPS"]].dropna().copy(); work["label"]=work["NOTA_NPS"].map(_label_nps)
    work["ANON_TRANSCRICAO"]=work["ANON_TRANSCRICAO"].astype(str).str.replace(r"\s+"," ",regex=True).str.strip(); work=work[work["ANON_TRANSCRICAO"].str.len()>3]
    x_train,_,y_train,_=train_test_split(work["ANON_TRANSCRICAO"],work["label"],test_size=.2,random_state=42,stratify=work["label"])
    _vectorizer=TfidfVectorizer(lowercase=True,strip_accents="unicode",ngram_range=(1,2),min_df=1,max_features=5000)
    _classifier=RandomForestClassifier(n_estimators=240,random_state=42,class_weight="balanced",n_jobs=-1); _classifier.fit(_vectorizer.fit_transform(x_train),y_train)
    return _classifier,_vectorizer

def _predict_sentiment(text):
    try:
        clf,vec=_train_sentiment_model(); probs=clf.predict_proba(vec.transform([text]))[0]
        return str(clf.predict(vec.transform([text]))[0]),round(float(max(probs))*100)
    except Exception: return "Neutro",0

def _extract_json(text):
    text=(text or "").strip(); text=re.sub(r"^```(?:json)?\s*","",text,flags=re.I); text=re.sub(r"\s*```$","",text)
    try: return json.loads(text)
    except json.JSONDecodeError:
        match=re.search(r"\{.*\}",text,flags=re.S)
        try: return json.loads(match.group(0)) if match else {}
        except json.JSONDecodeError: return {}

def _llm_analysis(transcript,ml_sentiment,ml_confidence):
    key=os.getenv("OPENAI_API_KEY")
    fallback={"summary":"Transcrição recebida. Configure OPENAI_API_KEY para ativar a camada de inteligência comercial.","opportunity":"Em avaliação","risk":"Em avaliação","intent":"Não identificado","objections":[],"products":[],"evidence":[],"next_move":"Revisar a transcrição e definir o próximo contato.","owner":"Comercial","deadline":"72h"}
    if not key: return fallback
    prompt=f'''Você é o motor de inteligência comercial do AURA AI. Analise a transcrição abaixo. O modelo ML classificou o sentimento como {ml_sentiment} com confiança de {ml_confidence}%. Use isso como sinal, sem inventar fatos. Retorne SOMENTE JSON válido com: summary, opportunity (Detectada|Em avaliação|Não identificada), risk (Alto|Médio|Baixo), intent, objections (array), products (array), evidence (até 3 trechos curtos literais), next_move, owner, deadline.\n\nTRANSCRIÇÃO:\n{transcript}'''
    try:
        response=OpenAI(api_key=key).responses.create(model=ANALYSIS_MODEL,input=prompt); data=_extract_json(getattr(response,"output_text",""))
        return data if isinstance(data,dict) and data else fallback
    except Exception: return {**fallback,"summary":"A transcrição foi processada, mas a camada estruturada não concluiu a resposta."}

def _supabase_request(method,path,payload=None):
    url,key=os.getenv("SUPABASE_URL"),os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key: return None
    import urllib.request
    headers={"apikey":key,"Authorization":f"Bearer {key}","Content-Type":"application/json","Prefer":"return=representation"}
    req=urllib.request.Request(url.rstrip("/")+"/rest/v1/"+path,method=method,headers=headers)
    if payload is not None: req.data=json.dumps(payload,ensure_ascii=False).encode()
    try:
        with urllib.request.urlopen(req,timeout=15) as r: return json.loads(r.read().decode() or "[]")
    except Exception as exc: raise RuntimeError(f"Supabase error: {exc}") from exc

def _save_meeting(data):
    fields=["source_type","file_name","transcript","summary","sentiment","sentiment_confidence","opportunity","risk","intent","objections","products","evidence","next_move","owner","deadline","model"]
    payload={k:data.get(k) for k in fields}; payload["client_name"]=data.get("client_name") or "Cliente não identificado"
    result=_supabase_request("POST","meetings",payload)
    return {"persisted":False,"storage":"local-only"} if result is None else {"persisted":True,"storage":"supabase","meeting":result[0] if result else None}

@app.get("/api/health")
def health(): return {"ok":True,"service":"aura-ai","version":"0.2.0","database":bool(os.getenv("SUPABASE_URL") and os.getenv("SUPABASE_SERVICE_ROLE_KEY"))}

@app.get("/api/meetings")
def meetings(limit:int=50):
    limit=max(1,min(limit,100)); result=_supabase_request("GET",f"meetings?select=*&order=created_at.desc&limit={limit}")
    return {"ok":True,"persisted":result is not None,"meetings":result or []}

@app.post("/api/meetings")
def create_meeting(payload:dict):
    if not payload.get("transcript"): raise HTTPException(status_code=400,detail="transcript é obrigatório")
    try: return {"ok":True,**_save_meeting(payload)}
    except RuntimeError as exc: raise HTTPException(status_code=502,detail=str(exc))

@app.post("/api/analyze-audio")
async def analyze_audio(file:UploadFile=File(...)):
    allowed={"audio/mpeg","audio/wav","audio/x-wav","audio/mp4","audio/x-m4a","audio/webm","audio/ogg"}
    if file.content_type not in allowed and not (file.filename or "").lower().endswith((".mp3",".wav",".m4a",".mp4",".webm",".ogg")): raise HTTPException(status_code=400,detail="Formato de áudio não suportado.")
    key=os.getenv("OPENAI_API_KEY")
    if not key: raise HTTPException(status_code=503,detail="OPENAI_API_KEY não configurada no ambiente do AURA.")
    data=await file.read()
    if not data: raise HTTPException(status_code=400,detail="Arquivo de áudio vazio.")
    if len(data)>25*1024*1024: raise HTTPException(status_code=413,detail="Áudio acima de 25 MB.")
    suffix=Path(file.filename or "audio").suffix or ".bin"
    with tempfile.NamedTemporaryFile(delete=False,suffix=suffix) as temp: temp.write(data); temp_path=temp.name
    try:
        with open(temp_path,"rb") as audio_file: transcription=OpenAI(api_key=key).audio.transcriptions.create(model=MODEL_NAME,file=audio_file,language="pt")
        transcript=(getattr(transcription,"text","") or "").strip()
        if not transcript: raise HTTPException(status_code=422,detail="Não foi possível obter uma transcrição do áudio.")
        sentiment,confidence=_predict_sentiment(transcript); intelligence=_llm_analysis(transcript,sentiment,confidence)
        result={"ok":True,"source":"audio","file_name":file.filename,"transcription_model":MODEL_NAME,"analysis_model":ANALYSIS_MODEL,"transcript":transcript,"sentiment":sentiment,"sentiment_confidence":confidence,"model":"Random Forest",**intelligence}
        try: result.update(_save_meeting({**result,"source_type":"audio"}))
        except RuntimeError: result.update({"persisted":False,"storage":"analysis-only"})
        return result
    finally:
        try: os.remove(temp_path)
        except OSError: pass
