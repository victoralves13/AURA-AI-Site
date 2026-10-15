"""AURA AI — acesso ao bucket privado de áudio (Supabase Storage), sempre com a chave de serviço do backend.

Fica isolado aqui para os testes substituírem estas três funções (nada de rede nos testes) e para o restante do código
nunca lidar com a chave de serviço. O navegador envia o áudio direto ao bucket por URL assinada de uso único.
"""
from __future__ import annotations

import os
from urllib.parse import quote

import security as sec


def bucket() -> str:
    return os.getenv("AURA_AUDIO_BUCKET", "aura-audio")


def _client():
    from supabase import create_client  # import tardio: os testes não precisam do pacote
    return create_client(sec.supabase_url(), sec.service_key())


def signed_upload(path: str) -> tuple[str, str | None]:
    """URL assinada (e token) para o navegador enviar UM arquivo para `path`."""
    response = _client().storage.from_(bucket()).create_signed_upload_url(path)
    data = getattr(response, "data", response)
    if isinstance(data, dict):
        url = data.get("signed_url") or data.get("signedURL")
        if url:
            return url, data.get("token")
    if hasattr(data, "token"):
        return getattr(data, "signed_url", None) or getattr(data, "signedURL", None), data.token
    raise RuntimeError("Supabase não retornou uma URL de upload assinada.")


def object_size(path: str) -> int | None:
    """Tamanho do arquivo no bucket, ou None se ele não existir."""
    url = f"{sec.supabase_url()}/storage/v1/object/info/{bucket()}/{quote(path, safe='/')}"
    status, body = sec.http_json("GET", url, sec.rest_headers(None))
    if status == 404 or (status == 400 and "not found" in str((body or {}).get("message", "")).lower()):
        return None
    if status >= 400:
        raise RuntimeError(f"Falha ao consultar o armazenamento (HTTP {status}).")
    size = (body or {}).get("size")
    if size is None:
        size = ((body or {}).get("metadata") or {}).get("size")
    return int(size) if size is not None else 0


def download(path: str, max_bytes: int = 25 * 1024 * 1024) -> bytes:
    """Baixa um arquivo do bucket (chave de serviço). Lança erro se faltar ou passar do tamanho máximo."""
    import urllib.error
    import urllib.request
    url = f"{sec.supabase_url()}/storage/v1/object/{bucket()}/{quote(path, safe='/')}"
    key = sec.service_key()
    req = urllib.request.Request(url, headers={"apikey": key, "Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            data = response.read(max_bytes + 1)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Falha ao baixar do armazenamento (HTTP {exc.code}).") from exc
    except Exception as exc:
        raise RuntimeError(f"Falha de rede: {type(exc).__name__}") from exc
    if len(data) > max_bytes:
        raise RuntimeError("Arquivo grande demais.")
    return data


def delete_objects(paths: list[str]) -> None:
    """Apaga arquivos do bucket. Lança erro se a exclusão falhar (quem chamou não deve apagar os registros)."""
    if not paths:
        return
    url = f"{sec.supabase_url()}/storage/v1/object/{bucket()}"
    status, _ = sec.http_json("DELETE", url, sec.rest_headers(None), {"prefixes": list(paths)}, timeout=30)
    if status >= 400:
        raise RuntimeError(f"Falha ao apagar do armazenamento (HTTP {status}).")
