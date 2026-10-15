"""Testes de organizações: membros, papéis e convites (sem rede)."""
import hashlib
import sys
import unittest
from pathlib import Path

from tests.backend.core.test_security import Base, ORG1, ORG2, UA, UB  # noqa: E402

UC = "cccccccc-cccc-cccc-cccc-cccccccccccc"
UD = "dddddddd-dddd-dddd-dddd-dddddddddddd"
UE = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"
UF = "ffffffff-ffff-ffff-ffff-ffffffffffff"
FAKE_ID = "99999999-9999-9999-9999-999999999999"


class OrgBase(Base):
    """ORG1: UA admin, UB gestor, UC colaborador. ORG2: UD admin. UE sem organização. UF sem e-mail confirmado."""

    def setUp(self):
        super().setUp()
        f = self.fake
        f.tables["memberships"].clear()
        f.add_user("tok-c", UC, "c@x.com")
        f.add_user("tok-d", UD, "d@x.com")
        f.add_user("tok-e", UE, "e@x.com")
        f.add_user("tok-f", UF, "f@x.com", confirmed=False)
        for org, user, role in [(ORG1, UA, "admin"), (ORG1, UB, "manager"), (ORG1, UC, "member"), (ORG2, UD, "admin")]:
            f.add_member(org, user, role)

    def role_of(self, org, user):
        rows = self.fake.rows("memberships", org_id=org, user_id=user)
        return rows[0]["role"] if rows else None

    def invite(self, tok="tok-a", org=ORG1, email="e@x.com", role="member"):
        return self.client.post(f"/api/orgs/{org}/invitations", headers=self.h(tok), json={"email": email, "role": role})

    def accept(self, token, tok="tok-e"):
        return self.client.post("/api/invitations/accept", headers=self.h(tok), json={"token": token})


class Acesso(OrgBase):
    def test_tudo_exige_login(self):
        c = self.client
        rotas = [
            c.get(f"/api/orgs/{ORG1}/members"), c.patch(f"/api/orgs/{ORG1}/members/{UC}", json={"role": "admin"}),
            c.delete(f"/api/orgs/{ORG1}/members/{UC}"), c.get(f"/api/orgs/{ORG1}/invitations"),
            c.post(f"/api/orgs/{ORG1}/invitations", json={"email": "e@x.com"}),
            c.delete(f"/api/orgs/{ORG1}/invitations/{FAKE_ID}"), c.post("/api/invitations/accept", json={"token": "x" * 30}),
        ]
        self.assertEqual([r.status_code for r in rotas], [401] * len(rotas))

    def test_so_administrador_gerencia(self):
        for tok in ("tok-b", "tok-c", "tok-e", "tok-d"):  # gestor, colaborador, sem org, admin de OUTRA org
            self.assertEqual(self.client.get(f"/api/orgs/{ORG1}/members", headers=self.h(tok)).status_code, 403, tok)
            self.assertEqual(self.client.get(f"/api/orgs/{ORG1}/invitations", headers=self.h(tok)).status_code, 403, tok)
            self.assertEqual(self.invite(tok).status_code, 403, tok)
            self.assertEqual(self.client.patch(f"/api/orgs/{ORG1}/members/{UC}", headers=self.h(tok), json={"role": "admin"}).status_code, 403, tok)
            # remover OUTRA pessoa (o administrador) exige members.manage; remover a si mesma é "sair", testado à parte
            self.assertEqual(self.client.delete(f"/api/orgs/{ORG1}/members/{UA}", headers=self.h(tok)).status_code, 403, tok)
        self.assertEqual(self.role_of(ORG1, UC), "member")
        self.assertEqual(self.role_of(ORG1, UA), "admin")
        self.assertEqual(self.fake.tables["invitations"], [])

    def test_identificadores_invalidos(self):
        self.assertEqual(self.client.get("/api/orgs/nao-e-uuid/members", headers=self.h()).status_code, 400)
        self.assertEqual(self.client.patch(f"/api/orgs/{ORG1}/members/xx", headers=self.h(), json={"role": "admin"}).status_code, 400)

    def test_me_mostra_permissoes_do_papel(self):
        admin = self.client.get("/api/me", headers=self.h("tok-a")).json()["organizations"][0]
        colab = self.client.get("/api/me", headers=self.h("tok-c")).json()["organizations"][0]
        self.assertEqual((admin["role"], colab["role"]), ("admin", "member"))
        self.assertIn("members.manage", admin["permissions"])
        self.assertNotIn("members.manage", colab["permissions"])


