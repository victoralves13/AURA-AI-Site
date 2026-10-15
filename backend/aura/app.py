"""AURA AI — aplicação FastAPI: compõe as funcionalidades, liga os ganchos entre elas e serve o front-end."""
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from aura.core import security as sec
from aura.features.actions.router import router as actions_router
from aura.features.analysis import router as analysis_mod
from aura.features.analysis.router import AUDIO_BUCKET, router as analysis_router
from aura.features.chat.router import router as conversations_router
from aura.features.clients.router import router as clients_router
from aura.features.integrations import providers
from aura.features.integrations.router import router as integrations_router
from aura.features.integrations.webhook import WebhookProvider
from aura.features.live import consolidate as live_consolidate
from aura.features.live.alerts import router as live_alerts_router
from aura.features.live.consolidate import router as live_consolidate_router
from aura.features.live.router import router as live_router
from aura.features.live.transcribe import router as live_transcribe_router
from aura.features.meetings.router import router as meetings_router
from aura.features.onboarding.router import router as onboarding_router
from aura.features.orgs.router import router as orgs_router

ROOT = Path(__file__).resolve().parents[2]  # raiz do repositório (o front-end público está nela)

app = FastAPI(title="AURA AI API", version="1.0.0-cloud")
handler = app
app.include_router(orgs_router)
app.include_router(clients_router)
app.include_router(actions_router)
app.include_router(conversations_router)
app.include_router(onboarding_router)
app.include_router(integrations_router)


def register_default_providers() -> None:
    providers.register_provider(WebhookProvider())


register_default_providers()
app.include_router(live_router)
app.include_router(live_transcribe_router)
app.include_router(live_alerts_router)
app.include_router(live_consolidate_router)
app.include_router(meetings_router)
app.include_router(analysis_router)
# O front-end é servido pela mesma origem, então CORS fica desligado por padrão.
# Para liberar origens específicas: AURA_ALLOWED_ORIGINS="https://app.exemplo.com,https://outra.com"
if sec.allowed_origins():
    app.add_middleware(CORSMiddleware, allow_origins=sec.allowed_origins(), allow_methods=["GET", "POST"], allow_headers=["Authorization", "Content-Type"])

live_consolidate.set_pipeline(analysis_mod._build_result)  # reuniões ao vivo usam a mesma análise

@app.get("/api/health")
def health():
    return {"ok": True, "service": "aura-ai", "version": "1.0.0-cloud", "engine": "OpenAI + AURA Intelligence", "openai_configured": bool(os.getenv("OPENAI_API_KEY")), "supabase_configured": bool(os.getenv("SUPABASE_URL") and (os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY"))), "audio_storage": AUDIO_BUCKET, "auth_required": sec.auth_required(), "auth_configured": bool(sec.supabase_url() and sec.publishable_key()), "publishable_key_kind": sec.key_kind(sec.publishable_key()), "service_key_kind": sec.key_kind(sec.service_key())}

@app.get("/api/config")
def public_config():
    # Valores públicos por natureza (a chave "publishable" do Supabase é feita para o navegador).
    return {"auth_required": sec.auth_required(), "supabase_url": sec.supabase_url() or None, "supabase_publishable_key": sec.publishable_key() or None}

# Serve só o front-end público (html/css/js/imagens na raiz); nunca api/, supabase/, .git, .env etc.
app.mount("/", sec.PublicFiles(directory=ROOT, html=True), name="frontend")
