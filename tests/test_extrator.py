from __future__ import annotations

import sys
import tempfile
import unittest
import importlib.util
import hashlib
import io
import json
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import cv2
import fitz
import numpy as np


PASTA_MODULO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PASTA_MODULO))

from extrair_tabuleiros_pdf import (  # noqa: E402
    Candidato,
    ErroExtracao,
    ExtracaoCancelada,
    LIMIAR_PADRAO,
    criar_pdf_a4,
    carregar_diagramas_do_pdf_extraido,
    detectar_no_pdf,
    detectar_tabuleiros,
    executar_com_interface,
    pontuar_tabuleiro,
    processar_pdf,
    remover_duplicados,
)
from autoupdate import Atualizacao, ErroAtualizacao, baixar_atualizacao, chave_versao, consultar_atualizacao  # noqa: E402
from interface_windows import InterfaceExtrator, caminho_recurso, sugerir_saida  # noqa: E402
from version import PUBLISHER, __version__  # noqa: E402

_spec_metadata = importlib.util.spec_from_file_location(
    "generate_build_metadata",
    PASTA_MODULO / "packaging" / "generate_build_metadata.py",
)
assert _spec_metadata and _spec_metadata.loader
_metadata = importlib.util.module_from_spec(_spec_metadata)
_spec_metadata.loader.exec_module(_metadata)
validar_versao = _metadata.validar_versao