class Membros(OrgBase):
    def test_lista_com_emails(self):
        r = self.client.get(f"/api/orgs/{ORG1}/members", headers=self.h())
        self.assertEqual(r.status_code, 200, r.text)
        ms = {m["user_id"]: m for m in r.json()["members"]}
        self.assertEqual(set(ms), {UA, UB, UC})  # nada da outra organização
        self.assertEqual(ms[UC]["email"], "c@x.com")
        self.assertTrue(ms[UA]["is_you"])
        self.assertNotIn(UD, ms)

    def test_mudar_papel(self):
        r = self.client.patch(f"/api/orgs/{ORG1}/members/{UC}", headers=self.h(), json={"role": "manager"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.role_of(ORG1, UC), "manager")
        self.assertIn("org.member.role", self.fake.actions())
        self.assertEqual(self.client.patch(f"/api/orgs/{ORG1}/members/{UC}", headers=self.h(), json={"role": "dono"}).status_code, 400)
        self.assertEqual(self.client.patch(f"/api/orgs/{ORG1}/members/{FAKE_ID}", headers=self.h(), json={"role": "admin"}).status_code, 404)

    def test_admin_de_outra_org_nao_toca_nesta(self):
        self.assertEqual(self.client.patch(f"/api/orgs/{ORG1}/members/{UC}", headers=self.h("tok-d"), json={"role": "admin"}).status_code, 403)
        self.assertEqual(self.client.patch(f"/api/orgs/{ORG2}/members/{UC}", headers=self.h("tok-d"), json={"role": "admin"}).status_code, 404)  # UC não é membro da ORG2
        self.assertEqual(self.role_of(ORG1, UC), "member")

    def test_nunca_sem_administrador(self):
        # único admin: não pode se rebaixar nem sair
        r = self.client.patch(f"/api/orgs/{ORG1}/members/{UA}", headers=self.h(), json={"role": "member"})
        self.assertEqual(r.status_code, 409)
        self.assertEqual(self.client.delete(f"/api/orgs/{ORG1}/members/{UA}", headers=self.h()).status_code, 409)
        self.assertEqual(self.role_of(ORG1, UA), "admin")
        # com dois admins, pode
        self.client.patch(f"/api/orgs/{ORG1}/members/{UB}", headers=self.h(), json={"role": "admin"})
        self.assertEqual(self.client.patch(f"/api/orgs/{ORG1}/members/{UA}", headers=self.h(), json={"role": "member"}).status_code, 200)
        self.assertEqual(self.client.delete(f"/api/orgs/{ORG1}/members/{UB}", headers=self.h("tok-b")).status_code, 409)  # agora UB é o último

    def test_remover_membro_e_sair(self):
        self.assertEqual(self.client.delete(f"/api/orgs/{ORG1}/members/{UC}", headers=self.h()).status_code, 200)
        self.assertIsNone(self.role_of(ORG1, UC))
        self.assertIn("org.member.remove", self.fake.actions())
        # colaborador sai por conta própria
        self.fake.add_member(ORG1, UC, "member")
        self.assertEqual(self.client.delete(f"/api/orgs/{ORG1}/members/{UC}", headers=self.h("tok-c")).status_code, 200)
        self.assertIn("org.member.leave", self.fake.actions())
        # quem não participa não consegue "sair"
        self.assertEqual(self.client.delete(f"/api/orgs/{ORG1}/members/{UE}", headers=self.h("tok-e")).status_code, 404)
        # e não consegue remover outros
        self.assertEqual(self.client.delete(f"/api/orgs/{ORG1}/members/{UB}", headers=self.h("tok-e")).status_code, 403)
        self.assertEqual(self.role_of(ORG1, UB), "manager")


class Convites(OrgBase):
    def test_criar_guarda_so_o_hash(self):
        r = self.invite(email="  Pessoa@X.com ", role="manager")
        self.assertEqual(r.status_code, 200, r.text)
        token = r.json()["token"]
        self.assertGreaterEqual(len(token), 40)
        row = self.fake.tables["invitations"][0]
        self.assertEqual(row["email"], "pessoa@x.com")
        self.assertEqual(row["token_hash"], hashlib.sha256(token.encode()).hexdigest())
        self.assertNotIn(token, str(self.fake.tables))  # o token não está em lugar nenhum do banco
        self.assertEqual(row["invited_by"], UA)
        self.assertNotIn(token, str(self.fake.tables["audit_log"]))
        self.assertNotIn("pessoa@x.com", str(self.fake.tables["audit_log"]))  # auditoria sem e-mail
        self.assertIn("org.invite.create", self.fake.actions())

    def test_validacoes(self):
        self.assertEqual(self.invite(email="sem-arroba").status_code, 400)
        self.assertEqual(self.invite(email="a" * 300 + "@x.com").status_code, 400)
        self.assertEqual(self.invite(role="superadmin").status_code, 400)
        self.assertEqual(self.fake.tables["invitations"], [])

    def test_novo_convite_substitui_o_anterior(self):
        old = self.invite().json()["token"]
        new = self.invite(role="manager").json()["token"]
        self.assertEqual(len(self.fake.tables["invitations"]), 1)
        self.assertEqual(self.accept(old).status_code, 404)  # o antigo deixou de valer
        self.assertEqual(self.accept(new).status_code, 200)
        self.assertEqual(self.role_of(ORG1, UE), "manager")

    def test_limite_de_pendentes(self):
        for i in range(50):
            self.fake.tables["invitations"].append({"id": f"i{i}", "org_id": ORG1, "email": f"p{i}@x.com", "role": "member",
                                                    "token_hash": f"h{i}", "accepted_at": None, "expires_at": "2999-01-01T00:00:00+00:00"})
        self.assertEqual(self.invite().status_code, 429)

    def test_listar_nao_expoe_token_nem_hash(self):
        self.invite()
        r = self.client.get(f"/api/orgs/{ORG1}/invitations", headers=self.h()).json()["invitations"]
        self.assertEqual(len(r), 1)
        self.assertFalse(r[0]["expired"])
        self.assertTrue({"token", "token_hash"}.isdisjoint(r[0]))
        self.fake.tables["invitations"][0]["expires_at"] = "2020-01-01T00:00:00+00:00"
        self.assertTrue(self.client.get(f"/api/orgs/{ORG1}/invitations", headers=self.h()).json()["invitations"][0]["expired"])

    def test_revogar(self):
        token = self.invite().json()["token"]
        inv_id = self.fake.tables["invitations"][0]["id"]
        self.assertEqual(self.client.delete(f"/api/orgs/{ORG2}/invitations/{inv_id}", headers=self.h("tok-d")).status_code, 200)  # admin da ORG2: não encontra o da ORG1
        self.assertEqual(len(self.fake.tables["invitations"]), 1)
        self.assertEqual(self.client.delete(f"/api/orgs/{ORG1}/invitations/{inv_id}", headers=self.h()).status_code, 200)
        self.assertEqual(self.fake.tables["invitations"], [])
        self.assertEqual(self.accept(token).status_code, 404)
        self.assertIn("org.invite.revoke", self.fake.actions())


class Aceite(OrgBase):
    def test_aceitar_cria_vinculo_uma_unica_vez(self):
        token = self.invite(role="manager").json()["token"]
        r = self.accept(token)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["organization"]["role"], "manager")
        self.assertEqual(self.role_of(ORG1, UE), "manager")
        self.assertIsNotNone(self.fake.tables["invitations"][0]["accepted_at"])
        self.assertIn("org.invite.accept", self.fake.actions())
        self.assertEqual(self.accept(token).status_code, 404)  # uso único
        self.assertEqual(len(self.fake.rows("memberships", org_id=ORG1, user_id=UE)), 1)
        me = self.client.get("/api/me", headers=self.h("tok-e")).json()["organizations"]
        self.assertEqual([o["id"] for o in me], [ORG1])

    def test_so_o_e_mail_convidado_aceita(self):
        token = self.invite(email="e@x.com").json()["token"]
        r = self.accept(token, tok="tok-c")  # outra pessoa, com o link vazado
        self.assertEqual(r.status_code, 403)
        self.assertIsNone(self.role_of(ORG1, UE))
        self.assertIsNone(self.fake.tables["invitations"][0]["accepted_at"])  # continua válido para o dono do e-mail
        self.assertEqual(self.accept(token).status_code, 200)

    def test_e_mail_nao_confirmado_nao_aceita(self):
        token = self.invite(email="f@x.com").json()["token"]
        self.assertEqual(self.accept(token, tok="tok-f").status_code, 403)
        self.assertIsNone(self.role_of(ORG1, UF))

    def test_expirado_e_invalido(self):
        token = self.invite().json()["token"]
        self.fake.tables["invitations"][0]["expires_at"] = "2020-01-01T00:00:00+00:00"
        self.assertEqual(self.accept(token).status_code, 410)
        self.assertEqual(self.accept("curto").status_code, 400)
        self.assertEqual(self.accept("x" * 43).status_code, 404)
        self.assertIsNone(self.role_of(ORG1, UE))

    def test_quem_ja_e_membro_nao_muda_de_papel(self):
        token = self.invite(email="c@x.com", role="admin").json()["token"]  # tentativa de promoção via convite
        r = self.accept(token, tok="tok-c")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(self.role_of(ORG1, UC), "member")
        self.assertEqual(r.json()["organization"]["role"], "member")

    def test_falha_ao_criar_vinculo_devolve_o_convite(self):
        token = self.invite().json()["token"]
        self.fake.fail.add(("POST", "memberships"))
        self.assertEqual(self.accept(token).status_code, 502)
        self.assertIsNone(self.fake.tables["invitations"][0]["accepted_at"])  # pode tentar de novo
        self.fake.fail.clear()
        self.assertEqual(self.accept(token).status_code, 200)

    def test_convite_so_vale_para_a_propria_organizacao(self):
        token = self.invite().json()["token"]
        self.accept(token)
        self.assertIsNone(self.role_of(ORG2, UE))
        self.assertEqual(self.client.get(f"/api/orgs/{ORG2}/members", headers=self.h("tok-e")).status_code, 403)


if __name__ == "__main__":
    unittest.main()
