"""Testes do webhook assinado: assinatura, proteção contra SSRF e envio de verdade a um servidor HTTPS local (certificado
gerado no teste, nenhuma rede externa). O fluxo completo (cadastro, evento, entrega) usa o mesmo provedor real."""
import datetime
import hashlib
import hmac
import http.server
import json
import os
import socket
import ssl
import sys
import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from cryptography import x509  # noqa: E402
from cryptography.hazmat.primitives import hashes, serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ec  # noqa: E402
from cryptography.x509.oid import NameOID  # noqa: E402

from aura.features.integrations import providers
from aura.features.integrations import service as integ  # noqa: E402
from aura.features.integrations import webhook as wp  # noqa: E402
from test_integrations_api import Base, KEY  # noqa: E402
from test_orgs import ORG1, UA  # noqa: E402

DIR = tempfile.mkdtemp(prefix="aura-wh-")
KEY_FILE, CERT_FILE = os.path.join(DIR, "k.pem"), os.path.join(DIR, "c.pem")


def _make_cert():
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "hook.test")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1)).not_valid_after(now + datetime.timedelta(days=2))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName("hook.test")]), critical=False).sign(key, hashes.SHA256()))
    with open(KEY_FILE, "wb") as f:
        f.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    with open(CERT_FILE, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))


_make_cert()


class Receiver:
    """Servidor HTTPS local que guarda o que recebe e responde como o teste mandar."""

    def __init__(self):
        self.requests, self.status, self.delay, self.location = [], 200, 0, None
        outer = self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                outer.requests.append({"path": self.path, "headers": dict(self.headers), "body": body})
                if outer.delay:
                    time.sleep(outer.delay)
                self.send_response(outer.status)
                if outer.location:
                    self.send_header("Location", outer.location)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"ok")

        class Quiet(http.server.ThreadingHTTPServer):
            def handle_error(self, request, client_address):  # o cliente que desiste (tempo esgotado) não é erro do teste
                pass

        self.server = Quiet(("127.0.0.1", 0), H)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(CERT_FILE, KEY_FILE)
        self.server.socket = ctx.wrap_socket(self.server.socket, server_side=True)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def trusting_context():
    ctx = ssl.create_default_context()
    ctx.load_verify_locations(CERT_FILE)
    return ctx


def local_provider(**kw):
    return wp.WebhookProvider(resolver=lambda host, port: ["127.0.0.1"], ssl_context=trusting_context(), allow_private=True, **kw)


EVENT = {"id": "11111111-1111-4111-8111-111111111111", "type": "meeting.analyzed", "entity_type": "meeting",
         "entity_id": "22222222-2222-4222-8222-222222222222", "data": {"title": "Plano"}, "created_at": "2026-10-15T10:00:00Z"}


class Assinatura(unittest.TestCase):
    def test_vetor_conhecido(self):
        expected = hmac.new(b"segredo", b"1700000000.{\"a\":1}", hashlib.sha256).hexdigest()
        self.assertEqual(wp.sign("segredo", 1700000000, b'{"a":1}'), "v1=" + expected)

    def test_verificacao_do_lado_de_quem_recebe(self):
        sig = wp.sign("s", 1000, b"corpo")
        self.assertTrue(wp.verify("s", 1000, b"corpo", sig, now=1100))
        self.assertFalse(wp.verify("s", 1000, b"corpo adulterado", sig, now=1100))
        self.assertFalse(wp.verify("outro", 1000, b"corpo", sig, now=1100))
        self.assertFalse(wp.verify("s", 1000, b"corpo", sig, now=1000 + 301))  # mensagem velha (repetição)
        self.assertFalse(wp.verify("s", 1000, b"corpo", "", now=1000))
        self.assertFalse(wp.verify("s", 1000, b"corpo", "v1=" + "0" * 64, now=1000))


