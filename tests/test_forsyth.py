from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import cv2
import fitz
import numpy as np


PASTA_MODULO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PASTA_MODULO))

from extrair_tabuleiros_pdf import (  # noqa: E402
    AnotacaoSaida,
    Candidato,
    criar_pdf_a4,
    detectar_tabuleiros,
)
from notacao_forsyth import (  # noqa: E402
    ALFABETO_MODELO,
    DadosCasa,
    ItemRevisao,
    ReferenciaCasa,
    ReconhecedorForsyth,
    ResultadoReconhecimento,
    RevisorAutomaticoLivro,
    SHA256_MODELO,
    aplicar_rascunho,
    aviso_plausibilidade,
    carregar_rascunho,
    carregar_referencias_manuais,
    caminho_modelo_padrao,
    caminho_rascunho,
    caminho_referencias_manuais,
    converter_padrao_para_idioma,
    converter_padrao_para_portugues,
    decodificar_probabilidades,
    girar_posicao,
    normalizar_posicao,
    paridade_casa_modelo,
    remover_rascunho,
    salvar_referencias_manuais,
    salvar_rascunho,
    validar_posicao,
    _descritor_casa,
)
from revisor_forsyth import JanelaRevisaoForsyth  # noqa: E402


class CampoTextoFake:
    def __init__(self, texto: str) -> None:
        self.texto = texto

    def get(self, *_args: object) -> str:
        return self.texto

    def delete(self, *_args: object) -> None:
        self.texto = ""

    def insert(self, _indice: object, texto: str) -> None:
        self.texto = texto


