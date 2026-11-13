from __future__ import annotations

import time
import unittest
from unittest.mock import MagicMock, patch

import ttkbootstrap as ttk

from importacao_imagem import TabuleiroImportado
from importacao_imagem_ui import JanelaImportarImagem, foco_em_campo_de_texto
from notacao_forsyth import ResultadoReconhecimento
from tabuleiros_padronizados import renderizar_tabuleiro

# Pretas embaixo: os peões brancos estão nas linhas superiores da imagem.
INVERTIDA_EN = "R2KQBNR/PPP1PPPP/2N5/3P1B2/3p1b2/5n2/ppp1pppp/rn1kqb1r"


def resultado(posicao: str, aviso: str = "") -> ResultadoReconhecimento:
    return ResultadoReconhecimento(posicao=posicao, confianca_minima=1, confianca_media=1, confiavel=not aviso,
                                   girado=False, orientacao_ambigua=False, aviso=aviso)


class TesteJanelaImportacao(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raiz = ttk.Window()
        cls.raiz.withdraw()

    @classmethod
    def tearDownClass(cls):
        cls.raiz.destroy()

    def setUp(self):
        self.janela = JanelaImportarImagem(self.raiz, "pt")
        self.imagem = renderizar_tabuleiro("4r3/8/8/8/8/8/8/4R3", tamanho=160)

    def tearDown(self):
        if self.janela.existe():
            self.janela.fechar()

    def reconhecer(self, posicao_en: str, aviso: str = "", idioma_durante: str | None = None):
        reconhecedor = MagicMock()
        reconhecedor.reconhecer.side_effect = lambda _imagem: resultado(
            posicao_en if reconhecedor.idioma == "en" else posicao_en.translate(
                str.maketrans("KQRBNPkqrbnp", "RDTBCPrdtbcp")), aviso)
        self.janela._reconhecedor = reconhecedor
        tabuleiro = TabuleiroImportado(self.imagem, None, 1.0, True)
        with patch("importacao_imagem_ui.localizar_tabuleiro", return_value=tabuleiro):
            self.janela.processar(self.imagem, "teste")
            if idioma_durante:
                self.janela.definir_idioma(idioma_durante)
            limite = time.monotonic() + 10
            while self.janela._trabalhando and time.monotonic() < limite:
                self.raiz.update()
                time.sleep(0.01)
        self.assertFalse(self.janela._trabalhando)

    def test_fen_completa_ou_inglesa_no_campo_e_aceita_e_define_lado(self):
        self.janela.posicao.set("4k3/8/8/8/8/8/8/3QK3 b - - 0 1")
        self.janela._atualizar_previa()
        self.assertEqual(self.janela.lado.get(), "b")
        self.assertEqual(str(self.janela.botao_copiar.cget("state")), "normal")
        self.assertEqual(self.janela.fen_atual(), "4k3/8/8/8/8/8/8/3QK3 b - - 0 1")
        self.janela.posicao.set("lixo")
        self.janela._atualizar_previa()
        self.assertEqual(str(self.janela.botao_copiar.cget("state")), "disabled")

    def test_troca_de_idioma_converte_a_posicao_atual(self):
        self.janela.posicao.set("4r3/8/8/8/8/8/8/3DR3")
        self.janela.definir_idioma("en")
        self.assertEqual(self.janela.posicao.get(), "4k3/8/8/8/8/8/8/3QK3")
        self.assertEqual(self.janela.fen_atual(), "4k3/8/8/8/8/8/8/3QK3 w - - 0 1")

    def test_troca_de_idioma_durante_reconhecimento_converte_o_resultado(self):
        self.reconhecer("4k3/8/8/8/8/8/8/3QK3", idioma_durante="en")
        self.assertEqual(self.janela.posicao.get(), "4k3/8/8/8/8/8/8/3QK3")

    def test_avisa_pretas_embaixo_e_inversao_explica_coordenadas(self):
        self.reconhecer(INVERTIDA_EN, aviso="Confira as casas: b2.")
        self.assertIn("pretas parecem estar embaixo", self.janela.aviso.get())
        self.janela._inverter()
        self.assertTrue(self.janela.aviso.get().startswith("Tabuleiro invertido"))
        self.assertEqual(self.janela.posicao.get(), "t1bdr1ct/pppp1ppp/2c5/2b1p3/2B1P3/5C2/PPPP1PPP/TCBDR2T")
        self.janela._inverter()
        self.assertFalse(self.janela.aviso.get().startswith("Tabuleiro invertido"))

    def test_colagem_durante_reconhecimento_informa_espera(self):
        self.janela._trabalhando = True
        self.janela.processar(self.imagem, "teste")
        self.assertIn("Aguarde", self.janela.status.get())
        self.janela._trabalhando = False

    def test_fechar_durante_reconhecimento_nao_gera_erro(self):
        self.janela._eventos.put((True, ("x", None, None, "pt")))
        self.janela.fechar()
        self.janela._consultar()  # Callback pendente após o fechamento.

    def test_foco_em_popup_interno_nao_quebra_ctrl_v(self):
        widget = MagicMock()
        widget.focus_get.side_effect = KeyError("popdown")
        self.assertFalse(foco_em_campo_de_texto(widget))
        with patch.object(self.janela.janela, "focus_get", return_value=self.janela.campo_posicao), \
                patch("importacao_imagem.ImageGrab.grabclipboard", return_value=None):
            self.assertIsNone(self.janela._ao_colar())  # Texto continua sendo colado no campo.


if __name__ == "__main__":
    unittest.main()
