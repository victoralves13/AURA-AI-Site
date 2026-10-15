"""Supabase simulado em memória (Auth + PostgREST mínimo) para os testes do backend.

Reproduz o que importa para a segurança:
  * leituras com token de usuário passam por um RLS simplificado: cada membro enxerga TODOS os
    vínculos (memberships) das organizações em que participa, não só os próprios;
  * leituras/escritas com a chave de serviço ignoram o RLS.
"""
import itertools
from datetime import date, datetime, timezone
import uuid
from urllib.parse import parse_qsl, urlsplit

SERVICE_KEY = "sk"
_CONTROL = {"select", "order", "limit", "offset", "on_conflict"}


class FakeSupabase:
    def __init__(self):
        self.users = {}  # token -> {id, email, confirmed}
        self.tables = {name: [] for name in ("organizations", "memberships", "membership_permissions",
                                              "invitations", "audit_log", "teams", "team_members", "meetings", "clients",
                                              "actions", "action_events", "action_outcomes", "action_feedback", "conversations", "messages", "live_sessions", "live_chunks")}
        self.calls = []  # (method, url, payload)
        self.fail = set()  # {("POST", "memberships")}: força erro 500
        self.clock = None  # ISO do "agora" das sessões ao vivo (os testes fixam)
        self.no_edit = set()  # ids de reuniões cujas ações a pessoa vê, mas não pode editar (a política real distingue)
        self._seq = itertools.count(1)

    # --- montagem de cenário -------------------------------------------------
    def add_user(self, token, user_id, email, confirmed=True):
        self.users[token] = {"id": user_id, "email": email, "confirmed": confirmed}

    def add_org(self, org_id, name="Org", created_by=None):
        self.tables["organizations"].append({"id": org_id, "name": name, "created_by": created_by, "created_at": self._ts()})

    def add_member(self, org_id, user_id, role):
        self.tables["memberships"].append({"org_id": org_id, "user_id": user_id, "role": role, "created_at": self._ts()})

    # --- regras de acesso espelhadas do SQL (as reais são testadas em tests/db/rls.test.mjs) ----------
    def _role(self, uid, org_id):
        for m in self.tables["memberships"]:
            if m["org_id"] == org_id and m["user_id"] == uid:
                return m["role"]
        return None

    def _can_read_client(self, c, uid):
        return (c.get("org_id") is None and c.get("owner_id") == uid) or (c.get("org_id") is not None and self._role(uid, c["org_id"]) is not None)

    def _can_manage_client(self, c, uid):
        return (c.get("org_id") is None and c.get("owner_id") == uid) or self._role(uid, c.get("org_id")) in ("admin", "manager")

    def _meeting_visible(self, row, uid):
        role = self._role(uid, row.get("org_id")) if row.get("org_id") else None
        return (row.get("owner_id") == uid and (row.get("org_id") is None or role is not None)) or role in ("admin", "manager")

    def _action_meeting_visible(self, action, uid):
        m = next((m for m in self.tables["meetings"] if m["id"] == action["meeting_id"]), None)
        return bool(m) and self._meeting_visible(m, uid)

    def _can_edit_actions(self, meeting, uid):  # espelha aura_private.can_edit_actions
        if meeting["id"] in self.no_edit:
            return False
        role = self._role(uid, meeting.get("org_id")) if meeting.get("org_id") else None
        return (meeting.get("owner_id") == uid and (meeting.get("org_id") is None or role is not None)) or role in ("admin", "manager")

    def _scope_error(self, meeting, client):
        if client is None:
            return 400, {"code": "23503", "message": "client_not_found"}
        if client.get("merged_into"):
            return 400, {"code": "23514", "message": "client_merged"}
        if client.get("org_id") != meeting.get("org_id") or (client.get("org_id") is None and client.get("owner_id") != meeting.get("owner_id")):
            return 400, {"code": "23514", "message": "client_scope_mismatch"}
        return None

    def _rpc(self, name, payload, uid):
        def err(msg):
            return 400, {"code": "P0001", "message": msg}
        clients = {c["id"]: c for c in self.tables["clients"]}
        meetings = self.tables["meetings"]
        if name == "merge_clients":
            s, t = clients.get(payload["p_source"]), clients.get(payload["p_target"])
            if not s or not t or not self._can_read_client(s, uid) or not self._can_read_client(t, uid):
                return err("client_not_found")
            if s["id"] == t["id"]:
                return err("same_client")
            if s.get("org_id") != t.get("org_id") or (s.get("org_id") is None and s.get("owner_id") != t.get("owner_id")):
                return err("client_scope_mismatch")
            if s.get("org_id") is not None and not self._can_manage_client(s, uid):
                return err("forbidden")
            if s.get("merged_into") or t.get("merged_into"):
                return err("already_merged")
            moved = [m for m in meetings if m.get("client_id") == s["id"]]  # definer: todas, vê ou não
            for m in moved:
                m.update(client_id=t["id"], client_link="confirmed", client_suggestion=[])
            s.update(merged_into=t["id"], merged_meeting_ids=[m["id"] for m in moved])
            t["aliases"] = sorted(set((t.get("aliases") or []) + (s.get("aliases") or []) + [s["name"]]))
            return 200, {"moved": len(moved), "target": t["id"]}
        if name == "unmerge_clients":
            s = clients.get(payload["p_source"])
            if not s or not self._can_read_client(s, uid):
                return err("client_not_found")
            if s.get("org_id") is not None and not self._can_manage_client(s, uid):
                return err("forbidden")
            if not s.get("merged_into"):
                return err("not_merged")
            target = clients[s["merged_into"]]
            ids = set(s.get("merged_meeting_ids") or [])
            s.update(merged_into=None, merged_meeting_ids=[])
            restored = [m for m in meetings if m.get("client_id") == target["id"] and m["id"] in ids]
            for m in restored:
                m["client_id"] = s["id"]
            drop = {s["name"], *(s.get("aliases") or [])}
            target["aliases"] = [a for a in (target.get("aliases") or []) if a not in drop]
            return 200, {"restored": len(restored), "client": s["id"]}
        return 404, {}

    def _actions_write(self, method, payload, uid, match):
        def err(code, msg, status=400):
            return status, {"code": code, "message": msg}
        acts = self.tables["actions"]
        events = self.tables["action_events"]

        def log(a, event, data):
            events.append({"id": next(self._seq), "action_id": a["id"], "at": self._ts(), "actor_id": uid, "event": event, "data": data})

        def member_ok(a):
            return a.get("assignee_user_id") is None or (a.get("org_id") is not None and self._role(a["assignee_user_id"], a["org_id"]))
        if method == "POST":
            m = next((m for m in self.tables["meetings"] if m["id"] == payload.get("meeting_id")), None)
            if not m or not self._can_edit_actions(m, uid):
                return 403, {"message": "new row violates row-level security policy"}
            row = {"status": "open", "source": "user", "source_key": None, "basis": None, "evidence": {}, "assignee_text": None,
                   "assignee_user_id": None, "due_text": None, "due_date": None, **payload,
                   "id": str(uuid.uuid4()), "org_id": m.get("org_id"), "created_by": uid, "created_at": self._ts(), "completed_at": None}
            if row["status"] == "done":
                row["completed_at"] = self._ts()
            if not 1 <= len(row.get("text") or "") <= 1000:
                return err("23514", "check constraint")
            if row["source_key"] and any(a["meeting_id"] == row["meeting_id"] and a["source_key"] == row["source_key"] for a in acts):
                return err("23505", "duplicate key value violates unique constraint", 409)
            if not member_ok(row):
                return err("23514", "assignee_not_member")
            acts.append(row)
            log(row, "created", {"source": row["source"], "status": row["status"]})
            return 201, [dict(row)]
        hit = [a for a in acts if self._action_meeting_visible(a, uid) and match(a)]
        meetings = {m["id"]: m for m in self.tables["meetings"]}
        hit = [a for a in hit if self._can_edit_actions(meetings[a["meeting_id"]], uid)]
        if method == "DELETE":
            hit = [a for a in hit if a["source"] == "user"]
            for a in hit:
                acts.remove(a)
            return 200, [dict(a) for a in hit]
        if method == "PATCH":
            for a in hit:
                for key in ("meeting_id", "org_id", "source", "source_key"):
                    if key in payload and payload[key] != a.get(key):
                        return err("23514", "action_immutable")
                if a["source"] == "ai" and any(k in payload and payload[k] != a.get(k) for k in ("text", "basis", "evidence")):
                    return err("23514", "action_text_locked")
                if payload.get("status") not in (None, "open", "in_progress", "done", "cancelled"):
                    return err("23514", "check constraint")
                if "assignee_user_id" in payload and not member_ok({**a, **payload}):
                    return err("23514", "assignee_not_member")
            for a in hit:
                before = dict(a)
                a.update(payload)
                if a["status"] != before["status"]:
                    a["completed_at"] = self._ts() if a["status"] == "done" else None
                    log(a, "status", {"from": before["status"], "to": a["status"]})
                if (a["assignee_text"], a["assignee_user_id"]) != (before["assignee_text"], before["assignee_user_id"]):
                    log(a, "assignee", {"from_text": before["assignee_text"], "to_text": a["assignee_text"]})
                if (a["due_text"], a["due_date"]) != (before["due_text"], before["due_date"]):
                    log(a, "due", {"from_date": before["due_date"], "to_date": a["due_date"]})
                if a["text"] != before["text"]:
                    log(a, "text", {"from": before["text"], "to": a["text"]})
            return 200, [dict(a) for a in hit]
        return 405, {}

    def _outcome_write(self, payload, uid):
        a = next((a for a in self.tables["actions"] if a["id"] == payload.get("action_id")), None)
        m = next((m for m in self.tables["meetings"] if a and m["id"] == a["meeting_id"]), None)
        if not a or not m or not self._can_edit_actions(m, uid):
            return 403, {"message": "new row violates row-level security policy"}
        if not (a["status"] in ("done", "cancelled") or (a.get("due_date") and str(a["due_date"]) < date.today().isoformat())):
            return 400, {"code": "23514", "message": "action_not_closed"}
        if payload.get("effectiveness") not in ("worked", "partial", "not_worked", "uncertain") or not payload.get("result"):
            return 400, {"code": "23514", "message": "check constraint"}
        row = {"observed_at": date.today().isoformat(), **payload, "id": str(uuid.uuid4()), "org_id": a.get("org_id"),
               "recorded_by": uid, "created_at": self._ts()}
        self.tables["action_outcomes"].append(row)
        self.tables["action_events"].append({"id": next(self._seq), "action_id": a["id"], "at": self._ts(), "actor_id": uid,
                                             "event": "outcome", "data": {"effectiveness": row["effectiveness"]}})
        return 201, [dict(row)]

    def _live_visible(self, s, uid):  # privada: só o dono (e, em organização, enquanto for membro)
        return s.get("owner_id") == uid and (s.get("org_id") is None or self._role(uid, s["org_id"]) is not None)

    def _live_ts(self):  # relógio controlável pelos testes (self.clock); sem ele, o padrão do simulador
        return self.clock or self._ts()

    def _live_write(self, table, method, payload, uid, match):
        sessions, chunks = self.tables["live_sessions"], self.tables["live_chunks"]
        reserved = ("meeting_id", "ended_at", "duration_seconds", "audio_deleted_at", "error", "last_chunk_at")
        if table == "live_sessions":
            if method == "POST":
                row = {"status": "recording", "alerts_enabled": True, "title": "Reunião ao vivo", "context": "Outro", "client_name": None, "meeting_id": None,
                       "ended_at": None, "duration_seconds": 0, "audio_deleted_at": None, "error": None, "last_chunk_at": None, **payload,
                       "id": str(uuid.uuid4()), "started_at": self._live_ts(), "created_at": self._live_ts(), "updated_at": self._live_ts()}
                if row.get("owner_id") != uid or not self._live_visible(row, uid):
                    return 403, {"message": "new row violates row-level security policy"}
                if not row.get("consent_at"):
                    return 400, {"code": "23502", "message": "null value in column consent_at"}
                if row["status"] != "recording" or any(payload.get(k) for k in reserved):
                    return 403, {"code": "23514", "message": "live_field_reserved"}
                if len([s for s in sessions if s["owner_id"] == uid and s["status"] in ("recording", "paused")]) >= 3:
                    return 400, {"code": "23514", "message": "too_many_active_sessions"}
                sessions.append(row)
                return 201, [dict(row)]
            hit = [s for s in sessions if self._live_visible(s, uid) and match(s)]
            if method == "PATCH":
                if any(k in payload for k in reserved) or any(k in payload for k in ("owner_id", "org_id", "consent_at", "started_at")):
                    return 400, {"code": "23514", "message": "live_field_reserved"}
                to = payload.get("status")
                for s in hit:
                    if to and to != s["status"]:
                        ok = {("recording", "paused"), ("paused", "recording"), ("recording", "processing"), ("paused", "processing"),
                              ("abandoned", "processing"), ("failed", "processing")}
                        if (s["status"], to) not in ok:
                            return 400, {"code": "23514", "message": "invalid_transition"}
                for s in hit:
                    s.update(payload)
                    s["updated_at"] = self._live_ts()
                return 200, [dict(s) for s in hit]
            if method == "DELETE":
                for s in hit:
                    sessions.remove(s)
                    self.tables["live_chunks"] = [c for c in self.tables["live_chunks"] if c["session_id"] != s["id"]]
                return 200, [dict(s) for s in hit]
            return 405, {}
        if method == "POST":
            s = next((s for s in sessions if s["id"] == payload.get("session_id")), None)
            if not s or not self._live_visible(s, uid):
                return 403, {"message": "new row violates row-level security policy"}
            if s["status"] not in ("recording", "paused", "processing") or s.get("audio_deleted_at"):
                return 400, {"code": "23514", "message": "session_closed"}
            if not 0 <= payload.get("seq", -1) <= 399 or not 0 <= payload.get("duration_ms", -1) <= 120000:
                return 400, {"code": "23514", "message": "check constraint"}
            if any(c["session_id"] == s["id"] and c["seq"] == payload["seq"] for c in chunks):
                return 409, {"code": "23505", "message": "duplicate key value violates unique constraint"}
            row = {"status": "uploaded", "text": None, "segments": [], "attempts": 0, "error": None, **payload, "id": str(uuid.uuid4()),
                   "owner_id": s["owner_id"], "created_at": self._live_ts(), "transcribed_at": None}
            if payload.get("status", "uploaded") != "uploaded" or payload.get("text"):
                return 403, {"code": "23514", "message": "live_field_reserved"}
            chunks.append(row)
            return 201, [dict(row)]
        return 405, {}

    def _conv_visible(self, conv, uid):  # privada: só o dono, e (em organização) enquanto puder usar o chat
        if conv.get("owner_id") != uid:
            return False
        return conv.get("org_id") is None or self._role(uid, conv["org_id"]) is not None

    def _chat_write(self, table, method, payload, uid, match):
        convs, msgs = self.tables["conversations"], self.tables["messages"]
        if table == "conversations":
            if method == "POST":
                row = {**payload, "id": str(uuid.uuid4()), "created_at": self._ts(), "last_message_at": self._ts(), "scope": payload.get("scope") or {}}
                if row.get("owner_id") != uid or not self._conv_visible(row, uid):
                    return 403, {"message": "new row violates row-level security policy"}
                if not 1 <= len(row.get("title") or "") <= 200:
                    return 400, {"code": "23514", "message": "check constraint"}
                if len([c for c in convs if c["owner_id"] == uid]) >= 500:
                    return 400, {"code": "23514", "message": "too_many_conversations"}
                convs.append(row)
                return 201, [dict(row)]
            hit = [c for c in convs if self._conv_visible(c, uid) and match(c)]
            if method == "PATCH":
                if any(k in payload for k in ("owner_id", "org_id", "scope")):
                    return 400, {"code": "23514", "message": "conversation_immutable"}
                for c in hit:
                    c.update(payload)
                return 200, [dict(c) for c in hit]
            if method == "DELETE":
                for c in hit:
                    convs.remove(c)
                    self.tables["messages"] = [m for m in self.tables["messages"] if m["conversation_id"] != c["id"]]
                return 200, [dict(c) for c in hit]
            return 405, {}
        if method == "POST":
            conv = next((c for c in convs if c["id"] == payload.get("conversation_id")), None)
            if not conv or not self._conv_visible(conv, uid) or payload.get("role") != "user":
                return 403, {"message": "new row violates row-level security policy"}
            if len([m for m in msgs if m["conversation_id"] == conv["id"]]) >= 400:
                return 400, {"code": "23514", "message": "conversation_full"}
            row = {**payload, "id": str(uuid.uuid4()), "owner_id": conv["owner_id"], "sources": [], "evidence_level": None, "created_at": self._ts()}
            msgs.append(row)
            conv["last_message_at"] = self._ts()
            return 201, [dict(row)]
        return 405, {}

    def _feedback_write(self, method, payload, uid, match):
        votes = self.tables["action_feedback"]
        if method == "POST":
            a = next((a for a in self.tables["actions"] if a["id"] == payload.get("action_id")), None)
            if not a or not self._action_meeting_visible(a, uid):
                return 403, {"message": "new row violates row-level security policy"}
            if a["source"] != "ai":
                return 400, {"code": "23514", "message": "feedback_only_ai"}
            if payload.get("rating") not in ("useful", "not_useful"):
                return 400, {"code": "23514", "message": "check constraint"}
            if any(v["action_id"] == a["id"] and v["user_id"] == uid for v in votes):
                return 409, {"code": "23505", "message": "duplicate key value violates unique constraint"}
            row = {**payload, "id": str(uuid.uuid4()), "user_id": uid, "org_id": a.get("org_id"), "created_at": self._ts()}
            votes.append(row)
            return 201, [dict(row)]
        acts = {a["id"]: a for a in self.tables["actions"]}
        hit = [v for v in votes if v["user_id"] == uid and match(v) and self._action_meeting_visible(acts[v["action_id"]], uid)]
        if method == "PATCH":
            for v in hit:
                v.update(payload)
            return 200, [dict(v) for v in hit]
        if method == "DELETE":
            for v in hit:
                votes.remove(v)
            return 200, [dict(v) for v in hit]
        return 405, {}

    def rows(self, table, **where):
        return [r for r in self.tables[table] if all(r.get(k) == v for k, v in where.items())]

    def actions(self):
        return [r["action"] for r in self.tables["audit_log"]]

    def _ts(self):
        return "2026-10-14T12:%02d:00+00:00" % (next(self._seq) % 60)

    # --- HTTP ------------------------------------------------------------------
    def _caller(self, headers):
        token = headers.get("Authorization", "").split(" ")[-1]
        return token, self.users.get(token)

    def __call__(self, method, url, headers, payload=None, timeout=15):
        self.calls.append((method, url, payload))
        if "/auth/v1/user" in url:
            _, u = self._caller(headers)
            if not u:
                return 401, {"msg": "invalid"}
            body = {"id": u["id"], "email": u["email"]}
            if u["confirmed"]:
                body["email_confirmed_at"] = "2026-10-01T00:00:00Z"
            return 200, body
        if "/auth/v1/admin/users/" in url:
            if headers.get("Authorization", "").split(" ")[-1] != SERVICE_KEY:
                return 401, {}
            uid = url.rsplit("/", 1)[1]
            for u in self.users.values():
                if u["id"] == uid:
                    return 200, {"id": uid, "email": u["email"]}
            return 404, {}
        if "/rest/v1/" not in url:
            return 404, {}

        parts = urlsplit(url.split("/rest/v1/")[1])
        table = parts.path
        query = parse_qsl(parts.query, keep_blank_values=True)
        token, caller = self._caller(headers)
        is_service = token == SERVICE_KEY
        if not is_service and caller is None:
            return 401, {"message": "JWT required"}
        if (method, table) in self.fail:
            return 500, {"message": "boom"}
        if table.startswith("rpc/"):
            return self._rpc(table[4:], payload or {}, caller["id"]) if not is_service else (403, {})
        if table not in self.tables:
            return 404, {}

        def match(row):
            for key, value in query:
                if key in _CONTROL:
                    continue
                if value.startswith("eq."):
                    if str(row.get(key)) != value[3:]:
                        return False
                elif value.startswith("in.("):
                    if str(row.get(key)) not in value[4:-1].split(","):
                        return False
                elif value.startswith("lt."):
                    if not (row.get(key) is not None and str(row.get(key)) < value[3:]):
                        return False
                elif value == "is.false":
                    if row.get(key) not in (False, None):
                        return False
                elif value == "is.null":
                    if row.get(key) is not None:
                        return False
                elif value == "not.is.null":
                    if row.get(key) is None:
                        return False
                elif value.startswith("gt."):
                    if not str(row.get(key) or "") > value[3:]:
                        return False
                elif value.startswith("gte."):
                    if not str(row.get(key) or "") >= value[4:]:
                        return False
                elif value.startswith("like."):
                    if not str(row.get(key) or "").startswith(value[5:].rstrip("*")):
                        return False
            return True

        def visible(row):  # RLS simplificado para token de usuário
            if is_service:
                return True
            uid = caller["id"]
            if table == "memberships":
                return any(m["org_id"] == row["org_id"] and m["user_id"] == uid for m in self.tables["memberships"])
            if table == "membership_permissions":
                return row["user_id"] == uid
            if table == "meetings":  # dono (enquanto for membro) ou administrador/gestor da organização
                role = self._role(uid, row.get("org_id")) if row.get("org_id") else None
                return (row.get("owner_id") == uid and (row.get("org_id") is None or role is not None)) or role in ("admin", "manager")
            if table == "clients":
                return self._can_read_client(row, uid)
            if table == "actions":
                return self._action_meeting_visible(row, uid)
            if table == "live_sessions":
                return self._live_visible(row, uid)
            if table == "live_chunks":
                s = next((s for s in self.tables["live_sessions"] if s["id"] == row["session_id"]), None)
                return bool(s) and self._live_visible(s, uid)
            if table == "conversations":
                return self._conv_visible(row, uid)
            if table == "messages":
                conv = next((c for c in self.tables["conversations"] if c["id"] == row["conversation_id"]), None)
                return bool(conv) and self._conv_visible(conv, uid)
            if table in ("action_events", "action_outcomes", "action_feedback"):
                act = next((a for a in self.tables["actions"] if a["id"] == row["action_id"]), None)
                return bool(act) and self._action_meeting_visible(act, uid)
            return False

        if method == "GET":
            out = [dict(r) for r in self.tables[table] if visible(r) and match(r)]
            select = dict(query).get("select", "")
            if table == "memberships" and "organizations(" in select:
                for r in out:
                    org = next((o for o in self.tables["organizations"] if o["id"] == r["org_id"]), {})
                    r["organizations"] = {"id": org.get("id"), "name": org.get("name")}
            if table == "actions" and "meetings(" in select:
                for r in out:
                    m = next((m for m in self.tables["meetings"] if m["id"] == r["meeting_id"]), {})
                    r["meetings"] = {k: m.get(k) for k in ("meeting_title", "client_name", "client_id", "created_at")}
            if table == "actions" and "action_outcomes(" in select:
                for r in out:
                    r["action_outcomes"] = [dict(o) for o in self.tables["action_outcomes"] if o["action_id"] == r["id"]]
            if table == "actions" and "action_feedback(" in select:
                for r in out:
                    r["action_feedback"] = [{"user_id": v["user_id"], "rating": v["rating"]} for v in self.tables["action_feedback"] if v["action_id"] == r["id"]]
            if table == "actions" and "(" in select:
                select = "*" if select.startswith("*") else ""
            if select and select != "*":  # projeção de colunas, como o PostgREST faz
                cols, depth, cur = [], 0, ""
                for ch in select:
                    depth += (ch == "(") - (ch == ")")
                    if ch == "," and depth == 0:
                        cols.append(cur)
                        cur = ""
                    else:
                        cur += ch
                cols.append(cur)
                keep = {c.split("(")[0] for c in cols}
                out = [{k: v for k, v in r.items() if k in keep} for r in out]
            order = dict(query).get("order", "")
            if order.startswith("seq."):  # ordenação por número (pedaços ao vivo)
                out.sort(key=lambda r: r.get("seq", 0), reverse=order.endswith(".desc"))
            elif order.endswith(".desc"):  # a ordem de inserção é a cronológica
                out.reverse()
            limit = dict(query).get("limit")
            return 200, out[: int(limit)] if limit else out

        if table == "meetings" and method == "POST" and not is_service:  # o RLS exige dono = usuário do token
            row = dict(payload, id=str(uuid.uuid4()), created_at=self._ts())
            if row.get("owner_id") != caller["id"]:
                return 403, {"message": "new row violates row-level security policy"}
            self.tables["meetings"].append(row)
            return 201, [dict(row)]

        if table in ("live_sessions", "live_chunks") and not is_service:
            return self._live_write(table, method, payload or {}, caller["id"], match)
        if table in ("conversations", "messages") and not is_service:
            return self._chat_write(table, method, payload or {}, caller["id"], match)
        if table == "action_feedback" and not is_service:
            return self._feedback_write(method, payload or {}, caller["id"], match)
        if table == "action_outcomes" and not is_service and method == "POST":
            return self._outcome_write(payload or {}, caller["id"])
        if table == "actions" and not is_service:
            return self._actions_write(method, payload or {}, caller["id"], match)
        if table == "clients" and not is_service and method == "POST":
            uid = caller["id"]
            row = dict(payload, id=str(uuid.uuid4()), created_at=self._ts(), merged_into=None, merged_meeting_ids=[])
            row.setdefault("aliases", [])
            if not ((row.get("org_id") is None and row.get("owner_id") == uid) or (row.get("org_id") is not None and self._role(uid, row["org_id"]))):
                return 403, {"message": "new row violates row-level security policy"}
            if any(c.get("org_id") == row.get("org_id") and c["normalized_name"] == row["normalized_name"]
                   and (row.get("org_id") is not None or c.get("owner_id") == row.get("owner_id")) for c in self.tables["clients"]):
                return 409, {"code": "23505", "message": "duplicate key value violates unique constraint"}
            self.tables["clients"].append(row)
            return 201, [dict(row)]
        if table in ("clients", "meetings") and not is_service and method == "PATCH":
            uid = caller["id"]
            hit = [r for r in self.tables[table] if visible(r) and match(r)]
            if table == "meetings":  # só o dono ou quem gerencia a organização altera (política meetings_update)
                hit = [r for r in hit if r.get("owner_id") == uid or self._role(uid, r.get("org_id")) in ("admin", "manager")]
            clients = {c["id"]: c for c in self.tables["clients"]}
            for r in hit:
                if table == "meetings" and payload.get("client_id"):
                    problem = self._scope_error(r, clients.get(payload["client_id"]))
                    if problem:
                        return problem
            for r in hit:
                r.update(payload)
            return 200, [dict(r) for r in hit]

        if not is_service:  # escritas de usuário nas tabelas de organização não são permitidas
            return 403, {"message": "denied"}

        if method == "POST":
            row = dict(payload)
            row.setdefault("created_at", self._ts())
            if table in ("organizations", "invitations", "teams", "messages"):
                row.setdefault("id", str(uuid.uuid4()))
            if table == "audit_log":
                row.setdefault("id", next(self._seq))
                row.setdefault("at", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"))
            if table == "memberships" and any(m["org_id"] == row["org_id"] and m["user_id"] == row["user_id"] for m in self.tables[table]):
                return 409, {"message": "duplicate"}
            if table == "invitations":
                row.setdefault("accepted_at", None)
            self.tables[table].append(row)
            return 201, [dict(row)]
        if method == "PATCH":
            hit = [r for r in self.tables[table] if match(r)]
            for r in hit:
                r.update(payload)
            return 200, [dict(r) for r in hit]
        if method == "DELETE":
            self.tables[table] = [r for r in self.tables[table] if not match(r)]
            return 204, None
        return 405, {}