class TesteNotacaoForsyth(unittest.TestCase):
    def test_a8_e_a_casa_clara_do_canto_superior_esquerdo(self) -> None:
        self.assertEqual(paridade_casa_modelo(56), 0)  # a8
        self.assertEqual(paridade_casa_modelo(57), 1)  # b8
        self.assertEqual(paridade_casa_modelo(0), 1)   # a1
        self.assertEqual(paridade_casa_modelo(1), 0)   # b1

    def test_converte_alfabeto_portugues(self) -> None:
        padrao = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR"
        esperado = "tcbdrbct/pppppppp/8/8/8/8/PPPPPPPP/TCBDRBCT"
        self.assertEqual(converter_padrao_para_portugues(padrao), esperado)

    def test_permite_escolher_alfabeto_ingles(self) -> None:
        padrao = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR"
        self.assertEqual(converter_padrao_para_idioma(padrao, "en"), padrao)
        self.assertTrue(validar_posicao("4k3/8/8/8/8/8/8/4K3", "en")[0])
        self.assertFalse(validar_posicao("4d3/8/8/8/8/8/8/4D3", "en")[0])
        self.assertEqual(
            girar_posicao("4k3/8/8/8/8/8/8/4K3", "en"),
            "3K4/8/8/8/8/8/8/3k4",
        )

    def test_exemplo_percorre_fileira_superior_da_esquerda(self) -> None:
        probabilidades = np.zeros((64, 13), dtype=np.float32)
        probabilidades[:, 0] = 1.0
        # O modelo enumera A1..H8; c8 contém rei preto e g8, torre preta.
        probabilidades[7 * 8 + 2] = 0
        probabilidades[7 * 8 + 2, ALFABETO_MODELO.index("k")] = 1
        probabilidades[7 * 8 + 6] = 0
        probabilidades[7 * 8 + 6, ALFABETO_MODELO.index("r")] = 1
        padrao, confiancas, minima, media = decodificar_probabilidades(probabilidades)
        self.assertEqual(padrao, "2k3r1/8/8/8/8/8/8/8")
        self.assertEqual(converter_padrao_para_portugues(padrao), "2r3t1/8/8/8/8/8/8/8")
        self.assertEqual(len(confiancas), 64)
        self.assertEqual((minima, media), (1.0, 1.0))

    def test_corrige_confusao_incerta_entre_peao_e_cavalo(self) -> None:
        probabilidades = np.zeros((64, 13), dtype=np.float32)
        probabilidades[:, 0] = 1.0
        # a2 e b2: cavalo foi o argmax, mas peão está próximo na fileira
        # inicial. f6: empate técnico no sentido inverso para peças pretas.
        for indice in (8, 9):
            probabilidades[indice] = 0
            probabilidades[indice, ALFABETO_MODELO.index("N")] = 0.55
            probabilidades[indice, ALFABETO_MODELO.index("P")] = 0.40
        indice_f6 = 5 * 8 + 5
        probabilidades[indice_f6] = 0
        probabilidades[indice_f6, ALFABETO_MODELO.index("p")] = 0.52
        probabilidades[indice_f6, ALFABETO_MODELO.index("n")] = 0.46

        padrao, _confiancas, minima, _media = decodificar_probabilidades(probabilidades)
        self.assertEqual(
            converter_padrao_para_portugues(padrao),
            "8/8/5c2/8/8/8/PP6/8",
        )
        self.assertAlmostEqual(minima, 0.40, places=5)

    def test_validacao_normalizacao_e_oito_fileiras(self) -> None:
        posicao = "4r3/8/8/3d4/8/8/8/4R3"
        self.assertTrue(validar_posicao(posicao)[0])
        self.assertEqual(normalizar_posicao(posicao), posicao)
        self.assertFalse(validar_posicao("8/8")[0])
        self.assertFalse(validar_posicao("9/8/8/8/8/8/8/8")[0])
        self.assertFalse(validar_posicao("4K3/8/8/8/8/8/8/4R3")[0])

    def test_validacao_exige_exatamente_um_rei_de_cada_cor(self) -> None:
        casos = (
            ("8/8/8/8/8/8/8/4R3", "rei preto"),
            ("4r3/8/8/8/8/8/8/8", "rei branco"),
            ("4r3/8/8/8/8/8/4R3/4R3", "mais de um rei branco"),
            ("4r3/4r3/8/8/8/8/8/4R3", "mais de um rei preto"),
        )
        for posicao, mensagem in casos:
            valido, erro = validar_posicao(posicao)
            self.assertFalse(valido)
            self.assertIn(mensagem, erro)

    def test_rotacao_mantem_imagem_e_posicao_sincronizadas(self) -> None:
        original = "2r3t1/8/8/8/8/8/8/T3R3"
        girada = girar_posicao(original)
        self.assertEqual(girada, "3R3T/8/8/8/8/8/8/1t3r2")
        self.assertEqual(girar_posicao(girada), original)

    def test_reis_inconsistentes_geram_aviso(self) -> None:
        self.assertIn("exatamente um rei", aviso_plausibilidade("8/8/8/8/8/8/8/8"))
        self.assertEqual(aviso_plausibilidade("4r3/8/8/8/8/8/8/4R3"), "")

    def test_notacoes_muito_improvaveis_sao_possiveis_falsos_positivos(self) -> None:
        casos = (
            "6P1/6p1/3DDDP1/1CDPCDp1/3rrBDd/1R1bRP2/3bBB1P/8",
            "DDDTDdDD/DTDRTDDD/TDTtTtDD/tDTDDDDD/DdDTDDDT/TDDTTDRD/DDDTDTTd/TDtTTDTD",
        )
        for posicao in casos:
            aviso = aviso_plausibilidade(posicao)
            self.assertIn("Possível falso positivo", aviso)
            self.assertIn("não seja um diagrama/tabuleiro", aviso)


