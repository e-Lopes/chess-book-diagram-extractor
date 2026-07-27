from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from biblioteca_livros import (
    BibliotecaLivros,
    DiagramaSalvo,
    LivroDuplicadoError,
    exportar_pgn,
    fen_exportacao,
    fen_completa,
    gerar_pgn,
)
from extrair_tabuleiros_pdf import AnotacaoSaida, Candidato, criar_pdf_a4


class TesteBibliotecaLivros(unittest.TestCase):
    @staticmethod
    def _criar_pdf(destino: Path) -> None:
        imagem = np.full((120, 120, 3), 240, dtype=np.uint8)
        cv2.circle(imagem, (60, 60), 25, (20, 20, 20), -1)
        quadro = np.array([[0, 0], [119, 0], [119, 119], [0, 119]], np.float32)
        criar_pdf_a4([Candidato(12, quadro, imagem, 0.91)], destino)

    def test_persiste_e_reabre_sem_a_copia_exportada(self) -> None:
        with tempfile.TemporaryDirectory() as temporaria:
            pasta = Path(temporaria)
            exportado = pasta / "exportado.pdf"
            self._criar_pdf(exportado)
            biblioteca = BibliotecaLivros(pasta / "dados")
            posicao = "4r3/8/8/8/8/8/8/4R3"
            salvo = biblioteca.salvar(
                exportado,
                "Meu livro",
                [DiagramaSalvo(12, 0.91, posicao, "b")],
                annotator="E. Lopes",
                paginas_originais=20,
            )
            exportado.unlink()

            reaberto = biblioteca.carregar(salvo.id)
            self.assertIsNotNone(reaberto)
            assert reaberto
            self.assertTrue(reaberto.pdf_interno.is_file())
            self.assertEqual(reaberto.diagramas[0].lado_a_jogar, "b")
            self.assertEqual(reaberto.annotator, "E. Lopes")
            candidatos = biblioteca.carregar_candidatos(reaberto)
            self.assertEqual(len(candidatos), 1)
            self.assertEqual(candidatos[0].pagina, 12)

    def test_atualiza_fen_lado_e_annotator(self) -> None:
        with tempfile.TemporaryDirectory() as temporaria:
            pasta = Path(temporaria)
            pdf = pasta / "diagramas.pdf"
            self._criar_pdf(pdf)
            biblioteca = BibliotecaLivros(pasta / "dados")
            livro = biblioteca.salvar(pdf, "Livro", [DiagramaSalvo(1)])
            posicao = "4r3/8/8/8/8/8/8/4R3"
            atualizado = biblioteca.salvar(
                livro.pdf_interno,
                livro.titulo,
                [DiagramaSalvo(1, posicao=posicao, lado_a_jogar="b")],
                annotator="Novo nome",
                livro_id=livro.id,
            )
            self.assertEqual(atualizado.diagramas[0].posicao, posicao)
            self.assertEqual(atualizado.diagramas[0].lado_a_jogar, "b")
            self.assertEqual(atualizado.annotator, "Novo nome")

    def test_recupera_do_pdf_uma_posicao_apagada_dos_metadados(self) -> None:
        with tempfile.TemporaryDirectory() as temporaria:
            pasta = Path(temporaria)
            pdf = pasta / "diagramas_anotados.pdf"
            imagem = np.full((120, 120, 3), 240, dtype=np.uint8)
            quadro = np.array([[0, 0], [119, 0], [119, 119], [0, 119]], np.float32)
            candidato = Candidato(14, quadro, imagem, 0.73)
            posicao = "2k2b1r/1pq3p1/2p1pp2/p1n1PnNp/2P2B2/2N4P/PP2QPP1/3R2K1"
            criar_pdf_a4(
                [candidato],
                pdf,
                anotacoes=[AnotacaoSaida(posicao=posicao)],
            )
            biblioteca = BibliotecaLivros(pasta / "dados")

            recuperado = biblioteca.salvar(
                pdf,
                "Livro recuperável",
                [DiagramaSalvo(14, 0.73, None)],
            )

            self.assertEqual(recuperado.diagramas[0].posicao, posicao)
            self.assertTrue((recuperado.pdf_interno.parent / "metadata.json.bak").is_file())

    def test_renomeia_sem_alterar_o_pdf_ou_os_diagramas(self) -> None:
        with tempfile.TemporaryDirectory() as temporaria:
            pasta = Path(temporaria)
            pdf = pasta / "diagramas.pdf"
            self._criar_pdf(pdf)
            biblioteca = BibliotecaLivros(pasta / "dados")
            livro = biblioteca.salvar(
                pdf,
                "Nome antigo",
                [DiagramaSalvo(12, 0.91, "8/8/8/8/8/8/8/8")],
            )

            renomeado = biblioteca.renomear(livro.id, "  Nome novo  ")

            self.assertEqual(renomeado.titulo, "Nome novo")
            self.assertEqual(renomeado.pdf_interno, livro.pdf_interno)
            self.assertEqual(renomeado.diagramas, livro.diagramas)

    def test_exclui_apenas_a_copia_interna_selecionada(self) -> None:
        with tempfile.TemporaryDirectory() as temporaria:
            pasta = Path(temporaria)
            pdf = pasta / "diagramas.pdf"
            self._criar_pdf(pdf)
            biblioteca = BibliotecaLivros(pasta / "dados")
            primeiro = biblioteca.salvar(pdf, "Primeiro", [DiagramaSalvo(1)])
            segundo = biblioteca.salvar(pdf, "Segundo", [DiagramaSalvo(2)])

            self.assertTrue(biblioteca.excluir(primeiro.id))

            self.assertIsNone(biblioteca.carregar(primeiro.id))
            self.assertIsNotNone(biblioteca.carregar(segundo.id))
            self.assertTrue(pdf.is_file())
            self.assertFalse(biblioteca.excluir(primeiro.id))

    def test_impede_dois_conjuntos_com_o_mesmo_nome(self) -> None:
        with tempfile.TemporaryDirectory() as temporaria:
            pasta = Path(temporaria)
            pdf = pasta / "diagramas.pdf"
            self._criar_pdf(pdf)
            biblioteca = BibliotecaLivros(pasta / "dados")
            existente = biblioteca.salvar(pdf, "Meu   Livro", [DiagramaSalvo(1)])

            with self.assertRaises(LivroDuplicadoError) as conflito:
                biblioteca.salvar(pdf, "  meu livro  ", [DiagramaSalvo(2)])

            self.assertEqual(conflito.exception.livro.id, existente.id)
            self.assertEqual(len(biblioteca.listar()), 1)

    def test_renomear_pode_substituir_um_nome_existente(self) -> None:
        with tempfile.TemporaryDirectory() as temporaria:
            pasta = Path(temporaria)
            pdf = pasta / "diagramas.pdf"
            self._criar_pdf(pdf)
            biblioteca = BibliotecaLivros(pasta / "dados")
            antigo = biblioteca.salvar(pdf, "Antigo", [DiagramaSalvo(1)])
            selecionado = biblioteca.salvar(pdf, "Selecionado", [DiagramaSalvo(2)])

            with self.assertRaises(LivroDuplicadoError):
                biblioteca.renomear(selecionado.id, "Antigo")
            substituto = biblioteca.renomear(
                selecionado.id, "Antigo", substituir=True
            )

            self.assertEqual(substituto.id, selecionado.id)
            self.assertIsNone(biblioteca.carregar(antigo.id))
            self.assertEqual(len(biblioteca.listar()), 1)


