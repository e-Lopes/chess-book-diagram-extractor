from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import cv2
import numpy as np
import ttkbootstrap as ttk

from biblioteca_livros import BibliotecaLivros, DiagramaSalvo, gerar_pgn, selecionar_diagramas_pgn
from extrair_tabuleiros_pdf import Candidato, criar_pdf_a4, detectar_tabuleiros, pontuar_tabuleiro
from interface_windows import InterfaceExtrator
from notacao_forsyth import ItemRevisao
from tabuleiros_padronizados import renderizar_tabuleiro
from visualizacao_diagramas import ComparadorDiagramas

RAIZ = Path(__file__).resolve().parents[1]
POSICAO = "4r3/8/8/8/8/8/8/4R3"


class TesteFiltroDiagramas(unittest.TestCase):
    def test_rejeita_os_sete_exemplos_reais_inclusive_por_caixa_de_imagem_pdf(self):
        for arquivo in sorted((RAIZ / "tests/fixtures/nonboards").glob("*.png")):
            with self.subTest(arquivo=arquivo.name):
                imagem = cv2.imread(str(arquivo))
                self.assertIsNotNone(imagem)
                altura, largura = imagem.shape[:2]
                quadro = np.array(((0, 0), (largura - 1, 0), (largura - 1, altura - 1), (0, altura - 1)), np.float32)
                self.assertEqual(pontuar_tabuleiro(imagem), 0)
                self.assertEqual(detectar_tabuleiros(imagem, quadros_adicionais=[quadro]), [])

    def test_pecas_classicas_formam_um_tabuleiro_detectavel(self):
        imagem = renderizar_tabuleiro("tcbdrbct/pppppppp/8/8/8/8/PPPPPPPP/TCBDRBCT", tamanho=400)
        pagina = np.full((700, 600, 3), 255, np.uint8)
        pagina[150:550, 100:500] = imagem
        self.assertGreater(pontuar_tabuleiro(imagem), .9)
        self.assertEqual(len(detectar_tabuleiros(pagina)), 1)

    def test_navegacao_oculta_descartados_sem_apagar_posicoes(self):
        interface = InterfaceExtrator.__new__(InterfaceExtrator)
        interface.itens_biblioteca = [ItemRevisao(posicao="invalida", nao_e_tabuleiro=True),
            ItemRevisao(posicao=POSICAO), ItemRevisao(posicao=POSICAO, nao_e_tabuleiro=True), ItemRevisao(posicao=POSICAO)]
        interface.mostrar_descartados_biblioteca = MagicMock()
        interface.mostrar_descartados_biblioteca.get.return_value = False
        interface._salvar_automaticamente_biblioteca = MagicMock(return_value=True)
        interface._exibir_diagrama_biblioteca = MagicMock()
        interface.indice_biblioteca = 1
        self.assertEqual(interface._indices_visiveis_biblioteca(), [1, 3])
        self.assertEqual(interface._indices_invalidos_biblioteca(interface.itens_biblioteca, "pt"), [])
        interface._navegar_biblioteca(1)
        self.assertEqual(interface.indice_biblioteca, 3)
        interface._ir_para_biblioteca(0)
        self.assertEqual(interface.indice_biblioteca, 1)
        interface.mostrar_descartados_biblioteca.get.return_value = True
        self.assertEqual(interface._indices_visiveis_biblioteca(), [0, 1, 2, 3])
        self.assertEqual(interface.itens_biblioteca[2].posicao, POSICAO)

    def test_pgn_ignora_descartado_mesmo_com_forsyth_valida(self):
        descartado = DiagramaSalvo(1, posicao=POSICAO, excluir=True)
        mantido = DiagramaSalvo(2, posicao=POSICAO, excluir=False)
        self.assertEqual(selecionar_diagramas_pgn([descartado, mantido]), ([mantido], []))
        self.assertEqual(gerar_pgn("Livro", [descartado, mantido], "", "pt").count('[FEN "'), 1)

    def test_exclusao_e_restauracao_manual_persistem_na_biblioteca(self):
        with tempfile.TemporaryDirectory() as pasta:
            pasta = Path(pasta)
            imagem = renderizar_tabuleiro(POSICAO, tamanho=160)
            quadro = np.array(((0, 0), (159, 0), (159, 159), (0, 159)), np.float32)
            pdf = pasta / "diagrama.pdf"
            criar_pdf_a4([Candidato(1, quadro, imagem, 0)], pdf)
            biblioteca = BibliotecaLivros(pasta / "dados")
            livro = biblioteca.salvar(pdf, "Livro", [DiagramaSalvo(1, posicao=POSICAO, excluir=True)])
            self.assertTrue(biblioteca.carregar(livro.id).diagramas[0].excluir)
            livro = biblioteca.salvar(livro.pdf_interno, livro.titulo,
                [DiagramaSalvo(1, posicao=POSICAO, excluir=False)], livro_id=livro.id)
            self.assertFalse(biblioteca.carregar(livro.id).diagramas[0].excluir)
            self.assertEqual(len(biblioteca.carregar_candidatos(livro)), 1)


