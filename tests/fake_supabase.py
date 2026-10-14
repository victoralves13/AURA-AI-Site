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
                                              "invitations", "audit_log", "teams", "team_members", "meetings")}
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
            if table == "meetings":  # dono, e só enquanto for membro da organização da reunião
                member = any(m["org_id"] == row.get("org_id") and m["user_id"] == uid for m in self.tables["memberships"])
                return row.get("owner_id") == uid and (row.get("org_id") is None or member)
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