class TesteExportacaoPgn(unittest.TestCase):
    def test_fen_completa_converte_portugues_e_inclui_lado(self) -> None:
        self.assertEqual(
            fen_completa("4r3/8/8/8/8/8/8/4R3", "b", "pt"),
            "4k3/8/8/8/8/8/8/4K3 b - - 0 1",
        )

    def test_fen_abreviada_para_exportacao_contem_apenas_o_lado(self) -> None:
        self.assertEqual(
            fen_exportacao("4r3/8/8/8/8/8/8/4R3", "b", "pt"),
            "4k3/8/8/8/8/8/8/4K3 b",
        )

    def test_gera_uma_entrada_por_posicao_valida(self) -> None:
        diagramas = [
            DiagramaSalvo(3, posicao="4r3/8/8/8/8/8/8/4R3", lado_a_jogar="w"),
            DiagramaSalvo(7, posicao="3r4/8/8/8/8/8/8/3R4", lado_a_jogar="b"),
        ]
        pgn = gerar_pgn('Livro "teste"', diagramas, "E. Lopes", "pt")
        self.assertEqual(pgn.count('[SetUp "1"]'), 2)
        self.assertEqual(pgn.count('[Annotator "E. Lopes"]'), 2)
        self.assertIn('[FEN "4k3/8/8/8/8/8/8/4K3 w"]', pgn)
        self.assertIn('[FEN "3k4/8/8/8/8/8/8/3K4 b"]', pgn)
        self.assertIn('[Event "Livro \\"teste\\""]', pgn)

    def test_exporta_atomicamente_em_utf8(self) -> None:
        with tempfile.TemporaryDirectory() as temporaria:
            destino = Path(temporaria) / "posicoes.pgn"
            exportar_pgn(
                destino,
                "Livro",
                [DiagramaSalvo(1, posicao="4r3/8/8/8/8/8/8/4R3")],
                "Joao",
            )
            self.assertIn("Joao", destino.read_text(encoding="utf-8"))
            self.assertFalse(destino.with_suffix(".pgn.tmp").exists())


if __name__ == "__main__":
    unittest.main()
