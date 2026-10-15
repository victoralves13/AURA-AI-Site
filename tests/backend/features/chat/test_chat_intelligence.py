"""Inteligência do chat: visão geral da carteira, evolução do risco, foco herdado da conversa, segunda rodada (`needs`), resposta direta e
recomendações. O modelo de IA é substituído; nada sai para a rede. Cada teste confere o que o MODELO RECEBERIA e o que o backend faz
com o que ele devolve (a conferência de trechos continua valendo)."""
import re
import unittest
from unittest import mock

from aura.features.chat import context
from aura.features.chat import engine as ce
from tests.backend.features.chat.test_chat_api import Base, ORG1

TR = "[00:05] Ana: Vamos revisar o contrato.\n[00:12] Cliente: O prazo preocupa muito a diretoria.\n"


def key_of(prompt: str, client: str, nth: int = -1) -> str:
    """Chave (S1, S2...) do bloco de reunião do cliente indicado (por padrão, o mais recente listado)."""
    keys = re.findall(r"\[(S\d+)\] REUNIÃO · título: [^\n]*· cliente: " + re.escape(client) + r" ·", prompt)
    return keys[nth]


class Carteira(Base):
    def setUp(self):
        super().setUp()
        for day, risk, opp, summary in (("01", "Baixo", "Alto", "Kickoff tranquilo."), ("08", "Médio", "Alto", "Prazo começou a apertar."),
                                        ("14", "Alto", "Baixo", "Cliente ameaçou cancelar por causa do prazo.")):
            self.add_meeting(title=f"Órbita dia {day}", client="Órbita Saúde", client_id="11111111-1111-4111-8111-111111111111", summary=summary,
                             risk=risk, opportunity=opp, transcript=TR, created_at=f"2026-10-{day}T10:00:00+00:00",
                             risk_signals=[{"description": "ameaça de cancelamento"}] if risk == "Alto" else [])
        self.add_meeting(title="Atlas dia 12", client="Grupo Atlas", client_id="22222222-2222-4222-8222-222222222222", summary="Proposta enviada.",
                         risk="Baixo", opportunity="Alto", transcript=TR, created_at="2026-10-12T10:00:00+00:00")
        self.calls = []

    def model(self, fn):
        def fake(system, user_text):
            self.calls.append(user_text)
            return fn(user_text)
        p = mock.patch.object(ce, "ask_model", fake)
        p.start()
        self.addCleanup(p.stop)

    def test_pergunta_de_carteira_recebe_a_visao_geral_com_evolucao_do_risco(self):
        self.model(lambda t: ce.ChatAnswer(claims=[]))
        self.ask(self.new(org_id=ORG1), "quais clientes mais preocupam?")
        data = self.calls[0].split("<dados>")[1]
        s0 = data.split("[S1]")[0]
        self.assertIn("[S0] VISÃO GERAL", s0)
        self.assertLess(s0.index("Órbita Saúde"), s0.index("Grupo Atlas"))  # o mais preocupante vem primeiro
        self.assertIn("risco: Baixo → Médio → Alto (subiu)", s0)
        self.assertIn("2026-10-01, 2026-10-08, 2026-10-14", s0)
        self.assertIn("HOJE:", self.calls[0])

    def test_fato_de_risco_e_comprovado_pela_visao_geral(self):
        self.model(lambda t: ce.ChatAnswer(claims=[ce.Claim(statement="O risco da Órbita Saúde subiu de Baixo para Alto.", source="S0",
                                                            quote="risco: Baixo → Médio → Alto", kind="inferencia")]))
        r = self.ask(self.new(org_id=ORG1), "quais clientes mais preocupam?").json()["answer"]
        self.assertEqual(r["evidence_level"], "parcial")  # vem da análise do AURA, não de fala literal
        self.assertIn("(inferência do AURA)", r["content"])
        self.assertEqual((r["sources"][0]["type"], r["sources"][0]["origin"]), ("overview", "analise"))

    def test_nivel_de_risco_e_sinais_agora_sao_citaveis_no_detalhe(self):
        def fn(t):
            k = key_of(t, "Órbita Saúde")
            return ce.ChatAnswer(claims=[ce.Claim(statement="A reunião mais recente da Órbita está com risco Alto.", source=k, quote="Risco: Alto · Oportunidade: Baixo"),
                                         ce.Claim(statement="Há ameaça de cancelamento.", source=k, quote="ameaça de cancelamento")])
        self.model(fn)
        a = self.ask(self.new(org_id=ORG1), "como está a Órbita?").json()["answer"]
        self.assertEqual(a["content"].count("•"), 2)
        self.assertIn("2026-10-14", self.calls[0])

    def test_pergunta_cita_um_cliente_so_ele_recebe_detalhe(self):
        self.model(lambda t: ce.ChatAnswer(claims=[]))
        self.ask(self.new(org_id=ORG1), "o que mudou desde a última reunião da Órbita?")
        data = self.calls[0].split("<dados>")[1]
        details = data.split("[S1]")[1]
        self.assertIn("Órbita dia 14", details)
        self.assertIn("Órbita dia 08", details)
        self.assertNotIn("Atlas dia 12", details)
        self.assertIn("FOCO DA CONVERSA: cliente citado na pergunta: Órbita Saúde", self.calls[0])
        self.assertLess(details.index("dia 01") if "dia 01" in details else 0, details.index("dia 14"))  # ordem cronológica

    def test_referencia_ao_contexto_anterior(self):
        def fn(t):
            if "Atlas" in t.split("PERGUNTA ATUAL:")[1].split("<dados>")[0]:
                return ce.ChatAnswer(claims=[])
            k = key_of(t, "Órbita Saúde")
            return ce.ChatAnswer(claims=[ce.Claim(statement="O prazo preocupa a diretoria da Órbita.", source=k, quote="O prazo preocupa muito a diretoria")])
        self.model(fn)
        cid = self.new(org_id=ORG1)
        self.ask(cid, "como está a Órbita?")
        self.ask(cid, "e o que aconteceu depois?")  # não cita cliente: herda da resposta anterior
        second = self.calls[1]
        self.assertIn("FOCO DA CONVERSA: cliente(s) da resposta anterior", second)
        self.assertIn("Órbita Saúde", second.split("FOCO DA CONVERSA:")[1].split("\n")[0])
        details = second.split("<dados>")[1].split("[S1]")[1]
        self.assertIn("Órbita dia 14", details)
        self.assertNotIn("Atlas dia 12", details)

    def test_cliente_novo_na_pergunta_vence_o_foco_antigo(self):
        self.model(lambda t: ce.ChatAnswer(claims=[]))
        cid = self.new(org_id=ORG1)
        self.ask(cid, "como está a Órbita?")
        self.ask(cid, "e a Atlas?")
        self.assertIn("cliente citado na pergunta: Grupo Atlas", self.calls[1])

    def test_segunda_rodada_quando_a_ia_pede_detalhe(self):
        answers = iter([ce.ChatAnswer(claims=[], needs=["Grupo Atlas"]),
                        ce.ChatAnswer(claims=[ce.Claim(statement="A Atlas enviou a proposta.", source="S1", quote="O prazo preocupa muito a diretoria", kind="inferencia")])])
        self.model(lambda t: next(answers))
        r = self.ask(self.new(org_id=ORG1), "compare os clientes").json()
        self.assertEqual(len(self.calls), 2)  # no máximo uma segunda rodada
        self.assertIn("Atlas dia 12", self.calls[1].split("<dados>")[1])
        self.assertTrue(r["answer"]["content"])

    def test_pedido_de_detalhe_inventado_nao_gasta_segunda_chamada(self):
        self.model(lambda t: ce.ChatAnswer(claims=[], needs=["Empresa Que Nao Existe"]))
        r = self.ask(self.new(org_id=ORG1), "e a outra empresa?").json()
        self.assertEqual(len(self.calls), 1)
        self.assertIn("Não encontrei evidência", r["answer"]["content"])

    def test_nunca_mais_que_duas_rodadas(self):
        self.model(lambda t: ce.ChatAnswer(claims=[], needs=["Órbita Saúde", "Grupo Atlas"]))
        self.ask(self.new(org_id=ORG1), "compare")
        self.assertEqual(len(self.calls), 2)

    def test_resposta_direta_sem_dados(self):
        self.model(lambda t: ce.ChatAnswer(claims=[], reply="Olá! Posso resumir reuniões, comparar clientes e apontar riscos e ações."))
        a = self.ask(self.new(org_id=ORG1), "oi, o que você faz?").json()["answer"]
        self.assertTrue(a["content"].startswith("Olá!"))
        self.assertIsNone(a["evidence_level"])  # não há o que comprovar
        self.assertEqual(a["sources"], [])

    def test_pedido_de_esclarecimento(self):
        self.model(lambda t: ce.ChatAnswer(claims=[], reply="De qual cliente você quer saber? Posso olhar a Órbita Saúde ou o Grupo Atlas."))
        a = self.ask(self.new(org_id=ORG1), "qual deles?").json()["answer"]
        self.assertIn("De qual cliente", a["content"])

    def test_resposta_direta_nao_mascara_afirmacao_sem_prova(self):
        bad = ce.Claim(statement="A Órbita pagou tudo.", source="S0", quote="pagamento integral confirmado hoje")
        self.model(lambda t: ce.ChatAnswer(claims=[bad], reply="Tudo certo com a Órbita!"))
        a = self.ask(self.new(org_id=ORG1), "como está a Órbita?").json()["answer"]
        self.assertIn("Não encontrei evidência", a["content"])
        self.assertNotIn("Tudo certo", a["content"])
        self.assertEqual(a["evidence_level"], "insuficiente")

    def test_fato_inferencia_e_recomendacao_ficam_separados(self):
        def fn(t):
            k = key_of(t, "Órbita Saúde")
            return ce.ChatAnswer(claims=[
                ce.Claim(statement="Em 14/10 o cliente ameaçou cancelar.", source=k, quote="ameaça de cancelamento", kind="fato"),
                ce.Claim(statement="O risco vem do prazo.", source=k, quote="O prazo preocupa muito a diretoria", kind="inferencia"),
                ce.Claim(statement="Priorizar uma reunião de alinhamento de prazo com a Órbita.", source=k, quote="ameaça de cancelamento", kind="recomendacao")])
        self.model(fn)
        text = self.ask(self.new(org_id=ORG1), "o que devo fazer com a Órbita?").json()["answer"]["content"]
        lines = text.split("\n")
        self.assertTrue(lines[0].startswith("• Em 14/10"))
        self.assertIn("(inferência do AURA)", lines[1])
        self.assertTrue(lines[2].startswith("→ Recomendação do AURA: Priorizar"))

    def test_recomendacao_sem_fato_comprovado_e_descartada(self):
        self.model(lambda t: ce.ChatAnswer(claims=[ce.Claim(statement="Ligue para o diretor.", source="S0", quote="ele pediu uma ligação urgente", kind="recomendacao")]))
        a = self.ask(self.new(org_id=ORG1), "o que fazer?").json()["answer"]
        self.assertNotIn("Ligue", a["content"])


