from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np
from PIL import Image

from importacao_imagem import (
    ErroImportacaoImagem,
    carregar_imagem,
    converter_pil_para_bgr,
    fen_completa,
    imagem_da_area_transferencia,
    interpretar_posicao,
    localizar_tabuleiro,
    parece_invertido,
)
from notacao_forsyth import ReconhecedorForsyth

RAIZ = Path(__file__).resolve().parents[1]
FENSHOT = RAIZ / "tests" / "fixtures" / "fenshot"


class TesteCarregamento(unittest.TestCase):
    def test_gif_png_transparente_e_jpg_viram_bgr(self):
        with tempfile.TemporaryDirectory() as pasta:
            rgba = Image.new("RGBA", (100, 80), (0, 0, 0, 0))
            rgba.paste((255, 0, 0, 255), (0, 0, 50, 80))
            rgba.save(Path(pasta) / "a.png")
            rgba.convert("RGB").save(Path(pasta) / "a.gif")
            rgba.convert("RGB").save(Path(pasta) / "á ç.jpg")
            png = carregar_imagem(Path(pasta) / "a.png")
            self.assertEqual(png.shape, (80, 100, 3))
            np.testing.assert_array_equal(png[10, 10], [0, 0, 255])  # vermelho em BGR
            np.testing.assert_array_equal(png[10, 90], [255, 255, 255])  # transparência → branco
            self.assertEqual(carregar_imagem(Path(pasta) / "a.gif").shape, (80, 100, 3))
            self.assertEqual(carregar_imagem(Path(pasta) / "á ç.jpg").shape, (80, 100, 3))

    def test_cinza_16_bits_e_reescalado_em_vez_de_cortado(self):
        valores = np.tile(np.linspace(0, 60000, 100), (100, 1)).astype(np.uint16)
        bgr = converter_pil_para_bgr(Image.fromarray(valores))
        self.assertEqual(int(bgr[0, 0, 0]), 0)
        self.assertEqual(int(bgr[0, 99, 0]), 255)
        self.assertTrue(100 < int(bgr[0, 50, 0]) < 155)

    def test_transparencia_vira_branco_e_alfa_zerado_e_ignorado(self):
        paleta = Image.new("P", (100, 100), 1)
        paleta.putpalette([0, 0, 0, 10, 20, 30] + [0] * 762)
        paleta.paste(0, (0, 0, 20, 20))
        paleta.info["transparency"] = 1  # GIF/PNG com cor de fundo transparente
        cinza_alfa = Image.fromarray(np.dstack([np.zeros((100, 100), np.uint8),
                                                np.pad(np.full((20, 20), 255, np.uint8), ((0, 80), (0, 80)))]), "LA")
        for imagem in (paleta, cinza_alfa):
            bgr = converter_pil_para_bgr(imagem)
            np.testing.assert_array_equal(bgr[50, 50], [255, 255, 255])
            np.testing.assert_array_equal(bgr[5, 5], [0, 0, 0])
        # Bitmap de 32 bits da área de transferência com alfa todo zerado.
        pixels = np.dstack([np.full((100, 100, 3), 40, np.uint8), np.zeros((100, 100), np.uint8)])
        np.testing.assert_array_equal(converter_pil_para_bgr(Image.fromarray(pixels))[50, 50], [40, 40, 40])

    def test_imagem_gigante_gera_erro_legivel(self):
        with tempfile.TemporaryDirectory() as pasta:
            Image.new("RGB", (100, 100)).save(Path(pasta) / "g.png")
            with patch("importacao_imagem.Image.open", side_effect=Image.DecompressionBombError("x")):
                with self.assertRaises(ErroImportacaoImagem):
                    carregar_imagem(Path(pasta) / "g.png")
            with patch("importacao_imagem.ImageGrab.grabclipboard",
                       side_effect=Image.DecompressionBombError("x")):
                with self.assertRaises(ErroImportacaoImagem):
                    imagem_da_area_transferencia()

    def test_arquivo_invalido_ou_pequeno_gera_erro_legivel(self):
        with tempfile.TemporaryDirectory() as pasta:
            texto = Path(pasta) / "x.png"
            texto.write_text("não é imagem", encoding="utf-8")
            with self.assertRaises(ErroImportacaoImagem):
                carregar_imagem(texto)
            Image.new("RGB", (30, 30)).save(Path(pasta) / "p.png")
            with self.assertRaises(ErroImportacaoImagem):
                carregar_imagem(Path(pasta) / "p.png")
            with self.assertRaises(ErroImportacaoImagem):
                carregar_imagem(Path(pasta) / "ausente.png")

    def test_area_transferencia_aceita_imagem_ou_arquivo_copiado(self):
        with patch("importacao_imagem.ImageGrab.grabclipboard", return_value=Image.new("RGB", (90, 90))):
            self.assertEqual(imagem_da_area_transferencia().shape, (90, 90, 3))
        with tempfile.TemporaryDirectory() as pasta:
            Image.new("RGB", (70, 70)).save(Path(pasta) / "d.webp")
            copiados = [str(Path(pasta) / "notas.txt"), str(Path(pasta) / "d.webp")]
            with patch("importacao_imagem.ImageGrab.grabclipboard", return_value=copiados):
                self.assertEqual(imagem_da_area_transferencia().shape, (70, 70, 3))
        with patch("importacao_imagem.ImageGrab.grabclipboard", return_value=None):
            self.assertIsNone(imagem_da_area_transferencia())