class TesteRascunhoForsyth(unittest.TestCase):
    def test_salva_restaura_e_remove_atomicamente(self) -> None:
        with tempfile.TemporaryDirectory() as pasta_temporaria:
            pasta = Path(pasta_temporaria)
            livro = pasta / "livro.pdf"
            livro.write_bytes(b"pdf de teste")
            itens = [
                ItemRevisao("4r3/8/8/8/8/8/8/4R3", True, False),
                ItemRevisao("", False, True, nao_e_tabuleiro=True),
            ]
            arquivo = salvar_rascunho(livro, itens, pasta / "dados")
            self.assertTrue(arquivo.is_file())
            self.assertFalse(arquivo.with_suffix(".json.tmp").exists())
            dados = carregar_rascunho(livro, 2, pasta / "dados")
            self.assertIsNotNone(dados)
            self.assertIsNone(carregar_rascunho(livro, 2, pasta / "dados", "en"))
            restaurados = [ItemRevisao(), ItemRevisao()]
            aplicar_rascunho(restaurados, dados or [])
            self.assertEqual(restaurados[0].posicao, itens[0].posicao)
            self.assertTrue(restaurados[0].confirmada)
            self.assertTrue(restaurados[1].girado)
            self.assertTrue(restaurados[1].nao_e_tabuleiro)
            remover_rascunho(livro, pasta / "dados")
            self.assertFalse(caminho_rascunho(livro, pasta / "dados").exists())

    def test_referencias_manuais_ficam_vinculadas_ao_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as pasta_temporaria:
            pasta = Path(pasta_temporaria)
            livro = pasta / "livro.pdf"
            livro.write_bytes(b"pdf de teste")
            imagem = np.full((32, 32), 0.75, dtype=np.float32)
            referencias = [ReferenciaCasa("Q", 1, imagem, 3, manual=True)]

            salvar_referencias_manuais(livro, referencias, pasta / "dados")
            restauradas = carregar_referencias_manuais(livro, pasta / "dados")

            self.assertEqual(len(restauradas), 1)
            self.assertEqual((restauradas[0].classe, restauradas[0].paridade), ("Q", 1))
            self.assertTrue(caminho_referencias_manuais(livro, pasta / "dados").is_file())
            outro = pasta / "outro.pdf"
            outro.write_bytes(b"outro")
            self.assertEqual(carregar_referencias_manuais(outro, pasta / "dados"), [])

    def test_navegacao_salva_e_confirma_posicao_valida(self) -> None:
        janela = JanelaRevisaoForsyth.__new__(JanelaRevisaoForsyth)
        janela.itens = [ItemRevisao(), ItemRevisao()]
        janela.indice = 0
        janela.idioma = "pt"
        janela.campo_posicao = CampoTextoFake("4r3/8/8/8/8/8/8/4R3")
        janela._salvar_rascunho = lambda: None
        janela._exibir_atual = lambda: None
        janela._navegar(1)
        self.assertEqual(janela.indice, 1)
        self.assertEqual(janela.itens[0].posicao, "4r3/8/8/8/8/8/8/4R3")
        self.assertTrue(janela.itens[0].confirmada)
        janela.campo_posicao.texto = "3r4/8/8/8/8/8/8/3R4"
        janela._ir_para(0)
        self.assertEqual(janela.indice, 0)
        self.assertEqual(janela.itens[1].posicao, "3r4/8/8/8/8/8/8/3R4")
        self.assertTrue(janela.itens[1].confirmada)

    def test_visualizador_salva_sugestao_invalida_sem_bloquear(self) -> None:
        janela = JanelaRevisaoForsyth.__new__(JanelaRevisaoForsyth)
        posicao = "8/8/8/8/8/8/8/8"
        janela.itens = [
            ItemRevisao(posicao=posicao),
            ItemRevisao(posicao="", nao_e_tabuleiro=True),
        ]
        janela.indice = 0
        janela.idioma = "pt"
        janela.campo_posicao = CampoTextoFake(posicao)
        janela._salvar_rascunho = lambda: None
        janela._redimensionamento_pendente = None
        janela._fechando = False
        janela.janela = MagicMock()
        recebidas = []
        janela.ao_finalizar = recebidas.append

        with patch("revisor_forsyth.messagebox.showwarning") as aviso:
            janela._concluir()

        aviso.assert_not_called()
        self.assertEqual(recebidas[0][0].posicao, posicao)
        self.assertIsNone(recebidas[0][1].posicao)
        self.assertTrue(recebidas[0][1].excluir)
        janela.janela.destroy.assert_called_once()

    def test_checkbox_de_exclusao_nao_revisa_o_livro_na_thread_visual(self) -> None:
        janela = JanelaRevisaoForsyth.__new__(JanelaRevisaoForsyth)
        janela.indice = 0
        janela.itens = [ItemRevisao()]
        janela.variavel_excluir = MagicMock()
        janela.variavel_excluir.get.return_value = True
        janela.revisor_automatico = MagicMock()
        janela._salvar_rascunho = MagicMock()
        janela._validar_digitacao = MagicMock()

        janela._alterar_exclusao()

        self.assertTrue(janela.itens[0].nao_e_tabuleiro)
        janela.revisor_automatico.definir_exclusao.assert_called_once_with(0, True)
        janela.revisor_automatico.revisar_itens.assert_not_called()

    def test_alternancia_do_lado_a_jogar_e_salva_no_item(self) -> None:
        janela = JanelaRevisaoForsyth.__new__(JanelaRevisaoForsyth)
        janela.indice = 0
        janela.itens = [ItemRevisao()]
        janela.variavel_lado = MagicMock()
        janela.variavel_lado.get.return_value = "b"
        janela._salvar_rascunho = MagicMock()

        janela._alterar_lado()

        self.assertEqual(janela.itens[0].lado_a_jogar, "b")
        janela._salvar_rascunho.assert_called_once()


