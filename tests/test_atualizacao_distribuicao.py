from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import urllib.error
from unittest.mock import patch
from unittest.mock import MagicMock
import threading

from autoupdate import (Atualizacao, AtualizacaoCancelada, ErroAtualizacao, baixar_atualizacao,
                        consultar_atualizacao, versao_mais_nova)
from interface_windows import InterfaceExtrator
import importlib.util
_spec = importlib.util.spec_from_file_location('prepare_release', Path(__file__).resolve().parents[1] / 'packaging/prepare_release.py')
_modulo = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_modulo)
preparar = _modulo.preparar


class Resposta:
    def __init__(self, dados):
        self.dados = dados
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def read(self, *_args):
        dados, self.dados = self.dados, b""
        return dados


class TesteAtualizacao(unittest.TestCase):
    def test_semver_previa_estavel_e_metadados(self):
        self.assertTrue(versao_mais_nova("1.2.3", "1.2.3-beta.9"))
        self.assertTrue(versao_mais_nova("1.2.3-beta.10", "1.2.3-beta.9"))
        self.assertFalse(versao_mais_nova("1.2.3-beta", "1.2.3"))
        self.assertFalse(versao_mais_nova("1.2.3+novo", "1.2.3+antigo"))

    def test_release_inexistente_nao_e_erro_de_conexao(self):
        with patch('autoupdate.urllib.request.urlopen', side_effect=urllib.error.HTTPError('url', 404, '', {}, None)) as abrir:
            self.assertIsNone(consultar_atualizacao('e-Lopes/repo', '0.4.0', abrir_url=abrir))

    def test_prerelease_e_rascunho_nao_sao_oferecidos(self):
        for campo in ('draft', 'prerelease'):
            self.assertIsNone(consultar_atualizacao('e-Lopes/repo', '0.4.0',
                abrir_url=lambda *_args, **_kwargs: Resposta(json.dumps({'tag_name':'v9.0.0', campo:True}).encode())))

    def test_cancelamento_remove_parcial_e_preserva_instalador_anterior(self):
        with tempfile.TemporaryDirectory() as pasta, patch('autoupdate.tempfile.gettempdir', return_value=pasta):
            nome = 'ChessBookDiagramExtractor-Setup-v1.0.0.exe'
            destino = Path(pasta) / 'ChessBookDiagramExtractor/updates' / nome
            destino.parent.mkdir(parents=True)
            destino.write_bytes(b'anterior')
            atualizacao = Atualizacao('1.0.0', nome, 'https://github.com/e-Lopes/repo/releases/download/v1.0.0/'+nome,
                                      hashlib.sha256(b'MZnovo').hexdigest(), 6, '')
            cancelado = False
            def progresso(*args):
                nonlocal cancelado
                cancelado = True
            with self.assertRaises(AtualizacaoCancelada):
                baixar_atualizacao(atualizacao, progresso=progresso, cancelado=lambda: cancelado,
                                   abrir_url=lambda *args, **kwargs: Resposta(b'MZnovo'))
            self.assertEqual(destino.read_bytes(), b'anterior')
            self.assertEqual(list(destino.parent.glob('*.partial')), [])

    def test_nome_fora_da_pasta_de_download_e_rejeitado(self):
        atualizacao = Atualizacao('1.0.0','../setup.exe','https://github.com/exe', 'a'*64, 2, '')
        with self.assertRaisesRegex(ErroAtualizacao, 'Nome'):
            baixar_atualizacao(atualizacao)

    def test_resposta_malformada_e_diagnosticada(self):
        with self.assertRaisesRegex(ErroAtualizacao, 'Resposta'):
            consultar_atualizacao('e-Lopes/repo', '0.4.0', abrir_url=lambda *a, **kw: Resposta(b'[]'))

    def test_manifesto_inclui_hash_e_tamanho_dos_dois_instaladores(self):
        with tempfile.TemporaryDirectory() as pasta:
            pasta = Path(pasta)
            for nome in ('ChessBookDiagramExtractor-Setup-v0.4.0.exe', 'ChessBookDiagramExtractor-Setup.exe'):
                (pasta/nome).write_bytes(b'MZsetup')
            preparar(pasta, '0.4.0')
            dados = json.loads((pasta/'release.json').read_text())
            self.assertEqual(dados['versao'], '0.4.0')
            self.assertEqual(len(dados['arquivos']), 2)
            self.assertEqual(len((pasta/'SHA256SUMS.txt').read_text().splitlines()), 2)

    def test_erro_de_consulta_silenciosa_nao_habilita_controles_durante_extracao(self):
        interface = InterfaceExtrator.__new__(InterfaceExtrator)
        interface.baixando_atualizacao = False
        interface.verificacao_silenciosa = True
        interface.botao_atualizar = MagicMock()
        interface._alternar_controles = MagicMock()
        interface._atualizar_estado_principal = MagicMock()
        interface._erro_atualizacao(RuntimeError('offline'))
        interface._alternar_controles.assert_not_called()
        interface._atualizar_estado_principal.assert_called_once()

    def test_download_iniciado_por_oferta_automatica_permite_cancelar_e_repetir(self):
        interface = InterfaceExtrator.__new__(InterfaceExtrator)
        interface.atualizacao_pendente = Atualizacao('1.0.0', 'setup.exe', 'url', 'a'*64, 2, '')
        interface.baixando_atualizacao = False
        interface.atualizando = False
        interface.processando = interface.revisando = False
        interface.cancelamento_atualizacao = threading.Event()
        interface.botao_atualizar = MagicMock()
        interface.botao_instalar_atualizacao = MagicMock()
        interface._alternar_controles = MagicMock()
        interface._definir_status = MagicMock()
        with patch('interface_windows.threading.Thread'):
            interface._iniciar_atualizacao_pendente()
        self.assertIsNotNone(interface.atualizacao_pendente)
        self.assertFalse(interface.verificacao_silenciosa)
        interface._iniciar_atualizacao_pendente()
        self.assertTrue(interface.cancelamento_atualizacao.is_set())