class TesteFen(unittest.TestCase):
    def test_fen_completa_converte_para_letras_inglesas_e_inclui_lado(self):
        self.assertEqual(fen_completa("4r3/8/8/8/8/8/8/3DR3", "b", "pt"), "4k3/8/8/8/8/8/8/3QK3 b - - 0 1")
        self.assertEqual(fen_completa("4k3/8/8/8/8/8/8/4K3", "x", "en"), "4k3/8/8/8/8/8/8/4K3 w - - 0 1")

    def test_campo_aceita_fen_completa_lado_e_outro_alfabeto(self):
        self.assertEqual(interpretar_posicao("4k3/8/8/8/8/8/8/3QK3 b - - 0 1", "pt"),
                         ("4r3/8/8/8/8/8/8/3DR3", "b"))
        self.assertEqual(interpretar_posicao("4r3/8/8/8/8/8/8/3DR3 w", "en"), ("4k3/8/8/8/8/8/8/3QK3", "w"))
        self.assertEqual(interpretar_posicao("4r3/8/8/8/8/8/8/3DR3", "pt"), ("4r3/8/8/8/8/8/8/3DR3", None))
        for texto in ("", "lixo", "8/8/8/8/8/8/8/8 w"):
            self.assertIsNone(interpretar_posicao(texto, "pt")[0])

    def test_peoes_indicam_diagrama_com_pretas_embaixo(self):
        self.assertTrue(parece_invertido("R2KQBNR/PPP1PPPP/2N5/3P1B2/3p1b2/5n2/ppp1pppp/rn1kqb1r", "en"))
        self.assertFalse(parece_invertido("r1bqk1nr/pppp1ppp/2n5/2b1p3/2B1P3/5N2/PPPP1PPP/RNBQK2R", "en"))
        self.assertFalse(parece_invertido("6k1/2Q5/8/8/8/2q5/8/6K1", "en"))  # sem peões: ambíguo


