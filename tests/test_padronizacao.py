from __future__ import annotations

import hashlib
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import cv2
import fitz
import numpy as np

from biblioteca_livros import BibliotecaLivros, DiagramaSalvo, diagramas_de_anotacoes
from extrair_tabuleiros_pdf import AnotacaoSaida, Candidato, ExtracaoCancelada, criar_pdf_a4, detectar_no_pdf
from interface_windows import InterfaceExtrator
from tabuleiros_padronizados import (
    DiagramaPadronizado, exportar_pdf_padronizado, localizar_diagramas_antigos,
    renderizar_tabuleiro,
)


POSICAO = "4r3/8/8/8/8/8/8/4R3"
QUADRO = ((60., 90.), (260., 90.), (260., 290.), (60., 290.))


def criar_original(caminho, rotacao=0, crop=False):
    with fitz.open() as pdf:
        pagina = pdf.new_page(width=400, height=500)
        pagina.insert_text((40, 40), "Texto preservado antes do diagrama")
        pagina.draw_rect(fitz.Rect(60, 90, 260, 290), color=(0, 0, 0), fill=(0.1, 0.1, 0.1))
        pagina.insert_text((40, 340), "Texto preservado depois do diagrama")
        pagina.insert_link({"kind": fitz.LINK_URI, "from": fitz.Rect(40, 30, 130, 45), "uri": "https://example.org/"})
        if crop:
            pagina.set_cropbox(fitz.Rect(10, 10, 390, 490))
        pagina.set_rotation(rotacao)
        pdf.new_page().insert_text((50, 50), "Segunda pagina intacta")
        pdf.set_metadata({"title": "Livro de teste"})
        pdf.save(caminho)


def pixels(pagina):
    p = pagina.get_pixmap(alpha=False)
    return np.frombuffer(p.samples, np.uint8).reshape(p.height, p.width, 3).copy()


class TesteRenderizacao(unittest.TestCase):
    def test_orientacao_cores_e_pecas(self):
        vazio = renderizar_tabuleiro("8/8/8/8/8/8/8/8")
        self.assertEqual(tuple(vazio[20, 20]), (255, 255, 255))  # a8
        self.assertEqual(tuple(vazio[20, 720]), (201, 201, 201))  # h8
        self.assertEqual(tuple(vazio[720, 20]), (201, 201, 201))  # a1
        self.assertEqual(tuple(vazio[720, 720]), (255, 255, 255))  # h1
        pecas = renderizar_tabuleiro("P7/8/8/8/8/8/8/7p")
        self.assertFalse(np.array_equal(vazio[:100, :100], pecas[:100, :100]))
        self.assertFalse(np.array_equal(vazio[700:, 700:], pecas[700:, 700:]))
        np.testing.assert_array_equal(vazio[100:700], pecas[100:700])

    def test_idiomas_e_lado_produzem_a_mesma_imagem(self):
        pt = "tcbdrbct/pppppppp/8/8/8/8/PPPPPPPP/TCBDRBCT w"
        en = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR b"
        np.testing.assert_array_equal(renderizar_tabuleiro(pt), renderizar_tabuleiro(en, "en"))
        np.testing.assert_array_equal(renderizar_tabuleiro(en, "en"), renderizar_tabuleiro(en + " KQkq - 0 1", "en"))

    def test_rejeita_notacao_e_tamanhos_invalidos(self):
        for posicao in ("invalida", "9/8/8/8/8/8/8/8", "<svg>/8/8/8/8/8/8/8"):
            with self.assertRaises(ValueError):
                renderizar_tabuleiro(posicao)
        with self.assertRaises(ValueError):
            renderizar_tabuleiro(POSICAO, tamanho=0)