class TesteRevisaoAutomaticaLivro(unittest.TestCase):
    @staticmethod
    def _imagem_dama() -> np.ndarray:
        imagem = np.full((32, 32), 0.90, dtype=np.float32)
        cv2.rectangle(imagem, (7, 15), (25, 26), 0.10, -1)
        for x in (8, 13, 19, 24):
            cv2.circle(imagem, (x, 9), 3, 0.10, -1)
        return imagem

    @staticmethod
    def _resultado_ambiguo(paridade: int = 1) -> ResultadoReconhecimento:
        probabilidades = np.full(13, 0.001, dtype=np.float32)
        probabilidades[ALFABETO_MODELO.index("B")] = 0.42
        probabilidades[ALFABETO_MODELO.index("Q")] = 0.38
        probabilidades[ALFABETO_MODELO.index("1")] = 0.10
        casa = DadosCasa(
            indice=0,
            coordenada="a1",
            paridade=paridade,
            imagem=TesteRevisaoAutomaticaLivro._imagem_dama(),
            probabilidades=probabilidades,
            classe_original="B",
            top3=("B", "Q", "1"),
            confianca=0.42,
            margem=0.04,
        )
        posicao = "8/8/8/8/8/8/8/B7"
        return ResultadoReconhecimento(
            posicao=posicao,
            confianca_minima=0.42,
            confianca_media=0.8,
            confiavel=False,
            girado=False,
            orientacao_ambigua=False,
            posicao_original_padrao=posicao,
            casas=(casa,),
        )

    @staticmethod
    def _referencias(paridade: int = 1, quantidade: int = 3) -> list[ReferenciaCasa]:
        referencias: list[ReferenciaCasa] = []
        for indice in range(quantidade):
            referencias.append(
                ReferenciaCasa("Q", paridade, TesteRevisaoAutomaticaLivro._imagem_dama(), indice, True)
            )
            referencias.append(
                ReferenciaCasa("B", paridade, np.full((32, 32), 0.90, np.float32), indice, True)
            )
        return referencias

    def test_corrige_com_tres_referencias_fortes_da_mesma_cor_de_casa(self) -> None:
        revisor = RevisorAutomaticoLivro(
            [self._resultado_ambiguo()],
            idioma="en",
            referencias_manuais=self._referencias(),
        )
        resultado = revisor.revisar()[0]
        self.assertEqual(resultado.posicao, "8/8/8/8/8/8/8/Q7")
        self.assertEqual(len(resultado.alteracoes_automaticas), 1)
        self.assertEqual(resultado.alteracoes_automaticas[0].coordenada, "a1")

    def test_nao_mistura_referencias_de_casas_claras_e_escuras(self) -> None:
        revisor = RevisorAutomaticoLivro(
            [self._resultado_ambiguo(paridade=1)],
            idioma="en",
            referencias_manuais=self._referencias(paridade=0),
        )
        self.assertEqual(revisor.revisar()[0].posicao, "8/8/8/8/8/8/8/B7")

    def test_menos_de_tres_referencias_nao_altera_a_peca(self) -> None:
        revisor = RevisorAutomaticoLivro(
            [self._resultado_ambiguo()],
            idioma="en",
            referencias_manuais=self._referencias(quantidade=2),
        )
        resultado = revisor.revisar()[0]
        self.assertEqual(resultado.posicao, "8/8/8/8/8/8/8/B7")
        self.assertEqual(len(resultado.duvidas_automaticas), 1)

    def test_subtracao_do_fundo_aproxima_a_mesma_silhueta(self) -> None:
        peca = self._imagem_dama()
        fundo_a = np.full((32, 32), 0.90, dtype=np.float32)
        fundo_b = np.full((32, 32), 0.70, dtype=np.float32)
        imagem_b = np.clip(peca - 0.20, 0, 1)
        descritor_a = _descritor_casa(peca, fundo_a)
        descritor_b = _descritor_casa(imagem_b, fundo_b)
        self.assertGreater(float(np.dot(descritor_a, descritor_b)), 0.98)

    def test_pares_conhecidos_sao_reavaliados_nos_dois_sentidos(self) -> None:
        for original, alternativa in (
            ("P", "N"),
            ("N", "P"),
            ("p", "n"),
            ("n", "p"),
            ("p", "b"),
            ("b", "p"),
            ("B", "Q"),
            ("Q", "B"),
        ):
            probabilidades = np.full(13, 0.001, dtype=np.float32)
            probabilidades[ALFABETO_MODELO.index(original)] = 0.42
            probabilidades[ALFABETO_MODELO.index(alternativa)] = 0.38
            probabilidades[0] = 0.10
            casa = DadosCasa(
                0,
                "a1",
                1,
                self._imagem_dama(),
                probabilidades,
                original,
                (original, alternativa, "1"),
                0.42,
                0.04,
            )
            posicao = f"8/8/8/8/8/8/8/{original}7"
            resultado = ResultadoReconhecimento(
                posicao,
                0.42,
                0.8,
                False,
                False,
                False,
                posicao_original_padrao=posicao,
                casas=(casa,),
            )
            referencias = [
                *[
                    ReferenciaCasa(alternativa, 1, self._imagem_dama(), indice, True)
                    for indice in range(3)
                ],
                *[
                    ReferenciaCasa(original, 1, np.full((32, 32), 0.9, np.float32), indice, True)
                    for indice in range(3)
                ],
            ]
            revisado = RevisorAutomaticoLivro(
                [resultado], idioma="en", referencias_manuais=referencias
            ).revisar()[0]
            self.assertEqual(
                revisado.posicao,
                f"8/8/8/8/8/8/8/{alternativa}7",
                (original, alternativa),
            )

    def test_edicoes_manuais_podem_revisar_ocorrencias_nao_editadas(self) -> None:
        resultados = [self._resultado_ambiguo() for _ in range(4)]
        referencias_bispo = [
            ReferenciaCasa("B", 1, np.full((32, 32), 0.9, np.float32), indice, True)
            for indice in range(3)
        ]
        revisor = RevisorAutomaticoLivro(
            resultados,
            idioma="en",
            referencias_manuais=referencias_bispo,
        )
        itens = [ItemRevisao.de_reconhecimento(resultado) for resultado in resultados]
        for indice in range(3):
            itens[indice].editada_manualmente = True
            itens[indice].posicao = "8/8/8/8/8/8/8/Q7"
            revisor.registrar_edicao(
                indice,
                itens[indice],
                "8/8/8/8/8/8/8/B7",
                itens[indice].posicao,
            )
        revisor.revisar_itens(itens)
        self.assertEqual(itens[3].posicao, "8/8/8/8/8/8/8/Q7")
        self.assertTrue(all(item.posicao.endswith("Q7") for item in itens[:3]))

    def test_referencias_automaticas_exigem_tres_casos_em_dois_diagramas(self) -> None:
        def resultado_referencia(quantidade_casas: int) -> ResultadoReconhecimento:
            probabilidades = np.full(13, 0.001, dtype=np.float32)
            probabilidades[ALFABETO_MODELO.index("Q")] = 0.92
            probabilidades[0] = 0.03
            casas = tuple(
                DadosCasa(
                    indice,
                    f"{chr(ord('a') + indice)}1",
                    1,
                    self._imagem_dama(),
                    probabilidades.copy(),
                    "Q",
                    ("Q", "1", "B"),
                    0.92,
                    0.89,
                )
                for indice in range(quantidade_casas)
            )
            return ResultadoReconhecimento(
                "8/8/8/8/8/8/8/Q7",
                0.92,
                0.92,
                True,
                False,
                False,
                posicao_original_padrao="8/8/8/8/8/8/8/Q7",
                casas=casas,
            )

        apenas_um_diagrama = RevisorAutomaticoLivro([resultado_referencia(3)], idioma="en")
        self.assertEqual(apenas_um_diagrama.referencias_automaticas, [])

        dois_diagramas = RevisorAutomaticoLivro(
            [resultado_referencia(2), resultado_referencia(1)],
            idioma="en",
        )
        self.assertEqual(len(dois_diagramas.referencias_automaticas), 3)
        dois_diagramas.definir_exclusao(1, True)
        # O checkbox apenas marca a biblioteca como desatualizada; a etapa
        # cara é executada somente quando uma nova revisão for solicitada.
        self.assertEqual(len(dois_diagramas.referencias_automaticas), 3)
        dois_diagramas.revisar()
        self.assertEqual(dois_diagramas.referencias_automaticas, [])