class Urls(unittest.TestCase):
    def test_aceita_enderecos_publicos(self):
        for url, expected in [("https://example.com/hook", ("example.com", 443, "/hook")), ("https://Example.COM", ("example.com", 443, "/")),
                              ("https://api.example.com:8443/a/b?x=1", ("api.example.com", 8443, "/a/b?x=1")), ("https://8.8.8.8/x", ("8.8.8.8", 443, "/x"))]:
            self.assertEqual(wp.parse_url(url), expected, url)

    def test_recusa(self):
        bad = ["http://example.com", "ftp://example.com", "https://", "https://user:pw@example.com", "https://example.com/#frag", "https://exa mple.com",
               "https://localhost/x", "https://app.localhost/x", "https://db.internal/x", "https://printer.local", "https://intranet/x",
               "https://127.0.0.1/x", "https://10.0.0.5/x", "https://192.168.1.1/x", "https://172.16.0.1/x", "https://169.254.169.254/latest/meta-data",
               "https://0.0.0.0/x", "https://100.64.0.1/x", "https://[::1]/x", "https://[fd00::1]/x", "https://[::ffff:127.0.0.1]/x", "https://example.com:99999/x",
               "", None, 5, "https://" + "a" * 2000 + ".com"]
        for url in bad:
            with self.assertRaises(ValueError, msg=str(url)[:60]):
                wp.parse_url(url)

    def test_validate_config_normaliza(self):
        self.assertEqual(wp.WebhookProvider().validate_config({"url": "https://Example.com:443/h"}), {"url": "https://example.com/h"})
        self.assertEqual(wp.WebhookProvider().validate_config({"url": "https://example.com:8443/h"}), {"url": "https://example.com:8443/h"})
        with self.assertRaises(ValueError):
            wp.WebhookProvider().validate_config({"url": "https://127.0.0.1/h"})
        with self.assertRaises(ValueError):
            wp.WebhookProvider().validate_config({})


class Ssrf(unittest.TestCase):
    def run_blocked(self, addresses):
        provider = wp.WebhookProvider(resolver=lambda host, port: addresses)
        with mock.patch.object(wp, "_PinnedHTTPS", side_effect=AssertionError("não podia conectar")):
            return provider.deliver({"url": "https://example.com/h"}, "s", EVENT)

    def test_bloqueia_nomes_que_resolvem_para_a_rede_interna(self):
        for addresses in (["127.0.0.1"], ["10.1.2.3"], ["169.254.169.254"], ["192.168.0.10"], ["::1"], ["fe80::1"], ["::ffff:10.0.0.1"], ["0.0.0.0"], ["224.0.0.1"]):
            r = self.run_blocked(addresses)
            self.assertFalse(r.ok, addresses)
            self.assertFalse(r.retryable, addresses)
            self.assertIn("bloqueado", r.error)

    def test_um_unico_endereco_interno_entre_varios_bloqueia(self):
        r = self.run_blocked(["93.184.216.34", "10.0.0.1"])  # nome com um IP público e um interno
        self.assertFalse(r.ok)
        self.assertIn("bloqueado", r.error)

    def test_dns_falhando_tenta_depois(self):
        def boom(host, port):
            raise socket.gaierror("sem dns")
        r = wp.WebhookProvider(resolver=boom).deliver({"url": "https://example.com/h"}, "s", EVENT)
        self.assertEqual((r.ok, r.retryable), (False, True))

    def test_url_invalida_na_entrega_nao_tenta_de_novo(self):
        r = wp.WebhookProvider().deliver({"url": "https://127.0.0.1/h"}, "s", EVENT)
        self.assertEqual((r.ok, r.retryable), (False, False))

    def test_usa_exatamente_o_ip_validado(self):
        seen = {}

        class Conn:
            def __init__(self, host, ip, port, timeout, ctx):
                seen.update(host=host, ip=ip, port=port)

            def request(self, *a, **k):
                raise OSError("parar aqui")

            def close(self):
                pass
        with mock.patch.object(wp, "_PinnedHTTPS", Conn):
            wp.WebhookProvider(resolver=lambda h, p: ["93.184.216.34"]).deliver({"url": "https://example.com:8443/h"}, "s", EVENT)
        self.assertEqual(seen, {"host": "example.com", "ip": "93.184.216.34", "port": 8443})