class TestePdfPadronizado(unittest.TestCase):
    def test_preserva_paginas_texto_links_metadados_e_pixels_externos(self):
        with tempfile.TemporaryDirectory() as pasta:
            origem, saida = Path(pasta) / "original.pdf", Path(pasta) / "novo.pdf"
            criar_original(origem)
            antes = origem.read_bytes()
            exportar_pdf_padronizado(origem, saida, [DiagramaPadronizado(1, QUADRO, POSICAO)])
            self.assertEqual(origem.read_bytes(), antes)
            with fitz.open(origem) as original, fitz.open(saida) as novo:
                self.assertEqual(len(novo), len(original))
                self.assertEqual(novo.metadata["title"], original.metadata["title"])
                for p, q in zip(original, novo):
                    self.assertEqual(p.get_text(), q.get_text())
                    self.assertEqual([l["uri"] for l in p.get_links()], [l["uri"] for l in q.get_links()])
                a, b = pixels(original[0]), pixels(novo[0])
                mascara = np.ones(a.shape[:2], bool)
                mascara[89:291, 59:261] = False
                np.testing.assert_array_equal(a[mascara], b[mascara])
                self.assertFalse(np.array_equal(a[100:280, 70:250], b[100:280, 70:250]))
                np.testing.assert_array_equal(pixels(original[1]), pixels(novo[1]))

    def test_rotacao_e_cropbox_preservam_orientacao_e_localizacao(self):
        with tempfile.TemporaryDirectory() as pasta:
            for rotacao in (0, 90, 180, 270):
                with self.subTest(rotacao=rotacao):
                    origem, saida = Path(pasta) / "original.pdf", Path(pasta) / "novo.pdf"
                    criar_original(origem, rotacao, crop=True)
                    with fitz.open(origem) as pdf:
                        # Converte os cantos do quadro para a página já recortada e rotacionada.
                        quadro = [tuple(fitz.Point(x - 10, y - 10) * pdf[0].rotation_matrix) for x, y in QUADRO]
                        # O primeiro canto sempre deve corresponder ao a8 visual.
                        centro = fitz.Point(150, 180) * pdf[0].rotation_matrix
                        anterior = pixels(pdf[0])
                    exportar_pdf_padronizado(origem, saida, [DiagramaPadronizado(1, tuple(quadro), POSICAO)])
                    with fitz.open(saida) as pdf:
                        self.assertEqual(pdf[0].rotation, rotacao)
                        self.assertEqual(pdf[0].cropbox, fitz.Rect(10, 10, 390, 490))
                        depois = pixels(pdf[0])
                        self.assertGreater(int(depois[int(centro.y), int(centro.x), 0]), 150)
                        self.assertFalse(np.array_equal(anterior, depois))

    def test_quadro_inclinado_nao_cobre_o_entorno(self):
        with tempfile.TemporaryDirectory() as pasta:
            origem, saida = Path(pasta) / "original.pdf", Path(pasta) / "novo.pdf"
            criar_original(origem)
            quadro = ((90., 80.), (270., 110.), (240., 300.), (60., 270.))
            exportar_pdf_padronizado(origem, saida, [DiagramaPadronizado(1, quadro, POSICAO)])
            with fitz.open(origem) as original, fitz.open(saida) as novo:
                a, b = pixels(original[0]), pixels(novo[0])
                mascara = np.zeros(a.shape[:2], np.uint8)
                cv2.fillConvexPoly(mascara, np.array(quadro, np.int32), 1)
                mascara = cv2.dilate(mascara, np.ones((5, 5), np.uint8)).astype(bool)
                np.testing.assert_array_equal(a[~mascara], b[~mascara])

    def test_entrada_invalida_nao_altera_saida_existente(self):
        with tempfile.TemporaryDirectory() as pasta:
            origem, saida = Path(pasta) / "original.pdf", Path(pasta) / "novo.pdf"
            criar_original(origem)
            saida.write_bytes(b"saida anterior")
            for diagramas in ([], [DiagramaPadronizado(3, QUADRO, POSICAO)],
                [DiagramaPadronizado(1, QUADRO, "invalida")],
                [DiagramaPadronizado(1, ((0., 0.),) * 4, POSICAO)],
                [DiagramaPadronizado(1, ((0., 0.), (900., 0.), (900., 900.), (0., 900.)), POSICAO)]):
                with self.assertRaises(ValueError):
                    exportar_pdf_padronizado(origem, saida, diagramas)
                self.assertEqual(saida.read_bytes(), b"saida anterior")
            with self.assertRaises(ValueError):
                exportar_pdf_padronizado(origem, origem, [DiagramaPadronizado(1, QUADRO, POSICAO)])

    def test_cancelamento_nao_substitui_saida(self):
        with tempfile.TemporaryDirectory() as pasta:
            origem, saida = Path(pasta) / "original.pdf", Path(pasta) / "novo.pdf"
            criar_original(origem)
            saida.write_bytes(b"saida anterior")
            sinal = threading.Event()
            with self.assertRaises(ExtracaoCancelada):
                exportar_pdf_padronizado(origem, saida, [DiagramaPadronizado(1, QUADRO, POSICAO)],
                    progresso=lambda *_: sinal.set(), cancelado=sinal.is_set)
            self.assertEqual(saida.read_bytes(), b"saida anterior")
            self.assertFalse(list(Path(pasta).glob("livro_padronizado_*.pdf")))

    def test_forsyth_abaixo_do_diagrama_sem_mensagem_de_falso_positivo(self):
        with tempfile.TemporaryDirectory() as pasta:
            imagem = renderizar_tabuleiro(POSICAO, tamanho=160)
            quadro = np.array(((0, 0), (159, 0), (159, 159), (0, 159)), np.float32)
            caminho = Path(pasta) / "extraido.pdf"
            criar_pdf_a4([Candidato(1, quadro, imagem, 0.1)], caminho,
                anotacoes=[AnotacaoSaida(posicao=POSICAO, possivel_falso_positivo=True, lado_a_jogar="b")])
            with fitz.open(caminho) as pdf:
                texto = pdf[0].get_text()
                self.assertIn(POSICAO + " b", texto)
                self.assertNotIn("falso positivo", texto.lower())
                self.assertGreater(pdf[0].search_for(POSICAO)[0].y0, pdf[0].get_image_rects(pdf[0].get_images()[0][0])[0].y1)