class TesteModeloForsyth(unittest.TestCase):
    def test_modelo_tem_hash_fixado_e_executa_64_casas(self) -> None:
        modelo = caminho_modelo_padrao()
        self.assertTrue(modelo.is_file())
        self.assertEqual(hashlib.sha256(modelo.read_bytes()).hexdigest().upper(), SHA256_MODELO)
        reconhecedor = ReconhecedorForsyth(modelo)
        imagem = np.full((256, 256, 3), 255, dtype=np.uint8)
        resultado = reconhecedor.reconhecer(imagem)
        # Uma imagem vazia ainda deve produzir sintaxe 8x8 normalizável, mas
        # não é uma posição válida porque não contém os dois reis.
        self.assertEqual(normalizar_posicao(resultado.posicao), resultado.posicao)
        self.assertEqual(len(resultado.casas), 64)
        self.assertTrue(all(casa.probabilidades.shape == (13,) for casa in resultado.casas))
        self.assertTrue(all(len(casa.top3) == 3 for casa in resultado.casas))
        self.assertEqual(resultado.casas[56].coordenada, "a8")
        self.assertEqual(resultado.casas[56].paridade, 0)

    def test_nenhuma_fixture_publica_incorreta_e_marcada_confiavel(self) -> None:
        pasta = PASTA_MODULO / "tests" / "fixtures" / "fenshot"
        esperadas = {
            "reddit-page-board.png": "2r5/pppd2b1/3p2p1/5cp1/P5C1/5p1P/1P2t2T/D4R2",
            "pale-blue-tds-board.png": "t1b2bct/p2pr1p1/cp2C2p/1Pp1D3/5pP1/B3P2B/P1PP1PdP/TC2R2T",
            "lichess-italian-black.png": "t1bdr1ct/pppp1ppp/2c5/2b1p3/2B1P3/5C2/PPPP1PPP/TCBDR2T",
            "lichess-italian-horsey.png": "t1bdr1ct/pppp1ppp/2c5/2b1p3/2B1P3/5C2/PPPP1PPP/TCBDR2T",
            "lichess-queens-only-board-marble.png": "6r1/2D5/8/8/8/2d5/8/6R1",
        }
        reconhecedor = ReconhecedorForsyth()
        confiaveis = 0
        orientacao_preta = {"reddit-page-board.png", "lichess-italian-black.png"}
        for nome, esperada in esperadas.items():
            imagem = cv2.imread(str(pasta / nome))
            self.assertIsNotNone(imagem, nome)
            candidatos = detectar_tabuleiros(imagem)
            self.assertLessEqual(len(candidatos), 1, nome)
            for candidato in candidatos:
                resultado = reconhecedor.reconhecer(candidato.imagem)
                if resultado.confiavel:
                    confiaveis += 1
                    if nome in orientacao_preta:
                        esperada = girar_posicao(esperada)
                    self.assertEqual(resultado.posicao, esperada, nome)
                self.assertFalse(resultado.girado)
        self.assertGreaterEqual(confiaveis, 2)


