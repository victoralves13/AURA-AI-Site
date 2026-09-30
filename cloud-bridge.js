/* AURA cloud bridge: keeps the existing analysis UI contract while routing audio through signed Supabase storage. */
(()=> {
  const originalFetch = window.fetch.bind(window);
  window.fetch = async (input, init={}) => {
    const url = typeof input === "string" ? input : input?.url || "";
    if (!url.endsWith("/api/analyze-audio") || !(init.body instanceof FormData)) {
      return originalFetch(input, init);
    }
    const file = init.body.get("file");
    if (!(file instanceof File)) return originalFetch(input, init);
    const base = window.AURA_API_BASE || location.origin;
    const prep = await originalFetch(base + "/api/audio-upload-url", {
      method: "POST",
      headers: {"Content-Type":"application/json"},
      body: JSON.stringify({file_name:file.name, content_type:file.type || "audio/mpeg", size_bytes:file.size})
    });
    const meta = await prep.json();
    if (!prep.ok) return new Response(JSON.stringify(meta), {status:prep.status, headers:{"Content-Type":"application/json"}});
    const upload = await originalFetch(meta.signed_url, {
      method: "PUT",
      headers: {"Content-Type":file.type || "application/octet-stream"},
      body:file
    });
    if (!upload.ok) return new Response(JSON.stringify({detail:"Falha no upload seguro do áudio."}), {status:502, headers:{"Content-Type":"application/json"}});
    return originalFetch(base + "/api/analyze-stored-audio", {
      method:"POST",
      headers:{"Content-Type":"application/json"},
      body:JSON.stringify({path:meta.path,file_name:file.name,client_name:"Cliente não identificado",context:window.AURA_SELECTED_CONTEXT||"Outro"})
    });
  };
})();