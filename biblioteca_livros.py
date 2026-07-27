"""Biblioteca permanente de livros processados e exportacao PGN."""

from __future__ import annotations

import json
import os
import shutil
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

import cv2
import fitz
import numpy as np

from extrair_tabuleiros_pdf import AnotacaoSaida, Candidato
from notacao_forsyth import converter_idioma_para_padrao, validar_posicao


SCHEMA_BIBLIOTECA = 1


class LivroDuplicadoError(ValueError):
    def __init__(self, livro: "LivroSalvo") -> None:
        self.livro = livro
        super().__init__(f'Ja existe um livro chamado "{livro.titulo}" na biblioteca.')


@dataclass(frozen=True)
class DiagramaSalvo:
    pagina: int
    confianca: float = 0.0
    posicao: str | None = None
    lado_a_jogar: str = "w"

    def __post_init__(self) -> None:
        if self.lado_a_jogar not in ("w", "b"):
            raise ValueError("O lado a jogar deve ser 'w' ou 'b'.")


@dataclass(frozen=True)
class LivroSalvo:
    id: str
    titulo: str
    annotator: str
    idioma: str
    paginas_originais: int
    criado_em: str
    atualizado_em: str
    diagramas: tuple[DiagramaSalvo, ...] = field(default_factory=tuple)
    pdf_interno: Path = field(default=Path(), compare=False)


