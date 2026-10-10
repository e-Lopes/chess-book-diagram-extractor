from __future__ import annotations

import json
from pathlib import Path
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from alinhamento_tabuleiro import alinhar_grade
from notacao_forsyth import ReconhecedorForsyth, substituir_casa, expandir_posicao
from restricoes_reconhecimento import eleger_com_reis
from reconhecimento_ensemble import CLASSES

RAIZ = Path(__file__).resolve().parents[1]


class TesteEdicaoCasa(unittest.TestCase):
    def test_substitui_remove_e_preserva_lado_nos_dois_idiomas(self):
        for idioma, rei in (("pt", "R"), ("en", "K")):
            posicao = f"4{rei.lower()}3/8/8/8/8/8/8/4{rei}3 b"
            nova = substituir_casa(posicao, 1, 5, "b", idioma)
            self.assertEqual(nova, f"4{rei.lower()}3/5b2/8/8/8/8/8/4{rei}3 b")
            self.assertEqual(substituir_casa(nova, 1, 5, "", idioma), posicao)

    def test_move_rei_sem_criar_duplicado_e_preserva_campos_fen(self):
        texto = "4k3/8/8/8/8/8/8/4K3 w - - 12 20"
        self.assertEqual(substituir_casa(texto, 6, 7, "K", "en"),
                         "4k3/8/8/8/8/8/7K/8 w - - 12 20")

    def test_casa_invalida_nao_produz_posicao(self):
        for linha, coluna, peca in ((-1, 0, "B"), (0, 8, "B"), (0, 0, "Z")):
            with self.assertRaises(ValueError):
                substituir_casa("8/8/8/8/8/8/8/8", linha, coluna, peca)


class TesteEleicaoReis(unittest.TestCase):
    def setUp(self):
        self.matriz = np.zeros((64, 13), np.float32)
        self.matriz[:, 0] = 1

    def casa(self, indice, probabilidades):
        self.matriz[indice] = 0
        for classe, valor in probabilidades.items():
            self.matriz[indice, CLASSES.index(classe)] = valor

    def test_duplicado_conserva_rei_forte_e_usa_segunda_peca_na_outra_casa(self):
        self.casa(7, {"K": .999, "Q": .001})
        self.casa(53, {"K": .80, "B": .19, "1": .01})
        self.casa(59, {"k": .99, "1": .01})
        antes = self.matriz.copy()
        indices, ajustadas = eleger_com_reis(self.matriz)
        classes = [CLASSES[i] for i in indices]
        self.assertEqual(classes.count("K"), 1)
        self.assertEqual(classes.count("k"), 1)
        self.assertEqual((classes[7], classes[53]), ("K", "B"))
        self.assertEqual(ajustadas, (53,))
        np.testing.assert_array_equal(self.matriz, antes)

    def test_reis_faltantes_escolhem_casas_distintas_sem_elevar_confianca(self):
        self.casa(4, {"1": .5, "K": .30, "k": .20})
        self.casa(60, {"1": .6, "k": .35, "K": .05})
        indices, ajustadas = eleger_com_reis(self.matriz)
        self.assertEqual(CLASSES[indices[4]], "K")
        self.assertEqual(CLASSES[indices[60]], "k")
        self.assertEqual(ajustadas, (4, 60))
        self.assertAlmostEqual(float(self.matriz[4, indices[4]]), .3)

    def test_duas_cores_disputando_a_mesma_casa_nao_se_sobrepoem(self):
        self.casa(4, {"K": .5, "k": .45, "1": .05})
        self.casa(60, {"k": .4, "1": .6})
        indices, _ajustadas = eleger_com_reis(self.matriz)
        self.assertEqual((CLASSES[indices[4]], CLASSES[indices[60]]), ("K", "k"))


class TesteCasosDoLivro(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reconhecedor = ReconhecedorForsyth(idioma="en")

    def test_circulo_f7_nao_vira_segundo_rei_e_rei_h1_permanece(self):
        imagem = cv2.imread(str(RAIZ / 'tests/fixtures/recognition/p0262-d01.png'))
        resultado = self.reconhecedor.reconhecer(imagem)
        self.assertEqual(resultado.posicao, "r4r2/pbqkn1pp/2bNp3/2P1n1B1/8/P2B4/2Q3PP/R4R1K")
        self.assertIn("f7", resultado.ajustes_reis)
        self.assertFalse(resultado.confiavel)
        self.assertEqual(len(resultado.casas[53].previsoes_modelos), 3)

    def test_borda_com_coordenadas_preserva_original_e_reconhece_todas_as_pecas(self):
        imagem = cv2.imread(str(RAIZ / 'tests/fixtures/recognition/p0565-d02.png'))
        antes = imagem.copy()
        alinhada, limites = alinhar_grade(imagem)
        self.assertGreater(limites[0], 0)
        self.assertLess(limites[3], imagem.shape[0])
        self.assertGreater(alinhada.shape[0], imagem.shape[0] * .85)
        resultado = self.reconhecedor.reconhecer(imagem)
        self.assertEqual(resultado.posicao, "4q2n/1p2r2P/p4R1Q/2kp4/2p5/P7/1PP5/1K6")
        np.testing.assert_array_equal(imagem, antes)