class TestePdfForsyth(unittest.TestCase):
    def test_anotacao_selecionavel_corresponde_a_cada_diagrama(self) -> None:
        with tempfile.TemporaryDirectory() as pasta_temporaria:
            saida = Path(pasta_temporaria) / "anotado.pdf"
            imagem_a = np.full((240, 240, 3), 245, dtype=np.uint8)
            imagem_b = np.full((240, 240, 3), 220, dtype=np.uint8)
            cv2.circle(imagem_a, (50, 50), 20, (0, 0, 0), -1)
            cv2.circle(imagem_b, (190, 190), 20, (0, 0, 0), -1)
            quadro = np.array([[0, 0], [239, 0], [239, 239], [0, 239]], np.float32)
            candidatos = [Candidato(2, quadro, imagem_a, 0.9), Candidato(7, quadro, imagem_b, 0.9)]
            posicao = "4r3/8/8/8/8/8/8/4R3"
            criar_pdf_a4(
                candidatos,
                saida,
                [AnotacaoSaida(posicao, False), AnotacaoSaida(None, True)],
            )
            documento = fitz.open(saida)
            try:
                self.assertEqual(documento.page_count, 3)
                self.assertIn(posicao, documento[0].get_text())
                self.assertIn("posição não informada", documento[1].get_text())
                self.assertIn("Página original (do pdf): 2", documento[0].get_text())
                self.assertNotIn("Confiança da detecção:", documento[0].get_text())
                self.assertIn("Página original (do pdf): 7", documento[1].get_text())
                self.assertEqual(len(documento[0].get_images(full=True)), 1)
                self.assertEqual(len(documento[1].get_images(full=True)), 1)
                linhas_indice = documento[2].get_text().splitlines()
                self.assertEqual(linhas_indice, [posicao, "posição não informada"])
                self.assertNotIn("Forsyth", documento[2].get_text())
            finally:
                documento.close()

    def test_indice_de_notacoes_continua_em_novas_paginas(self) -> None:
        with tempfile.TemporaryDirectory() as pasta_temporaria:
            saida = Path(pasta_temporaria) / "indice_longo.pdf"
            imagem = np.full((80, 80, 3), 255, dtype=np.uint8)
            quadro = np.array([[0, 0], [79, 0], [79, 79], [0, 79]], np.float32)
            candidatos = [Candidato(indice + 1, quadro, imagem, 0.9) for indice in range(70)]
            anotacoes = [AnotacaoSaida(f"8/8/8/8/8/8/8/{indice % 8 + 1}") for indice in range(70)]

            criar_pdf_a4(candidatos, saida, anotacoes)

            with fitz.open(saida) as documento:
                self.assertGreater(documento.page_count, len(candidatos) + 1)
                linhas = [
                    linha
                    for pagina in documento[len(candidatos) :]
                    for linha in pagina.get_text().splitlines()
                ]
                self.assertEqual(linhas, [anotacao.posicao for anotacao in anotacoes])

    def test_recorte_marcado_como_nao_tabuleiro_e_excluido_do_pdf_final(self) -> None:
        with tempfile.TemporaryDirectory() as pasta_temporaria:
            saida = Path(pasta_temporaria) / "filtrado.pdf"
            imagem = np.full((80, 80, 3), 255, dtype=np.uint8)
            quadro = np.array([[0, 0], [79, 0], [79, 79], [0, 79]], np.float32)
            candidatos = [
                Candidato(2, quadro, imagem, 0.9),
                Candidato(4, quadro, imagem, 0.9),
            ]
            removida = "8/8/8/8/8/8/8/8"
            mantida = "4r3/8/8/8/8/8/8/4R3"
            anotacoes = [
                AnotacaoSaida(removida, excluir=True),
                AnotacaoSaida(mantida),
            ]

            criar_pdf_a4(candidatos, saida, anotacoes)

            with fitz.open(saida) as documento:
                self.assertEqual(documento.page_count, 2)
                self.assertIn("Página original (do pdf): 4", documento[0].get_text())
                self.assertNotIn(removida, "\n".join(pagina.get_text() for pagina in documento))
                self.assertEqual(documento[1].get_text().splitlines(), [mantida])


if __name__ == "__main__":
    unittest.main()