class TesteLocalizacao(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.reconhecedor = ReconhecedorForsyth(idioma="en")
        cls.posicoes = {d["arquivo"]: d["posicao"] for d in
                        json.loads((FENSHOT / "posicoes.json").read_text(encoding="utf-8"))}

    def test_captura_de_site_localiza_tabuleiro_e_reconhece_posicao(self):
        for arquivo in ("lichess-queens-only-board-marble.png", "pale-blue-tds-board.png"):
            with self.subTest(arquivo=arquivo):
                imagem = carregar_imagem(FENSHOT / arquivo)
                pequena = cv2.resize(imagem, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
                tabuleiro = localizar_tabuleiro(pequena)
                self.assertTrue(tabuleiro.detectado)
                # O tabuleiro é uma parte da página, não a captura inteira.
                self.assertLess(cv2.contourArea(tabuleiro.quadro), pequena.shape[0] * pequena.shape[1] * 0.6)
                resultado = self.reconhecedor.reconhecer(tabuleiro.imagem)
                self.assertEqual(resultado.posicao, self.posicoes[arquivo])

    def test_recorte_justo_usa_imagem_inteira(self):
        imagem = cv2.imread(str(RAIZ / "tests/fixtures/recognition/p0262-d01.png"))
        tabuleiro = localizar_tabuleiro(imagem)
        self.assertEqual(tabuleiro.imagem.shape[:2], imagem.shape[:2])
        self.assertEqual(self.reconhecedor.reconhecer(tabuleiro.imagem).posicao,
                         "r4r2/pbqkn1pp/2bNp3/2P1n1B1/8/P2B4/2Q3PP/R4R1K")

    def test_diagrama_pequeno_no_meio_de_texto(self):
        diagrama = cv2.imread(str(RAIZ / "tests/fixtures/recognition/p0565-d02.png"))
        pagina = np.full((900, 700, 3), 255, np.uint8)
        for y in range(40, 880, 28):
            cv2.putText(pagina, "1.e4 e5 2.Nf3 Nc6 3.Bb5 a6 4.Ba4 Nf6", (30, y),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 1)
        pagina[300:600, 150:450] = 255
        pagina[320:580, 170:430] = cv2.resize(diagrama, (260, 260), interpolation=cv2.INTER_AREA)
        tabuleiro = localizar_tabuleiro(pagina)
        self.assertTrue(tabuleiro.detectado)
        np.testing.assert_allclose(tabuleiro.quadro.min(axis=0), [170, 320], atol=4)
        np.testing.assert_allclose(tabuleiro.quadro.max(axis=0), [429, 579], atol=4)
        self.assertEqual(self.reconhecedor.reconhecer(tabuleiro.imagem).posicao,
                         "4q2n/1p2r2P/p4R1Q/2kp4/2p5/P7/1PP5/1K6")

    def test_foto_inclinada_ocupando_a_imagem_ainda_e_retificada(self):
        diagrama = cv2.imread(str(RAIZ / "tests/fixtures/recognition/p0565-d02.png"))
        lado = diagrama.shape[0]
        destino = np.float32([[40, 10], [lado + 20, 45], [lado - 5, lado + 30], [5, lado + 5]])
        matriz = cv2.getPerspectiveTransform(
            np.float32([[0, 0], [lado - 1, 0], [lado - 1, lado - 1], [0, lado - 1]]), destino)
        foto = cv2.warpPerspective(diagrama, matriz, (lado + 30, lado + 40), borderValue=(255, 255, 255))
        tabuleiro = localizar_tabuleiro(foto)
        self.assertTrue(tabuleiro.detectado)
        self.assertNotEqual(tabuleiro.imagem.shape[:2], foto.shape[:2])
        self.assertEqual(self.reconhecedor.reconhecer(tabuleiro.imagem).posicao,
                         "4q2n/1p2r2P/p4R1Q/2kp4/2p5/P7/1PP5/1K6")

    def test_sem_moldura_remove_faixa_uniforme_e_usa_o_restante(self):
        imagem = np.full((300, 400, 3), 240, np.uint8)
        imagem[50:250, 100:300] = np.kron((np.indices((8, 8)).sum(axis=0) % 2) * 120 + 60,
                                          np.ones((25, 25)))[..., None].astype(np.uint8)
        tabuleiro = localizar_tabuleiro(imagem)
        np.testing.assert_allclose(tabuleiro.quadro.min(axis=0), [100, 50], atol=3)
        np.testing.assert_allclose(tabuleiro.quadro.max(axis=0), [299, 249], atol=3)


if __name__ == "__main__":
    unittest.main()
