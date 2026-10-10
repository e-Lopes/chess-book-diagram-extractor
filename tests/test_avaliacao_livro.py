"""Verifica métricas com referência independente, inclusive erros em casas vazias."""
from __future__ import annotations

import unittest

from tools.avaliar_livro import avaliar_anotacoes, posicao_classes
from notacao_forsyth import _classes_modelo_da_posicao
from tools.referencia_fontes_pdf import decodificar_linha


class TesteAvaliacaoLivro(unittest.TestCase):
    def test_fontes_decodificam_cor_e_prefixos_de_fundo_sem_modelos(self):
        self.assertEqual(decodificar_linha("4tMvWlVmT5", "ChessMerida", 8), list("rnbqkbnr"))
        self.assertEqual(decodificar_linha("4RnBqKbNr5", "ChessMerida", 1), list("RNBQKBNR"))
        pua = "".join(chr(ord(c) + 0xF000) for c in "4oO +pP +5")
        self.assertEqual(decodificar_linha(pua, "ChessMerida", 7), ["p", "p", "", "", "P", "P", "", ""])
        self.assertEqual(decodificar_linha("4.: +pP +5", "ChessMerida", 7), ["", "", "", "", "P", "P", "", ""])
        self.assertEqual(decodificar_linha("8r+-wQ-zpvLmK(", "DiagramTTFritz", 8),
                         ["r", "", "", "Q", "", "p", "B", "K"])

    def test_fontes_rejeitam_linhas_incompletas_e_glifos_desconhecidos(self):
        for texto, fonte in (("4oO?+pP +5", "ChessMerida"), ("4oO +pP +", "ChessMerida"),
                             ("8r+-+-+-?(", "DiagramTTFritz"), ("8r+-+-+-+", "DiagramTTFritz"),
                             ("8r+-+-+-+(", "fonte desconhecida")):
            with self.assertRaises(ValueError):
                decodificar_linha(texto, fonte, 8)

    def setUp(self):
        self.correta = "4k3/8/8/8/8/8/P7/4K3"
        self.errada = "4k3/8/8/8/8/8/N7/4K2q"
        self.relatorio = {"sha256_pdf": "hash", "paginas": [
            {"pagina": 1, "candidatos": ["d1", "d2"]}], "candidatos": [
            {"id": "d1", "posicao": self.errada, "posicoes_modelos": {"modelo": self.correta}},
            {"id": "d2", "posicao": self.correta, "posicoes_modelos": {"modelo": self.correta}}]}

    def test_ordenacao_preserva_orientacao_da_imagem(self):
        self.assertEqual(posicao_classes(_classes_modelo_da_posicao(self.correta)), self.correta)

    def test_mede_pecas_e_vazias_sem_tratar_falso_positivo_como_tabuleiro(self):
        notas = {"sha256_pdf": "hash", "diagramas": {"d1": {"posicao": self.correta},
                 "d2": {"falso_positivo": True, "posicao": self.correta}}, "paginas": {"1": 2}}
        resultado = avaliar_anotacoes(self.relatorio, notas)
        self.assertEqual(resultado["posicoes_anotadas"], 1)
        self.assertEqual(resultado["falsos_positivos_confirmados"], 1)
        ensemble = resultado["modelos"]["ensemble"]
        self.assertEqual(ensemble["casas_corretas"], 62)
        self.assertEqual(ensemble["casas_ocupadas"], 3)
        self.assertEqual(ensemble["casas_ocupadas_corretas"], 2)
        self.assertEqual({e["casa"] for e in ensemble["erros"][0]["casas"]}, {"a2", "h1"})
        self.assertEqual(resultado["modelos"]["modelo"]["posicoes_exatas"], 1)
        self.assertEqual(resultado["paginas_anotadas"][0]["diferenca_contagem"], -1)

    def test_nao_anotadas_nao_entram_na_acuracia(self):
        resultado = avaliar_anotacoes(self.relatorio, {"sha256_pdf": "hash"})
        self.assertEqual(resultado["posicoes_anotadas"], 0)
        self.assertEqual(resultado["modelos"], {})

    def test_rejeita_referencia_invalida_ou_de_outro_livro(self):
        for notas in ({"sha256_pdf": "outro"}, {"sha256_pdf": "hash", "diagramas": {"d3": {}}},
                      {"sha256_pdf": "hash", "diagramas": {"d1": {"posicao": "inválida"}}},
                      {"sha256_pdf": "hash", "paginas": {"1": -1}}):
            with self.assertRaises(ValueError):
                avaliar_anotacoes(self.relatorio, notas)

    def test_rejeita_anotacoes_de_outros_recortes_do_mesmo_pdf(self):
        self.relatorio["sha256_recortes"] = "recortes-atuais"
        with self.assertRaises(ValueError):
            avaliar_anotacoes(self.relatorio, {"sha256_pdf": "hash", "sha256_recortes": "recortes-antigos"})


if __name__ == "__main__":
    unittest.main()
