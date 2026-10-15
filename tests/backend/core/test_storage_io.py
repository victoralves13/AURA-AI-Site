"""Testes do acesso ao bucket de áudio (sem rede: a camada HTTP é substituída)."""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

from aura.core import security as sec  # noqa: E402
from aura.core import storage as storage_io  # noqa: E402

ENV = {"SUPABASE_URL": "https://x.supabase.co", "SUPABASE_SECRET_KEY": "sk", "SUPABASE_PUBLISHABLE_KEY": "pk", "AURA_AUDIO_BUCKET": "aura-audio"}


class Armazenamento(unittest.TestCase):
    def setUp(self):
        p = mock.patch.dict(os.environ, ENV)
        p.start()
        self.addCleanup(p.stop)
        self.calls = []

    def respond(self, status, body):
        def fake(method, url, headers, payload=None, timeout=15):
            self.calls.append((method, url, headers, payload))
            return status, body
        return mock.patch.object(sec, "http_json", fake)

    def test_tamanho_do_arquivo(self):
        with self.respond(200, {"size": 1234}):
            self.assertEqual(storage_io.object_size("users/u/live/s/0000.webm"), 1234)
        method, url, headers, _ = self.calls[0]
        self.assertEqual((method, url), ("GET", "https://x.supabase.co/storage/v1/object/info/aura-audio/users/u/live/s/0000.webm"))
        self.assertIn("sk", headers.get("Authorization", ""))  # chave de serviço, só no backend

    def test_tamanho_dentro_de_metadata(self):
        with self.respond(200, {"metadata": {"size": 77}}):
            self.assertEqual(storage_io.object_size("a/b.webm"), 77)

    def test_arquivo_inexistente(self):
        with self.respond(404, {"message": "Object not found"}):
            self.assertIsNone(storage_io.object_size("a/b.webm"))
        with self.respond(400, {"message": "Object not found"}):
            self.assertIsNone(storage_io.object_size("a/b.webm"))

    def test_erro_do_storage_nao_vira_inexistente(self):
        with self.respond(500, {"message": "boom"}):
            with self.assertRaises(RuntimeError):
                storage_io.object_size("a/b.webm")

    def test_caminho_e_codificado(self):
        with self.respond(200, {"size": 1}):
            storage_io.object_size("users/u/live/s/0 0.webm")
        self.assertIn("0%200.webm", self.calls[0][1])

    def test_apaga_varios_arquivos_de_uma_vez(self):
        with self.respond(200, []):
            storage_io.delete_objects(["a/1.webm", "a/2.webm"])
        method, url, _, payload = self.calls[0]
        self.assertEqual((method, url, payload), ("DELETE", "https://x.supabase.co/storage/v1/object/aura-audio", {"prefixes": ["a/1.webm", "a/2.webm"]}))

    def test_nada_a_apagar_nao_chama_a_rede(self):
        with self.respond(200, []):
            storage_io.delete_objects([])
        self.assertEqual(self.calls, [])

    def test_falha_ao_apagar_levanta_erro(self):
        with self.respond(500, {"message": "x"}):
            with self.assertRaises(RuntimeError):
                storage_io.delete_objects(["a/1.webm"])


if __name__ == "__main__":
    unittest.main()
