from __future__ import annotations

import threading
import time
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import cv2
import numpy as np
import ttkbootstrap as ttk

from biblioteca_livros import BibliotecaLivros, DiagramaSalvo, resumir_diagramas
from interface_windows import InterfaceExtrator
from notacao_forsyth import ItemRevisao, ReconhecedorForsyth, RevisorAutomaticoLivro
from revisor_forsyth import JanelaRevisaoForsyth
from revisao_assincrona import RevisaoAssincrona
from marcadores_diagrama import casas_com_bolinhas
from restricoes_reconhecimento import eleger_com_reis
from reconhecimento_ensemble import CLASSES
from tabuleiros_padronizados import renderizar_previa, renderizar_tabuleiro
from visualizacao_diagramas import ComparadorDiagramas

RAIZ = Path(__file__).resolve().parents[1]
POSICAO = "4k3/8/8/8/8/8/8/4K3"


class RevisorLento:
    def __init__(self):
        self.resultados_originais = []
        self.referencias_manuais = []
        self.excluidos = set()
        self.fundos = {}
        self.referencias_automaticas = []
        self.inicio = threading.Event()
        self.liberar = threading.Event()
        self.threads = []

    def revisar_itens(self, itens):
        self.threads.append(threading.get_ident())
        self.inicio.set()
        if not self.liberar.wait(3):
            raise RuntimeError("A worker não foi liberada pelo teste.")
        for item in itens:
            item.posicao = "revista"


class TesteRevisaoAssincrona(unittest.TestCase):
    def setUp(self):
        self.janela = MagicMock()
        self.indicar, self.aplicar, self.erro = MagicMock(), MagicMock(), MagicMock()
        self.tarefa = RevisaoAssincrona(self.janela, self.indicar, self.aplicar, self.erro)
        self.revisor = RevisorLento()
        self.itens = [ItemRevisao(posicao=POSICAO)]

    def tearDown(self):
        self.revisor.liberar.set()
        self.tarefa.fechar()

    def esperar_fila(self):
        prazo = time.monotonic() + 3
        while self.tarefa._fila.empty() and time.monotonic() < prazo:
            time.sleep(.001)
        self.assertFalse(self.tarefa._fila.empty())

    def iniciar(self):
        self.tarefa.agendar(self.revisor, self.itens)
        self.tarefa._iniciar()
        self.assertTrue(self.revisor.inicio.wait(1))

    def test_worker_isola_itens_e_exportacao_aguarda_sem_bloquear(self):
        self.iniciar()
        callback = MagicMock()
        self.assertFalse(self.tarefa.quando_pronto(callback))
        self.assertNotEqual(self.revisor.threads[0], threading.get_ident())
        self.tarefa._consultar()  # A interface continua podendo atender eventos.
        self.assertEqual(self.itens[0].posicao, POSICAO)
        self.aplicar.assert_not_called()
        self.revisor.liberar.set()
        self.esperar_fila()
        self.tarefa._consultar()
        anteriores, revisados = self.aplicar.call_args.args
        self.assertEqual(anteriores, [POSICAO])
        self.assertEqual(revisados[0].posicao, "revista")
        self.assertEqual(self.itens[0].posicao, POSICAO)
        callback.assert_called_once()
        self.indicar.assert_called_with("")

    def test_nova_edicao_descarta_resultados_antigos_e_executa_a_mais_recente(self):
        self.iniciar()
        self.itens[0].posicao = "nova"
        self.tarefa.agendar(self.revisor, self.itens)
        self.revisor.liberar.set()
        self.esperar_fila()
        self.tarefa._consultar()
        self.aplicar.assert_not_called()
        self.esperar_fila()
        self.tarefa._consultar()
        self.aplicar.assert_called_once()
        self.assertEqual(self.aplicar.call_args.args[0], ["nova"])

    def test_fechar_impede_aplicar_resultado_e_exportar_em_janela_destruida(self):
        self.iniciar()
        callback = MagicMock()
        self.tarefa.quando_pronto(callback)
        self.tarefa.fechar()
        self.revisor.liberar.set()
        self.esperar_fila()
        self.tarefa._consultar()
        self.aplicar.assert_not_called()
        callback.assert_not_called()

    def test_merge_preserva_edicao_manual_e_digitacao_ainda_nao_salva(self):
        janela = JanelaRevisaoForsyth.__new__(JanelaRevisaoForsyth)
        janela.itens = [ItemRevisao(posicao=POSICAO), ItemRevisao(posicao=POSICAO, editada_manualmente=True),
                        ItemRevisao(posicao=POSICAO)]
        janela.indice = 0
        janela._texto_campo = lambda: "3k4/8/8/8/8/8/8/4K3"
        janela._salvar_rascunho = MagicMock()
        janela._exibir_atual = MagicMock()
        janela._aplicar_revisao_assincrona([POSICAO] * 3, [ItemRevisao(posicao="revista")] * 3)
        self.assertEqual([i.posicao for i in janela.itens], [POSICAO, POSICAO, "revista"])
        janela._exibir_atual.assert_not_called()