class TesteAssetsClassicos(unittest.TestCase):
    def test_doze_svgs_e_licenca_sao_preservados(self):
        pasta = RAIZ / "assets/pieces/cburnett"
        manifesto = json.loads((pasta / "manifest.json").read_text(encoding="utf8"))
        self.assertEqual(manifesto["licenca"], "BSD-3-Clause")
        self.assertEqual(set(manifesto["arquivos"]), {f"{cor}{p}.svg" for cor in "wb" for p in "KQRBNP"})
        for nome, item in manifesto["arquivos"].items():
            self.assertEqual(hashlib.sha256((pasta / nome).read_bytes()).hexdigest(), item["sha256"])
            self.assertTrue(item["licenca_fonte"].startswith("https://commons.wikimedia.org/wiki/File:"))
        self.assertTrue((RAIZ / "licenses/cburnett-BSD-3-Clause.txt").is_file())


class TesteComparadorReal(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raiz = ttk.Window()
        cls.raiz.withdraw()

    @classmethod
    def tearDownClass(cls):
        cls.raiz.destroy()

    def setUp(self):
        self.quadro = ComparadorDiagramas(self.raiz)
        self.quadro.pack(fill="both", expand=True)
        self.original = renderizar_tabuleiro(POSICAO, tamanho=160)

    def tearDown(self):
        self.quadro.destroy()

    def test_lado_a_lado_tem_imagens_independentes_e_atualiza_ao_editar(self):
        antes = self.original.copy()
        self.quadro.exibir(self.original, POSICAO, "pt")
        self.assertEqual(set(self.quadro._imagens_tk), {"original", "padronizado"})
        self.assertEqual(self.quadro.paineis["original"].grid_info()["column"], 0)
        self.assertEqual(self.quadro.paineis["padronizado"].grid_info()["column"], 2)
        self.assertEqual(self.quadro.seta.grid_info()["column"], 1)
        foto_anterior = self.quadro._imagens_tk["padronizado"]
        nova = "3r4/8/8/8/8/8/8/4R3"
        self.quadro.exibir(self.original, nova, "pt")
        self.assertEqual(self.quadro._chave_previa, (nova, "pt"))
        self.assertIsNot(self.quadro._imagens_tk["padronizado"], foto_anterior)
        np.testing.assert_array_equal(self.original, antes)

    def test_forsyth_invalida_nao_mostra_foto_original_como_padronizado(self):
        self.quadro.exibir(self.original, "invalida", "pt")
        self.assertIn("original", self.quadro._imagens_tk)
        self.assertNotIn("padronizado", self.quadro._imagens_tk)
        self.assertIn("Forsyth inválida", self.quadro.rotulos["padronizado"].cget("text"))

    def test_clique_desconta_margens_da_imagem_e_nao_edita_area_externa(self):
        self.quadro.exibir(self.original, POSICAO, "pt")
        self.quadro._tamanho_padronizado = (320, 320)
        rotulo = self.quadro.rotulos['padronizado']
        with patch.object(rotulo, 'winfo_width', return_value=400), patch.object(rotulo, 'winfo_height', return_value=600):
            self.assertEqual(self.quadro.casa_no_ponto(41, 141), (0, 0))
            self.assertEqual(self.quadro.casa_no_ponto(359, 459), (7, 7))
            self.assertIsNone(self.quadro.casa_no_ponto(20, 300))
            self.assertIsNone(self.quadro.casa_no_ponto(200, 500))

    def test_seletor_tem_doze_pecas_e_vazio_e_atualiza_forsyth(self):
        self.quadro.ao_editar = MagicMock()
        self.quadro.exibir(self.original, POSICAO + ' b', 'pt')
        self.quadro._abrir_seletor(1, 5)
        janela = self.quadro._seletor
        self.assertIs(janela.master, self.raiz)
        botoes = [w for quadro in janela.winfo_children() for w in quadro.winfo_children()
                  if isinstance(w, ttk.Button)]
        self.assertEqual(len(botoes), 14)
        bispos = [b for b in botoes if b.cget('text') == 'Bispo']
        bispos[1].invoke()
        self.quadro.ao_editar.assert_called_once_with('4r3/5b2/8/8/8/8/8/4R3 b')
        self.assertIsNone(self.quadro._seletor)

    def test_modos_individuais_ocupam_a_area_da_comparacao(self):
        for modo in ("original", "padronizado"):
            self.quadro.exibir(self.original, POSICAO, "pt", modo)
            self.assertEqual(self.quadro.paineis[modo].grid_info()["columnspan"], 3)
            outro = "original" if modo == "padronizado" else "padronizado"
            self.assertEqual(self.quadro.paineis[outro].winfo_manager(), "")

    def test_livro_antigo_oculta_nao_tabuleiros_e_permite_restaurar(self):
        with tempfile.TemporaryDirectory() as pasta, patch("interface_windows.pasta_dados_aplicativo", return_value=Path(pasta)), patch("interface_windows.configurar_logger", return_value=MagicMock()):
            interface = InterfaceExtrator(self.raiz)
        interface._salvar_automaticamente_biblioteca = MagicMock(return_value=True)
        quad = np.array(((0, 0), (159, 0), (159, 159), (0, 159)), np.float32)
        candidatos = [Candidato(1, quad, np.full((160, 160, 3), 255, np.uint8), 0),
                      Candidato(2, quad, self.original, .95)]
        livro = SimpleNamespace(diagramas=[DiagramaSalvo(1, posicao="invalida"), DiagramaSalvo(2, posicao=POSICAO)],
                               idioma="pt", titulo="Livro antigo", annotator="", paginas_originais=2)
        interface._mostrar_livro_biblioteca(livro, candidatos)
        self.assertEqual(interface.indice_biblioteca, 1)
        self.assertTrue(interface.itens_biblioteca[0].nao_e_tabuleiro)
        interface.mostrar_descartados_biblioteca.set(True)
        interface._ir_para_biblioteca(0)
        self.assertEqual(interface.indice_biblioteca, 0)
        interface.excluir_biblioteca.set(False)
        interface._alterar_exclusao_biblioteca()
        self.assertFalse(interface.itens_biblioteca[0].nao_e_tabuleiro)

    def test_livro_com_todos_os_recortes_descartados_nao_exibe_imagem_oculta(self):
        with tempfile.TemporaryDirectory() as pasta, patch("interface_windows.pasta_dados_aplicativo", return_value=Path(pasta)), patch("interface_windows.configurar_logger", return_value=MagicMock()):
            interface = InterfaceExtrator(self.raiz)
        quad = np.array(((0, 0), (159, 0), (159, 159), (0, 159)), np.float32)
        livro = SimpleNamespace(diagramas=[DiagramaSalvo(1)], idioma="pt", titulo="Sem tabuleiros", annotator="", paginas_originais=1)
        interface._mostrar_livro_biblioteca(livro, [Candidato(1, quad, self.original, 0)])
        self.assertEqual(interface.comparador_biblioteca._imagens_tk, {})
        self.assertEqual(interface.rotulo_contador_biblioteca.cget("text"), "0 tabuleiros")
        self.assertEqual(str(interface.botao_proximo_biblioteca.cget("state")), "disabled")


if __name__ == "__main__":
    unittest.main()
