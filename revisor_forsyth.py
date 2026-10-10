"""Visualizador da notação Forsyth dos diagramas extraídos."""

from __future__ import annotations

import logging
import tkinter as tk
from pathlib import Path
from typing import Callable, Sequence
from tkinter import filedialog, messagebox, simpledialog

import cv2
import ttkbootstrap as ttk
from PIL import Image, ImageTk

from extrair_tabuleiros_pdf import AnotacaoSaida, Candidato
from biblioteca_livros import DiagramaSalvo, exportar_pgn
from exportacao_padronizada_ui import exportar_livro_padronizado
from visualizacao_diagramas import ComparadorDiagramas
from reconhecimento_ui import reavaliar_imagem
from revisao_assincrona import RevisaoAssincrona
from notacao_forsyth import (
    ItemRevisao,
    RevisorAutomaticoLivro,
    aplicar_rascunho,
    aviso_plausibilidade,
    caminho_recurso,
    carregar_rascunho,
    formatar_posicao_lado,
    normalizar_posicao,
    remover_rascunho,
    salvar_rascunho,
    separar_posicao_lado,
    validar_posicao,
)


LARGURA_REVISOR = 1280
ALTURA_REVISOR = 720


class JanelaRevisaoForsyth:
    def __init__(
        self,
        raiz: tk.Misc,
        candidatos: Sequence[Candidato],
        itens: Sequence[ItemRevisao],
        caminho_pdf: str,
        pasta_dados: Path,
        idioma: str,
        revisor_automatico: RevisorAutomaticoLivro | None,
        ao_finalizar: Callable[[list[AnotacaoSaida]], None],
        ao_cancelar: Callable[[], None],
        logger: logging.Logger,
        annotator: str = "",
        titulo_livro: str = "Livro de xadrez",
        ao_salvar_annotator: Callable[[str], None] | None = None,
        modo_biblioteca: bool = False,
        ao_salvar_revisao: Callable[[list[ItemRevisao]], None] | None = None,
    ) -> None:
        if not candidatos or len(candidatos) != len(itens):
            raise ValueError("A revisão exige um estado para cada diagrama.")
        self.raiz = raiz
        self.candidatos = list(candidatos)
        self.itens = list(itens)
        self.caminho_pdf = caminho_pdf
        self.pasta_dados = pasta_dados
        self.idioma = idioma
        self.revisor_automatico = revisor_automatico
        self.ao_finalizar = ao_finalizar
        self.ao_cancelar = ao_cancelar
        self.logger = logger
        self.annotator = annotator
        self.titulo_livro = titulo_livro
        self.ao_salvar_annotator = ao_salvar_annotator
        self.modo_biblioteca = modo_biblioteca
        self.ao_salvar_revisao = ao_salvar_revisao
        self.indice = 0
        self._fechando = False
        self._imagem_tk: ImageTk.PhotoImage | None = None
        self._redimensionamento_pendente: str | None = None

        self.janela = ttk.Toplevel(master=raiz)
        self.variavel_excluir = tk.BooleanVar(master=self.janela, value=False)
        self.variavel_lado = tk.StringVar(master=self.janela, value="w")
        self.variavel_annotator = tk.StringVar(master=self.janela, value=annotator)
        self.janela.title("Visualizar notações Forsyth")
        largura_inicial = min(LARGURA_REVISOR, max(900, self.janela.winfo_screenwidth() - 80))
        altura_inicial = min(ALTURA_REVISOR, max(620, self.janela.winfo_screenheight() - 100))
        self.janela.geometry(f"{largura_inicial}x{altura_inicial}")
        self.janela.minsize(min(1000, largura_inicial), min(640, altura_inicial))
        self.janela.transient(raiz)
        self.janela.grab_set()
        self.janela.protocol("WM_DELETE_WINDOW", self._fechar)
        self.janela.bind("<Escape>", lambda _evento: self._fechar())

        icone = caminho_recurso("icon", "chess-book-diagram-extractor.ico")
        if icone.is_file():
            try:
                self.janela.iconbitmap(str(icone))
            except tk.TclError:
                pass

        self._montar()
        self._revisao_assincrona = RevisaoAssincrona(
            self.janela, self.comparador.indicar_trabalho,
            self._aplicar_revisao_assincrona, self._erro_revisao_assincrona)
        self._restaurar_rascunho()
        self._exibir_atual()
        self.janela.after_idle(self._centralizar)

    def _centralizar(self) -> None:
        self.janela.update_idletasks()
        largura = self.janela.winfo_width()
        altura = self.janela.winfo_height()
        x = max(0, self.raiz.winfo_rootx() + (self.raiz.winfo_width() - largura) // 2)
        y = max(0, self.raiz.winfo_rooty() + (self.raiz.winfo_height() - altura) // 2)
        self.janela.geometry(f"{largura}x{altura}+{x}+{y}")

    def _montar(self) -> None:
        principal = ttk.Frame(self.janela, padding=20)
        principal.pack(fill="both", expand=True)
        principal.columnconfigure(0, weight=4)
        principal.columnconfigure(1, weight=1, minsize=280)
        principal.rowconfigure(1, weight=1)

        cabecalho = ttk.Frame(principal)
        cabecalho.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 14))
        cabecalho.columnconfigure(0, weight=1)
        ttk.Label(cabecalho, text="Visualizar notações", style="HeaderTitle.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        self.rotulo_contador = ttk.Label(cabecalho, bootstyle="secondary", font=("Segoe UI", 11, "bold"))
        self.rotulo_contador.grid(row=0, column=1, sticky="e")

        self.quadro_imagem = ttk.Frame(principal, padding=12, bootstyle="@card")
        self.quadro_imagem.grid(row=1, column=0, sticky="nsew", padx=(0, 14))
        self.quadro_imagem.columnconfigure(0, weight=1)
        self.quadro_imagem.rowconfigure(1, weight=1)
        self.modo_imagem = tk.StringVar(master=self.janela, value="comparar")
        modos_imagem = ttk.Frame(self.quadro_imagem)
        modos_imagem.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        for valor, texto in (("comparar", "Lado a lado"), ("original", "Original"), ("padronizado", "Padronizado")):
            ttk.Radiobutton(modos_imagem, text=texto, value=valor,
                variable=self.modo_imagem, command=self._atualizar_imagem,
                bootstyle="primary toolbutton", padding=(10, 6)).pack(side="left", padx=(0, 6))
        self.comparador = ComparadorDiagramas(self.quadro_imagem, ao_editar=self._editar_pelo_tabuleiro)
        self.comparador.grid(row=1, column=0, sticky="nsew")
        self.rotulo_imagem = self.comparador.rotulos["original"]
        self.quadro_imagem.bind("<Configure>", self._ao_redimensionar_imagem)

        painel = ttk.Frame(principal, padding=18, bootstyle="@card")
        painel.grid(row=1, column=1, sticky="nsew")
        painel.columnconfigure(0, weight=1)
        painel.rowconfigure(10, weight=1)

        self.rotulo_origem = ttk.Label(painel, style="FieldLabel.TLabel")
        self.rotulo_origem.grid(row=0, column=0, sticky="w")
        ttk.Label(
            painel,
            text=(
                "Clique em uma casa do tabuleiro reconstruído para trocar a peça "
                "ou deixá-la vazia. A Forsyth abaixo acompanha as alterações."
            ),
            bootstyle="secondary",
            wraplength=270,
        ).grid(row=1, column=0, sticky="w", pady=(3, 18))

        linha_forsyth = ttk.Frame(self.quadro_imagem)
        linha_forsyth.grid(row=2, column=0, sticky="ew", pady=(10, 4))
        ttk.Label(linha_forsyth, text="Forsyth completa", style="FieldLabel.TLabel").pack(side="left")
        ttk.Button(linha_forsyth, text="Copiar", command=self._copiar_posicao,
                   bootstyle="secondary link").pack(side="right")
        self.campo_posicao = tk.Text(self.quadro_imagem, width=1, height=2,
            wrap="char", font=("Consolas", 11), relief="solid", borderwidth=1,
            padx=9, pady=8, undo=True)
        self.campo_posicao.grid(row=3, column=0, sticky="ew")
        self.campo_posicao.bind("<KeyRelease>", self._validar_digitacao)

        self.rotulo_validacao = ttk.Label(painel, wraplength=270, justify="left")
        self.rotulo_validacao.grid(row=4, column=0, sticky="ew")

        self.rotulo_lado = ttk.Label(painel, text="Lado a jogar", style="FieldLabel.TLabel")
        self.rotulo_lado.grid(
            row=5, column=0, sticky="w", pady=(14, 4)
        )
        self.quadro_lados = ttk.Frame(painel)
        self.quadro_lados.grid(row=6, column=0, sticky="w")
        self.botao_white = ttk.Radiobutton(self.quadro_lados, text="Brancas",
            variable=self.variavel_lado, value="w", command=lambda: self._alterar_lado("w"),
            bootstyle="primary toolbutton", padding=(14, 8))
        self.botao_white.pack(side="left")
        self.botao_black = ttk.Radiobutton(self.quadro_lados, text="Pretas",
            variable=self.variavel_lado, value="b", command=lambda: self._alterar_lado("b"),
            bootstyle="primary toolbutton", padding=(14, 8))
        self.botao_black.pack(side="left", padx=(6, 0))

        self.rotulo_annotator = ttk.Label(
            painel, text="Responsável pelas anotações", style="FieldLabel.TLabel"
        )
        self.rotulo_annotator.grid(
            row=7, column=0, sticky="w", pady=(14, 4)
        )
        self.campo_annotator = ttk.Entry(painel, textvariable=self.variavel_annotator)
        self.campo_annotator.grid(row=8, column=0, sticky="ew")

        self.checkbox_excluir = ttk.Checkbutton(
            painel,
            text="Descartar este recorte",
            variable=self.variavel_excluir,
            command=self._alterar_exclusao,
            bootstyle="danger",
        )
        self.checkbox_excluir.grid(row=9, column=0, sticky="w", pady=(14, 12))

        self.rotulo_ajuda = ttk.Label(
            painel,
            text=(
                (
                    "Use R/D/T/B/C/P"
                    if self.idioma == "pt"
                    else "Use K/Q/R/B/N/P"
                )
                + " para as peças brancas e letras minúsculas para as pretas. "
                "Leia cada linha da esquerda para a direita, de cima para baixo."
            ),
            wraplength=270,
            justify="left",
            bootstyle="secondary",
        )
        self.rotulo_ajuda.grid(row=10, column=0, sticky="sw", pady=(18, 0))
        ttk.Button(painel, text="Reavaliar imagem", command=self._reavaliar_imagem,
                   bootstyle="secondary outline").grid(row=11, column=0, sticky="ew", pady=(12, 0))
        ttk.Button(painel, text="Confirmar diagrama conferido", command=self._confirmar_diagrama,
                   bootstyle="success outline").grid(row=12, column=0, sticky="ew", pady=(8, 0))

        navegacao = ttk.Frame(principal)
        navegacao.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(16, 0))
        navegacao.columnconfigure(0, weight=1)
        grupo_navegacao = ttk.Frame(navegacao)
        grupo_navegacao.grid(row=0, column=0, sticky="w")
        self.botao_primeiro = ttk.Button(
            grupo_navegacao,
            text="|← Primeiro",
            command=lambda: self._ir_para(0),
            bootstyle="secondary outline",
        )
        self.botao_primeiro.pack(side="left", padx=(0, 8))
        self.botao_anterior = ttk.Button(
            grupo_navegacao,
            text="← Anterior",
            command=lambda: self._navegar(-1),
            bootstyle="secondary outline",
        )
        self.botao_anterior.pack(side="left", padx=(0, 8))
        self.botao_proximo = ttk.Button(
            grupo_navegacao,
            text="Próximo →",
            command=lambda: self._navegar(1),
            bootstyle="secondary outline",
        )
        self.botao_proximo.pack(side="left", padx=(0, 8))
        self.botao_ultimo = ttk.Button(
            grupo_navegacao,
            text="Último →|",
            command=lambda: self._ir_para(len(self.itens) - 1),
            bootstyle="secondary outline",
        )
        self.botao_ultimo.pack(side="left")
        self.botao_finalizar = ttk.Button(
            navegacao,
            text="Salvar notações no PDF",
            command=self._concluir,
            bootstyle="primary",
        )
        self.botao_finalizar.grid(row=0, column=1, sticky="e", padx=(18, 0))
        self.botao_exportar_pgn = ttk.Button(
            navegacao,
            text="Exportar PGN",
            command=self._exportar_pgn,
            bootstyle="success outline",
        )
        self.botao_exportar_pgn.grid(row=0, column=2, sticky="e", padx=(8, 0))
        ttk.Button(navegacao, text="Exportar livro padronizado",
            command=self._exportar_pdf_padronizado, bootstyle="primary outline"
        ).grid(row=1, column=0, columnspan=3, sticky="e", pady=(10, 0))

    def _editar_pelo_tabuleiro(self, texto: str) -> None:
        self._definir_campo(texto)
        self.itens[self.indice].editada_manualmente = True
        self._salvar_atual(confirmar=False)
        self._validar_digitacao()
        self._atualizar_imagem()

    def _confirmar_diagrama(self) -> None:
        if self._salvar_atual(confirmar=True):
            item = self.itens[self.indice]
            item.editada_manualmente = True
            item.revisao_necessaria = False
            self._salvar_rascunho()
            self._validar_digitacao()

    def _aplicar_revisao_assincrona(self, anteriores, revisados) -> None:
        atual = self.itens[self.indice]
        campo = separar_posicao_lado(self._texto_campo(), atual.lado_a_jogar)[0]
        mudou_atual = False
        for indice, (item, anterior, revisado) in enumerate(zip(self.itens, anteriores, revisados)):
            if item.editada_manualmente or item.nao_e_tabuleiro or item.posicao != anterior:
                continue
            # Digitação ainda não salva também precisa ser preservada.
            if indice == self.indice and campo != anterior:
                continue
            for atributo in ("posicao", "aviso", "alteracoes_automaticas", "duvidas_automaticas", "confiavel", "revisao_necessaria"):
                setattr(item, atributo, getattr(revisado, atributo))
            mudou_atual |= indice == self.indice
        self._salvar_rascunho()
        if mudou_atual:
            self._exibir_atual()

    def _erro_revisao_assincrona(self, erro) -> None:
        self.logger.error("Falha ao revisar o livro em segundo plano: %s", erro,
                          exc_info=(type(erro), erro, erro.__traceback__))
        self.rotulo_validacao.configure(text="Correção salva. Não foi possível atualizar o reconhecimento do livro.",
                                        bootstyle="warning")

    def _aguardar_revisao(self, callback) -> bool:
        tarefa = getattr(self, "_revisao_assincrona", None)
        return tarefa is None or tarefa.quando_pronto(callback)

    def _reavaliar_imagem(self) -> None:
        self._salvar_atual(confirmar=False)
        indice = self.indice
        anterior = self.itens[indice]
        def aplicar(resultado):
            novo = ItemRevisao.de_reconhecimento(resultado)
            novo.lado_a_jogar, novo.nao_e_tabuleiro = anterior.lado_a_jogar, anterior.nao_e_tabuleiro
            self.itens[indice] = novo
            if self.revisor_automatico is not None:
                self.revisor_automatico.substituir_resultado(indice, resultado)
                self._revisao_assincrona.agendar(self.revisor_automatico, self.itens)
            self._salvar_rascunho()
            self._exibir_atual()
        reavaliar_imagem(self.janela, self.candidatos[indice].imagem, self.idioma, aplicar)

    def _copiar_posicao(self) -> None:
        self.janela.clipboard_clear()
        self.janela.clipboard_append(self._texto_campo())

    def _exportar_pdf_padronizado(self) -> None:
        self._salvar_atual(confirmar=False)
        if not self._aguardar_revisao(self._exportar_pdf_padronizado):
            return
        exportar_livro_padronizado(self.janela, self.caminho_pdf, self.candidatos,
                                  self.itens, self.idioma, self.titulo_livro)

    def _restaurar_rascunho(self) -> None:
        dados = carregar_rascunho(
            self.caminho_pdf,
            len(self.itens),
            self.pasta_dados,
            self.idioma,
        )
        if dados is None:
            return
        retomar = messagebox.askyesno(
            "Retomar visualização",
            "Foi encontrado um rascunho deste PDF. Deseja continuar de onde parou?",
            parent=self.janela,
        )
        if retomar:
            aplicar_rascunho(self.itens, dados)
        else:
            remover_rascunho(self.caminho_pdf, self.pasta_dados)

    def _texto_campo(self) -> str:
        return " ".join(self.campo_posicao.get("1.0", "end-1c").split())

    def _definir_campo(self, texto: str) -> None:
        self.campo_posicao.delete("1.0", "end")
        self.campo_posicao.insert("1.0", texto)

    def _salvar_rascunho(self) -> None:
        try:
            salvar_rascunho(self.caminho_pdf, self.itens, self.pasta_dados, self.idioma)
            callback = getattr(self, "ao_salvar_revisao", None)
            if callback is not None:
                callback(self.itens)
        except OSError:
            self.logger.warning("Não foi possível salvar o rascunho Forsyth.", exc_info=True)

    def _salvar_atual(self, confirmar: bool) -> bool:
        item = self.itens[self.indice]
        texto_anterior = item.posicao
        variavel_lado = getattr(self, "variavel_lado", None)
        lado_atual = variavel_lado.get() if variavel_lado is not None else item.lado_a_jogar
        texto, lado = separar_posicao_lado(self._texto_campo(), lado_atual)
        if variavel_lado is not None:
            variavel_lado.set(lado)
        valido, _mensagem = validar_posicao(texto, self.idioma)
        if valido:
            texto = normalizar_posicao(texto, self.idioma)
            self._definir_campo(formatar_posicao_lado(texto, lado))
        item.posicao = texto
        # Campo legado mantido no rascunho; agora significa apenas que a
        # notação possui sintaxe válida, sem exigir confirmação manual.
        item.confirmada = valido
        variavel_excluir = getattr(self, "variavel_excluir", None)
        if variavel_excluir is not None:
            item.nao_e_tabuleiro = bool(variavel_excluir.get())
        item.lado_a_jogar = lado
        if variavel_lado is not None:
            self._atualizar_badges_lado()
        if (
            valido
            and texto != texto_anterior
            and getattr(self, "revisor_automatico", None) is not None
            and item.casas
        ):
            item.editada_manualmente = True
            self.revisor_automatico.registrar_edicao(
                self.indice,
                item,
                texto_anterior,
                texto,
            )
            self._revisao_assincrona.agendar(self.revisor_automatico, self.itens)
        if valido:
            if texto != texto_anterior:
                item.editada_manualmente = True
            item.posicao_original = texto
        self._salvar_rascunho()
        return valido

    def _alterar_exclusao(self) -> None:
        item = self.itens[self.indice]
        item.nao_e_tabuleiro = bool(self.variavel_excluir.get())
        if self.revisor_automatico is not None:
            self.revisor_automatico.definir_exclusao(self.indice, item.nao_e_tabuleiro)
            self._revisao_assincrona.agendar(self.revisor_automatico, self.itens)
        self._salvar_rascunho()
        self._validar_digitacao()

    def _atualizar_badges_lado(self) -> None:
        # Os Radiobuttons acompanham a variável sem mudar bordas ou dimensões.
        if hasattr(self, "botao_white"):
            self.botao_white.configure(bootstyle="primary toolbutton")
            self.botao_black.configure(bootstyle="primary toolbutton")

    def _alterar_lado(self, lado: str | None = None) -> None:
        lado = lado if lado in ("w", "b") else self.variavel_lado.get()
        lado = lado if lado in ("w", "b") else "w"
        self.variavel_lado.set(lado)
        item = self.itens[self.indice]
        posicao = item.posicao
        if hasattr(self, "campo_posicao"):
            posicao, _lado_anterior = separar_posicao_lado(
                self._texto_campo(), item.lado_a_jogar
            )
        item.lado_a_jogar = lado
        if hasattr(self, "campo_posicao"):
            self._definir_campo(formatar_posicao_lado(posicao, lado))
        self._atualizar_badges_lado()
        self._salvar_rascunho()

    def _navegar(self, deslocamento: int) -> None:
        self._ir_para(min(len(self.itens) - 1, max(0, self.indice + deslocamento)))

    def _ir_para(self, novo: int) -> None:
        self._salvar_atual(confirmar=True)
        novo = min(len(self.itens) - 1, max(0, novo))
        if novo != self.indice:
            self.indice = novo
            self._exibir_atual()

    @staticmethod
    def _aviso_ensemble(item: ItemRevisao) -> str:
        if item.editada_manualmente:
            return ""
        if item.ajustes_reis:
            return "Reis ajustados pela confiança. Confira: " + ", ".join(item.ajustes_reis) + "."
        divergentes = [c.coordenada for c in item.casas if c.divergencia_modelos and not c.marcador_vazio]
        if not divergentes:
            return ""
        lista = ", ".join(divergentes[:8])
        restante = f" e mais {len(divergentes) - 8}" if len(divergentes) > 8 else ""
        return f"Confira {len(divergentes)} casa(s) com reconhecimento incerto: {lista}{restante}."

    def _validar_digitacao(self, _evento: object | None = None) -> None:
        if hasattr(self, "modo_imagem") and self.modo_imagem.get() in ("comparar", "padronizado"):
            self._ao_redimensionar_imagem()
        if self.variavel_excluir.get():
            self.rotulo_validacao.configure(
                text="Este recorte será excluído do PDF final e da lista de notações.",
                bootstyle="danger",
            )
            return
        texto, lado = separar_posicao_lado(
            self._texto_campo(), self.itens[self.indice].lado_a_jogar
        )
        if lado != self.variavel_lado.get():
            self.variavel_lado.set(lado)
            self._atualizar_badges_lado()
        valido, mensagem = validar_posicao(texto, self.idioma)
        if valido:
            aviso = aviso_plausibilidade(texto, self.idioma) or self._aviso_ensemble(self.itens[self.indice])
            item = self.itens[self.indice]
            if item.revisao_necessaria and not item.editada_manualmente:
                aviso = aviso or "Reconhecimento incerto. Confira as peças e confirme ou corrija o diagrama."
            if aviso:
                self.rotulo_validacao.configure(text=aviso, bootstyle="warning")
            else:
                self.rotulo_validacao.configure(text=mensagem, bootstyle="success")
        else:
            self.rotulo_validacao.configure(text=mensagem, bootstyle="danger")

    def _atualizar_imagem(self) -> None:
        self.comparador.exibir(self.candidatos[self.indice].imagem, self._texto_campo(),
                              self.idioma, self.modo_imagem.get())

    def _ao_redimensionar_imagem(self, _evento: object | None = None) -> None:
        if self._redimensionamento_pendente is not None:
            self.janela.after_cancel(self._redimensionamento_pendente)
        self._redimensionamento_pendente = self.janela.after(80, self._aplicar_redimensionamento)

    def _aplicar_redimensionamento(self) -> None:
        self._redimensionamento_pendente = None
        self._atualizar_imagem()

    def _cancelar_redimensionamento(self) -> None:
        if self._redimensionamento_pendente is not None:
            self.janela.after_cancel(self._redimensionamento_pendente)
            self._redimensionamento_pendente = None

    def _exibir_atual(self) -> None:
        candidato = self.candidatos[self.indice]
        item = self.itens[self.indice]
        self.rotulo_contador.configure(text=f"Diagrama {self.indice + 1} de {len(self.itens)}")
        self.rotulo_origem.configure(text=f"Página original: {candidato.pagina}")
        self._definir_campo(formatar_posicao_lado(item.posicao, item.lado_a_jogar))
        self.variavel_excluir.set(item.nao_e_tabuleiro)
        self.variavel_lado.set(item.lado_a_jogar if item.lado_a_jogar in ("w", "b") else "w")
        self._atualizar_badges_lado()
        self._atualizar_imagem()
        if item.nao_e_tabuleiro:
            estado = "Este recorte será excluído do PDF final e da lista de notações."
            estilo = "danger"
        elif not validar_posicao(item.posicao, self.idioma)[0]:
            estado = item.aviso or "Posição vazia ou com sintaxe inválida."
            estilo = "warning" if item.aviso else "danger"
        else:
            aviso = aviso_plausibilidade(item.posicao, self.idioma) or self._aviso_ensemble(item)
            estado = aviso
            estilo = "warning" if aviso else "secondary"
        self.rotulo_validacao.configure(text=estado, bootstyle=estilo)
        self.botao_primeiro.configure(state="normal" if self.indice > 0 else "disabled")
        self.botao_anterior.configure(state="normal" if self.indice > 0 else "disabled")
        self.botao_proximo.configure(state="normal" if self.indice < len(self.itens) - 1 else "disabled")
        self.botao_ultimo.configure(
            state="normal" if self.indice < len(self.itens) - 1 else "disabled"
        )
        self.campo_posicao.focus_set()
        self._validar_digitacao()

    def _concluir(self) -> None:
        self._salvar_atual(confirmar=True)
        if not self._aguardar_revisao(self._concluir):
            return
        if getattr(self, "modo_biblioteca", False):
            for indice, item in enumerate(self.itens):
                if item.nao_e_tabuleiro:
                    continue
                valido, mensagem = validar_posicao(item.posicao, self.idioma)
                if not valido:
                    self.indice = indice
                    self._exibir_atual()
                    messagebox.showwarning(
                        "Posição inválida",
                        f"Revise o diagrama {indice + 1}: {mensagem}",
                        parent=self.janela,
                    )
                    return
        anotacoes: list[AnotacaoSaida] = []
        for item in self.itens:
            valido = validar_posicao(item.posicao, self.idioma)[0]
            posicao_bruta = item.posicao.strip() or None
            posicao = (
                normalizar_posicao(item.posicao, self.idioma)
                if valido
                else posicao_bruta
            )
            anotacoes.append(
                AnotacaoSaida(
                    posicao=posicao,
                    girado=False,
                    possivel_falso_positivo=bool(
                        item.aviso
                        or (valido and posicao and aviso_plausibilidade(posicao, self.idioma))
                    ),
                    excluir=item.nao_e_tabuleiro,
                    lado_a_jogar=item.lado_a_jogar,
                )
            )
        variavel_annotator = getattr(self, "variavel_annotator", None)
        annotator = variavel_annotator.get().strip() if variavel_annotator is not None else ""
        ao_salvar_annotator = getattr(self, "ao_salvar_annotator", None)
        if ao_salvar_annotator is not None:
            ao_salvar_annotator(annotator)
        self._fechando = True
        if hasattr(self, "_revisao_assincrona"):
            self._revisao_assincrona.fechar()
        self._cancelar_redimensionamento()
        self.janela.grab_release()
        self.janela.destroy()
        self.ao_finalizar(anotacoes)

    def _diagramas_para_pgn(self) -> list[DiagramaSalvo]:
        diagramas: list[DiagramaSalvo] = []
        for candidato, item in zip(self.candidatos, self.itens):
            if item.nao_e_tabuleiro:
                continue
            valido = validar_posicao(item.posicao, self.idioma)[0]
            if not valido:
                continue
            diagramas.append(
                DiagramaSalvo(
                    pagina=candidato.pagina,
                    confianca=candidato.confianca,
                    posicao=normalizar_posicao(item.posicao, self.idioma),
                    lado_a_jogar=item.lado_a_jogar,
                )
            )
        return diagramas

    def _exportar_pgn(self) -> None:
        self._salvar_atual(confirmar=True)
        if not self._aguardar_revisao(self._exportar_pgn):
            return
        diagramas = self._diagramas_para_pgn()
        if not diagramas:
            messagebox.showwarning(
                "Nenhuma posicao valida",
                "Informe ao menos uma posicao valida antes de exportar.",
                parent=self.janela,
            )
            return
        annotator = simpledialog.askstring(
            "Exportar PGN",
            "Nome do Annotator:",
            initialvalue=self.variavel_annotator.get().strip(),
            parent=self.janela,
        )
        if annotator is None:
            return
        annotator = annotator.strip()
        self.variavel_annotator.set(annotator)
        destino = filedialog.asksaveasfilename(
            title="Salvar arquivo PGN",
            initialfile=(
                "".join(
                    "_" if caractere in '<>:"/\\|?*' else caractere
                    for caractere in self.titulo_livro
                ).strip(" .")
                or "posicoes"
            )
            + ".pgn",
            defaultextension=".pgn",
            filetypes=[("Arquivos PGN", "*.pgn")],
            parent=self.janela,
        )
        if not destino:
            return
        if Path(destino).suffix.lower() == ".pdf":
            messagebox.showerror(
                "Destino inválido",
                "Escolha um arquivo com extensão .pgn. O PDF não será sobrescrito.",
                parent=self.janela,
            )
            return
        try:
            exportar_pgn(destino, self.titulo_livro, diagramas, annotator, self.idioma)
            if self.ao_salvar_annotator is not None:
                self.ao_salvar_annotator(annotator)
            messagebox.showinfo(
                "PGN exportado",
                (
                    f"{len(diagramas)} posição(ões) exportada(s) com sucesso."
                    + (
                        f"\n{sum(not validar_posicao(item.posicao, self.idioma)[0] for item in self.itens if not item.nao_e_tabuleiro)} posição(ões) inválida(s) foram omitidas."
                        if any(
                            not validar_posicao(item.posicao, self.idioma)[0]
                            for item in self.itens
                            if not item.nao_e_tabuleiro
                        )
                        else ""
                    )
                ),
                parent=self.janela,
            )
        except (OSError, ValueError) as erro:
            self.logger.exception("Falha ao exportar o PGN.")
            messagebox.showerror("Nao foi possivel exportar o PGN", str(erro), parent=self.janela)

    def _fechar(self) -> None:
        if self._fechando:
            return
        if not messagebox.askyesno(
            "Fechar visualização",
            "O rascunho será salvo para continuar depois. Deseja fechar a visualização?",
            parent=self.janela,
        ):
            return
        self._salvar_atual(confirmar=False)
        ao_salvar_annotator = getattr(self, "ao_salvar_annotator", None)
        if ao_salvar_annotator is not None:
            variavel_annotator = getattr(self, "variavel_annotator", None)
            ao_salvar_annotator(
                variavel_annotator.get().strip() if variavel_annotator is not None else ""
            )
        self._fechando = True
        if hasattr(self, "_revisao_assincrona"):
            self._revisao_assincrona.fechar()
        self._cancelar_redimensionamento()
        self.janela.grab_release()
        self.janela.destroy()
        self.ao_cancelar()