class TestePreviaEEdicao(unittest.TestCase):
    def test_alterar_uma_casa_reutiliza_pecas_e_preserva_todo_o_resto(self):
        antes = renderizar_previa("4k3/8/8/8/8/8/8/4K3", "en")
        renderizar_previa("4k3/5b2/8/8/8/8/8/8", "en")  # Aquece a única peça nova.
        with patch("tabuleiros_padronizados.fitz.open", side_effect=AssertionError("SVG reaberto")):
            depois = renderizar_previa("4k3/5b2/8/8/8/8/8/4K3", "en")
            vazio = renderizar_previa(POSICAO, "en")
        alteradas = np.any(antes != depois, axis=2)
        alteradas[100:200, 500:600] = False
        self.assertFalse(alteradas.any())
        np.testing.assert_array_equal(antes, vazio)

    def test_biblioteca_reconstroi_antes_de_agendar_salvamento_e_aceita_rei_removido(self):
        app = InterfaceExtrator.__new__(InterfaceExtrator)
        app.campo_fen_biblioteca = MagicMock()
        app.itens_biblioteca = [ItemRevisao(posicao=POSICAO)]
        app.indice_biblioteca = 0
        app._validar_fen_biblioteca = MagicMock()
        ordem = []
        app._atualizar_imagem_biblioteca = lambda: ordem.append("imagem")
        app._agendar_salvamento_biblioteca = MagicMock(side_effect=lambda *a, **k: ordem.append("salvar"))
        app._salvar_automaticamente_biblioteca = MagicMock()
        app._editar_pelo_tabuleiro_biblioteca("4k3/8/8/8/8/8/8/8 w")
        self.assertEqual(ordem, ["imagem", "salvar"])
        app._agendar_salvamento_biblioteca.assert_called_once_with(250, exigir_atual_valida=False)
        app._salvar_automaticamente_biblioteca.assert_not_called()

    def test_arrastar_peca_e_vazio_atualiza_forsyth_e_marca_casa(self):
        raiz = ttk.Window()
        raiz.withdraw()
        quadro = ComparadorDiagramas(raiz, ao_editar=MagicMock())
        try:
            quadro.exibir(renderizar_previa(POSICAO, "en"), POSICAO + " b", "en")
            quadro._tamanho_padronizado = (320, 320)
            rotulo = quadro.rotulos["padronizado"]
            with patch.object(rotulo, "winfo_width", return_value=400), patch.object(rotulo, "winfo_height", return_value=600), \
                 patch.object(rotulo, "winfo_rootx", return_value=100), patch.object(rotulo, "winfo_rooty", return_value=200):
                origem = SimpleNamespace(widget=MagicMock(), x_root=5, y_root=5)
                destino = SimpleNamespace(widget=origem.widget, x_root=360, y_root=400)  # f7
                quadro._iniciar_arraste(origem, "b")
                quadro._mover_arraste(destino)
                self.assertEqual(quadro._selecionada, (1, 5))
                self.assertTrue(all(b.winfo_manager() == "place" for b in quadro._bordas))
                quadro._terminar_arraste(destino)
                quadro.ao_editar.assert_called_once_with("4k3/5b2/8/8/8/8/8/4K3 b")
                quadro._texto = quadro.ao_editar.call_args.args[0]
                quadro._iniciar_arraste(origem, "")
                quadro._terminar_arraste(destino)
                quadro.ao_editar.assert_called_with(POSICAO + " b")
                quadro._iniciar_arraste(origem, "q")
                quadro._terminar_arraste(origem)  # Clique sem arrastar não altera nada.
                self.assertEqual(quadro.ao_editar.call_count, 2)
        finally:
            quadro.destroy()
            raiz.destroy()