class EnvioReal(unittest.TestCase):
    def setUp(self):
        self.rx = Receiver()
        self.addCleanup(self.rx.close)
        self.cfg = {"url": f"https://hook.test:{self.rx.port}/aura/in?x=1"}
        self.provider = local_provider()

    def test_entrega_assinada(self):
        r = self.provider.deliver(self.cfg, "whsec_abc", EVENT)
        self.assertEqual((r.ok, r.status_code), (True, 200))
        req = self.rx.requests[0]
        h = {k.lower(): v for k, v in req["headers"].items()}
        self.assertEqual(req["path"], "/aura/in?x=1")
        self.assertEqual(h["host"], f"hook.test:{self.rx.port}")  # o nome original, não o IP
        self.assertEqual(h["x-aura-event"], "meeting.analyzed")
        self.assertEqual(h["x-aura-delivery"], EVENT["id"])
        self.assertEqual(h["content-type"], "application/json; charset=utf-8")
        self.assertTrue(h["user-agent"].startswith("AURA-Webhook/"))
        self.assertTrue(wp.verify("whsec_abc", int(h["x-aura-timestamp"]), req["body"], h["x-aura-signature"]))
        self.assertFalse(wp.verify("outro", int(h["x-aura-timestamp"]), req["body"], h["x-aura-signature"]))
        body = json.loads(req["body"])
        self.assertEqual(body, {"id": EVENT["id"], "type": "meeting.analyzed", "created_at": "2026-10-15T10:00:00Z",
                                "entity": {"type": "meeting", "id": EVENT["entity_id"]}, "data": {"title": "Plano"}})
        self.assertNotIn("whsec_abc", req["body"].decode())

    def test_mesmo_id_em_todas_as_tentativas(self):
        self.provider.deliver(self.cfg, "s", EVENT)
        self.provider.deliver(self.cfg, "s", EVENT)
        ids = {r["headers"]["X-Aura-Delivery"] for r in self.rx.requests}
        self.assertEqual(ids, {EVENT["id"]})

    def test_status_e_se_vale_tentar_de_novo(self):
        for status, ok, retry in [(204, True, True), (500, False, True), (503, False, True), (429, False, True), (408, False, True),
                                  (400, False, False), (401, False, False), (404, False, False), (410, False, False)]:
            self.rx.status = status
            r = self.provider.deliver(self.cfg, "s", EVENT)
            self.assertEqual((r.ok, r.status_code), (ok, status), status)
            if not ok:
                self.assertEqual(r.retryable, retry, status)
                self.assertEqual(r.error, f"HTTP {status}")

    def test_nao_segue_redirecionamento(self):
        self.rx.status, self.rx.location = 302, "https://example.org/outro"
        r = self.provider.deliver(self.cfg, "s", EVENT)
        self.assertEqual((r.ok, r.status_code, r.retryable), (False, 302, False))
        self.assertEqual(len(self.rx.requests), 1)

    def test_tempo_esgotado_tenta_depois(self):
        self.rx.delay = 1.5
        with mock.patch.object(wp, "TIMEOUT", 0.3):
            r = self.provider.deliver(self.cfg, "s", EVENT)
        self.assertEqual((r.ok, r.retryable, r.error), (False, True, "Tempo esgotado."))

    def test_certificado_de_outro_nome_e_recusado(self):
        r = self.provider.deliver({"url": f"https://outro.test:{self.rx.port}/x"}, "s", EVENT)
        self.assertEqual((r.ok, r.retryable), (False, False))
        self.assertIn("Certificado", r.error)
        self.assertEqual(self.rx.requests, [])  # nada foi enviado

    def test_certificado_nao_confiavel_e_recusado(self):
        provider = wp.WebhookProvider(resolver=lambda h, p: ["127.0.0.1"], allow_private=True)  # contexto padrão: não confia no certificado do teste
        r = provider.deliver(self.cfg, "s", EVENT)
        self.assertEqual((r.ok, r.retryable), (False, False))
        self.assertEqual(self.rx.requests, [])

    def test_conexao_recusada_tenta_depois(self):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        r = self.provider.deliver({"url": f"https://hook.test:{port}/x"}, "s", EVENT)
        self.assertEqual((r.ok, r.retryable, r.error), (False, True, "Falha de conexão."))

    def test_corpo_grande_demais_nao_e_enviado(self):
        big = dict(EVENT, data={"x": "y" * (wp.MAX_BODY + 1)})
        r = self.provider.deliver(self.cfg, "s", big)
        self.assertEqual((r.ok, r.retryable), (False, False))
        self.assertEqual(self.rx.requests, [])


