"""Atualizacao segura a partir da ultima GitHub Release publica."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import tempfile
import urllib.request
import urllib.error
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


API_VERSION = "2026-03-10"
TAMANHO_MAXIMO = 350 * 1024 * 1024


class ErroAtualizacao(RuntimeError):
    pass


class AtualizacaoCancelada(ErroAtualizacao):
    pass


@dataclass(frozen=True)
class Atualizacao:
    versao: str
    nome_arquivo: str
    url: str
    sha256: str
    tamanho: int
    notas: str


def chave_versao(valor: str) -> tuple[int, int, int]:
    limpa = valor.strip().removeprefix("v")
    correspondencia = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)(?:[-+][0-9A-Za-z.-]+)?", limpa)
    if not correspondencia:
        raise ValueError(f"Versao invalida: {valor}")
    return tuple(int(parte) for parte in correspondencia.groups())  # type: ignore[return-value]


def versao_mais_nova(nova: str, atual: str) -> bool:
    """Compara também pré-releases; metadados +build não mudam a ordem."""
    def chave(valor):
        numeros = chave_versao(valor)
        principal = valor.strip().removeprefix("v").split("+", 1)[0]
        partes = principal.split("-", 1)
        previa = tuple((0, int(p)) if p.isdigit() else (1, p) for p in partes[1].split(".")) if len(partes) == 2 else ()
        return numeros, len(partes) == 1, previa
    return chave(nova) > chave(atual)


def consultar_atualizacao(
    repositorio: str,
    versao_atual: str,
    abrir_url: Callable[..., object] = urllib.request.urlopen,
) -> Atualizacao | None:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repositorio):
        raise ErroAtualizacao("O repositório de atualizações ainda não foi configurado.")
    requisicao = urllib.request.Request(
        f"https://api.github.com/repos/{repositorio}/releases/latest",
        headers={
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": API_VERSION,
            "User-Agent": "ChessBookDiagramExtractor-Updater",
        },
    )
    try:
        with abrir_url(requisicao, timeout=10) as resposta:  # type: ignore[attr-defined]
            dados = json.loads(resposta.read().decode("utf-8"))
    except urllib.error.HTTPError as erro:
        if erro.code == 404:
            return None
        if erro.code in (403, 429):
            raise ErroAtualizacao("O GitHub limitou as consultas. Tente novamente mais tarde.") from erro
        raise ErroAtualizacao(f"Não foi possível consultar o GitHub (HTTP {erro.code}).") from erro
    except Exception as erro:
        raise ErroAtualizacao(f"Não foi possível consultar o GitHub: {erro}") from erro

    if not isinstance(dados, dict):
        raise ErroAtualizacao("Resposta de atualização inválida.")
    if dados.get("draft") or dados.get("prerelease"):
        return None
    versao = str(dados.get("tag_name", "")).removeprefix("v")
    try:
        if not versao_mais_nova(versao, versao_atual):
            return None
    except ValueError as erro:
        raise ErroAtualizacao(str(erro)) from erro

    nome_esperado = f"ChessBookDiagramExtractor-Setup-v{versao}.exe"
    ativo = next((item for item in dados.get("assets", []) if item.get("name") == nome_esperado), None)
    if ativo is None:
        raise ErroAtualizacao(f"A Release {versao} não contém {nome_esperado}.")

    digest = str(ativo.get("digest") or "")
    if not re.fullmatch(r"sha256:[0-9a-fA-F]{64}", digest):
        raise ErroAtualizacao("O instalador publicado não possui um SHA-256 válido.")
    try:
        tamanho = int(ativo.get("size") or 0)
    except (TypeError, ValueError) as erro:
        raise ErroAtualizacao("O tamanho do instalador publicado é inválido.") from erro
    if tamanho <= 0 or tamanho > TAMANHO_MAXIMO:
        raise ErroAtualizacao("O tamanho do instalador publicado é inválido.")
    url = str(ativo.get("browser_download_url") or "")
    url_esperada = f"https://github.com/{repositorio}/releases/download/{dados['tag_name']}/{nome_esperado}"
    if url != url_esperada:
        raise ErroAtualizacao("A URL do instalador não pertence à Release esperada.")

    return Atualizacao(
        versao=versao,
        nome_arquivo=nome_esperado,
        url=url,
        sha256=digest.split(":", 1)[1].lower(),
        tamanho=tamanho,
        notas=str(dados.get("body") or ""),
    )


def baixar_atualizacao(
    atualizacao: Atualizacao,
    progresso: Callable[[int, int], None] | None = None,
    abrir_url: Callable[..., object] = urllib.request.urlopen,
    cancelado: Callable[[], bool] | None = None,
) -> Path:
    if (Path(atualizacao.nome_arquivo).name != atualizacao.nome_arquivo
            or not re.fullmatch(r"ChessBookDiagramExtractor-Setup-v[0-9A-Za-z.+-]+\.exe", atualizacao.nome_arquivo)):
        raise ErroAtualizacao("Nome do instalador inválido.")
    if not 0 < atualizacao.tamanho <= TAMANHO_MAXIMO:
        raise ErroAtualizacao("Tamanho do instalador inválido.")
    def verificar_cancelamento():
        if cancelado and cancelado():
            raise AtualizacaoCancelada("Download cancelado.")
    verificar_cancelamento()
    pasta = Path(tempfile.gettempdir()) / "ChessBookDiagramExtractor" / "updates"
    pasta.mkdir(parents=True, exist_ok=True)
    destino = pasta / atualizacao.nome_arquivo
    # Arquivo único evita colisões entre duas instâncias ou downloads abortados.
    descritor, temporario = tempfile.mkstemp(prefix="download-", suffix=".partial", dir=pasta)
    import os
    os.close(descritor)
    parcial = Path(temporario)
    requisicao = urllib.request.Request(
        atualizacao.url,
        headers={"User-Agent": "ChessBookDiagramExtractor-Updater"},
    )
    hash_arquivo = hashlib.sha256()
    recebido = 0
    try:
        with abrir_url(requisicao, timeout=30) as resposta, parcial.open("wb") as arquivo:  # type: ignore[attr-defined]
            while bloco := resposta.read(1024 * 1024):
                verificar_cancelamento()
                recebido += len(bloco)
                if recebido > atualizacao.tamanho:
                    raise ErroAtualizacao("O download excedeu o tamanho máximo permitido.")
                arquivo.write(bloco)
                hash_arquivo.update(bloco)
                if progresso:
                    progresso(recebido, atualizacao.tamanho)
        verificar_cancelamento()
        if recebido != atualizacao.tamanho:
            raise ErroAtualizacao("O download terminou com tamanho diferente do publicado.")
        if hash_arquivo.hexdigest().lower() != atualizacao.sha256:
            raise ErroAtualizacao("A verificação SHA-256 do instalador falhou.")
        parcial.replace(destino)
        return destino
    except Exception as erro:
        parcial.unlink(missing_ok=True)
        if isinstance(erro, ErroAtualizacao):
            raise
        raise ErroAtualizacao(f"Não foi possível baixar a atualização: {erro}") from erro


def iniciar_instalador(caminho: Path) -> None:
    if not caminho.is_file():
        raise ErroAtualizacao("O instalador baixado não foi encontrado.")
    subprocess.Popen(
        [
            str(caminho),
            "/SILENT",
            "/CLOSEAPPLICATIONS",
            "/NORESTART",
            "/NORESTARTAPPLICATIONS",
            "/REOPENAPP=1",
        ],
        close_fds=True,
    )