class TestePersistenciaPadronizacao(unittest.TestCase):
    def test_biblioteca_preserva_original_e_cantos_apos_edicao_e_renomeacao(self):
        with tempfile.TemporaryDirectory() as pasta:
            pasta = Path(pasta)
            origem, extraido = pasta / "original.pdf", pasta / "diagramas.pdf"
            criar_original(origem)
            sha = hashlib.sha256(origem.read_bytes()).hexdigest()
            imagem = renderizar_tabuleiro(POSICAO, tamanho=160)
            candidato = Candidato(1, np.array(QUADRO, np.float32), imagem, 0.9, QUADRO)
            anotacoes = [AnotacaoSaida(posicao=POSICAO)]
            criar_pdf_a4([candidato], extraido, anotacoes=anotacoes)
            biblioteca = BibliotecaLivros(pasta / "dados")
            livro = biblioteca.salvar(extraido, "Livro", diagramas_de_anotacoes([candidato], anotacoes), pdf_original=origem)
            origem.unlink()
            extraido.unlink()
            self.assertEqual(hashlib.sha256(livro.pdf_original.read_bytes()).hexdigest(), sha)
            livro = biblioteca.salvar(livro.pdf_interno, livro.titulo, livro.diagramas, livro_id=livro.id)
            livro = biblioteca.renomear(livro.id, "Novo nome")
            self.assertEqual(livro.diagramas[0].quadro_pdf, QUADRO)
            self.assertEqual(biblioteca.carregar_candidatos(livro)[0].quadro_pdf, QUADRO)
            self.assertTrue(livro.pdf_original.is_file())

    def test_metadados_antigos_continuam_abrindo(self):
        import json
        with tempfile.TemporaryDirectory() as pasta:
            pasta = Path(pasta)
            pdf = pasta / "extraido.pdf"
            candidato = Candidato(1, np.array(QUADRO, np.float32), renderizar_tabuleiro(POSICAO, tamanho=160), 0.9)
            criar_pdf_a4([candidato], pdf)
            biblioteca = BibliotecaLivros(pasta / "dados")
            livro = biblioteca.salvar(pdf, "Antigo", [DiagramaSalvo(1, posicao=POSICAO)])
            metadata = livro.pdf_interno.parent / "metadata.json"
            dados = json.loads(metadata.read_text(encoding="utf-8"))
            dados["diagramas"][0].pop("quadro_pdf")
            metadata.write_text(json.dumps(dados), encoding="utf-8")
            antigo = biblioteca.carregar(livro.id)
            self.assertIsNotNone(antigo)
            self.assertIsNone(antigo.pdf_original)
            self.assertEqual(antigo.diagramas[0].quadro_pdf, ())

    def test_coordenadas_detectadas_independem_do_dpi(self):
        with tempfile.TemporaryDirectory() as pasta:
            origem = Path(pasta) / "original.pdf"
            imagem = renderizar_tabuleiro(POSICAO, tamanho=240)
            _, png = cv2.imencode(".png", imagem)
            with fitz.open() as pdf:
                pdf.new_page(width=400, height=400).insert_image(fitz.Rect(60, 90, 260, 290), stream=png.tobytes())
                pdf.save(origem)
            for dpi in (72, 144):
                _, candidatos = detectar_no_pdf(origem, dpi=dpi)
                self.assertEqual(len(candidatos), 1)
                np.testing.assert_allclose(candidatos[0].quadro_pdf, QUADRO, atol=2)

    def test_recuperacao_visual_nao_confunde_recortes_identicos(self):
        with tempfile.TemporaryDirectory() as pasta:
            origem = Path(pasta) / "original.pdf"
            criar_original(origem)
            imagem = renderizar_tabuleiro(POSICAO, tamanho=160)
            candidato = Candidato(1, np.array(QUADRO, np.float32), imagem, 0.9)
            with patch("extrair_tabuleiros_pdf.detectar_tabuleiros", return_value=[candidato, candidato]):
                self.assertEqual(localizar_diagramas_antigos(origem, [candidato]), {})
            with patch("extrair_tabuleiros_pdf.detectar_tabuleiros", return_value=[candidato]):
                self.assertEqual(set(localizar_diagramas_antigos(origem, [candidato])), {0})
                self.assertEqual(localizar_diagramas_antigos(origem, [candidato, candidato]), {})