class TesteBolinhas(unittest.TestCase):
    def test_eleicao_de_reis_nunca_coloca_pecas_nas_bolinhas(self):
        matriz = np.zeros((64, 13), np.float32)
        matriz[:, 0] = 1
        indices, _ = eleger_com_reis(matriz, casas_vazias=(0, 1))
        self.assertEqual(tuple(indices[:2]), (0, 0))
        self.assertEqual(sum(CLASSES[i] == "K" for i in indices), 1)
        self.assertEqual(sum(CLASSES[i] == "k" for i in indices), 1)
        indices, _ = eleger_com_reis(matriz, casas_vazias=tuple(range(64)))
        self.assertTrue(np.all(indices == 0))

    def test_exemplo_real_tem_sete_marcadores_vazios_e_nao_muda_pecas(self):
        imagem = cv2.imread(str(RAIZ / "tests/fixtures/recognition/p0309-d05.png"))
        reconhecedor = ReconhecedorForsyth(idioma="en")
        resultado = reconhecedor.reconhecer(imagem)
        self.assertEqual(resultado.posicao, "r2q1rk1/pp4pp/2p5/3p4/3P1p2/4P3/PP3PPP/1RR3K1")
        marcadas = {c.coordenada for c in resultado.casas if c.marcador_vazio}
        self.assertEqual(marcadas, {"e7", "f6", "g6", "h6", "g5", "h4", "f3"})
        self.assertTrue(any(c.top3[0] != "1" for c in resultado.casas if c.marcador_vazio))
        revisor = RevisorAutomaticoLivro([resultado] * 3, idioma="en")
        self.assertEqual(revisor.revisar()[0].posicao, resultado.posicao)

    def test_pecas_classicas_brancas_pretas_nao_sao_bolinhas(self):
        imagem = renderizar_tabuleiro("kqrnbp2/KQRNBP2/2kqrnbp/2KQRNBP/8/8/8/8", "en")
        self.assertEqual(casas_com_bolinhas(imagem), ())


class TesteResumoBiblioteca(unittest.TestCase):
    def test_contagens_incluem_conferencia_e_sintaxe_invalida_sem_contar_descartados(self):
        diagramas = [DiagramaSalvo(1, posicao=POSICAO), DiagramaSalvo(2, posicao=POSICAO, revisao_necessaria=True),
                    DiagramaSalvo(3, posicao="8/8/8/8/8/8/8/8"), DiagramaSalvo(4, excluir=True)]
        self.assertEqual(resumir_diagramas(diagramas, "en"), (3, 1, 2))

    def test_processamento_salva_livro_antes_da_revisao_e_reabre_sem_reconhecer(self):
        import fitz
        from extrair_tabuleiros_pdf import Candidato
        with tempfile.TemporaryDirectory() as pasta:
            pasta = Path(pasta)
            origem = pasta / "livro.pdf"
            with fitz.open() as pdf:
                pdf.new_page()
                pdf.save(origem)
            imagem = renderizar_previa(POSICAO, "en")
            quad = np.array(((0, 0), (799, 0), (799, 799), (0, 799)), np.float32)
            candidato = Candidato(1, quad, imagem, .95)
            app = InterfaceExtrator.__new__(InterfaceExtrator)
            app.biblioteca = BibliotecaLivros(pasta)
            app.eventos = __import__('queue').Queue()
            app.cancelamento = threading.Event()
            app.logger = MagicMock()
            with patch("interface_windows.detectar_no_pdf", return_value=(1, [candidato])), \
                 patch("interface_windows.ReconhecedorForsyth", side_effect=RuntimeError("Sem modelo")), \
                 patch("interface_windows.pasta_dados_aplicativo", return_value=pasta):
                app._preparar_revisao(str(origem), str(pasta / "extraido.pdf"), "en")
            eventos = list(app.eventos.queue)
            self.assertEqual(eventos[-1][0], "revisao_pronta")
            livro_id = eventos[-1][1][7]
            livro = app.biblioteca.carregar(livro_id)
            self.assertIsNotNone(livro)
            self.assertEqual(resumir_diagramas(livro.diagramas, "en"), (1, 0, 1))
            self.assertTrue(livro.pdf_original.is_file())
            with patch("notacao_forsyth.ReconhecedorForsyth", side_effect=AssertionError("Reprocessou")):
                self.assertEqual(len(app.biblioteca.carregar_candidatos(livro)), 1)


if __name__ == "__main__":
    unittest.main()
