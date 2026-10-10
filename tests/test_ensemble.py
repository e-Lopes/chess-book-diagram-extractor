from __future__ import annotations

import hashlib
import json
from dataclasses import replace
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock
from types import SimpleNamespace

import numpy as np

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from reconhecimento_ensemble import (
    CLASSES, ConfiguracaoModelo, ModeloONNX, carregar_catalogo,
    combinar_probabilidades, preparar_casas_pillow, temperar_probabilidades,
)
from notacao_forsyth import ReconhecedorForsyth, RevisorAutomaticoLivro
from notacao_forsyth import ItemRevisao
from revisor_forsyth import JanelaRevisaoForsyth


def matriz_com_classe(classe: str, confianca: float = 1.0) -> np.ndarray:
    matriz = np.full((64, 13), (1 - confianca) / 12, np.float32)
    matriz[:, CLASSES.index(classe)] = confianca
    return matriz


class TesteVotacao(unittest.TestCase):
    def test_dois_modelos_podem_superar_um_modelo_mais_confiante(self) -> None:
        principal = matriz_com_classe("N", 0.99)
        especialistas = matriz_com_classe("P", 0.90)
        eleita = combinar_probabilidades([principal, especialistas, especialistas], [1, 1, 1])
        self.assertTrue(np.all(eleita.argmax(axis=1) == CLASSES.index("P")))
        self.assertTrue(np.allclose(eleita.sum(axis=1), 1))

    def test_pesos_e_decisao_independentes_por_casa(self) -> None:
        a, b = matriz_com_classe("N"), matriz_com_classe("P")
        b[17] = a[17]
        resultado = combinar_probabilidades([a, b], [1, 3])
        self.assertEqual(CLASSES[resultado[0].argmax()], "P")
        self.assertEqual(CLASSES[resultado[17].argmax()], "N")
        np.testing.assert_allclose(resultado, combinar_probabilidades([b, a], [3, 1]))

    def test_temperatura_reduz_excesso_de_confianca_sem_trocar_classe(self) -> None:
        original = matriz_com_classe("Q", 0.99)
        ajustada = temperar_probabilidades(original, 2.0)
        self.assertLess(ajustada[0].max(), original[0].max())
        np.testing.assert_array_equal(ajustada.argmax(axis=1), original.argmax(axis=1))
        np.testing.assert_allclose(ajustada.sum(axis=1), 1, atol=2e-7)
        np.testing.assert_array_equal(temperar_probabilidades(matriz_com_classe("1"), 2), matriz_com_classe("1"))

    def test_recusa_pesos_e_matrizes_invalidos(self) -> None:
        matriz = matriz_com_classe("1")
        for matrizes, pesos in (([], []), ([matriz], []), ([matriz], [0]),
                                ([matriz], [-1]), ([matriz], [np.nan]),
                                ([matriz], [np.inf]), ([matriz.T], [1])):
            with self.assertRaises(ValueError):
                combinar_probabilidades(matrizes, pesos)
        for temperatura in (0, -1, np.inf, np.nan):
            with self.assertRaises(ValueError):
                temperar_probabilidades(matriz, temperatura)

    def test_remapeia_classes_nativas_antes_de_combinar(self) -> None:
        nativas = "1RNBQKPrnbqkp"
        matriz = np.zeros((64, 13), np.float32)
        matriz[:, nativas.index("K")] = 1
        modelo = ModeloONNX.__new__(ModeloONNX)
        modelo.configuracao = ConfiguracaoModelo("teste", "modelo.onnx", "a" * 64, 1, classes=nativas)
        modelo.sessao = MagicMock()
        modelo.sessao.run.return_value = [matriz]
        modelo.entrada, modelo.saida = "tiles", "probs"
        previsto = modelo.prever(np.zeros((64, 1024), np.float32))
        self.assertTrue(np.all(previsto.argmax(axis=1) == CLASSES.index("K")))