class RespostaFake(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def criar_tabuleiro(lado_casa: int = 34, borda: int = 7, com_pecas: bool = True) -> np.ndarray:
    lado = lado_casa * 8 + borda * 2
    imagem = np.full((lado, lado, 3), 255, dtype=np.uint8)
    cv2.rectangle(imagem, (1, 1), (lado - 2, lado - 2), (15, 15, 15), borda)
    for linha in range(8):
        for coluna in range(8):
            tom = 72 if (linha + coluna) % 2 else 232
            x0, y0 = borda + coluna * lado_casa, borda + linha * lado_casa
            cv2.rectangle(imagem, (x0, y0), (x0 + lado_casa, y0 + lado_casa), (tom,) * 3, -1)
    if com_pecas:
        for linha, coluna, cor in [(0, 4, 10), (7, 4, 245), (3, 3, 20), (5, 6, 240)]:
            centro = (borda + coluna * lado_casa + lado_casa // 2, borda + linha * lado_casa + lado_casa // 2)
            cv2.circle(imagem, centro, lado_casa // 3, (cor,) * 3, -1)
            cv2.circle(imagem, centro, lado_casa // 3, (255 - cor,) * 3, 2)
    return imagem


def colar(destino: np.ndarray, origem: np.ndarray, x: int, y: int) -> None:
    altura, largura = origem.shape[:2]
    destino[y : y + altura, x : x + largura] = origem


def criar_pagina(quantidade: int, rotacao: float = 0.0) -> np.ndarray:
    pagina = np.full((1100, 800, 3), 255, dtype=np.uint8)
    cv2.putText(pagina, "Chess exercises", (45, 65), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 0), 2)
    posicoes = [(75, 130), (420, 650)]
    for indice in range(quantidade):
        tabuleiro = criar_tabuleiro(31 if indice else 34)
        if rotacao:
            centro = (tabuleiro.shape[1] / 2, tabuleiro.shape[0] / 2)
            matriz = cv2.getRotationMatrix2D(centro, rotacao, 1.0)
            tabuleiro = cv2.warpAffine(tabuleiro, matriz, tabuleiro.shape[1::-1], borderValue=(255, 255, 255))
        x, y = posicoes[indice]
        colar(pagina, tabuleiro, x, y)
        cv2.putText(pagina, f"{57 + indice}", (x + 80, y - 25), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 2)
        cv2.putText(pagina, "White to Move", (x + 35, y + tabuleiro.shape[0] + 42), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 2)
    return pagina


def criar_grade_textual() -> np.ndarray:
    """Imita a falsa deteccao: matriz 8x8 de codigos em fundo branco."""
    lado = 600
    imagem = np.full((lado, lado, 3), 255, dtype=np.uint8)
    cv2.line(imagem, (4, 5), (4, lado - 6), (20, 20, 20), 2)
    cv2.line(imagem, (lado - 5, 5), (lado - 5, lado - 6), (20, 20, 20), 2)
    celula = 72
    for linha in range(8):
        for coluna in range(8):
            x, y = 15 + coluna * celula, 30 + linha * celula
            espessura = 2 if (linha + coluna) % 2 else 1
            cv2.putText(imagem, f"Q{coluna + 1}", (x, y), cv2.FONT_HERSHEY_SIMPLEX, 0.46, (10, 10, 10), espessura)
            cv2.putText(imagem, f"K{linha + 1}", (x, y + 19), cv2.FONT_HERSHEY_SIMPLEX, 0.46, (10, 10, 10), espessura)
    return imagem


def criar_falsos_positivos_visuais() -> list[np.ndarray]:
    imagens: list[np.ndarray] = []

    circulo = np.full((300, 300, 3), (35, 45, 48), dtype=np.uint8)
    cv2.circle(circulo, (150, 150), 132, (235, 238, 215), -1)
    imagens.append(circulo)

    peca_escura = np.full((300, 300, 3), (235, 242, 230), dtype=np.uint8)
    cv2.rectangle(peca_escura, (118, 40), (182, 215), (20, 45, 38), -1)
    cv2.ellipse(peca_escura, (150, 225), (105, 55), 0, 0, 360, (20, 45, 38), -1)
    cv2.ellipse(peca_escura, (150, 42), (58, 18), 0, 0, 360, (30, 55, 48), -1)
    imagens.append(peca_escura)

    peca_clara = np.full((300, 300, 3), (230, 240, 225), dtype=np.uint8)
    for deslocamento in range(-300, 400, 34):
        cv2.line(peca_clara, (deslocamento, 0), (deslocamento + 300, 300), (55, 170, 150), 12)
    cv2.rectangle(peca_clara, (108, 20), (192, 220), (225, 225, 205), -1)
    cv2.ellipse(peca_clara, (150, 235), (115, 60), 0, 0, 360, (225, 225, 205), -1)
    imagens.append(peca_clara)

    imagens.append(criar_grade_textual())
    return imagens


def salvar_pagina_em_pdf(documento: fitz.Document, imagem: np.ndarray) -> None:
    pagina = documento.new_page(width=imagem.shape[1], height=imagem.shape[0])
    ok, buffer = cv2.imencode(".png", imagem)
    assert ok
    pagina.insert_image(pagina.rect, stream=buffer.tobytes())


class TesteDetector(unittest.TestCase):
    def test_pontuacao_distingue_tabuleiro_de_ruido(self) -> None:
        tabuleiro = criar_tabuleiro()
        ruido = np.random.default_rng(42).integers(0, 256, tabuleiro.shape, dtype=np.uint8)
        self.assertGreater(pontuar_tabuleiro(tabuleiro), 0.45)
        self.assertLess(pontuar_tabuleiro(ruido), pontuar_tabuleiro(tabuleiro))

    def test_grade_textual_8x8_nao_e_tabuleiro(self) -> None:
        grade = criar_grade_textual()
        self.assertLess(pontuar_tabuleiro(grade), LIMIAR_PADRAO)
        self.assertEqual(detectar_tabuleiros(grade), [])

    def test_circulo_pecas_ampliadas_e_texto_sao_rejeitados(self) -> None:
        for imagem in criar_falsos_positivos_visuais():
            with self.subTest(formato=imagem.shape):
                self.assertEqual(pontuar_tabuleiro(imagem), 0.0)

    def test_paginas_com_zero_um_e_dois_diagramas(self) -> None:
        self.assertEqual(detectar_tabuleiros(criar_pagina(0)), [])
        self.assertEqual(len(detectar_tabuleiros(criar_pagina(1))), 1)
        encontrados = detectar_tabuleiros(criar_pagina(2))
        self.assertEqual(len(encontrados), 2)
        self.assertLess(encontrados[0].y, encontrados[1].y)

    def test_recorte_e_quadrado_e_nao_inclui_textos_externos(self) -> None:
        encontrado = detectar_tabuleiros(criar_pagina(1))[0]
        altura, largura = encontrado.imagem.shape[:2]
        self.assertEqual(altura, largura)
        self.assertLess(altura, 340)  # bloco com numero/texto seria mais alto

    def test_pequena_rotacao_e_corrigida(self) -> None:
        encontrados = detectar_tabuleiros(criar_pagina(1, rotacao=2.0), limiar=0.20)
        self.assertEqual(len(encontrados), 1)
        self.assertEqual(encontrados[0].imagem.shape[0], encontrados[0].imagem.shape[1])

    def test_duplicatas_sao_removidas(self) -> None:
        imagem = criar_tabuleiro()
        q1 = np.array([[10, 10], [300, 10], [300, 300], [10, 300]], np.float32)
        q2 = q1 + 2
        candidatos = [Candidato(1, q1, imagem, 0.8), Candidato(1, q2, imagem, 0.9)]
        resultado = remover_duplicados(candidatos)
        self.assertEqual(len(resultado), 1)
        self.assertEqual(resultado[0].confianca, 0.9)

    def test_padrao_alternado_recupera_pagina_incompleta(self) -> None:
        with tempfile.TemporaryDirectory() as pasta:
            entrada = Path(pasta) / "alternado.pdf"
            documento = fitz.open()
            for _ in range(10):
                documento.new_page(width=800, height=1100)
            documento.save(entrada)
            documento.close()

            imagem = criar_tabuleiro()

            def candidato(pagina: int, y: float) -> Candidato:
                quadro = np.array([[10, y], [300, y], [300, y + 290], [10, y + 290]], np.float32)
                return Candidato(pagina, quadro, imagem, 0.42)

            def detectar(_imagem, pagina=1, alta_sensibilidade=False, **_kwargs):
                if pagina % 2 == 0:
                    return []
                if pagina == 5 and not alta_sensibilidade:
                    return [candidato(pagina, 10)]
                return [candidato(pagina, 10), candidato(pagina, 400)]

            with (
                patch("extrair_tabuleiros_pdf.renderizar_pagina", return_value=imagem),
                patch("extrair_tabuleiros_pdf.detectar_tabuleiros", side_effect=detectar),
            ):
                total, encontrados = detectar_no_pdf(entrada)

            self.assertEqual(total, 10)
            self.assertEqual(len(encontrados), 10)
            self.assertEqual(sum(item.pagina == 5 for item in encontrados), 2)


class TesteIntegracao(unittest.TestCase):
    def test_cancelamento_interrompe_deteccao_e_geracao(self) -> None:
        with tempfile.TemporaryDirectory() as pasta:
            entrada = Path(pasta) / "livro.pdf"
            documento = fitz.open()
            documento.new_page()
            documento.save(entrada)
            documento.close()
            with self.assertRaises(ExtracaoCancelada):
                detectar_no_pdf(entrada, dpi=72, cancelado=lambda: True)

            imagem = np.full((80, 80, 3), 255, dtype=np.uint8)
            quadro = np.array([[0, 0], [79, 0], [79, 79], [0, 79]], np.float32)
            saida = Path(pasta) / "cancelado.pdf"
            with self.assertRaises(ExtracaoCancelada):
                criar_pdf_a4(
                    [Candidato(1, quadro, imagem, 0.9)],
                    saida,
                    cancelado=lambda: True,
                )
            self.assertFalse(saida.exists())

    def test_botao_cancelar_apenas_sinaliza_a_thread_de_trabalho(self) -> None:
        interface = InterfaceExtrator.__new__(InterfaceExtrator)
        interface.processando = True
        interface.cancelamento = threading.Event()
        interface.botao_cancelar = MagicMock()
        interface._definir_status = MagicMock()
        interface.detalhes = MagicMock()

        interface._cancelar_processamento()

        self.assertTrue(interface.cancelamento.is_set())
        interface.botao_cancelar.configure.assert_called_once_with(state="disabled")

    def test_editor_publico(self) -> None:
        self.assertEqual(PUBLISHER, "E-Lopes")

    def test_comparacao_de_versoes(self) -> None:
        self.assertLess(chave_versao("v1.2.3"), chave_versao("1.3.0"))
        self.assertEqual(chave_versao("1.2.3-beta"), (1, 2, 3))

    def test_consulta_release_e_valida_digest(self) -> None:
        conteudo = b"instalador de teste"
        digest = hashlib.sha256(conteudo).hexdigest()
        dados = {
            "tag_name": "v9.9.9",
            "body": "Notas da versao",
            "assets": [{
                "name": "ChessBookDiagramExtractor-Setup-v9.9.9.exe",
                "browser_download_url": "https://github.com/e-lopes/chess-book-diagram-extractor/releases/download/v9.9.9/ChessBookDiagramExtractor-Setup-v9.9.9.exe",
                "digest": f"sha256:{digest}",
                "size": len(conteudo),
            }],
        }
        abrir_api = lambda *_args, **_kwargs: RespostaFake(json.dumps(dados).encode())
        atualizacao = consultar_atualizacao("e-lopes/chess-book-diagram-extractor", "0.1.2", abrir_url=abrir_api)
        self.assertIsNotNone(atualizacao)
        assert atualizacao
        caminho = baixar_atualizacao(
            atualizacao,
            abrir_url=lambda *_args, **_kwargs: RespostaFake(conteudo),
        )
        try:
            self.assertEqual(caminho.read_bytes(), conteudo)
        finally:
            caminho.unlink(missing_ok=True)

    def test_download_adulterado_e_rejeitado(self) -> None:
        atualizacao = Atualizacao(
            versao="9.9.8",
            nome_arquivo="ChessBookDiagramExtractor-Setup-v9.9.8.exe",
            url="https://github.com/e-lopes/chess-book-diagram-extractor/releases/download/v9.9.8/ChessBookDiagramExtractor-Setup-v9.9.8.exe",
            sha256="0" * 64,
            tamanho=5,
            notas="",
        )
        with self.assertRaisesRegex(ErroAtualizacao, "SHA-256"):
            baixar_atualizacao(
                atualizacao,
                abrir_url=lambda *_args, **_kwargs: RespostaFake(b"abcde"),
            )

    def test_metadados_aceitam_versao_estavel_e_pre_release(self) -> None:
        self.assertEqual(validar_versao("1.2.3"), (1, 2, 3, 0))
        self.assertEqual(validar_versao("1.2.3-beta.1"), (1, 2, 3, 0))
        with self.assertRaises(ValueError):
            validar_versao("versao-invalida")

    def test_icone_da_interface_existe(self) -> None:
        self.assertTrue(
            caminho_recurso("icon", "chess-book-diagram-extractor.png").is_file()
        )

    def test_versao_publica_tem_formato_semantico(self) -> None:
        partes = __version__.split(".")
        self.assertEqual(len(partes), 3)
        self.assertTrue(all(parte.isdigit() for parte in partes))

    def test_interface_sugere_saida_ao_lado_do_livro(self) -> None:
        sugestao = Path(sugerir_saida(str(Path("C:/livros/meu_livro.pdf"))))
        self.assertEqual(sugestao.name, "meu_livro_diagramas.pdf")
        self.assertEqual(sugestao.parent.name, "livros")

        sugestao_acentuada = Path(sugerir_saida(str(Path("C:/Meus Livros/posição final.PDF"))))
        self.assertEqual(sugestao_acentuada.name, "posição final_diagramas.pdf")
        self.assertEqual(sugestao_acentuada.parent.name, "Meus Livros")

    def test_interface_formata_estimativa_de_tempo(self) -> None:
        self.assertEqual(InterfaceExtrator._formatar_tempo(42), "42 s")
        self.assertEqual(InterfaceExtrator._formatar_tempo(75), "1 min 15 s")
        self.assertEqual(InterfaceExtrator._formatar_tempo(3660), "1 h 01 min")

    def test_pdf_sintetico_gera_um_diagrama_por_pagina_a4(self) -> None:
        with tempfile.TemporaryDirectory() as pasta:
            entrada = Path(pasta) / "livro.pdf"
            saida = Path(pasta) / "Diagramas_Livro.pdf"
            documento = fitz.open()
            salvar_pagina_em_pdf(documento, criar_pagina(0))
            salvar_pagina_em_pdf(documento, criar_pagina(1))
            salvar_pagina_em_pdf(documento, criar_pagina(2))
            documento.save(entrada)
            documento.close()

            eventos: list[tuple[int, int, int]] = []
            resultado = processar_pdf(entrada, saida, dpi=72, progresso=lambda a, t, e: eventos.append((a, t, e)))
            self.assertEqual(resultado.paginas_processadas, 3)
            self.assertEqual(resultado.diagramas_encontrados, 3)
            self.assertEqual(eventos, [(1, 3, 0), (2, 3, 1), (3, 3, 3)])
            self.assertTrue(saida.exists())

            pdf_saida = fitz.open(saida)
            try:
                self.assertEqual(pdf_saida.page_count, 3)
                for pagina in pdf_saida:
                    self.assertAlmostEqual(pagina.rect.width, fitz.paper_size("a4")[0], places=1)
                    self.assertAlmostEqual(pagina.rect.height, fitz.paper_size("a4")[1], places=1)
                    self.assertEqual(len(pagina.get_images(full=True)), 1)
                    self.assertIn("Página original (do pdf):", pagina.get_text())
                    self.assertIn("Confiança da detecção:", pagina.get_text())
            finally:
                pdf_saida.close()

            _total, originais = detectar_no_pdf(entrada, dpi=72)
            relidos = carregar_diagramas_do_pdf_extraido(saida, originais)
            self.assertEqual(len(relidos), len(originais))
            for original, relido in zip(originais, relidos):
                self.assertEqual(relido.pagina, original.pagina)
                self.assertEqual(relido.imagem.shape, original.imagem.shape)
                self.assertTrue(np.array_equal(relido.imagem, original.imagem))

    def test_nenhum_diagrama_nao_cria_saida(self) -> None:
        with tempfile.TemporaryDirectory() as pasta:
            entrada = Path(pasta) / "vazio.pdf"
            saida = Path(pasta) / "saida.pdf"
            documento = fitz.open()
            salvar_pagina_em_pdf(documento, criar_pagina(0))
            documento.save(entrada)
            documento.close()
            resultado = processar_pdf(entrada, saida, dpi=72)
            self.assertEqual(resultado.diagramas_encontrados, 0)
            self.assertFalse(saida.exists())

    def test_arquivo_invalido(self) -> None:
        with tempfile.TemporaryDirectory() as pasta:
            invalido = Path(pasta) / "invalido.pdf"
            invalido.write_text("isto nao e um pdf", encoding="utf-8")
            with self.assertRaises(ErroExtracao):
                processar_pdf(invalido, Path(pasta) / "saida.pdf")

    def test_pdf_protegido_por_senha(self) -> None:
        with tempfile.TemporaryDirectory() as pasta:
            protegido = Path(pasta) / "protegido.pdf"
            documento = fitz.open()
            documento.new_page()
            documento.save(
                protegido,
                encryption=fitz.PDF_ENCRYPT_AES_256,
                owner_pw="senha-proprietario",
                user_pw="senha-usuario",
            )
            documento.close()
            with self.assertRaisesRegex(ErroExtracao, "protegido por senha"):
                processar_pdf(protegido, Path(pasta) / "saida.pdf")

    def test_cancelamento_dos_seletores(self) -> None:
        self.assertEqual(executar_com_interface(lambda: "", lambda _: "nao-usado.pdf"), 1)
        self.assertEqual(executar_com_interface(lambda: "livro.pdf", lambda _: ""), 1)

    def test_criar_pdf_recusa_lista_vazia(self) -> None:
        with self.assertRaises(ErroExtracao):
            criar_pdf_a4([], "nao_deve_existir.pdf")


if __name__ == "__main__":
    unittest.main()