class VariosEnderecos(unittest.TestCase):
    def setUp(self):
        self.rx = Receiver()
        self.addCleanup(self.rx.close)
        self.cfg = {"url": f"https://hook.test:{self.rx.port}/x"}

    def test_se_o_primeiro_endereco_nao_conecta_tenta_o_proximo(self):
        dead = socket.socket()
        dead.bind(("127.0.0.2", 0))
        dead_port = dead.getsockname()[1]
        dead.close()  # nada escuta lá
        # 1º endereço: porta fechada no mesmo número de porta do destino real não existe; simulamos pelo IP sem servidor
        provider = wp.WebhookProvider(resolver=lambda h, p: ["127.0.0.2", "127.0.0.1"], ssl_context=trusting_context(), allow_private=True)
        r = provider.deliver(self.cfg, "s", EVENT)
        self.assertEqual((r.ok, r.status_code), (True, 200))
        self.assertEqual(len(self.rx.requests), 1)

    def test_todos_falhando_devolve_falha_de_conexao(self):
        provider = wp.WebhookProvider(resolver=lambda h, p: ["127.0.0.2", "127.0.0.3"], ssl_context=trusting_context(), allow_private=True)
        r = provider.deliver({"url": f"https://hook.test:{self.rx.port + 1}/x"}, "s", EVENT)
        self.assertEqual((r.ok, r.retryable, r.error), (False, True, "Falha de conexão."))

    def test_limita_a_quatro_enderecos(self):
        self.assertEqual(len(wp.WebhookProvider(resolver=lambda h, p: [f"93.184.216.{i}" for i in range(10)])._pick_ips("example.com", 443)), 4)


class FluxoCompleto(Base):
    """Cadastro pela API, evento e entrega com o provedor REAL falando com o servidor local."""

    def setUp(self):
        super().setUp()
        providers.register_provider(local_provider())  # substitui o falso da base
        self.rx = Receiver()
        self.addCleanup(self.rx.close)
        # a URL cadastrada precisa passar na validação pública; o provedor de teste a resolve para o servidor local
        out = self.new(config={"url": f"https://hook.test:{self.rx.port}/in"})
        self.iid, self.secret = out["integration"]["id"], out["secret"]

    def test_evento_chega_assinado_com_o_segredo_mostrado_na_criacao(self):
        integ.emit_event(ORG1, UA, "meeting.analyzed", "meeting", str(uuid.uuid4()), {"title": "Plano"}, "k1")
        self.assertEqual(integ.dispatch_due()["succeeded"], 1)
        req = self.rx.requests[0]
        h = {k.lower(): v for k, v in req["headers"].items()}
        self.assertTrue(wp.verify(self.secret, int(h["x-aura-timestamp"]), req["body"], h["x-aura-signature"]))
        self.assertEqual(json.loads(req["body"])["data"], {"title": "Plano"})

    def test_botao_de_teste_e_falha_com_destino_fora_do_ar(self):
        r = self.client.post(f"/api/integrations/{self.iid}/test", headers=self.h()).json()
        self.assertEqual(r["delivery"]["status"], "succeeded")
        self.rx.status = 500
        r = self.client.post(f"/api/integrations/{self.iid}/test", headers=self.h()).json()
        self.assertEqual((r["delivery"]["status"], r["delivery"]["last_status"]), ("failed", 500))

    def test_girar_o_segredo_muda_a_assinatura(self):
        new = self.client.post(f"/api/integrations/{self.iid}/rotate-secret", headers=self.h()).json()["secret"]
        self.client.post(f"/api/integrations/{self.iid}/test", headers=self.h())
        req = self.rx.requests[0]
        h = {k.lower(): v for k, v in req["headers"].items()}
        self.assertTrue(wp.verify(new, int(h["x-aura-timestamp"]), req["body"], h["x-aura-signature"]))
        self.assertFalse(wp.verify(self.secret, int(h["x-aura-timestamp"]), req["body"], h["x-aura-signature"]))

    def test_criar_com_endereco_interno_e_recusado_pelo_provedor_real(self):
        providers.register_provider(wp.WebhookProvider())  # o de produção
        for url in ("https://127.0.0.1/x", "https://169.254.169.254/x", "https://localhost/x", "http://example.com/x"):
            self.assertEqual(self.create(config={"url": url}).status_code, 400, url)

    def test_reenviar_entrega_encerrada(self):
        self.rx.status = 404
        integ.emit_event(ORG1, UA, "meeting.analyzed", "meeting", str(uuid.uuid4()), {}, "k2")
        integ.dispatch_due()
        d = self.rows("integration_deliveries")[0]
        self.assertEqual(d["status"], "dead")  # 404: não adianta repetir
        self.rx.status = 200
        r = self.client.post(f"/api/integrations/{self.iid}/deliveries/{d['id']}/retry", headers=self.h())
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((d["status"], d["attempts"]), ("pending", 0))
        self.assertEqual(integ.dispatch_due()["succeeded"], 1)
        again = self.client.post(f"/api/integrations/{self.iid}/deliveries/{d['id']}/retry", headers=self.h())
        self.assertEqual(again.status_code, 409)  # já concluída
        self.assertEqual(self.client.post(f"/api/integrations/{self.iid}/deliveries/{uuid.uuid4()}/retry", headers=self.h()).status_code, 404)
        self.assertEqual(self.client.post(f"/api/integrations/{self.iid}/deliveries/{d['id']}/retry", headers=self.h("tok-c")).status_code, 404)  # quem não gerencia não vê nem a integração

    def test_enviar_pendentes_agora(self):
        integ.emit_event(ORG1, UA, "meeting.analyzed", "meeting", str(uuid.uuid4()), {}, "k3")
        r = self.client.post(f"/api/integrations/{self.iid}/flush", headers=self.h())
        self.assertEqual((r.status_code, r.json()["succeeded"]), (200, 1))
        self.assertEqual(self.client.post(f"/api/integrations/{self.iid}/flush", headers=self.h("tok-d")).status_code, 404)