class BibliotecaLivros:
    """Armazena copias internas independentes dos arquivos exportados."""

    def __init__(self, pasta_dados: os.PathLike[str] | str) -> None:
        self.pasta = Path(pasta_dados) / "library"

    def _pasta_livro(self, livro_id: str) -> Path:
        if not livro_id or any(c not in "0123456789abcdef-" for c in livro_id.lower()):
            raise ValueError("Identificador de livro invalido.")
        return self.pasta / livro_id

    @staticmethod
    def _agora() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    def salvar(
        self,
        pdf: os.PathLike[str] | str,
        titulo: str,
        diagramas: Sequence[DiagramaSalvo],
        *,
        idioma: str = "pt",
        annotator: str = "",
        paginas_originais: int = 0,
        livro_id: str | None = None,
    ) -> LivroSalvo:
        origem = Path(pdf)
        if not origem.is_file():
            raise FileNotFoundError(f"PDF de diagramas nao encontrado: {origem}")
        if idioma not in ("pt", "en"):
            raise ValueError("Idioma de notacao invalido.")
        if livro_id is None:
            duplicado = self.buscar_por_titulo(titulo)
            if duplicado is not None:
                raise LivroDuplicadoError(duplicado)
            livro_id = uuid.uuid4().hex
        pasta = self._pasta_livro(livro_id)
        pasta.mkdir(parents=True, exist_ok=True)
        destino_pdf = pasta / "diagramas.pdf"
        if origem.resolve() != destino_pdf.resolve():
            temporario_pdf = pasta / "diagramas.pdf.tmp"
            shutil.copyfile(origem, temporario_pdf)
            os.replace(temporario_pdf, destino_pdf)

        anterior = self.carregar(livro_id)
        agora = self._agora()
        conteudo = {
            "schema": SCHEMA_BIBLIOTECA,
            "id": livro_id,
            "titulo": titulo.strip() or "Livro sem titulo",
            "annotator": annotator.strip(),
            "idioma": idioma,
            "paginas_originais": max(0, int(paginas_originais)),
            "criado_em": anterior.criado_em if anterior else agora,
            "atualizado_em": agora,
            "diagramas": [asdict(item) for item in diagramas],
        }
        temporario_json = pasta / "metadata.json.tmp"
        temporario_json.write_text(
            json.dumps(conteudo, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        metadados = pasta / "metadata.json"
        if metadados.is_file():
            shutil.copyfile(metadados, pasta / "metadata.json.bak")
        os.replace(temporario_json, metadados)
        livro = self.carregar(livro_id)
        if livro is None:  # pragma: no cover - protecao contra falha inesperada de E/S
            raise OSError("Nao foi possivel reabrir o livro salvo.")
        return livro

    def carregar(self, livro_id: str) -> LivroSalvo | None:
        try:
            pasta = self._pasta_livro(livro_id)
            caminho_metadados = pasta / "metadata.json"
            dados = json.loads(caminho_metadados.read_text(encoding="utf-8"))
            if dados.get("schema") != SCHEMA_BIBLIOTECA or dados.get("id") != livro_id:
                return None
            diagramas = tuple(
                DiagramaSalvo(
                    pagina=int(item["pagina"]),
                    confianca=float(item.get("confianca", 0.0)),
                    posicao=item.get("posicao") if isinstance(item.get("posicao"), str) else None,
                    lado_a_jogar=item.get("lado_a_jogar", "w"),
                )
                for item in dados.get("diagramas", [])
                if isinstance(item, dict)
            )
            pdf = pasta / "diagramas.pdf"
            if not pdf.is_file():
                return None
            diagramas, recuperados = self._recuperar_posicoes_do_pdf(pdf, diagramas)
            if recuperados:
                for indice, posicao in recuperados.items():
                    dados["diagramas"][indice]["posicao"] = posicao
                try:
                    backup = pasta / "metadata.json.bak"
                    if not backup.exists():
                        shutil.copyfile(caminho_metadados, backup)
                    temporario = pasta / "metadata.json.recovery.tmp"
                    temporario.write_text(
                        json.dumps(dados, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    os.replace(temporario, caminho_metadados)
                except OSError:
                    pass
            return LivroSalvo(
                id=livro_id,
                titulo=str(dados.get("titulo", "Livro sem titulo")),
                annotator=str(dados.get("annotator", "")),
                idioma=str(dados.get("idioma", "pt")),
                paginas_originais=int(dados.get("paginas_originais", 0)),
                criado_em=str(dados.get("criado_em", "")),
                atualizado_em=str(dados.get("atualizado_em", "")),
                diagramas=diagramas,
                pdf_interno=pdf,
            )
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            return None

    @staticmethod
    def _recuperar_posicoes_do_pdf(
        pdf: Path, diagramas: tuple[DiagramaSalvo, ...]
    ) -> tuple[tuple[DiagramaSalvo, ...], dict[int, str]]:
        faltantes = {
            indice for indice, diagrama in enumerate(diagramas) if not diagrama.posicao
        }
        if not faltantes:
            return diagramas, {}
        recuperados: dict[int, str] = {}
        try:
            with fitz.open(pdf) as documento:
                for indice in faltantes:
                    if indice >= documento.page_count:
                        continue
                    linhas = [
                        linha.strip()
                        for linha in documento[indice].get_text("text").splitlines()
                        if linha.strip()
                    ]
                    posicao = next(
                        (
                            linha
                            for linha in linhas
                            if linha.count("/") == 7
                            and not any(caractere.isspace() for caractere in linha)
                        ),
                        None,
                    )
                    if posicao:
                        recuperados[indice] = posicao
        except (OSError, RuntimeError, ValueError):
            return diagramas, {}
        if not recuperados:
            return diagramas, {}
        restaurados = tuple(
            DiagramaSalvo(
                pagina=diagrama.pagina,
                confianca=diagrama.confianca,
                posicao=recuperados.get(indice, diagrama.posicao),
                lado_a_jogar=diagrama.lado_a_jogar,
            )
            for indice, diagrama in enumerate(diagramas)
        )
        return restaurados, recuperados

    def listar(self) -> list[LivroSalvo]:
        if not self.pasta.is_dir():
            return []
        livros = [livro for pasta in self.pasta.iterdir() if pasta.is_dir() if (livro := self.carregar(pasta.name))]
        return sorted(livros, key=lambda livro: livro.atualizado_em, reverse=True)

    @staticmethod
    def _chave_titulo(titulo: str) -> str:
        return " ".join(titulo.split()).casefold()

    def buscar_por_titulo(
        self, titulo: str, *, ignorar_id: str | None = None
    ) -> LivroSalvo | None:
        chave = self._chave_titulo(titulo)
        if not chave:
            return None
        return next(
            (
                livro
                for livro in self.listar()
                if livro.id != ignorar_id and self._chave_titulo(livro.titulo) == chave
            ),
            None,
        )

    def renomear(
        self, livro_id: str, novo_titulo: str, *, substituir: bool = False
    ) -> LivroSalvo:
        titulo = novo_titulo.strip()
        if not titulo:
            raise ValueError("O nome do livro nao pode ficar vazio.")
        livro = self.carregar(livro_id)
        if livro is None:
            raise FileNotFoundError("Livro nao encontrado na biblioteca interna.")
        duplicado = self.buscar_por_titulo(titulo, ignorar_id=livro_id)
        if duplicado is not None and not substituir:
            raise LivroDuplicadoError(duplicado)
        renomeado = self.salvar(
            livro.pdf_interno,
            titulo,
            livro.diagramas,
            idioma=livro.idioma,
            annotator=livro.annotator,
            paginas_originais=livro.paginas_originais,
            livro_id=livro.id,
        )
        if duplicado is not None:
            self.excluir(duplicado.id)
        return renomeado

    def excluir(self, livro_id: str) -> bool:
        """Exclui somente a pasta interna correspondente ao identificador informado."""
        pasta_raiz = self.pasta.resolve()
        pasta_livro = self._pasta_livro(livro_id).resolve()
        if pasta_livro.parent != pasta_raiz:
            raise ValueError("Destino de exclusao fora da biblioteca interna.")
        if not pasta_livro.is_dir():
            return False
        shutil.rmtree(pasta_livro)
        return True

    def carregar_candidatos(self, livro: LivroSalvo) -> list[Candidato]:
        candidatos: list[Candidato] = []
        with fitz.open(livro.pdf_interno) as documento:
            if documento.page_count < len(livro.diagramas):
                raise ValueError("O PDF interno nao corresponde aos dados do livro.")
            for indice, diagrama in enumerate(livro.diagramas):
                imagens = documento[indice].get_images(full=True)
                if not imagens:
                    raise ValueError(f"O diagrama {indice + 1} nao possui imagem no PDF interno.")
                maior = max(imagens, key=lambda item: int(item[2]) * int(item[3]))
                dados = documento.extract_image(int(maior[0])).get("image")
                if not isinstance(dados, bytes):
                    raise ValueError(f"Nao foi possivel ler o diagrama {indice + 1}.")
                imagem = cv2.imdecode(np.frombuffer(dados, np.uint8), cv2.IMREAD_COLOR)
                if imagem is None:
                    raise ValueError(f"Nao foi possivel decodificar o diagrama {indice + 1}.")
                altura, largura = imagem.shape[:2]
                quadro = np.array(
                    [[0, 0], [largura - 1, 0], [largura - 1, altura - 1], [0, altura - 1]],
                    dtype=np.float32,
                )
                candidatos.append(Candidato(diagrama.pagina, quadro, imagem, diagrama.confianca))
        return candidatos


def diagramas_de_anotacoes(
    candidatos: Sequence[Candidato], anotacoes: Sequence[AnotacaoSaida]
) -> list[DiagramaSalvo]:
    if len(candidatos) != len(anotacoes):
        raise ValueError("Cada diagrama precisa de uma anotacao.")
    return [
        DiagramaSalvo(
            pagina=candidato.pagina,
            confianca=candidato.confianca,
            posicao=anotacao.posicao,
            lado_a_jogar=anotacao.lado_a_jogar,
        )
        for candidato, anotacao in zip(candidatos, anotacoes)
        if not anotacao.excluir
    ]


def fen_completa(posicao: str, lado_a_jogar: str, idioma: str = "pt") -> str:
    valido, mensagem = validar_posicao(posicao, idioma)
    if not valido:
        raise ValueError(mensagem)
    if lado_a_jogar not in ("w", "b"):
        raise ValueError("O lado a jogar deve ser 'w' ou 'b'.")
    tabuleiro = converter_idioma_para_padrao(posicao, idioma)
    return f"{tabuleiro} {lado_a_jogar} - - 0 1"


def fen_exportacao(posicao: str, lado_a_jogar: str, idioma: str = "pt") -> str:
    """Retorna a forma abreviada solicitada para a tag FEN do PGN."""
    valido, mensagem = validar_posicao(posicao, idioma)
    if not valido:
        raise ValueError(mensagem)
    if lado_a_jogar not in ("w", "b"):
        raise ValueError("O lado a jogar deve ser 'w' ou 'b'.")
    tabuleiro = converter_idioma_para_padrao(posicao, idioma)
    return f"{tabuleiro} {lado_a_jogar}"


def _valor_tag(valor: str) -> str:
    return valor.replace("\\", "\\\\").replace('"', '\\"').replace("\r", " ").replace("\n", " ")


def gerar_pgn(
    titulo: str,
    diagramas: Sequence[DiagramaSalvo],
    annotator: str,
    idioma: str = "pt",
) -> str:
    partidas: list[str] = []
    for indice, diagrama in enumerate(diagramas, start=1):
        if not diagrama.posicao:
            continue
        fen = fen_exportacao(diagrama.posicao, diagrama.lado_a_jogar, idioma)
        tags = [
            ("Event", titulo),
            ("Site", "?"),
            ("Date", "????.??.??"),
            ("Round", str(indice)),
            ("White", "?"),
            ("Black", "?"),
            ("Result", "*"),
            ("Annotator", annotator),
            ("SetUp", "1"),
            ("FEN", fen),
        ]
        partidas.append("\n".join(f'[{nome} "{_valor_tag(valor)}"]' for nome, valor in tags) + "\n\n*")
    return "\n\n".join(partidas) + ("\n" if partidas else "")


def exportar_pgn(
    destino: os.PathLike[str] | str,
    titulo: str,
    diagramas: Sequence[DiagramaSalvo],
    annotator: str,
    idioma: str = "pt",
) -> Path:
    caminho = Path(destino)
    conteudo = gerar_pgn(titulo, diagramas, annotator, idioma)
    temporario = caminho.with_suffix(caminho.suffix + ".tmp")
    temporario.write_text(conteudo, encoding="utf-8", newline="\n")
    os.replace(temporario, caminho)
    return caminho