class TestePreparacaoModelos(unittest.TestCase):
    def test_pillow_preserva_ordem_a1_h8_e_escala(self) -> None:
        imagem = np.zeros((256, 256), np.uint8)
        imagem[0:32, 0:32] = 255  # a8
        imagem[224:256, 32:64] = 128  # b1
        for modo in ("pillow_gray", "pillow_rgb_gray"):
            casas = preparar_casas_pillow(imagem, 0, modo)
            self.assertEqual(casas.shape, (64, 1024))
            self.assertEqual(casas.dtype, np.float32)
            self.assertAlmostEqual(float(casas[56].mean()), 1, places=4)
            self.assertAlmostEqual(float(casas[1].mean()), 128 / 255, places=4)
            self.assertEqual(float(casas[0].mean()), 0)

    def test_cor_bgr_nao_troca_vermelho_e_azul(self) -> None:
        vermelho = np.full((256, 256, 3), (0, 0, 255), np.uint8)
        azul = np.full((256, 256, 3), (255, 0, 0), np.uint8)
        for modo in ("pillow_gray", "pillow_rgb_gray"):
            self.assertGreater(preparar_casas_pillow(vermelho, 0, modo).mean(),
                               preparar_casas_pillow(azul, 0, modo).mean())

    def test_todos_os_pesos_publicados_tem_hash_e_contrato_validos(self) -> None:
        catalogo = carregar_catalogo(RAIZ / "models/ensemble.json")
        self.assertEqual(len(catalogo), 3)
        for configuracao in catalogo:
            with self.subTest(modelo=configuracao.nome):
                arquivo = RAIZ / "models" / configuracao.arquivo
                self.assertEqual(hashlib.sha256(arquivo.read_bytes()).hexdigest(), configuracao.sha256.lower())
                modelo = ModeloONNX(configuracao, arquivo.parent)
                matriz = modelo.prever(np.zeros((64, 1024), np.float32))
                self.assertEqual(matriz.shape, (64, 13))

    def test_modelo_adulterado_e_rejeitado_antes_de_carregar_onnx(self) -> None:
        with tempfile.TemporaryDirectory() as temporaria:
            pasta = Path(temporaria)
            (pasta / "modelo.onnx").write_bytes(b"adulterado")
            cfg = ConfiguracaoModelo("teste", "modelo.onnx", "a" * 64, 1)
            with self.assertRaisesRegex(RuntimeError, "SHA-256"):
                ModeloONNX(cfg, pasta)

    def test_catalogo_nao_conta_copias_como_modelos_independentes(self) -> None:
        with tempfile.TemporaryDirectory() as temporaria:
            caminho = Path(temporaria) / "ensemble.json"
            dados = {"versao": 1, "modelos": [
                {"nome": n, "arquivo": n + ".onnx", "sha256": "a" * 64, "peso": 1}
                for n in ("a", "b")
            ]}
            caminho.write_text(json.dumps(dados), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "cópias"):
                carregar_catalogo(caminho)


class TesteIntegracaoEnsemble(unittest.TestCase):
    def test_visualizador_exibe_aviso_curto_e_respeita_edicao_manual(self) -> None:
        item = ItemRevisao(casas=tuple(SimpleNamespace(coordenada=f"a{i}", divergencia_modelos=True, marcador_vazio=False)
                                     for i in range(1, 10)))
        aviso = JanelaRevisaoForsyth._aviso_ensemble(item)
        self.assertIn("a1", aviso)
        self.assertIn("mais 1", aviso)
        self.assertNotIn("a9", aviso)
        item.editada_manualmente = True
        self.assertEqual(JanelaRevisaoForsyth._aviso_ensemble(item), "")

    def test_divergencia_e_preservada_e_nao_vira_referencia_automatica(self) -> None:
        base = matriz_com_classe("1")
        for indice, classe in ((4, "K"), (60, "k")):
            base[indice] = matriz_com_classe(classe)[0]
        a, b, c = [base.copy() for _ in range(3)]
        a[8] = matriz_com_classe("N", 0.99)[0]
        b[8] = c[8] = matriz_com_classe("P", 0.90)[0]
        reconhecedor = ReconhecedorForsyth.__new__(ReconhecedorForsyth)
        reconhecedor.idioma = "en"
        reconhecedor._configuracoes = tuple(ConfiguracaoModelo(n, n + ".onnx", str(i) * 64, 1)
                                           for i, n in enumerate(("a", "b", "c"), start=1))
        reconhecedor._prever_ensemble = MagicMock(return_value=(combinar_probabilidades([a, b, c], [1, 1, 1]), (a, b, c)))
        resultado = reconhecedor.reconhecer(np.zeros((256, 256, 3), np.uint8))
        casa = resultado.casas[8]
        self.assertEqual(casa.classe_original, "P")
        self.assertEqual([v.classe for v in casa.previsoes_modelos], ["N", "P", "P"])
        self.assertAlmostEqual(casa.concordancia, 2 / 3)
        self.assertTrue(casa.divergencia_modelos)
        self.assertIn("a2", resultado.aviso)
        self.assertFalse(resultado.confiavel)
        # Mesmo uma votação com confiança alta fica fora das referências
        # quando um membro aponta uma alternativa forte.
        a[8] = b[8] = matriz_com_classe("P")[0]
        c[8] = matriz_com_classe("N", 0.99)[0]
        pesos = [0.90, 0.09, 0.01]
        reconhecedor._configuracoes = tuple(replace(cfg, peso=peso) for cfg, peso
                                           in zip(reconhecedor._configuracoes, pesos))
        reconhecedor._prever_ensemble.return_value = (combinar_probabilidades([a, b, c], pesos), (a, b, c))
        forte = reconhecedor.reconhecer(np.zeros((256, 256, 3), np.uint8))
        self.assertGreater(forte.casas[8].confianca, 0.85)
        self.assertGreater(forte.casas[8].margem, 0.30)
        revisor = RevisorAutomaticoLivro([forte, forte, forte], idioma="en")
        self.assertFalse(any(ref.classe == "P" for ref in revisor.referencias_automaticas))
        sem_divergencia = replace(forte, casas=(replace(forte.casas[8], divergencia_modelos=False),))
        controle = RevisorAutomaticoLivro([sem_divergencia] * 3, idioma="en")
        self.assertTrue(any(ref.classe == "P" for ref in controle.referencias_automaticas))


if __name__ == "__main__":
    unittest.main()