class TesteFluxosInterface(unittest.TestCase):
    def test_atualizacao_fecha_sem_modal_que_bloqueie_instalador(self):
        interface = InterfaceExtrator.__new__(InterfaceExtrator)
        interface.raiz = MagicMock()
        interface.estado_barra = MagicMock()
        with patch("interface_windows.iniciar_instalador") as iniciar, patch("interface_windows.messagebox.showinfo") as modal:
            interface._instalar_atualizacao(Path("setup.exe"))
        iniciar.assert_called_once()
        modal.assert_not_called()
        interface.raiz.after.assert_called_once_with(300, interface.raiz.destroy)

    def test_pgn_com_pendencias_nao_requer_geracao_do_pdf(self):
        interface = InterfaceExtrator.__new__(InterfaceExtrator)
        interface.raiz = MagicMock()
        interface.annotator_biblioteca = MagicMock()
        interface._cancelar_salvamento_biblioteca_pendente = MagicMock()
        interface._atualizar_biblioteca = MagicMock()
        interface._persistir_editor_biblioteca = MagicMock(return_value=MagicMock(
            diagramas=[DiagramaSalvo(1, posicao=POSICAO), DiagramaSalvo(2, posicao="invalida")],
            idioma="pt", titulo="Livro", annotator=""))
        with patch("interface_windows.simpledialog.askstring", return_value="Eduardo"), \
             patch("interface_windows.filedialog.asksaveasfilename", return_value="livro.pgn"), \
             patch("interface_windows.exportar_pgn") as exportar, \
             patch("interface_windows.criar_pdf_a4", side_effect=AssertionError("PDF não deve ser necessário")), \
             patch("interface_windows.messagebox.showinfo") as sucesso:
            interface._exportar_pgn_biblioteca()
        self.assertEqual(len(exportar.call_args.args[2]), 1)
        self.assertIn("Omitidas por erro: 2", sucesso.call_args.args[1])


if __name__ == "__main__":
    unittest.main()
