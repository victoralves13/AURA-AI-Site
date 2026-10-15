"""Nova análise com contexto: cliente existente, grupo, título, participantes e data da reunião (sem rede e sem OpenAI)."""
import unittest
from datetime import date, timedelta

from aura.features.analysis import service as analysis
from tests.backend.features.clients.test_clients_api import Base, ORG1, UA, UC, TEXT  # noqa: F401


class NovaAnaliseComContexto(Base):
    def test_cliente_escolhido_vale_sem_adivinhar_e_grava_o_grupo(self):
        atlas = self.add_client("Grupo Atlas")
        p = self.analyze(ai="Outra Empresa", client_id=atlas, group_name="  Holding   Atlas ")
        self.assertEqual((p["client_id"], p["client_link"], p["client_name"]), (atlas, "confirmed", "Grupo Atlas"))
        self.assertEqual(self.row_client(atlas)["group_name"], "Holding Atlas")
        self.assertEqual(len(self.fake.tables["clients"]), 1)  # nada duplicado

    def test_cliente_novo_digitado_nasce_com_grupo(self):
        p = self.analyze(typed="Horizonte Digital", group_name="Grupo Horizonte")
        self.assertEqual(self.row_client(p["client_id"])["group_name"], "Grupo Horizonte")

    def test_sem_grupo_nem_cliente_continua_funcionando(self):
        p = self.analyze(typed="Horizonte Digital")
        self.assertNotIn("group_name", self.row_client(p["client_id"]))

    def test_cliente_escolhido_invalido_e_recusado_antes_da_ia(self):
        outro_espaco = self.add_client("Pessoal", org=None, owner=UA)
        fundido = self.add_client("Antigo", merged_into=self.add_client("Novo"))
        for cid, status in [("11111111-1111-1111-1111-111111111111", 404), (outro_espaco, 409), (fundido, 409), ("nao-e-uuid", 400)]:
            r = self.client.post("/api/analyze-transcript", headers=self.h(), json={"transcript": TEXT, "org_id": ORG1, "client_id": cid})
            self.assertEqual(r.status_code, status, (cid, r.text))
        self.assertEqual(self.saved, [])

    def test_grupo_longo_demais_e_recusado(self):
        r = self.client.post("/api/analyze-transcript", headers=self.h(), json={"transcript": TEXT, "org_id": ORG1, "group_name": "x" * 121})
        self.assertEqual(r.status_code, 400)

    def test_titulo_participantes_e_data_sao_gravados(self):
        p = self.analyze(typed="Grupo Atlas", meeting_title="Renovação 2027", participants="Ana, Carlos;ana\nBeatriz", meeting_date="2026-09-30")
        self.assertEqual(p["meeting_title"], "Renovação 2027")
        self.assertEqual(p["participants"][:3], ["Ana", "Carlos", "Beatriz"])
        self.assertEqual(p["created_at"], "2026-09-30T12:00:00+00:00")

    def test_data_futura_ou_invalida_e_recusada(self):
        futuro = (date.today() + timedelta(days=3)).isoformat()
        for value in (futuro, "30/09/2026", "1999-01-01"):
            r = self.client.post("/api/analyze-transcript", headers=self.h(), json={"transcript": TEXT, "org_id": ORG1, "meeting_date": value})
            self.assertEqual(r.status_code, 400, value)

    def test_sem_data_a_reuniao_fica_com_o_horario_do_banco(self):
        p = self.analyze(typed="Grupo Atlas")
        self.assertNotIn("created_at", p)

    def test_grupo_ausente_no_banco_nao_derruba_a_analise(self):
        from aura.features.clients import repository
        atlas = self.add_client("Grupo Atlas")
        old = repository._GROUPS["supported"]
        self.addCleanup(lambda: repository._GROUPS.update(supported=old))
        repository._GROUPS["supported"] = False
        r = self.client.post("/api/analyze-transcript", headers=self.h(), json={"transcript": TEXT, "org_id": ORG1, "client_id": atlas, "group_name": "Holding Atlas"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["client_id"], atlas)
        self.assertFalse(r.json()["client_group_saved"])


class ParseHelpers(unittest.TestCase):
    def test_participantes(self):
        self.assertEqual(analysis.parse_participants(["Ana ", "ana", "", "Bia"]), ["Ana", "Bia"])
        self.assertEqual(analysis.parse_participants(None), [])
        self.assertEqual(len(analysis.parse_participants(",".join(str(i) for i in range(50)))), analysis.MAX_PARTICIPANTS)


if __name__ == "__main__":
    unittest.main()
