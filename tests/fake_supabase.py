"""Supabase simulado em memória (Auth + PostgREST mínimo) para os testes do backend.

Reproduz o que importa para a segurança:
  * leituras com token de usuário passam por um RLS simplificado: cada membro enxerga TODOS os
    vínculos (memberships) das organizações em que participa, não só os próprios;
  * leituras/escritas com a chave de serviço ignoram o RLS.
"""
import itertools
import uuid
from urllib.parse import parse_qsl, urlsplit

SERVICE_KEY = "sk"
_CONTROL = {"select", "order", "limit", "offset", "on_conflict"}


class FakeSupabase:
    def __init__(self):
        self.users = {}  # token -> {id, email, confirmed}
        self.tables = {name: [] for name in ("organizations", "memberships", "membership_permissions",
                                              "invitations", "audit_log", "teams", "team_members", "meetings", "clients")}
        self.calls = []  # (method, url, payload)
        self.fail = set()  # {("POST", "memberships")}: força erro 500
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
            return False

        if method == "GET":
            out = [dict(r) for r in self.tables[table] if visible(r) and match(r)]
            select = dict(query).get("select", "")
            if table == "memberships" and "organizations(" in select:
                for r in out:
                    org = next((o for o in self.tables["organizations"] if o["id"] == r["org_id"]), {})
                    r["organizations"] = {"id": org.get("id"), "name": org.get("name")}
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
            limit = dict(query).get("limit")
            return 200, out[: int(limit)] if limit else out

        if table == "meetings" and method == "POST" and not is_service:  # o RLS exige dono = usuário do token
            row = dict(payload, id=str(uuid.uuid4()), created_at=self._ts())
            if row.get("owner_id") != caller["id"]:
                return 403, {"message": "new row violates row-level security policy"}
            self.tables["meetings"].append(row)
            return 201, [dict(row)]

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
            if table in ("organizations", "invitations", "teams"):
                row.setdefault("id", str(uuid.uuid4()))
            if table == "audit_log":
                row.setdefault("id", next(self._seq))
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
