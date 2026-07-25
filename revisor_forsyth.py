"""Visualizador da notação Forsyth dos diagramas extraídos."""

from __future__ import annotations

import logging
import tkinter as tk
from pathlib import Path
from typing import Callable, Sequence
from tkinter import messagebox

import cv2
import ttkbootstrap as ttk
from PIL import Image, ImageTk

from extrair_tabuleiros_pdf import AnotacaoSaida, Candidato
from notacao_forsyth import (
    ItemRevisao,
    RevisorAutomaticoLivro,
    aplicar_rascunho,
    aviso_plausibilidade,
    caminho_recurso,
    carregar_rascunho,
    normalizar_posicao,
    remover_rascunho,
    salvar_rascunho,
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
        self.indice = 0
        self._fechando = False
        self._imagem_tk: ImageTk.PhotoImage | None = None
        self._redimensionamento_pendente: str | None = None

        self.janela = ttk.Toplevel(master=raiz)
        self.variavel_excluir = tk.BooleanVar(master=self.janela, value=False)
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
        principal.columnconfigure(0, weight=3)
        principal.columnconfigure(1, weight=2)
        principal.rowconfigure(1, weight=1)

        cabecalho = ttk.Frame(principal)
        cabecalho.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 14))
        cabecalho.columnconfigure(0, weight=1)
        ttk.Label(cabecalho, text="Visualizar notações", style="HeaderTitle.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        self.rotulo_contador = ttk.Label(cabecalho, bootstyle="secondary", font=("Segoe UI", 10, "bold"))
        self.rotulo_contador.grid(row=0, column=1, sticky="e")

        self.quadro_imagem = ttk.Frame(principal, padding=12, bootstyle="@card")
        self.quadro_imagem.grid(row=1, column=0, sticky="nsew", padx=(0, 14))
        self.quadro_imagem.columnconfigure(0, weight=1)
        self.quadro_imagem.rowconfigure(0, weight=1)
        self.rotulo_imagem = ttk.Label(self.quadro_imagem, anchor="center")
        self.rotulo_imagem.grid(row=0, column=0, sticky="nsew")
        self.quadro_imagem.bind("<Configure>", self._ao_redimensionar_imagem)

        painel = ttk.Frame(principal, padding=18, bootstyle="@card")
        painel.grid(row=1, column=1, sticky="nsew")
        painel.columnconfigure(0, weight=1)
        painel.rowconfigure(6, weight=1)

        self.rotulo_origem = ttk.Label(painel, style="FieldLabel.TLabel")
        self.rotulo_origem.grid(row=0, column=0, sticky="w")
        ttk.Label(
            painel,
            text="Navegue pelas sugestões e edite uma posição somente se desejar.",
            bootstyle="secondary",
            wraplength=360,
        ).grid(row=1, column=0, sticky="w", pady=(3, 18))

        ttk.Label(painel, text="Posição das peças", style="FieldLabel.TLabel").grid(
            row=2, column=0, sticky="w"
        )
        self.campo_posicao = tk.Text(
            painel,
            width=46,
            height=4,
            wrap="char",
            font=("Consolas", 11),
            relief="solid",
            borderwidth=1,
            padx=9,
            pady=8,
            undo=True,
        )
        self.campo_posicao.grid(row=3, column=0, sticky="ew", pady=(6, 8))
        self.campo_posicao.bind("<KeyRelease>", self._validar_digitacao)

        self.rotulo_validacao = ttk.Label(painel, wraplength=360, justify="left")
        self.rotulo_validacao.grid(row=4, column=0, sticky="ew")

        self.checkbox_excluir = ttk.Checkbutton(
            painel,
            text="Não é um tabuleiro/diagrama — excluir do PDF final",
            variable=self.variavel_excluir,
            command=self._alterar_exclusao,
            bootstyle="danger",
        )
        self.checkbox_excluir.grid(row=5, column=0, sticky="w", pady=(14, 12))

        ttk.Label(
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
            wraplength=360,
            justify="left",
            bootstyle="secondary",
        ).grid(row=6, column=0, sticky="sw", pady=(18, 0))

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
        return self.campo_posicao.get("1.0", "end-1c").strip().replace("\n", "")

    def _definir_campo(self, texto: str) -> None:
        self.campo_posicao.delete("1.0", "end")
        self.campo_posicao.insert("1.0", texto)

    def _salvar_rascunho(self) -> None:
        try:
            salvar_rascunho(self.caminho_pdf, self.itens, self.pasta_dados, self.idioma)
        except OSError:
            self.logger.warning("Não foi possível salvar o rascunho Forsyth.", exc_info=True)

    def _salvar_atual(self, confirmar: bool) -> bool:
        item = self.itens[self.indice]
        texto_anterior = item.posicao
        texto = self._texto_campo()
        valido, _mensagem = validar_posicao(texto, self.idioma)
        if valido:
            texto = normalizar_posicao(texto, self.idioma)
            self._definir_campo(texto)
        item.posicao = texto
        # Campo legado mantido no rascunho; agora significa apenas que a
        # notação possui sintaxe válida, sem exigir confirmação manual.
        item.confirmada = valido
        variavel_excluir = getattr(self, "variavel_excluir", None)
        if variavel_excluir is not None:
            item.nao_e_tabuleiro = bool(variavel_excluir.get())
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
            self.revisor_automatico.revisar_itens(self.itens)
        if valido:
            item.posicao_original = texto
        self._salvar_rascunho()
        return valido

    def _alterar_exclusao(self) -> None:
        item = self.itens[self.indice]
        item.nao_e_tabuleiro = bool(self.variavel_excluir.get())
        if self.revisor_automatico is not None:
            self.revisor_automatico.definir_exclusao(self.indice, item.nao_e_tabuleiro)
        self._salvar_rascunho()
        self._validar_digitacao()

    def _navegar(self, deslocamento: int) -> None:
        self._ir_para(min(len(self.itens) - 1, max(0, self.indice + deslocamento)))

    def _ir_para(self, novo: int) -> None:
        self._salvar_atual(confirmar=True)
        novo = min(len(self.itens) - 1, max(0, novo))
        if novo != self.indice:
            self.indice = novo
            self._exibir_atual()

    def _validar_digitacao(self, _evento: object | None = None) -> None:
        if self.variavel_excluir.get():
            self.rotulo_validacao.configure(
                text="Este recorte será excluído do PDF final e da lista de notações.",
                bootstyle="danger",
            )
            return
        texto = self._texto_campo()
        valido, mensagem = validar_posicao(texto, self.idioma)
        if valido:
            aviso = aviso_plausibilidade(texto, self.idioma)
            if aviso:
                self.rotulo_validacao.configure(text=aviso, bootstyle="warning")
            else:
                self.rotulo_validacao.configure(text=mensagem, bootstyle="success")
        else:
            self.rotulo_validacao.configure(text=mensagem, bootstyle="danger")

    def _atualizar_imagem(self) -> None:
        candidato = self.candidatos[self.indice]
        item = self.itens[self.indice]
        imagem = candidato.imagem
        if imagem.ndim == 3:
            imagem = cv2.cvtColor(imagem, cv2.COLOR_BGR2RGB)
        pil = Image.fromarray(imagem)
        largura_disponivel = max(220, self.quadro_imagem.winfo_width() - 28)
        altura_disponivel = max(220, self.quadro_imagem.winfo_height() - 28)
        pil.thumbnail(
            (min(600, largura_disponivel), min(570, altura_disponivel)),
            Image.Resampling.LANCZOS,
        )
        self._imagem_tk = ImageTk.PhotoImage(pil)
        self.rotulo_imagem.configure(image=self._imagem_tk)

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
        self._definir_campo(item.posicao)
        self.variavel_excluir.set(item.nao_e_tabuleiro)
        self._atualizar_imagem()
        valido = validar_posicao(item.posicao, self.idioma)[0]
        if item.nao_e_tabuleiro:
            estado = "Este recorte será excluído do PDF final e da lista de notações."
            estilo = "danger"
        elif not valido:
            estado = "Posição vazia ou com sintaxe inválida."
            estilo = "danger"
        else:
            aviso = aviso_plausibilidade(item.posicao, self.idioma)
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

    def _concluir(self) -> None:
        self._salvar_atual(confirmar=True)
        anotacoes: list[AnotacaoSaida] = []
        for item in self.itens:
            valido = validar_posicao(item.posicao, self.idioma)[0]
            posicao = normalizar_posicao(item.posicao, self.idioma) if valido else None
            anotacoes.append(
                AnotacaoSaida(
                    posicao=posicao,
                    girado=False,
                    possivel_falso_positivo=bool(
                        posicao and aviso_plausibilidade(posicao, self.idioma)
                    ),
                    excluir=item.nao_e_tabuleiro,
                )
            )
        self._fechando = True
        self._cancelar_redimensionamento()
        self.janela.grab_release()
        self.janela.destroy()
        self.ao_finalizar(anotacoes)

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
        self._fechando = True
        self._cancelar_redimensionamento()
        self.janela.grab_release()
        self.janela.destroy()
        self.ao_cancelar()