class AgendadorERetencao(Base):
    def setUp(self):
        super().setUp()
        self.iid = self.new()["integration"]["id"]

    def test_vercel_cron_usa_bearer_e_aceita_get(self):
        with mock.patch.dict(os.environ, {"CRON_SECRET": "vercel-secret"}):
            os.environ.pop("AURA_CRON_SECRET", None)
            self.assertEqual(self.client.get("/api/integrations/dispatch").status_code, 401)
            self.assertEqual(self.client.get("/api/integrations/dispatch", headers={"Authorization": "Bearer errado"}).status_code, 401)
            self.assertEqual(self.client.get("/api/integrations/dispatch", headers={"Authorization": "Bearer vercel-secret"}).status_code, 200)

    def test_remove_eventos_antigos_e_preserva_os_recentes_e_os_pendentes(self):
        old, recent, pending = (integ.emit_event(ORG1, UA, "meeting.analyzed", "meeting", str(uuid.uuid4()), {}, k) for k in ("o", "r", "p"))
        by_id = {e["id"]: e for e in self.rows("integration_events")}
        by_id[old]["created_at"] = "2020-01-01T00:00:00Z"
        by_id[pending]["created_at"] = "2020-01-01T00:00:00Z"
        for d in self.rows("integration_deliveries"):
            if d["event_id"] == old:
                d["status"] = "succeeded"
        with mock.patch.dict(os.environ, {"AURA_CRON_SECRET": "abc"}):
            os.environ.pop("CRON_SECRET", None)
            with mock.patch.object(integ, "dispatch_due", return_value={"found": 0}):  # só a limpeza, sem entregar
                self.assertEqual(self.client.post("/api/integrations/dispatch", headers={"X-Cron-Secret": "abc"}).status_code, 200)
        ids = {e["id"] for e in self.rows("integration_events")}
        self.assertEqual(ids, {recent, pending})  # o antigo já entregue saiu; o antigo pendente fica
        self.assertEqual({d["event_id"] for d in self.rows("integration_deliveries")}, {recent, pending})

    def test_retencao_configuravel(self):
        with mock.patch.dict(os.environ, {"AURA_INTEGRATION_EVENT_RETENTION_DAYS": "7"}):
            self.assertEqual(integ.retention_days(), 7)
        with mock.patch.dict(os.environ, {"AURA_INTEGRATION_EVENT_RETENTION_DAYS": "lixo"}):
            self.assertEqual(integ.retention_days(), 30)
        with mock.patch.dict(os.environ, {"AURA_INTEGRATION_EVENT_RETENTION_DAYS": "0"}):
            self.assertEqual(integ.retention_days(), 1)

    def test_falha_na_limpeza_nao_impede_as_entregas(self):
        with mock.patch.dict(os.environ, {"AURA_CRON_SECRET": "abc"}), mock.patch.object(integ, "prune_old_events", side_effect=RuntimeError("x")):
            r = self.client.post("/api/integrations/dispatch", headers={"X-Cron-Secret": "abc"})
        self.assertEqual(r.status_code, 200)

    def test_provedor_padrao_e_registrado_no_app(self):
        from aura import app as index
        from aura.features.meetings import repository as meetings_repo
        from aura.features.meetings import service as meetings_mod
        from aura.features.analysis import repository as analysis_repo
        from aura.features.analysis import service as analysis_mod
        providers.unregister_provider("webhook")
        index.register_default_providers()
        self.assertIsInstance(providers._PROVIDERS["webhook"], wp.WebhookProvider)


if __name__ == "__main__":
    unittest.main()