class ContextoPuro(unittest.TestCase):
    def test_nivel_de_risco(self):
        for value, level in (("Alto", "Alto"), ("risco alto", "Alto"), ("Médio", "Médio"), ("Baixo", "Baixo"), (None, "—"), ("", "—")):
            self.assertEqual(context.risk_level(value), level, value)

    def test_clientes_citados_ignoram_acento_e_palavras_genericas(self):
        clients = [{"key": "a", "name": "Órbita Saúde"}, {"key": "b", "name": "Grupo Atlas"}, {"key": "c", "name": "Grupo"}]
        self.assertEqual(context.mentioned_clients("como esta a orbita saude?", clients), ["a"])
        self.assertEqual(context.mentioned_clients("o grupo atlas atrasou", clients), ["b"])
        self.assertEqual(context.mentioned_clients("o grupo atrasou", clients), [])  # nome só com palavras genéricas não conta
        self.assertEqual(context.mentioned_clients("oi", clients), [])
        self.assertEqual(context.mentioned_clients("como está a Órbita?", clients), ["a"])  # basta a primeira palavra do nome
        self.assertEqual(context.mentioned_clients("como está a saúde do relacionamento?", clients), [])  # palavra comum não escolhe cliente
        two = [{"key": "x", "name": "Grupo Atlas"}, {"key": "y", "name": "Atlas Sul"}]
        self.assertEqual(context.mentioned_clients("e a Atlas Sul?", two), ["y"])
        self.assertEqual(context.mentioned_clients("e a Atlas?", two), ["x"])  # o nome inteiro vence o parcial

    def test_ordem_da_visao_geral(self):
        ms = [{"id": "1", "client_name": "A", "client_id": "a", "created_at": "2026-10-01", "risk": "Baixo", "summary": "x"},
              {"id": "2", "client_name": "B", "client_id": "b", "created_at": "2026-10-02", "risk": "Alto", "summary": "y"},
              {"id": "3", "client_name": "B", "client_id": "b", "created_at": "2026-10-03", "risk": "Baixo", "summary": "z"}]
        text, rows = context.build_overview(ms, [], "2026-10-15")
        self.assertEqual([r["name"] for r in rows], ["A", "B"][::-1] if rows[0]["name"] == "B" else ["A", "B"])
        self.assertIn("risco: Alto → Baixo (caiu)", text)

    def test_acoes_atrasadas_pesam_na_preocupacao(self):
        ms = [{"id": "1", "client_name": "A", "client_id": "a", "created_at": "2026-10-01", "risk": "Médio", "summary": "x"},
              {"id": "2", "client_name": "B", "client_id": "b", "created_at": "2026-10-01", "risk": "Médio", "summary": "y"}]
        acts = [{"meeting_id": "2", "status": "open", "due_date": "2026-10-05", "meetings": {"client_id": "b", "client_name": "B"}}]
        text, rows = context.build_overview(ms, acts, "2026-10-15")
        self.assertEqual(rows[0]["name"], "B")
        self.assertIn("1 em aberto (1 atrasada(s))", text)

    def test_grupo_aparece_na_visao_geral_e_vale_como_citacao(self):
        ms = [{"id": "1", "client_name": "Atlas Sul", "client_id": "a", "created_at": "2026-10-01", "risk": "Alto", "summary": "x"},
              {"id": "2", "client_name": "Atlas Norte", "client_id": "b", "created_at": "2026-10-02", "risk": "Baixo", "summary": "y"},
              {"id": "3", "client_name": "Horizonte", "client_id": "c", "created_at": "2026-10-03", "risk": "Baixo", "summary": "z"}]
        text, rows = context.build_overview(ms, [], "2026-10-15", {"a": "Holding Delta", "b": "Holding Delta"})
        self.assertIn("- Atlas Sul | grupo: Holding Delta | reuniões: 1", text)
        self.assertNotIn("Horizonte | grupo", text)
        self.assertEqual(sorted(context.mentioned_clients("como vai a holding delta?", rows)), ["a", "b"])
        self.assertEqual(context.mentioned_clients("e o Atlas Sul na holding delta?", rows), ["a"])  # cliente citado vence o grupo

    def test_foco_nunca_passa_do_limite(self):
        ms = [{"id": str(i), "client_name": "A", "client_id": "a", "created_at": f"2026-10-{i:02d}", "risk": "Alto", "summary": "x"} for i in range(1, 12)]
        _text, rows = context.build_overview(ms, [], "2026-10-15")
        chosen, _keys, _note = context.choose_focus("como está a A?", [], {}, ms, rows)
        self.assertLessEqual(len(chosen), context.PER_CLIENT)
        chosen, _keys, _note = context.choose_focus("compare", [], {}, ms, rows, limit=2)
        self.assertLessEqual(len(chosen), 2)


if __name__ == "__main__":
    unittest.main()
