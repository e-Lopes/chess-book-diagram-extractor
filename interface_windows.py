"""Interface Windows do Chess Book Diagram Extractor."""

from __future__ import annotations

import os
import json
import logging
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
import unicodedata
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog

import cv2
import fitz
import ttkbootstrap as ttk
from PIL import Image, ImageTk
from ttkbootstrap.style import ThemeDefinition
from ttkbootstrap.widgets import ToolTip

from autoupdate import Atualizacao, baixar_atualizacao, consultar_atualizacao, iniciar_instalador
from biblioteca_livros import (
    BibliotecaLivros,
    DiagramaSalvo,
    LivroDuplicadoError,
    LivroSalvo,
    diagramas_de_anotacoes,
    exportar_pgn,
)
from extrair_tabuleiros_pdf import (
    AnotacaoSaida,
    Candidato,
    ErroExtracao,
    ExtracaoCancelada,
    ResultadoExtracao,
    carregar_diagramas_do_pdf_extraido,
    criar_pdf_a4,
    detectar_no_pdf,
)
from notacao_forsyth import (
    ItemRevisao,
    ReconhecedorForsyth,
    RevisorAutomaticoLivro,
    ResultadoReconhecimento,
    aviso_plausibilidade,
    caminho_rascunho,
    normalizar_posicao,
    validar_posicao,
)
from revisor_forsyth import JanelaRevisaoForsyth
from version import GITHUB_REPOSITORY, __version__


TEMA = "chesswindows"
LARGURA_JANELA = 1440
ALTURA_JANELA = 860
LARGURA_LATERAL = 430
LIVROS_POR_PAGINA = 15
REPOSITORIO_PUBLICO = GITHUB_REPOSITORY or "e-Lopes/chess-book-diagram-extractor"
URL_GITHUB = f"https://github.com/{REPOSITORIO_PUBLICO}"


def pasta_dados_aplicativo() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    return base / "ChessBookDiagramExtractor"


def carregar_preferencia_abrir_pdf() -> bool:
    try:
        dados = json.loads((pasta_dados_aplicativo() / "settings.json").read_text(encoding="utf-8"))
        return bool(dados.get("abrir_pdf_ao_concluir", True))
    except (OSError, ValueError, TypeError):
        return True


def carregar_preferencia_incluir_forsyth() -> bool:
    try:
        dados = json.loads((pasta_dados_aplicativo() / "settings.json").read_text(encoding="utf-8"))
        return bool(dados.get("incluir_notacao_forsyth", True))
    except (OSError, ValueError, TypeError):
        return True


def carregar_preferencia_idioma_notacao() -> str:
    try:
        dados = json.loads((pasta_dados_aplicativo() / "settings.json").read_text(encoding="utf-8"))
        idioma = dados.get("idioma_notacao", "pt")
        return idioma if idioma in ("pt", "en") else "pt"
    except (OSError, ValueError, TypeError):
        return "pt"


def configurar_logger() -> logging.Logger:
    logger = logging.getLogger("ChessBookDiagramExtractor")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    try:
        pasta = pasta_dados_aplicativo()
        pasta.mkdir(parents=True, exist_ok=True)
        handler: logging.Handler = logging.FileHandler(pasta / "app.log", encoding="utf-8")
    except OSError:
        handler = logging.NullHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    return logger


def caminho_recurso(*partes: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base.joinpath(*partes)


def sugerir_saida(caminho_entrada: str) -> str:
    if not caminho_entrada:
        return ""
    entrada = Path(caminho_entrada)
    return str(entrada.with_name(f"{entrada.stem}_diagramas.pdf"))


def localizar_desinstalador() -> Path | None:
    if not getattr(sys, "frozen", False):
        return None
    caminho = Path(sys.executable).resolve().parent / "unins000.exe"
    return caminho if caminho.is_file() else None


class InterfaceExtrator:
    def __init__(self, raiz: ttk.Window) -> None:
        self.raiz = raiz
        self.raiz.title("Chess Book Diagram Extractor")
        self.raiz.geometry(f"{LARGURA_JANELA}x{ALTURA_JANELA}")
        self.raiz.minsize(1180, 720)
        self.raiz.resizable(True, True)
        self.raiz.option_add("*Font", ("Segoe UI", 10))

        caminho_ico = caminho_recurso("icon", "chess-book-diagram-extractor.ico")
        caminho_png = caminho_recurso("icon", "chess-book-diagram-extractor.png")
        icone_configurado = False
        if sys.platform == "win32" and caminho_ico.is_file():
            try:
                self.raiz.iconbitmap(str(caminho_ico))
                icone_configurado = True
            except tk.TclError:
                pass
        if not icone_configurado and caminho_png.is_file():
            self._icone_janela = tk.PhotoImage(file=caminho_png)
            self.raiz.iconphoto(True, self._icone_janela)

        self.entrada = tk.StringVar()
        self.saida = tk.StringVar()
        self.entrada_exibida = tk.StringVar(value="Nenhum arquivo selecionado")
        self.saida_exibida = tk.StringVar(value="Definido após selecionar um PDF")
        self.entrada_info = tk.StringVar(value="O livro original nunca será alterado.")
        self.abrir_ao_concluir = tk.BooleanVar(value=carregar_preferencia_abrir_pdf())
        self.incluir_forsyth = tk.BooleanVar(value=carregar_preferencia_incluir_forsyth())
        self.idioma_notacao = tk.StringVar(value=carregar_preferencia_idioma_notacao())
        self.status = tk.StringVar(value="Selecione um arquivo PDF para começar.")
        self.texto_percentual = tk.StringVar(value="0%")
        self.estatistica_paginas = tk.StringVar(value="—")
        self.estatistica_diagramas = tk.StringVar(value="0")
        self.estatistica_atencao = tk.StringVar(value="0")
        self.estatistica_excluidos = tk.StringVar(value="0")
        self.estado_barra = tk.StringVar(value="Pronto")
        self.busca_biblioteca = tk.StringVar()
        self.texto_paginacao_biblioteca = tk.StringVar()
        self.pagina_biblioteca = 0
        self.inicio_progresso: float | None = None
        # Mantida para compatibilidade com o fluxo existente, mas não é exibida.
        self.detalhes = tk.StringVar(value="Nenhum processamento em andamento.")
        self.eventos: queue.Queue[tuple[str, object]] = queue.Queue()
        self.cancelamento = threading.Event()
        self.processando = False
        self.revisando = False
        self.atualizando = False
        self.verificacao_silenciosa = False
        self.ultimo_resultado: ResultadoExtracao | None = None
        self.atualizacao_pendente: Atualizacao | None = None
        self.janela_sobre: ttk.Toplevel | None = None
        self.janela_ajuda: ttk.Toplevel | None = None
        self.janela_revisao: JanelaRevisaoForsyth | None = None
        self.ultimo_diretorio = Path.cwd()
        self.logger = configurar_logger()
        self.biblioteca = BibliotecaLivros(pasta_dados_aplicativo())
        self.livro_em_edicao = None
        self.candidatos_biblioteca: list[Candidato] = []
        self.itens_biblioteca: list[ItemRevisao] = []
        self.indice_biblioteca = 0
        self._imagem_biblioteca_tk: ImageTk.PhotoImage | None = None
        self._redimensionamento_biblioteca_pendente: str | None = None
        self._salvamento_biblioteca_pendente: str | None = None
        self._sincronizando_fen_biblioteca = False
        self.carregando_livro = False

        self._configurar_estilo()
        self._montar_tela()
        self.entrada.trace_add("write", self._ao_alterar_entrada)
        self.busca_biblioteca.trace_add("write", self._ao_filtrar_biblioteca)
        self.raiz.bind("<Return>", self._ao_pressionar_enter)
        self.raiz.after_idle(self._centralizar_janela)
        self.raiz.protocol("WM_DELETE_WINDOW", self._ao_fechar)
        self.raiz.after(100, self._verificar_eventos)
        if GITHUB_REPOSITORY:
            self.raiz.after(2500, lambda: self._verificar_atualizacoes(silencioso=True))

    def _configurar_estilo(self) -> None:
        estilo = ttk.Style()
        if TEMA not in estilo.theme_names():
            estilo.register_theme(
                ThemeDefinition(
                    name=TEMA,
                    themetype="light",
                    colors={
                        "primary": "#1769C2",
                        "secondary": "#667085",
                        "success": "#16803A",
                        "info": "#2563A8",
                        "warning": "#E39100",
                        "danger": "#C73737",
                        "light": "#F4F6F8",
                        "dark": "#172436",
                        "bg": "#E9EDF2",
                        "fg": "#172436",
                        "selectbg": "#1769C2",
                        "selectfg": "#FFFFFF",
                        "border": "#C6CDD6",
                        "inputfg": "#18212F",
                        "inputbg": "#FAFBFC",
                        "active": "#DDE6F0",
                    },
                )
            )
        estilo.theme_use(TEMA)
        self.raiz.option_add("*Font", ("Segoe UI", 11))
        estilo.configure("TLabel", font=("Segoe UI", 11))
        estilo.configure("TButton", font=("Segoe UI", 11))
        estilo.configure("TCheckbutton", font=("Segoe UI", 10))
        estilo.configure("HeaderTitle.TLabel", font=("Segoe UI", 23, "bold"))
        estilo.configure("HeaderSubtitle.TLabel", font=("Segoe UI", 11))
        estilo.configure("AppTitle.TLabel", font=("Segoe UI", 21, "bold"), foreground="#172436")
        estilo.configure("SectionTitle.TLabel", font=("Segoe UI", 12, "bold"), foreground="#172436")
        estilo.configure("ContentTitle.TLabel", font=("Segoe UI", 18, "bold"), foreground="#172436")
        estilo.configure("EditorTitle.TLabel", font=("Segoe UI", 20, "bold"), foreground="#172436")
        estilo.configure("EditorField.TLabel", font=("Segoe UI", 12, "bold"), foreground="#172436")
        estilo.configure("EditorStatus.TLabel", font=("Segoe UI", 11, "bold"))
        estilo.configure("StatValue.TLabel", font=("Segoe UI", 21, "bold"), foreground="#172436")
        estilo.configure("StatTitle.TLabel", font=("Segoe UI", 10), foreground="#344054")
        estilo.configure("FieldLabel.TLabel", font=("Segoe UI", 11, "bold"))
        estilo.configure("Status.TLabel", font=("Segoe UI", 10))
        estilo.configure("Footer.TLabel", font=("Segoe UI", 10))
        estilo.configure("primary.TButton", font=("Segoe UI", 11, "bold"), padding=(18, 12))
        estilo.configure("success.TButton", font=("Segoe UI", 11, "bold"), padding=(18, 12))
        estilo.configure("primary.Outline.TButton", font=("Segoe UI", 11), padding=(12, 8))
        estilo.configure("secondary.Outline.TButton", font=("Segoe UI", 11), padding=(12, 8))
        estilo.configure("success.Outline.TButton", font=("Segoe UI", 11), padding=(12, 8))
        estilo.configure("info.Outline.TButton", font=("Segoe UI", 10, "bold"), padding=(10, 6))
        estilo.configure("TEntry", padding=(9, 8), font=("Segoe UI", 11))
        estilo.configure(
            "Treeview",
            font=("Segoe UI", 11),
            rowheight=32,
            background="#FAFBFC",
            fieldbackground="#FAFBFC",
        )
        estilo.configure(
            "Treeview.Heading",
            font=("Segoe UI", 11, "bold"),
            background="#D3D9E1",
            foreground="#172436",
            padding=(8, 9),
            relief="flat",
        )
        estilo.map(
            "Treeview.Heading",
            background=[("active", "#C5CDD7")],
            foreground=[("active", "#172436")],
        )
        estilo.configure(
            "Section.Horizontal.TSeparator",
            background="#C3CAD3",
        )

    def _centralizar_janela(self) -> None:
        self.raiz.update_idletasks()
        largura = max(self.raiz.winfo_width(), LARGURA_JANELA)
        altura = max(self.raiz.winfo_height(), ALTURA_JANELA)
        x = max(0, (self.raiz.winfo_screenwidth() - largura) // 2)
        y = max(0, (self.raiz.winfo_screenheight() - altura) // 2)
        self.raiz.geometry(f"{largura}x{altura}+{x}+{y}")

    def _montar_tela(self) -> None:
        self.estrutura = ttk.Frame(self.raiz)
        self.estrutura.pack(fill="both", expand=True)
        self.estrutura.columnconfigure(0, weight=0, minsize=LARGURA_LATERAL)
        self.estrutura.columnconfigure(1, weight=1)
        self.estrutura.rowconfigure(0, weight=1)
        self.estrutura.rowconfigure(1, weight=0)

        lateral = ttk.Frame(self.estrutura, padding=(24, 22, 24, 18), width=LARGURA_LATERAL)
        lateral.grid(row=0, column=0, sticky="nsew")
        lateral.grid_propagate(False)
        lateral.columnconfigure(0, weight=1)
        lateral.rowconfigure(5, weight=1)
        ttk.Separator(self.estrutura, orient="vertical").grid(row=0, column=0, sticky="nse")

        principal = ttk.Frame(self.estrutura, padding=(18, 22, 24, 16))
        principal.grid(row=0, column=1, sticky="nsew")
        principal.columnconfigure(0, weight=1)
        principal.rowconfigure(0, weight=1)

        self._criar_cabecalho(lateral)
        self._criar_formulario(lateral)
        self._criar_opcoes(lateral)
        self._criar_progresso_e_acoes(lateral)
        self._criar_biblioteca(principal)
        self._criar_rodape(self.estrutura)
        self._atualizar_biblioteca()

    def _criar_cabecalho(self, principal: ttk.Frame) -> None:
        cabecalho = ttk.Frame(principal)
        cabecalho.grid(row=0, column=0, sticky="ew", pady=(0, 16))
        cabecalho.columnconfigure(1, weight=1)

        caminho_logo = caminho_recurso("icon", "chess-book-diagram-extractor.png")
        if caminho_logo.is_file():
            imagem_logo = Image.open(caminho_logo)
            imagem_logo.thumbnail((88, 88), Image.Resampling.LANCZOS)
            self._logo_lateral = ImageTk.PhotoImage(imagem_logo)
            ttk.Label(cabecalho, image=self._logo_lateral).grid(
                row=0, column=0, rowspan=2, sticky="nw", padx=(0, 16)
            )

        ttk.Label(
            cabecalho,
            text=(
                "Extraia diagramas de livros de xadrez em PDF e gere um novo PDF A4 "
                "com um diagrama por página."
            ),
            style="HeaderSubtitle.TLabel",
            bootstyle="secondary",
            wraplength=270,
            justify="left",
        ).grid(row=0, column=1, sticky="nw")

        self.botao_atualizar = ttk.Menubutton(
            cabecalho,
            text="Opções",
            bootstyle="secondary outline",
            direction="below",
        )
        self.botao_atualizar.grid(row=1, column=1, sticky="w", pady=(10, 0))
        menu_acoes = tk.Menu(self.botao_atualizar, tearoff=False)
        menu_acoes.add_command(label="Verificar atualizações", command=self._verificar_atualizacoes)
        menu_acoes.add_separator()
        menu_acoes.add_command(label="Sobre", command=self._mostrar_sobre)
        menu_acoes.add_command(label="Sair", command=self._ao_fechar)
        self.botao_atualizar["menu"] = menu_acoes
        ToolTip(self.botao_atualizar, text="Mais opções", delay=400)

    def _criar_formulario(self, principal: ttk.Frame) -> None:
        formulario = ttk.Frame(principal)
        formulario.grid(row=1, column=0, sticky="ew")
        formulario.columnconfigure(0, weight=1)

        ttk.Separator(
            formulario, orient="horizontal", style="Section.Horizontal.TSeparator"
        ).grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 15))
        ttk.Label(formulario, text="❶  Selecionar PDF do livro", style="SectionTitle.TLabel").grid(
            row=1, column=0, columnspan=2, sticky="w"
        )
        self.campo_entrada = ttk.Entry(formulario, textvariable=self.entrada_exibida, state="readonly")
        self.campo_entrada.grid(row=2, column=0, sticky="ew", padx=(0, 8), pady=(7, 18))
        self.tooltip_entrada = ToolTip(
            self.campo_entrada,
            text="Selecione um livro em PDF.",
            wraplength=520,
            delay=450,
        )
        self.botao_entrada = ttk.Button(
            formulario,
            text="Selecionar PDF",
            command=self._selecionar_entrada,
            bootstyle="primary outline",
        )
        self.botao_entrada.grid(row=2, column=1, sticky="e", pady=(7, 18))

        ttk.Label(
            formulario,
            textvariable=self.entrada_info,
            bootstyle="secondary",
            font=("Segoe UI", 9),
        ).grid(row=3, column=0, columnspan=2, sticky="w", pady=(0, 14))

        ttk.Separator(
            formulario, orient="horizontal", style="Section.Horizontal.TSeparator"
        ).grid(row=4, column=0, columnspan=2, sticky="ew", pady=(0, 15))
        ttk.Label(formulario, text="❷  Arquivo de saída", style="SectionTitle.TLabel").grid(
            row=5, column=0, columnspan=2, sticky="w"
        )
        self.campo_saida = ttk.Entry(formulario, textvariable=self.saida_exibida, state="readonly")
        self.campo_saida.grid(row=6, column=0, sticky="ew", padx=(0, 8), pady=(7, 4))
        self.tooltip_saida = ToolTip(
            self.campo_saida,
            text="A saída será criada na mesma pasta do livro.",
            wraplength=520,
            delay=450,
        )
        self.botao_saida = ttk.Button(
            formulario,
            text="Alterar",
            command=self._selecionar_saida,
            state="disabled",
            bootstyle="secondary outline",
        )
        self.botao_saida.grid(row=6, column=1, sticky="e", pady=(7, 4))
        self.rotulo_saida_ok = ttk.Label(
            formulario,
            text="✓ Arquivo de saída sugerido automaticamente.",
            bootstyle="success",
            font=("Segoe UI", 10),
        )
        self.rotulo_saida_ok.grid(row=7, column=0, columnspan=2, sticky="w", pady=(2, 0))
        self.rotulo_saida_ok.grid_remove()

    def _criar_opcoes(self, principal: ttk.Frame) -> None:
        opcoes = ttk.Frame(principal)
        opcoes.grid(row=2, column=0, sticky="ew", pady=(18, 0))
        ttk.Separator(
            opcoes, orient="horizontal", style="Section.Horizontal.TSeparator"
        ).grid(row=0, column=0, columnspan=4, sticky="ew", pady=(0, 15))
        ttk.Label(opcoes, text="❸  Opções", style="SectionTitle.TLabel").grid(
            row=1, column=0, columnspan=4, sticky="w", pady=(0, 9)
        )
        self.checkbox_forsyth = ttk.Checkbutton(
            opcoes,
            text="Incluir notação Forsyth e reconhecer as peças",
            variable=self.incluir_forsyth,
            bootstyle="primary",
            command=self._salvar_preferencia,
        )
        self.checkbox_forsyth.grid(row=2, column=0, columnspan=4, sticky="w")
        ttk.Label(
            opcoes,
            text="Permite revisar e editar as posições antes de gerar o PDF final.",
            bootstyle="secondary",
            wraplength=360,
            font=("Segoe UI", 9),
        ).grid(row=3, column=0, columnspan=4, sticky="w", padx=(22, 0), pady=(2, 9))
        ttk.Label(opcoes, text="Notação das peças:", bootstyle="secondary").grid(
            row=4, column=0, sticky="w", pady=(0, 9)
        )
        self.radio_portugues = ttk.Radiobutton(
            opcoes,
            text="Português",
            variable=self.idioma_notacao,
            value="pt",
            bootstyle="primary",
            command=self._salvar_preferencia,
        )
        self.radio_portugues.grid(row=4, column=1, sticky="w", pady=(0, 9))
        self.radio_ingles = ttk.Radiobutton(
            opcoes,
            text="Inglês",
            variable=self.idioma_notacao,
            value="en",
            bootstyle="primary",
            command=self._salvar_preferencia,
        )
        self.radio_ingles.grid(row=4, column=2, sticky="w", padx=(10, 0), pady=(0, 9))
        self.checkbox_abrir = ttk.Checkbutton(
            opcoes,
            text="Abrir o PDF ao concluir",
            variable=self.abrir_ao_concluir,
            bootstyle="primary",
            command=self._salvar_preferencia,
        )
        self.checkbox_abrir.grid(row=5, column=0, columnspan=4, sticky="w")

    def _criar_progresso_e_acoes(self, principal: ttk.Frame) -> None:
        bloco = ttk.Frame(principal)
        bloco.grid(row=3, column=0, sticky="ew", pady=(18, 0))
        bloco.columnconfigure(0, weight=1)
        ttk.Separator(
            bloco, orient="horizontal", style="Section.Horizontal.TSeparator"
        ).grid(row=0, column=0, sticky="ew", pady=(0, 15))
        ttk.Label(bloco, text="❹  Ações", style="SectionTitle.TLabel").grid(
            row=1, column=0, sticky="w", pady=(0, 9)
        )
        linha_progresso = ttk.Frame(bloco)
        linha_progresso.grid(row=2, column=0, sticky="ew", pady=(0, 7))
        linha_progresso.columnconfigure(0, weight=1)
        self.progresso = ttk.Progressbar(
            linha_progresso,
            mode="determinate",
            maximum=100,
            bootstyle="primary thin",
        )
        self.progresso.grid(row=0, column=0, sticky="ew")
        ttk.Label(
            linha_progresso,
            textvariable=self.texto_percentual,
            width=5,
            anchor="e",
            font=("Segoe UI", 10, "bold"),
            bootstyle="secondary",
        ).grid(row=0, column=1, padx=(10, 0))

        linha_status = ttk.Frame(bloco)
        linha_status.grid(row=3, column=0, sticky="ew")
        linha_status.columnconfigure(0, weight=1)
        self.rotulo_status = ttk.Label(
            linha_status,
            textvariable=self.status,
            style="Status.TLabel",
            bootstyle="secondary",
            anchor="w",
            justify="left",
            wraplength=355,
        )
        self.rotulo_status.grid(row=0, column=0, sticky="ew")
        linha_status.bind(
            "<Configure>",
            lambda evento: self.rotulo_status.configure(
                wraplength=max(220, evento.width - 8)
            ),
        )
        self.botao_instalar_atualizacao = ttk.Button(
            linha_status,
            text="Atualizar",
            command=self._iniciar_atualizacao_pendente,
            bootstyle="info outline",
        )
        self.botao_instalar_atualizacao.grid(
            row=1, column=0, sticky="w", pady=(8, 0)
        )
        self.botao_instalar_atualizacao.grid_remove()
        ToolTip(
            self.botao_instalar_atualizacao,
            text="Baixar e instalar a nova versão disponível.",
            delay=400,
        )

        acoes = ttk.Frame(bloco)
        acoes.grid(row=4, column=0, sticky="ew", pady=(12, 0))
        acoes.columnconfigure(0, weight=1)

        self.botao_abrir_pdf = ttk.Button(
            acoes,
            text="Abrir PDF",
            command=self._abrir_pdf,
            bootstyle="success outline",
        )
        self.botao_abrir_pdf.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        self.botao_abrir = ttk.Button(
            acoes,
            text="Abrir pasta",
            command=self._abrir_pasta,
            bootstyle="secondary outline",
        )
        self.botao_abrir.grid(row=3, column=0, sticky="ew", pady=(6, 0))
        ToolTip(self.botao_abrir, text="Abrir a pasta onde o PDF foi salvo.", delay=400)
        self.botao_processar = ttk.Button(
            acoes,
            text="▷  Extrair diagramas",
            command=self._iniciar,
            state="disabled",
            bootstyle="primary",
        )
        self.botao_processar.grid(row=0, column=0, sticky="ew")
        self.botao_cancelar = ttk.Button(
            acoes,
            text="Cancelar operação",
            command=self._cancelar_processamento,
            bootstyle="danger outline",
        )
        self.botao_cancelar.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        self.botao_cancelar.grid_remove()
        self._ocultar_acoes_resultado()

    def _criar_rodape(self, principal: ttk.Frame) -> None:
        rodape = ttk.Frame(principal, padding=(18, 6))
        rodape.grid(row=1, column=0, columnspan=2, sticky="ew")
        rodape.columnconfigure(0, weight=1)
        ttk.Label(
            rodape,
            text=f"v{__version__}  ·  E-Lopes",
            style="Footer.TLabel",
            bootstyle="secondary",
        ).grid(row=0, column=0, sticky="e")

    def _mostrar_configuracoes(self) -> None:
        messagebox.showinfo(
            "Configurações",
            "As opções principais de extração e reconhecimento estão disponíveis no painel lateral.",
            parent=self.raiz,
        )

    def _abrir_ajuda(self) -> None:
        if self.janela_ajuda is not None and self.janela_ajuda.winfo_exists():
            self.janela_ajuda.lift()
            self.janela_ajuda.focus_force()
            return
        janela = ttk.Toplevel(self.raiz)
        self.janela_ajuda = janela
        janela.title("Como usar — Chess Book Diagram Extractor")
        janela.geometry("780x680")
        janela.minsize(620, 500)
        janela.transient(self.raiz)
        janela.columnconfigure(0, weight=1)
        janela.rowconfigure(1, weight=1)

        cabecalho = ttk.Frame(janela, padding=(24, 20, 24, 14))
        cabecalho.grid(row=0, column=0, sticky="ew")
        ttk.Label(cabecalho, text="Como usar", style="HeaderTitle.TLabel").pack(anchor="w")
        ttk.Label(
            cabecalho,
            text="Fluxo completo da seleção do livro à revisão e exportação.",
            bootstyle="secondary",
        ).pack(anchor="w", pady=(3, 0))

        conteudo = ttk.Frame(janela, padding=(24, 0, 24, 14))
        conteudo.grid(row=1, column=0, sticky="nsew")
        conteudo.columnconfigure(0, weight=1)
        conteudo.rowconfigure(0, weight=1)
        texto = tk.Text(
            conteudo,
            wrap="word",
            font=("Segoe UI", 11),
            relief="flat",
            padx=16,
            pady=14,
            spacing1=2,
            spacing3=7,
            cursor="arrow",
        )
        barra = ttk.Scrollbar(conteudo, orient="vertical", command=texto.yview)
        texto.configure(yscrollcommand=barra.set)
        texto.grid(row=0, column=0, sticky="nsew")
        barra.grid(row=0, column=1, sticky="ns")
        texto.insert("1.0", self._carregar_texto_como_usar())
        texto.configure(state="disabled")

        rodape = ttk.Frame(janela, padding=(24, 0, 24, 20))
        rodape.grid(row=2, column=0, sticky="ew")
        botao_fechar = ttk.Button(
            rodape,
            text="Fechar",
            command=janela.destroy,
            bootstyle="primary",
            width=14,
            padding=(10, 8),
        )
        botao_fechar.pack(side="right")

        def ao_fechar_ajuda() -> None:
            self.janela_ajuda = None
            janela.destroy()

        botao_fechar.configure(command=ao_fechar_ajuda)
        janela.protocol("WM_DELETE_WINDOW", ao_fechar_ajuda)
        janela.bind("<Escape>", lambda _evento: ao_fechar_ajuda())
        janela.after_idle(lambda: self._centralizar_secundaria(janela))

    @staticmethod
    def _carregar_texto_como_usar() -> str:
        try:
            readme = caminho_recurso("README.md").read_text(encoding="utf-8")
            inicio = readme.index("## Como usar") + len("## Como usar")
            fim = readme.find("\n## ", inicio)
            secao = readme[inicio : fim if fim >= 0 else None].strip()
            return secao.replace("**", "").replace("`", "")
        except (OSError, ValueError):
            return (
                "1. Selecione um livro em PDF.\n"
                "2. Confira o arquivo de saída e as opções.\n"
                "3. Clique em Extrair diagramas.\n"
                "4. Revise as posições Forsyth e salve o PDF.\n"
                "5. Reabra o livro pela biblioteca para editar ou exportar PGN."
            )

    def _centralizar_secundaria(self, janela: tk.Misc) -> None:
        janela.update_idletasks()
        largura = janela.winfo_width()
        altura = janela.winfo_height()
        x = max(0, self.raiz.winfo_rootx() + (self.raiz.winfo_width() - largura) // 2)
        y = max(0, self.raiz.winfo_rooty() + (self.raiz.winfo_height() - altura) // 2)
        janela.geometry(f"{largura}x{altura}+{x}+{y}")

    def _criar_biblioteca(self, principal: ttk.Frame) -> None:
        self.quadro_biblioteca = ttk.Frame(principal, padding=12, bootstyle="@card")
        self.quadro_biblioteca.grid(row=0, column=0, sticky="nsew")
        self.quadro_biblioteca.columnconfigure(0, weight=1)
        self.quadro_biblioteca.rowconfigure(0, weight=1)
        self.painel_lista_biblioteca = ttk.Frame(self.quadro_biblioteca)
        self.painel_lista_biblioteca.grid(row=0, column=0, sticky="nsew")
        self.painel_lista_biblioteca.columnconfigure(0, weight=1)
        self.painel_lista_biblioteca.rowconfigure(1, weight=1)
        topo = ttk.Frame(self.painel_lista_biblioteca)
        topo.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        topo.columnconfigure(0, weight=1)
        ttk.Label(topo, text="Livros processados", style="ContentTitle.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            topo,
            text=(
                "Dê dois cliques em um livro para revisar a posição Forsyth de cada "
                "diagrama e exportar o arquivo PGN."
            ),
            bootstyle="secondary",
            justify="left",
            wraplength=760,
        ).grid(row=1, column=0, sticky="w", pady=(2, 0))
        busca = ttk.Frame(topo)
        busca.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(16, 0))
        busca.columnconfigure(1, weight=1)
        ttk.Label(busca, text="Filtro livre", style="FieldLabel.TLabel").grid(
            row=0, column=0, sticky="w", padx=(0, 12)
        )
        self.campo_busca_biblioteca = ttk.Entry(
            busca,
            textvariable=self.busca_biblioteca,
        )
        self.campo_busca_biblioteca.grid(row=0, column=1, sticky="ew")
        ToolTip(
            self.campo_busca_biblioteca,
            text="Pesquisar por nome, quantidade de diagramas ou data de criação.",
            delay=450,
        )
        acoes_biblioteca = ttk.Frame(topo)
        acoes_biblioteca.grid(
            row=3, column=0, columnspan=2, sticky="ew", pady=(14, 0)
        )
        for coluna in range(3):
            acoes_biblioteca.columnconfigure(coluna, weight=1, uniform="acoes_biblioteca")
        self.botao_visualizar_livro = ttk.Button(
            acoes_biblioteca,
            text="Visualizar selecionado",
            command=self._abrir_livro_selecionado,
            state="disabled",
            bootstyle="primary",
            padding=(10, 8),
        )
        self.botao_visualizar_livro.grid(row=0, column=0, sticky="ew", padx=(0, 14))
        self.botao_renomear_livro = ttk.Button(
            acoes_biblioteca,
            text="Renomear",
            command=self._renomear_livro_selecionado,
            state="disabled",
            bootstyle="secondary outline",
            padding=(10, 8),
        )
        self.botao_renomear_livro.grid(row=0, column=1, sticky="ew", padx=7)
        self.botao_excluir_livro = ttk.Button(
            acoes_biblioteca,
            text="Excluir",
            command=self._excluir_livro_selecionado,
            state="disabled",
            bootstyle="danger outline",
            padding=(10, 8),
        )
        self.botao_excluir_livro.grid(row=0, column=2, sticky="ew", padx=(14, 0))
        self.lista_livros = ttk.Treeview(
            self.painel_lista_biblioteca,
            columns=("diagramas", "criado_em"),
            show="tree headings",
            height=14,
            selectmode="browse",
        )
        self.lista_livros.heading("#0", text="Livro")
        self.lista_livros.heading("diagramas", text="Diagramas")
        self.lista_livros.heading("criado_em", text="Data de criação")
        self.lista_livros.column("#0", width=440, stretch=True)
        self.lista_livros.column("diagramas", width=110, anchor="center", stretch=False)
        self.lista_livros.column("criado_em", width=150, anchor="center", stretch=False)
        self.lista_livros.grid(row=1, column=0, sticky="nsew")
        self.lista_livros.bind("<<TreeviewSelect>>", self._ao_selecionar_livro)
        self.lista_livros.bind("<Button-1>", self._bloquear_redimensionamento_colunas)
        self.lista_livros.bind("<Double-1>", self._ao_duplo_clique_biblioteca)
        self.lista_livros.bind("<Configure>", self._posicionar_separadores_biblioteca)
        self.lista_livros.bind("<Return>", self._visualizar_livro_por_teclado)
        self.lista_livros.bind("<F2>", self._renomear_livro_por_teclado)
        self.lista_livros.bind("<Delete>", self._excluir_livro_por_teclado)
        self.separadores_biblioteca = [
            tk.Frame(self.lista_livros, width=2, background="#A9B2BE"),
            tk.Frame(self.lista_livros, width=2, background="#A9B2BE"),
        ]

        self.controles_paginacao_biblioteca = ttk.Frame(self.painel_lista_biblioteca)
        self.controles_paginacao_biblioteca.grid(
            row=2, column=0, sticky="ew", pady=(10, 0)
        )
        self.controles_paginacao_biblioteca.columnconfigure(1, weight=1)
        self.botao_pagina_anterior = ttk.Button(
            self.controles_paginacao_biblioteca,
            text="← Anterior",
            command=lambda: self._mudar_pagina_biblioteca(-1),
            bootstyle="secondary outline",
            width=13,
            padding=(9, 6),
        )
        self.botao_pagina_anterior.grid(row=0, column=0, sticky="w")
        ttk.Label(
            self.controles_paginacao_biblioteca,
            textvariable=self.texto_paginacao_biblioteca,
            bootstyle="secondary",
            anchor="center",
        ).grid(row=0, column=1, sticky="ew", padx=12)
        self.botao_proxima_pagina = ttk.Button(
            self.controles_paginacao_biblioteca,
            text="Próxima →",
            command=lambda: self._mudar_pagina_biblioteca(1),
            bootstyle="secondary outline",
            width=13,
            padding=(9, 6),
        )
        self.botao_proxima_pagina.grid(row=0, column=2, sticky="e")

        self.carregamento_biblioteca = ttk.Frame(
            self.painel_lista_biblioteca, padding=36, bootstyle="@card"
        )
        self.carregamento_biblioteca.columnconfigure(0, weight=1)
        self.carregamento_biblioteca.rowconfigure(0, weight=1)
        centro_carregamento = ttk.Frame(self.carregamento_biblioteca)
        centro_carregamento.grid(row=0, column=0)
        ttk.Label(
            centro_carregamento,
            text="Carregando diagramas...",
            style="ContentTitle.TLabel",
        ).pack(pady=(0, 6))
        self.rotulo_carregamento_biblioteca = ttk.Label(
            centro_carregamento,
            text="Lendo a cópia interna do livro. Isso pode levar alguns segundos.",
            bootstyle="secondary",
        )
        self.rotulo_carregamento_biblioteca.pack(pady=(0, 14))
        self.progresso_carregamento_biblioteca = ttk.Progressbar(
            centro_carregamento,
            mode="indeterminate",
            length=320,
            bootstyle="primary striped",
        )
        self.progresso_carregamento_biblioteca.pack()
        self._criar_editor_biblioteca()

    def _criar_editor_biblioteca(self) -> None:
        self.painel_editor_biblioteca = ttk.Frame(self.quadro_biblioteca)
        self.painel_editor_biblioteca.columnconfigure(
            0, weight=3, minsize=420, uniform="colunas_editor"
        )
        self.painel_editor_biblioteca.columnconfigure(
            1, weight=2, minsize=320, uniform="colunas_editor"
        )
        self.painel_editor_biblioteca.rowconfigure(1, weight=1)

        cabecalho = ttk.Frame(self.painel_editor_biblioteca)
        cabecalho.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 16))
        cabecalho.columnconfigure(1, weight=1)
        ttk.Button(
            cabecalho,
            text="← Biblioteca",
            command=self._fechar_editor_biblioteca,
            bootstyle="secondary outline",
            width=15,
            padding=(10, 8),
        ).grid(row=0, column=0, sticky="w", padx=(0, 12))
        self.rotulo_titulo_biblioteca = ttk.Label(
            cabecalho, style="ContentTitle.TLabel", anchor="w", width=1
        )
        self.rotulo_titulo_biblioteca.grid(row=0, column=1, sticky="ew")
        self.rotulo_pendencias_biblioteca = ttk.Label(
            cabecalho,
            text="Verificando...",
            bootstyle="secondary inverse",
            font=("Segoe UI", 10, "bold"),
            padding=(9, 4),
        )
        self.rotulo_pendencias_biblioteca.grid(
            row=0, column=2, sticky="e", padx=(12, 14)
        )
        self.rotulo_contador_biblioteca = ttk.Label(
            cabecalho, bootstyle="secondary", font=("Segoe UI", 10)
        )
        self.rotulo_contador_biblioteca.grid(row=0, column=3, sticky="e")

        self.quadro_imagem_biblioteca = ttk.Frame(
            self.painel_editor_biblioteca, padding=16, bootstyle="@card"
        )
        self.quadro_imagem_biblioteca.grid(
            row=1, column=0, sticky="nsew", padx=(0, 16)
        )
        self.quadro_imagem_biblioteca.columnconfigure(0, weight=1)
        self.quadro_imagem_biblioteca.rowconfigure(0, weight=1)
        self.rotulo_imagem_biblioteca = ttk.Label(
            self.quadro_imagem_biblioteca, anchor="center"
        )
        self.rotulo_imagem_biblioteca.grid(row=0, column=0, sticky="nsew")
        self.rotulo_origem_biblioteca = ttk.Label(
            self.quadro_imagem_biblioteca, anchor="center", bootstyle="secondary"
        )
        self.rotulo_origem_biblioteca.grid(row=1, column=0, sticky="ew", pady=(7, 0))
        self.quadro_imagem_biblioteca.bind(
            "<Configure>", self._agendar_redimensionamento_biblioteca
        )

        painel = ttk.Frame(
            self.painel_editor_biblioteca, padding=24, bootstyle="@card"
        )
        painel.grid(row=1, column=1, sticky="nsew")
        painel.columnconfigure(0, weight=1)
        ttk.Label(
            painel,
            text="Edição da Posição Forsyth",
            style="EditorTitle.TLabel",
        ).grid(
            row=1, column=0, sticky="w", pady=(20, 14)
        )
        self.quadro_edicao_forsyth = ttk.Frame(
            painel,
            padding=12,
            bootstyle="light",
            relief="solid",
            borderwidth=1,
        )
        self.quadro_edicao_forsyth.grid(row=2, column=0, sticky="ew")
        self.quadro_edicao_forsyth.columnconfigure(0, weight=1)
        self.quadro_edicao_forsyth.rowconfigure(1, minsize=285)

        modos_edicao = ttk.Frame(self.quadro_edicao_forsyth, bootstyle="light")
        modos_edicao.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        modos_edicao.columnconfigure(0, weight=1)
        modos_edicao.columnconfigure(1, weight=1)
        self.modo_edicao_fen_biblioteca = tk.StringVar(value="completa")
        ttk.Radiobutton(
            modos_edicao,
            text="Posição completa",
            variable=self.modo_edicao_fen_biblioteca,
            value="completa",
            command=self._alternar_modo_edicao_fen,
            bootstyle="primary toolbutton",
            padding=(10, 7),
        ).grid(row=0, column=0, sticky="ew", padx=(0, 4))
        ttk.Radiobutton(
            modos_edicao,
            text="Editar por linhas",
            variable=self.modo_edicao_fen_biblioteca,
            value="linhas",
            command=self._alternar_modo_edicao_fen,
            bootstyle="primary toolbutton",
            padding=(10, 7),
        ).grid(row=0, column=1, sticky="ew", padx=(4, 0))

        self.campo_fen_biblioteca = tk.Text(
            self.quadro_edicao_forsyth,
            width=1,
            height=4,
            wrap="char",
            font=("Consolas", 13),
            relief="solid",
            borderwidth=1,
            padx=12,
            pady=10,
            undo=True,
        )
        self.campo_fen_biblioteca.grid(row=1, column=0, sticky="new", pady=(8, 8))
        self.campo_fen_biblioteca.bind("<KeyRelease>", self._validar_fen_biblioteca)

        self.editor_linhas_fen_biblioteca = ttk.Frame(
            self.quadro_edicao_forsyth, padding=(0, 5), bootstyle="light"
        )
        self.editor_linhas_fen_biblioteca.columnconfigure(1, weight=1)
        self.campos_linhas_fen_biblioteca: list[ttk.Entry] = []
        for indice, numero_linha in enumerate(range(8, 0, -1)):
            ttk.Label(
                self.editor_linhas_fen_biblioteca,
                text=str(numero_linha),
                style="EditorField.TLabel",
                width=2,
                anchor="center",
            ).grid(row=indice, column=0, sticky="w", padx=(0, 8), pady=2)
            campo_linha = ttk.Entry(
                self.editor_linhas_fen_biblioteca,
                font=("Consolas", 12),
                width=1,
            )
            campo_linha.grid(row=indice, column=1, sticky="ew", pady=1)
            campo_linha.bind("<KeyRelease>", self._ao_editar_linha_fen)
            self.campos_linhas_fen_biblioteca.append(campo_linha)
        self.editor_linhas_fen_biblioteca.grid(
            row=1, column=0, sticky="new", pady=(3, 5)
        )
        self.editor_linhas_fen_biblioteca.grid_remove()

        self.rotulo_validacao_biblioteca = ttk.Label(
            self.quadro_edicao_forsyth,
            wraplength=270,
            justify="left",
            anchor="w",
            style="EditorStatus.TLabel",
            font=("Segoe UI", 11, "bold"),
        )
        self.rotulo_validacao_biblioteca.grid(row=2, column=0, sticky="ew")
        self.quadro_edicao_forsyth.bind(
            "<Configure>",
            lambda evento: self.rotulo_validacao_biblioteca.configure(
                wraplength=max(190, evento.width - 32)
            ),
        )

        lados = ttk.Frame(painel)
        lados.grid(row=0, column=0, sticky="w")
        ttk.Label(
            lados,
            text="Player to Move:",
            style="EditorField.TLabel",
        ).pack(side="left", padx=(0, 12))
        self.lado_preto_biblioteca = tk.BooleanVar(value=False)
        self.rotulo_white_biblioteca = ttk.Label(
            lados,
            text="White",
            bootstyle="primary",
            font=("Segoe UI", 11, "bold"),
        )
        self.rotulo_white_biblioteca.pack(side="left")
        self.switch_lado_biblioteca = ttk.Checkbutton(
            lados,
            text="",
            variable=self.lado_preto_biblioteca,
            command=self._alterar_lado_biblioteca,
            bootstyle="primary round-toggle",
        )
        self.switch_lado_biblioteca.pack(side="left", padx=10)
        self.rotulo_black_biblioteca = ttk.Label(
            lados,
            text="Black",
            bootstyle="secondary",
            font=("Segoe UI", 11, "bold"),
        )
        self.rotulo_black_biblioteca.pack(side="left")

        self.annotator_biblioteca = tk.StringVar()

        navegacao = ttk.Frame(
            self.painel_editor_biblioteca, padding=(10, 8), bootstyle="@card"
        )
        navegacao.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(16, 0))
        navegacao.columnconfigure(0, weight=1)
        grupo = ttk.Frame(navegacao)
        grupo.grid(row=0, column=0, sticky="w")
        self.botao_primeiro_biblioteca = ttk.Button(
            grupo,
            text="|← Primeiro",
            command=lambda: self._ir_para_biblioteca(0),
            bootstyle="secondary outline",
            width=13,
            padding=(10, 8),
        )
        self.botao_primeiro_biblioteca.pack(side="left", padx=(0, 6))
        self.botao_anterior_biblioteca = ttk.Button(
            grupo,
            text="← Anterior",
            command=lambda: self._navegar_biblioteca(-1),
            bootstyle="secondary outline",
            width=13,
            padding=(10, 8),
        )
        self.botao_anterior_biblioteca.pack(side="left", padx=(0, 6))
        self.botao_proximo_biblioteca = ttk.Button(
            grupo,
            text="Próximo →",
            command=lambda: self._navegar_biblioteca(1),
            bootstyle="secondary outline",
            width=13,
            padding=(10, 8),
        )
        self.botao_proximo_biblioteca.pack(side="left")
        self.botao_ultimo_biblioteca = ttk.Button(
            grupo,
            text="Último →|",
            command=lambda: self._ir_para_biblioteca(len(self.itens_biblioteca) - 1),
            bootstyle="secondary outline",
            width=13,
            padding=(10, 8),
        )
        self.botao_ultimo_biblioteca.pack(side="left", padx=(6, 0))

        ttk.Separator(navegacao, orient="vertical").grid(
            row=0, column=1, sticky="ns", padx=16
        )
        grupo_revisao = ttk.Frame(navegacao)
        grupo_revisao.grid(row=0, column=2, sticky="e")
        self.botao_proximo_erro_biblioteca = ttk.Button(
            grupo_revisao,
            text="Próximo com erro (0)",
            command=self._ir_para_proximo_erro_biblioteca,
            state="disabled",
            bootstyle="warning outline",
            width=20,
            padding=(10, 8),
        )
        self.botao_proximo_erro_biblioteca.pack(side="left", padx=(0, 8))
        self.botao_exportar_pgn_biblioteca = ttk.Button(
            grupo_revisao,
            text="Exportar PGN",
            command=self._exportar_pgn_biblioteca,
            state="disabled",
            bootstyle="success outline",
            width=20,
            padding=(10, 8),
        )
        self.botao_exportar_pgn_biblioteca.pack(side="left")
        ToolTip(
            self.botao_exportar_pgn_biblioteca,
            text="Disponível quando todas as posições Forsyth estiverem válidas.",
            delay=450,
        )

    @staticmethod
    def _chave_busca_biblioteca(valor: str) -> str:
        normalizado = unicodedata.normalize("NFKD", valor)
        return " ".join(
            "".join(letra for letra in normalizado if not unicodedata.combining(letra))
            .casefold()
            .split()
        )

    @staticmethod
    def _formatar_data_criacao(valor: str) -> str:
        try:
            ano, mes, dia = valor[:10].split("-")
            if not (len(ano) == 4 and len(mes) == 2 and len(dia) == 2):
                raise ValueError
            return f"{dia}/{mes}/{ano}"
        except (AttributeError, ValueError):
            return "—"

    @classmethod
    def _livro_corresponde_ao_filtro(cls, livro: LivroSalvo, filtro: str) -> bool:
        termos = cls._chave_busca_biblioteca(filtro).split()
        if not termos:
            return True
        conteudo = cls._chave_busca_biblioteca(
            " ".join(
                (
                    livro.titulo,
                    str(len(livro.diagramas)),
                    cls._formatar_data_criacao(livro.criado_em),
                )
            )
        )
        return all(termo in conteudo for termo in termos)

    def _ao_filtrar_biblioteca(self, *_args: object) -> None:
        self.pagina_biblioteca = 0
        self._atualizar_biblioteca()

    def _mudar_pagina_biblioteca(self, deslocamento: int) -> None:
        self.pagina_biblioteca = max(0, self.pagina_biblioteca + deslocamento)
        self._atualizar_biblioteca()

    def _atualizar_biblioteca(self) -> None:
        if not hasattr(self, "lista_livros"):
            return
        selecao = self.lista_livros.selection()
        selecionado = selecao[0] if selecao else None
        livros = self.biblioteca.listar()
        filtro = self.busca_biblioteca.get()
        if filtro.strip():
            livros = [
                livro
                for livro in livros
                if self._livro_corresponde_ao_filtro(livro, filtro)
            ]
        total = len(livros)
        total_paginas = max(1, (total + LIVROS_POR_PAGINA - 1) // LIVROS_POR_PAGINA)
        self.pagina_biblioteca = min(self.pagina_biblioteca, total_paginas - 1)
        inicio = self.pagina_biblioteca * LIVROS_POR_PAGINA
        livros_da_pagina = livros[inicio : inicio + LIVROS_POR_PAGINA]

        self.lista_livros.delete(*self.lista_livros.get_children())
        for livro in livros_da_pagina:
            self.lista_livros.insert(
                "",
                "end",
                iid=livro.id,
                text=livro.titulo,
                values=(
                    len(livro.diagramas),
                    self._formatar_data_criacao(livro.criado_em),
                ),
            )
        descricao_total = "livro" if total == 1 else "livros"
        self.texto_paginacao_biblioteca.set(
            f"Página {self.pagina_biblioteca + 1} de {total_paginas}  ·  "
            f"{total} {descricao_total}"
        )
        self.botao_pagina_anterior.configure(
            state="normal" if self.pagina_biblioteca > 0 else "disabled"
        )
        self.botao_proxima_pagina.configure(
            state=(
                "normal"
                if self.pagina_biblioteca < total_paginas - 1
                else "disabled"
            )
        )
        if selecionado and self.lista_livros.exists(selecionado):
            self.lista_livros.selection_set(selecionado)
        self._ao_selecionar_livro()

    def _ao_selecionar_livro(self, _evento: object | None = None) -> None:
        habilitado = (
            bool(self.lista_livros.selection())
            and not self.processando
            and not self.revisando
            and not self.carregando_livro
        )
        estado = "normal" if habilitado else "disabled"
        self.botao_visualizar_livro.configure(state=estado)
        self.botao_renomear_livro.configure(state=estado)
        self.botao_excluir_livro.configure(state=estado)

    def _bloquear_redimensionamento_colunas(self, evento: tk.Event) -> str | None:
        if self.lista_livros.identify_region(evento.x, evento.y) == "separator":
            return "break"
        return None

    def _ao_duplo_clique_biblioteca(self, evento: tk.Event) -> str | None:
        if self.lista_livros.identify_region(evento.x, evento.y) not in ("tree", "cell"):
            return "break"
        self._abrir_livro_selecionado()
        return "break"

    def _posicionar_separadores_biblioteca(
        self, _evento: object | None = None
    ) -> None:
        if not hasattr(self, "separadores_biblioteca"):
            return
        largura = self.lista_livros.winfo_width()
        altura = self.lista_livros.winfo_height()
        posicoes = (largura - 260, largura - 150)
        for separador, posicao in zip(self.separadores_biblioteca, posicoes):
            separador.place(x=max(1, posicao), y=0, width=2, height=altura)
            separador.lift()

    def _visualizar_livro_por_teclado(self, _evento: object | None = None) -> str:
        self._abrir_livro_selecionado()
        return "break"

    def _renomear_livro_por_teclado(self, _evento: object | None = None) -> str:
        self._renomear_livro_selecionado()
        return "break"

    def _excluir_livro_por_teclado(self, _evento: object | None = None) -> str:
        self._excluir_livro_selecionado()
        return "break"

    def _livro_selecionado(self) -> LivroSalvo | None:
        selecao = self.lista_livros.selection()
        return self.biblioteca.carregar(selecao[0]) if selecao else None

    def _solicitar_novo_nome_livro(self, titulo_atual: str) -> str | None:
        resultado: dict[str, str | None] = {"valor": None}
        janela = ttk.Toplevel(self.raiz)
        janela.title("Renomear livro")
        janela.geometry("660x190")
        janela.minsize(520, 190)
        janela.resizable(True, False)
        janela.transient(self.raiz)
        janela.columnconfigure(0, weight=1)

        conteudo = ttk.Frame(janela, padding=(24, 20))
        conteudo.grid(row=0, column=0, sticky="nsew")
        conteudo.columnconfigure(0, weight=1)
        ttk.Label(
            conteudo,
            text="Renomear livro",
            style="SectionTitle.TLabel",
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            conteudo,
            text="Digite o nome que será exibido na biblioteca:",
            bootstyle="secondary",
        ).grid(row=1, column=0, sticky="w", pady=(4, 10))

        novo_titulo = tk.StringVar(value=titulo_atual)
        campo = ttk.Entry(conteudo, textvariable=novo_titulo)
        campo.grid(row=2, column=0, sticky="ew")

        botoes = ttk.Frame(conteudo)
        botoes.grid(row=3, column=0, sticky="e", pady=(16, 0))

        def cancelar(_evento: object | None = None) -> str:
            janela.destroy()
            return "break"

        def confirmar(_evento: object | None = None) -> str:
            valor = novo_titulo.get().strip()
            if not valor:
                messagebox.showwarning(
                    "Nome necessário",
                    "Digite um nome para o livro.",
                    parent=janela,
                )
                campo.focus_set()
                return "break"
            resultado["valor"] = valor
            janela.destroy()
            return "break"

        ttk.Button(
            botoes,
            text="Cancelar",
            command=cancelar,
            bootstyle="secondary outline",
            width=14,
            padding=(10, 8),
        ).pack(side="left", padx=(0, 8))
        ttk.Button(
            botoes,
            text="Renomear",
            command=confirmar,
            bootstyle="primary",
            width=14,
            padding=(10, 8),
        ).pack(side="left")

        janela.protocol("WM_DELETE_WINDOW", cancelar)
        janela.bind("<Escape>", cancelar)
        campo.bind("<Return>", confirmar)

        def preparar_janela() -> None:
            self._centralizar_secundaria(janela)
            campo.focus_set()
            campo.selection_range(0, "end")
            campo.icursor("end")

        janela.after_idle(preparar_janela)
        janela.grab_set()
        self.raiz.wait_window(janela)
        return resultado["valor"]

    def _renomear_livro_selecionado(self) -> None:
        if self.processando or self.revisando:
            return
        livro = self._livro_selecionado()
        if livro is None:
            return
        novo_titulo = self._solicitar_novo_nome_livro(livro.titulo)
        if novo_titulo is None:
            return
        try:
            try:
                renomeado = self.biblioteca.renomear(livro.id, novo_titulo)
            except LivroDuplicadoError as conflito:
                substituir = messagebox.askyesno(
                    "Nome já utilizado",
                    (
                        f'Já existe um livro chamado "{conflito.livro.titulo}".\n\n'
                        "Deseja substituir a cópia interna e as posições desse livro? "
                        "Os PDFs originais e exportados não serão alterados."
                    ),
                    icon="warning",
                    parent=self.raiz,
                )
                if not substituir:
                    return
                renomeado = self.biblioteca.renomear(
                    livro.id, novo_titulo, substituir=True
                )
            self._atualizar_biblioteca()
            if self.lista_livros.exists(renomeado.id):
                self.lista_livros.selection_set(renomeado.id)
                self.lista_livros.focus(renomeado.id)
                self.lista_livros.see(renomeado.id)
            self._ao_selecionar_livro()
            self._definir_status(f'Livro renomeado para "{renomeado.titulo}".', "success")
        except (OSError, ValueError) as erro:
            messagebox.showerror("Não foi possível renomear", str(erro), parent=self.raiz)

    def _excluir_livro_selecionado(self) -> None:
        if self.processando or self.revisando:
            return
        livro = self._livro_selecionado()
        if livro is None:
            return
        confirmar = messagebox.askyesno(
            "Excluir livro da biblioteca",
            (
                f'Deseja excluir "{livro.titulo}" da biblioteca interna?\n\n'
                "A cópia interna e suas posições serão removidas permanentemente. "
                "O PDF original e a cópia exportada não serão alterados."
            ),
            icon="warning",
            parent=self.raiz,
        )
        if not confirmar:
            return
        try:
            if not self.biblioteca.excluir(livro.id):
                raise FileNotFoundError("O livro já não existe na biblioteca interna.")
            self._atualizar_biblioteca()
            self._definir_status(f'Livro "{livro.titulo}" excluído da biblioteca.', "success")
        except (OSError, ValueError) as erro:
            messagebox.showerror("Não foi possível excluir", str(erro), parent=self.raiz)

    def _abrir_livro_selecionado(self) -> None:
        selecao = self.lista_livros.selection()
        if not selecao or self.processando or self.revisando or self.carregando_livro:
            return
        livro = self.biblioteca.carregar(selecao[0])
        if livro is None:
            self._atualizar_biblioteca()
            messagebox.showerror(
                "Livro indisponivel",
                "Os dados internos deste livro nao puderam ser carregados.",
                parent=self.raiz,
            )
            return
        self.carregando_livro = True
        self._ao_selecionar_livro()
        self.lista_livros.grid_remove()
        self.controles_paginacao_biblioteca.grid_remove()
        self.carregamento_biblioteca.grid(row=1, column=0, sticky="nsew")
        self.progresso_carregamento_biblioteca.start(12)
        self.estado_barra.set("Carregando livro")
        threading.Thread(
            target=self._carregar_livro_biblioteca,
            args=(livro,),
            daemon=True,
        ).start()

    def _carregar_livro_biblioteca(self, livro: LivroSalvo) -> None:
        try:
            candidatos = self.biblioteca.carregar_candidatos(livro)
        except (OSError, ValueError) as erro:
            self.logger.exception("Falha ao carregar livro da biblioteca.")
            self.eventos.put(("erro_biblioteca", erro))
        else:
            self.eventos.put(("biblioteca_carregada", (livro, candidatos)))

    def _finalizar_carregamento_biblioteca(self) -> None:
        self.progresso_carregamento_biblioteca.stop()
        self.carregamento_biblioteca.grid_remove()
        self.lista_livros.grid(row=1, column=0, sticky="nsew")
        self.controles_paginacao_biblioteca.grid(
            row=2, column=0, sticky="ew", pady=(10, 0)
        )
        self.carregando_livro = False

    def _mostrar_livro_biblioteca(
        self, livro: LivroSalvo, candidatos: list[Candidato]
    ) -> None:
        self._finalizar_carregamento_biblioteca()
        itens = [
            ItemRevisao(
                posicao=diagrama.posicao or "",
                confirmada=bool(diagrama.posicao),
                posicao_original=diagrama.posicao or "",
                lado_a_jogar=diagrama.lado_a_jogar,
            )
            for diagrama in livro.diagramas
        ]
        self.livro_em_edicao = livro
        self.estatistica_paginas.set(str(livro.paginas_originais or "—"))
        self.estatistica_diagramas.set(str(len(livro.diagramas)))
        self.estatistica_atencao.set(
            str(sum(not diagrama.posicao for diagrama in livro.diagramas))
        )
        self.estatistica_excluidos.set("0")
        self.revisando = True
        self._atualizar_estado_principal()
        self.candidatos_biblioteca = candidatos
        self.itens_biblioteca = itens
        self.indice_biblioteca = 0
        self.annotator_biblioteca.set(livro.annotator)
        self.painel_lista_biblioteca.grid_remove()
        self.painel_editor_biblioteca.grid(row=0, column=0, sticky="nsew")
        self.rotulo_titulo_biblioteca.configure(text=livro.titulo)
        self.estado_barra.set("Visualizando livro")
        self._exibir_diagrama_biblioteca()

    def _mostrar_erro_biblioteca(self, erro: object) -> None:
        self._finalizar_carregamento_biblioteca()
        self.lista_livros.grid(row=1, column=0, sticky="nsew")
        self._ao_selecionar_livro()
        self.estado_barra.set("Erro")
        messagebox.showerror("Não foi possível abrir o livro", str(erro), parent=self.raiz)

    @staticmethod
    def _separar_linhas_forsyth(texto: str) -> list[str]:
        linhas = texto.strip().replace("\n", "").split("/")
        return (linhas + [""] * 8)[:8]

    @staticmethod
    def _juntar_linhas_forsyth(linhas: list[str]) -> str:
        return "/".join(linha.strip().replace("/", "") for linha in linhas)

    def _preencher_linhas_fen_biblioteca(self, texto: str) -> None:
        self._sincronizando_fen_biblioteca = True
        try:
            for campo, linha in zip(
                self.campos_linhas_fen_biblioteca,
                self._separar_linhas_forsyth(texto),
            ):
                campo.delete(0, "end")
                campo.insert(0, linha)
        finally:
            self._sincronizando_fen_biblioteca = False

    def _ao_editar_linha_fen(self, evento: object | None = None) -> None:
        if self._sincronizando_fen_biblioteca:
            return
        texto = self._juntar_linhas_forsyth(
            [campo.get() for campo in self.campos_linhas_fen_biblioteca]
        )
        self._sincronizando_fen_biblioteca = True
        try:
            self.campo_fen_biblioteca.delete("1.0", "end")
            self.campo_fen_biblioteca.insert("1.0", texto)
        finally:
            self._sincronizando_fen_biblioteca = False
        self._validar_fen_biblioteca(evento)

    def _alternar_modo_edicao_fen(self) -> None:
        if self.modo_edicao_fen_biblioteca.get() == "linhas":
            self._preencher_linhas_fen_biblioteca(self._texto_fen_biblioteca())
            self.campo_fen_biblioteca.grid_remove()
            self.editor_linhas_fen_biblioteca.grid(
                row=1, column=0, sticky="new", pady=(3, 5)
            )
            self.campos_linhas_fen_biblioteca[0].focus_set()
        else:
            self._ao_editar_linha_fen()
            self.editor_linhas_fen_biblioteca.grid_remove()
            self.campo_fen_biblioteca.grid(
                row=1, column=0, sticky="new", pady=(8, 8)
            )
            self.campo_fen_biblioteca.focus_set()
        self._validar_fen_biblioteca()

    def _texto_fen_biblioteca(self) -> str:
        return self.campo_fen_biblioteca.get("1.0", "end-1c").strip().replace("\n", "")

    def _salvar_diagrama_atual_biblioteca(self) -> bool:
        if not self.itens_biblioteca:
            return False
        item = self.itens_biblioteca[self.indice_biblioteca]
        texto = self._texto_fen_biblioteca()
        valido, _mensagem = validar_posicao(texto, self.livro_em_edicao.idioma)
        if valido:
            texto = normalizar_posicao(texto, self.livro_em_edicao.idioma)
        item.posicao = texto
        item.confirmada = valido
        item.lado_a_jogar = "b" if self.lado_preto_biblioteca.get() else "w"
        return valido

    def _validar_fen_biblioteca(self, _evento: object | None = None) -> None:
        if self.livro_em_edicao is None:
            return
        texto = self._texto_fen_biblioteca()
        if (
            self.modo_edicao_fen_biblioteca.get() == "completa"
            and not self._sincronizando_fen_biblioteca
        ):
            self._preencher_linhas_fen_biblioteca(texto)
        valido, mensagem = validar_posicao(texto, self.livro_em_edicao.idioma)
        if self.itens_biblioteca:
            item_atual = self.itens_biblioteca[self.indice_biblioteca]
            item_atual.posicao = texto
            item_atual.confirmada = valido
        if valido:
            aviso = aviso_plausibilidade(texto, self.livro_em_edicao.idioma)
            self.rotulo_validacao_biblioteca.configure(
                text=aviso or mensagem,
                bootstyle="warning" if aviso else "success",
            )
            if _evento is not None:
                self._agendar_salvamento_biblioteca()
        else:
            self.rotulo_validacao_biblioteca.configure(text=mensagem, bootstyle="danger")
            if _evento is not None:
                self._cancelar_salvamento_biblioteca_pendente()
                self.estado_barra.set("Alterações pendentes")
        self._atualizar_acoes_validacao_biblioteca()

    @staticmethod
    def _indices_invalidos_biblioteca(
        itens: list[ItemRevisao], idioma: str
    ) -> list[int]:
        return [
            indice
            for indice, item in enumerate(itens)
            if not validar_posicao(item.posicao, idioma)[0]
        ]

    def _atualizar_acoes_validacao_biblioteca(self) -> None:
        if self.livro_em_edicao is None:
            return
        invalidos = self._indices_invalidos_biblioteca(
            self.itens_biblioteca, self.livro_em_edicao.idioma
        )
        self.botao_exportar_pgn_biblioteca.configure(
            state="disabled" if invalidos or not self.itens_biblioteca else "normal"
        )
        if invalidos:
            texto_pendencias = (
                "1 pendente" if len(invalidos) == 1 else f"{len(invalidos)} pendentes"
            )
            self.rotulo_pendencias_biblioteca.configure(
                text=texto_pendencias,
                bootstyle="danger inverse",
            )
        else:
            self.rotulo_pendencias_biblioteca.configure(
                text="Tudo revisado",
                bootstyle="success inverse",
            )
        existem_outros = any(
            indice != self.indice_biblioteca for indice in invalidos
        )
        self.botao_proximo_erro_biblioteca.configure(
            text=f"Próximo com erro ({len(invalidos)})",
            state="normal" if existem_outros else "disabled",
        )

    def _ir_para_proximo_erro_biblioteca(self) -> None:
        if self.livro_em_edicao is None or not self.itens_biblioteca:
            return
        invalidos = set(
            self._indices_invalidos_biblioteca(
                self.itens_biblioteca, self.livro_em_edicao.idioma
            )
        )
        for deslocamento in range(1, len(self.itens_biblioteca) + 1):
            indice = (self.indice_biblioteca + deslocamento) % len(
                self.itens_biblioteca
            )
            if indice in invalidos:
                self._ir_para_biblioteca(indice)
                return

    def _exibir_diagrama_biblioteca(self) -> None:
        if not self.itens_biblioteca:
            return
        item = self.itens_biblioteca[self.indice_biblioteca]
        candidato = self.candidatos_biblioteca[self.indice_biblioteca]
        self.rotulo_contador_biblioteca.configure(
            text=f"Diagrama {self.indice_biblioteca + 1} de {len(self.itens_biblioteca)}"
        )
        self.rotulo_origem_biblioteca.configure(
            text=f"Página original: {candidato.pagina}"
        )
        self.campo_fen_biblioteca.delete("1.0", "end")
        self.campo_fen_biblioteca.insert("1.0", item.posicao)
        self._preencher_linhas_fen_biblioteca(item.posicao)
        self.lado_preto_biblioteca.set(item.lado_a_jogar == "b")
        self._atualizar_rotulos_lado_biblioteca()
        self._atualizar_imagem_biblioteca()
        self.botao_anterior_biblioteca.configure(
            state="normal" if self.indice_biblioteca > 0 else "disabled"
        )
        self.botao_primeiro_biblioteca.configure(
            state="normal" if self.indice_biblioteca > 0 else "disabled"
        )
        self.botao_proximo_biblioteca.configure(
            state=(
                "normal"
                if self.indice_biblioteca < len(self.itens_biblioteca) - 1
                else "disabled"
            )
        )
        self.botao_ultimo_biblioteca.configure(
            state=(
                "normal"
                if self.indice_biblioteca < len(self.itens_biblioteca) - 1
                else "disabled"
            )
        )
        self._validar_fen_biblioteca()

    def _agendar_redimensionamento_biblioteca(
        self, _evento: object | None = None
    ) -> None:
        if not self.itens_biblioteca:
            return
        if self._redimensionamento_biblioteca_pendente is not None:
            self.raiz.after_cancel(self._redimensionamento_biblioteca_pendente)
        self._redimensionamento_biblioteca_pendente = self.raiz.after(
            80, self._atualizar_imagem_biblioteca
        )

    def _atualizar_rotulos_lado_biblioteca(self) -> None:
        pretas = self.lado_preto_biblioteca.get()
        self.rotulo_white_biblioteca.configure(
            bootstyle="secondary" if pretas else "primary"
        )
        self.rotulo_black_biblioteca.configure(
            bootstyle="primary" if pretas else "secondary"
        )

    def _alterar_lado_biblioteca(self) -> None:
        self._atualizar_rotulos_lado_biblioteca()
        self._agendar_salvamento_biblioteca(250)

    def _cancelar_salvamento_biblioteca_pendente(self) -> None:
        if self._salvamento_biblioteca_pendente is not None:
            self.raiz.after_cancel(self._salvamento_biblioteca_pendente)
            self._salvamento_biblioteca_pendente = None

    def _agendar_salvamento_biblioteca(self, atraso: int = 650) -> None:
        self._cancelar_salvamento_biblioteca_pendente()
        self.estado_barra.set("Alterações pendentes")
        self._salvamento_biblioteca_pendente = self.raiz.after(
            atraso,
            lambda: self._salvar_automaticamente_biblioteca(
                exigir_todas_validas=False
            ),
        )

    def _atualizar_imagem_biblioteca(self) -> None:
        self._redimensionamento_biblioteca_pendente = None
        if not self.candidatos_biblioteca:
            return
        candidato = self.candidatos_biblioteca[self.indice_biblioteca]
        imagem = candidato.imagem
        if imagem.ndim == 3:
            imagem = cv2.cvtColor(imagem, cv2.COLOR_BGR2RGB)
        pil = Image.fromarray(imagem)
        largura = max(300, self.quadro_imagem_biblioteca.winfo_width() - 24)
        altura = max(300, self.quadro_imagem_biblioteca.winfo_height() - 54)
        escala = min(largura / pil.width, altura / pil.height)
        novo_tamanho = (
            max(1, int(round(pil.width * escala))),
            max(1, int(round(pil.height * escala))),
        )
        if novo_tamanho != pil.size:
            pil = pil.resize(novo_tamanho, Image.Resampling.LANCZOS)
        self._imagem_biblioteca_tk = ImageTk.PhotoImage(pil)
        self.rotulo_imagem_biblioteca.configure(image=self._imagem_biblioteca_tk)

    def _navegar_biblioteca(self, deslocamento: int) -> None:
        if not self._salvar_automaticamente_biblioteca(
            silencioso=False,
            exigir_todas_validas=False,
            exigir_atual_valida=False,
        ):
            return
        novo = min(
            len(self.itens_biblioteca) - 1,
            max(0, self.indice_biblioteca + deslocamento),
        )
        if novo != self.indice_biblioteca:
            self.indice_biblioteca = novo
            self._exibir_diagrama_biblioteca()

    def _ir_para_biblioteca(self, indice: int) -> None:
        if not self._salvar_automaticamente_biblioteca(
            silencioso=False,
            exigir_todas_validas=False,
            exigir_atual_valida=False,
        ):
            return
        self.indice_biblioteca = min(len(self.itens_biblioteca) - 1, max(0, indice))
        self._exibir_diagrama_biblioteca()

    def _diagramas_editados_biblioteca(self) -> list[DiagramaSalvo]:
        return [
            DiagramaSalvo(
                candidato.pagina,
                candidato.confianca,
                item.posicao,
                item.lado_a_jogar,
            )
            for candidato, item in zip(self.candidatos_biblioteca, self.itens_biblioteca)
        ]

    def _persistir_editor_biblioteca(
        self,
        *,
        exigir_todas_validas: bool = True,
        exigir_atual_valida: bool = True,
    ) -> LivroSalvo:
        atual_valido = self._salvar_diagrama_atual_biblioteca()
        livro = self.livro_em_edicao
        if livro is None:
            raise ValueError("Nenhum livro esta aberto.")
        if not atual_valido and exigir_atual_valida:
            _valido, mensagem = validar_posicao(
                self.itens_biblioteca[self.indice_biblioteca].posicao,
                livro.idioma,
            )
            raise ValueError(
                f"Revise o diagrama {self.indice_biblioteca + 1}: {mensagem}"
            )
        if exigir_todas_validas:
            for indice, item in enumerate(self.itens_biblioteca):
                valido, mensagem = validar_posicao(item.posicao, livro.idioma)
                if not valido:
                    self.indice_biblioteca = indice
                    self._exibir_diagrama_biblioteca()
                    raise ValueError(f"Revise o diagrama {indice + 1}: {mensagem}")
        atualizado = self.biblioteca.salvar(
            livro.pdf_interno,
            livro.titulo,
            self._diagramas_editados_biblioteca(),
            idioma=livro.idioma,
            annotator=self.annotator_biblioteca.get().strip(),
            paginas_originais=livro.paginas_originais,
            livro_id=livro.id,
        )
        self.livro_em_edicao = atualizado
        return atualizado

    def _salvar_automaticamente_biblioteca(
        self,
        silencioso: bool = True,
        *,
        exigir_todas_validas: bool = True,
        exigir_atual_valida: bool = True,
    ) -> bool:
        pendente = self._salvamento_biblioteca_pendente
        self._salvamento_biblioteca_pendente = None
        if pendente is not None:
            self.raiz.after_cancel(pendente)
        try:
            self._persistir_editor_biblioteca(
                exigir_todas_validas=exigir_todas_validas,
                exigir_atual_valida=exigir_atual_valida,
            )
            self._atualizar_biblioteca()
            self.estado_barra.set("Alterações salvas automaticamente")
            return True
        except ValueError as erro:
            self.estado_barra.set("Alterações pendentes")
            if not silencioso:
                messagebox.showwarning("Posição inválida", str(erro), parent=self.raiz)
            return False
        except OSError as erro:
            self.logger.exception("Falha ao salvar alterações da biblioteca.")
            self.estado_barra.set("Erro ao salvar")
            if not silencioso:
                messagebox.showerror("Não foi possível salvar", str(erro), parent=self.raiz)
            return False

    def _exportar_pgn_biblioteca(self) -> None:
        self._cancelar_salvamento_biblioteca_pendente()
        try:
            livro = self._persistir_editor_biblioteca()
        except (OSError, ValueError) as erro:
            messagebox.showerror("Nao foi possivel salvar", str(erro), parent=self.raiz)
            return
        diagramas = [diagrama for diagrama in livro.diagramas if diagrama.posicao]
        if not diagramas:
            messagebox.showwarning(
                "Nenhuma posicao valida",
                "Informe ao menos uma posicao valida antes de exportar.",
                parent=self.raiz,
            )
            return
        annotator = simpledialog.askstring(
            "Exportar PGN",
            "Nome do Annotator:",
            initialvalue=livro.annotator,
            parent=self.raiz,
        )
        if annotator is None:
            return
        annotator = annotator.strip()
        self.annotator_biblioteca.set(annotator)
        nome_seguro = "".join(
            "_" if caractere in '<>:"/\\|?*' else caractere for caractere in livro.titulo
        ).strip(" .") or "posicoes"
        destino = filedialog.asksaveasfilename(
            title="Salvar arquivo PGN",
            initialfile=f"{nome_seguro}.pgn",
            defaultextension=".pgn",
            filetypes=[("Arquivos PGN", "*.pgn")],
            parent=self.raiz,
        )
        if not destino:
            return
        try:
            self._persistir_editor_biblioteca()
            exportar_pgn(destino, livro.titulo, diagramas, annotator, livro.idioma)
            self._atualizar_biblioteca()
            messagebox.showinfo(
                "PGN exportado",
                f"{len(diagramas)} posicao(oes) exportada(s) com sucesso.",
                parent=self.raiz,
            )
        except (OSError, ValueError) as erro:
            self.logger.exception("Falha ao exportar PGN.")
            messagebox.showerror("Nao foi possivel exportar", str(erro), parent=self.raiz)

    def _fechar_editor_biblioteca(self) -> None:
        if self.livro_em_edicao is not None and not self._salvar_automaticamente_biblioteca(
            silencioso=False,
            exigir_todas_validas=False,
            exigir_atual_valida=False,
        ):
            return
        self._cancelar_salvamento_biblioteca_pendente()
        self.painel_editor_biblioteca.grid_remove()
        self.painel_lista_biblioteca.grid(row=0, column=0, sticky="nsew")
        self.livro_em_edicao = None
        self.revisando = False
        self.candidatos_biblioteca = []
        self.itens_biblioteca = []
        self._imagem_biblioteca_tk = None
        self.raiz.geometry(f"{LARGURA_JANELA}x{ALTURA_JANELA}")
        self._atualizar_estado_principal()
        self._ao_selecionar_livro()

    def _definir_status(self, mensagem: str, tipo: str = "secondary") -> None:
        self.status.set(mensagem)
        self.rotulo_status.configure(bootstyle=tipo)

    @staticmethod
    def _formatar_tempo(segundos: float) -> str:
        segundos = max(0, int(round(segundos)))
        if segundos < 60:
            return f"{segundos} s"
        minutos, segundos = divmod(segundos, 60)
        if minutos < 60:
            return f"{minutos} min {segundos:02d} s" if segundos else f"{minutos} min"
        horas, minutos = divmod(minutos, 60)
        return f"{horas} h {minutos:02d} min"

    def _mostrar_progresso(
        self,
        percentual: float,
        mensagem: str,
        tipo: str = "info",
        estimar: bool = True,
    ) -> None:
        percentual = max(0.0, min(100.0, percentual))
        self.progresso["value"] = percentual
        self.texto_percentual.set(f"{percentual:.0f}%")
        inicio = self.inicio_progresso
        if estimar and inicio is not None and 0.5 <= percentual < 100:
            decorrido = time.monotonic() - inicio
            if decorrido >= 3.0:
                restante = decorrido * (100.0 - percentual) / percentual
                mensagem += f" — cerca de {self._formatar_tempo(restante)} restantes"
        self._definir_status(mensagem, tipo)

    def _salvar_preferencia(self) -> None:
        try:
            pasta = pasta_dados_aplicativo()
            pasta.mkdir(parents=True, exist_ok=True)
            temporario = pasta / "settings.json.tmp"
            temporario.write_text(
                json.dumps(
                    {
                        "abrir_pdf_ao_concluir": self.abrir_ao_concluir.get(),
                        "incluir_notacao_forsyth": self.incluir_forsyth.get(),
                        "idioma_notacao": self.idioma_notacao.get(),
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            temporario.replace(pasta / "settings.json")
        except OSError:
            self.logger.warning("Não foi possível salvar a preferência da interface.", exc_info=True)

    def _ao_pressionar_enter(self, _evento: object) -> None:
        if str(self.botao_processar.cget("state")) != "disabled" and not self.processando:
            self._iniciar()

    def _abrir_github(self) -> None:
        webbrowser.open(URL_GITHUB)

    def _mostrar_sobre(self) -> None:
        if self.janela_sobre is not None and self.janela_sobre.winfo_exists():
            self.janela_sobre.focus_force()
            return

        janela = ttk.Toplevel(master=self.raiz)
        self.janela_sobre = janela
        janela.title("Sobre")
        janela.geometry("440x285")
        janela.resizable(False, False)
        janela.transient(self.raiz)
        janela.grab_set()
        janela.bind("<Escape>", lambda _evento: janela.destroy())

        janela.update_idletasks()
        x = self.raiz.winfo_rootx() + (self.raiz.winfo_width() - 440) // 2
        y = self.raiz.winfo_rooty() + (self.raiz.winfo_height() - 285) // 2
        janela.geometry(f"440x285+{max(0, x)}+{max(0, y)}")

        conteudo = ttk.Frame(janela, padding=24)
        conteudo.pack(fill="both", expand=True)
        ttk.Label(conteudo, text="Chess Book Diagram Extractor", style="HeaderTitle.TLabel").pack()
        ttk.Label(conteudo, text=f"Versão {__version__}", bootstyle="secondary").pack(pady=(2, 12))
        ttk.Label(
            conteudo,
            text=(
                "Ferramenta para localizar diagramas de xadrez 8×8 em livros PDF "
                "e gerar um novo documento com um diagrama por página."
            ),
            justify="center",
            wraplength=380,
        ).pack()
        ttk.Label(conteudo, text="Desenvolvido por E-Lopes · Licença MIT", bootstyle="secondary").pack(
            pady=(12, 4)
        )
        ttk.Button(
            conteudo,
            text="Abrir repositório no GitHub",
            command=self._abrir_github,
            bootstyle="primary link",
        ).pack()

    def _ao_alterar_entrada(self, *_args: object) -> None:
        if self.processando or self.revisando:
            return
        self._atualizar_estado_principal()

    def _entrada_valida(self) -> bool:
        entrada = Path(self.entrada.get().strip())
        return entrada.is_file() and entrada.suffix.lower() == ".pdf"

    def _atualizar_estado_principal(self) -> None:
        if self.processando or self.revisando or self.atualizando:
            self.botao_processar.configure(state="disabled")
            return
        entrada_valida = self._entrada_valida()
        self.botao_saida.configure(state="normal" if entrada_valida else "disabled")
        valido = entrada_valida and bool(self.saida.get().strip())
        self.botao_processar.configure(state="normal" if valido else "disabled")
        if self.entrada.get().strip() and not self._entrada_valida():
            self._definir_status("Selecione um arquivo PDF válido.", "danger")
        elif valido and self.ultimo_resultado is None:
            self._definir_status("PDF selecionado. Pronto para extrair.", "primary")

    def _ocultar_acoes_resultado(self) -> None:
        self.botao_abrir_pdf.grid_remove()
        self.botao_abrir.grid_remove()

    def _mostrar_acoes_resultado(self) -> None:
        self.botao_abrir_pdf.grid()
        self.botao_abrir.grid()

    def _selecionar_entrada(self) -> None:
        caminho = filedialog.askopenfilename(
            parent=self.raiz,
            title="Selecione o livro em PDF",
            initialdir=self.ultimo_diretorio,
            filetypes=[("Arquivos PDF", "*.pdf"), ("Todos os arquivos", "*.*")],
        )
        if caminho:
            caminho_pdf = Path(caminho)
            self.entrada.set(caminho)
            self.saida.set(sugerir_saida(caminho))
            self.entrada_exibida.set(caminho_pdf.name)
            self.saida_exibida.set(Path(self.saida.get()).name)
            self.rotulo_saida_ok.grid()
            self.tooltip_entrada.text = str(caminho_pdf)
            self.tooltip_saida.text = self.saida.get()
            self.ultimo_diretorio = caminho_pdf.parent
            self.ultimo_resultado = None
            try:
                with fitz.open(caminho_pdf) as documento:
                    paginas = documento.page_count
                tamanho_mb = caminho_pdf.stat().st_size / 1024 / 1024
                self.entrada_info.set(f"{paginas} página(s)  ·  {tamanho_mb:.1f} MB")
                self.estatistica_paginas.set(str(paginas))
            except (OSError, ValueError, RuntimeError):
                self.entrada_info.set("PDF selecionado. O livro original não será alterado.")
                self.estatistica_paginas.set("—")
            self.estatistica_diagramas.set("0")
            self.estatistica_atencao.set("0")
            self.estatistica_excluidos.set("0")
            self.estado_barra.set("PDF selecionado")
            self._ocultar_acoes_resultado()
            self._atualizar_estado_principal()

    def _selecionar_saida(self) -> None:
        entrada = self.entrada.get().strip()
        sugestao = Path(sugerir_saida(entrada)) if entrada else self.ultimo_diretorio / "livro_diagramas.pdf"
        caminho = filedialog.asksaveasfilename(
            parent=self.raiz,
            title="Salvar PDF com os diagramas",
            initialdir=sugestao.parent,
            initialfile=sugestao.name,
            defaultextension=".pdf",
            filetypes=[("Arquivos PDF", "*.pdf")],
        )
        if caminho:
            self.saida.set(caminho)
            self.saida_exibida.set(Path(caminho).name)
            self.rotulo_saida_ok.configure(text="✓ Arquivo de saída definido.")
            self.rotulo_saida_ok.grid()
            self.tooltip_saida.text = caminho
            self.ultimo_diretorio = Path(caminho).parent
            self._atualizar_estado_principal()

    def _validar(self) -> tuple[str, str] | None:
        entrada, saida = self.entrada.get().strip(), self.saida.get().strip()
        if not entrada:
            messagebox.showwarning("Livro não selecionado", "Selecione o livro em PDF.", parent=self.raiz)
            return None
        if not Path(entrada).is_file() or Path(entrada).suffix.lower() != ".pdf":
            messagebox.showerror("Arquivo inválido", "Selecione um arquivo PDF válido.", parent=self.raiz)
            return None
        if not saida:
            messagebox.showwarning("Destino não selecionado", "Escolha onde salvar o PDF de saída.", parent=self.raiz)
            return None
        caminho_saida = Path(saida)
        if Path(entrada).resolve() == caminho_saida.resolve():
            messagebox.showerror("Destino inválido", "O PDF de saída não pode substituir o livro original.", parent=self.raiz)
            return None
        if caminho_saida.suffix.lower() != ".pdf":
            messagebox.showerror("Destino inválido", "O arquivo de saída precisa ter a extensão .pdf.", parent=self.raiz)
            return None
        if not caminho_saida.parent.is_dir() or not os.access(caminho_saida.parent, os.W_OK):
            messagebox.showerror(
                "Pasta sem permissão",
                "Escolha uma pasta em que o aplicativo possa salvar o PDF.",
                parent=self.raiz,
            )
            return None
        return entrada, saida

    def _iniciar(self) -> None:
        validado = self._validar()
        if validado is None:
            return
        entrada, saida = validado
        titulo_livro = Path(entrada).stem
        livro_existente = self.biblioteca.buscar_por_titulo(titulo_livro)
        livro_id: str | None = None
        annotator_existente = ""
        if livro_existente is not None:
            substituir = messagebox.askyesno(
                "Livro já processado",
                (
                    f'Já existe um conjunto de diagramas para "{livro_existente.titulo}".\n\n'
                    "Deseja processar novamente e substituir a cópia interna anterior? "
                    "O PDF original e as cópias exportadas não serão alterados."
                ),
                icon="warning",
                parent=self.raiz,
            )
            if not substituir:
                return
            livro_id = livro_existente.id
            annotator_existente = livro_existente.annotator
        self.cancelamento.clear()
        self.processando = True
        self.estado_barra.set("Processando")
        self.inicio_progresso = time.monotonic()
        self.ultimo_resultado = None
        self._mostrar_progresso(0, "Preparando o livro...", "info", estimar=False)
        self.detalhes.set("O tempo depende da quantidade de páginas.")
        self._ocultar_acoes_resultado()
        self.botao_processar.configure(text="Extraindo...")
        self._alternar_controles(False)
        if self.incluir_forsyth.get():
            threading.Thread(
                target=self._preparar_revisao,
                args=(
                    entrada,
                    saida,
                    self.idioma_notacao.get(),
                    livro_id,
                    annotator_existente,
                ),
                daemon=True,
            ).start()
        else:
            threading.Thread(
                target=self._processar,
                args=(entrada, saida, self.idioma_notacao.get(), livro_id),
                daemon=True,
            ).start()

    def _processar(
        self,
        entrada: str,
        saida: str,
        idioma: str = "pt",
        livro_id: str | None = None,
    ) -> None:
        def informar(atual: int, total: int, encontrados: int) -> None:
            self.eventos.put(("progresso", (atual, total, encontrados)))

        try:
            total_paginas, candidatos = detectar_no_pdf(
                entrada,
                progresso=informar,
                cancelado=self.cancelamento.is_set,
            )
            if not candidatos:
                resultado = ResultadoExtracao(total_paginas, 0, None)
            else:
                arquivo_saida = criar_pdf_a4(
                    candidatos, saida, cancelado=self.cancelamento.is_set
                )
                self.biblioteca.salvar(
                    arquivo_saida,
                    Path(entrada).stem,
                    [
                        DiagramaSalvo(candidato.pagina, candidato.confianca)
                        for candidato in candidatos
                    ],
                    idioma=idioma,
                    paginas_originais=total_paginas,
                    livro_id=livro_id,
                )
                resultado = ResultadoExtracao(total_paginas, len(candidatos), arquivo_saida)
            self.eventos.put(("concluido", resultado))
        except ExtracaoCancelada:
            self.eventos.put(("cancelado", None))
        except Exception as erro:
            self.logger.exception("Falha durante a extração do PDF.")
            self.eventos.put(("erro", erro))

    def _preparar_revisao(
        self,
        entrada: str,
        saida: str,
        idioma: str,
        livro_id: str | None = None,
        annotator: str = "",
    ) -> None:
        def informar(atual: int, total: int, encontrados: int) -> None:
            self.eventos.put(("progresso_deteccao_forsyth", (atual, total, encontrados)))

        try:
            total_paginas, candidatos = detectar_no_pdf(
                entrada,
                progresso=informar,
                cancelado=self.cancelamento.is_set,
            )
            if not candidatos:
                self.eventos.put(("concluido", ResultadoExtracao(total_paginas, 0, None)))
                return

            # O PDF simples é concluído primeiro. A notação trabalha depois
            # sobre as imagens efetivamente gravadas nesse documento.
            arquivo_extraido = criar_pdf_a4(
                candidatos,
                saida,
                cancelado=self.cancelamento.is_set,
            )
            candidatos = carregar_diagramas_do_pdf_extraido(
                arquivo_extraido,
                candidatos,
                cancelado=self.cancelamento.is_set,
            )
            self.eventos.put(("pdf_extraido", (len(candidatos), arquivo_extraido)))

            itens: list[ItemRevisao] = []
            revisor_automatico: RevisorAutomaticoLivro | None = None
            try:
                reconhecedor = ReconhecedorForsyth(idioma=idioma)
            except Exception as erro:
                self.logger.warning("Reconhecimento Forsyth indisponível.", exc_info=True)
                aviso = f"Sugestão automática indisponível: {erro}"
                itens = [ItemRevisao(aviso=aviso) for _ in candidatos]
            else:
                reconhecidos: list[ResultadoReconhecimento | None] = []
                for indice, candidato in enumerate(candidatos, start=1):
                    if self.cancelamento.is_set():
                        raise ExtracaoCancelada("A extração foi cancelada.")
                    try:
                        resultado = reconhecedor.reconhecer(candidato.imagem)
                        reconhecidos.append(resultado)
                    except Exception as erro:
                        self.logger.warning(
                            "Falha ao reconhecer o diagrama %s.", indice, exc_info=True
                        )
                        reconhecidos.append(None)
                    self.eventos.put(("progresso_reconhecimento", (indice, len(candidatos))))

                validos = [resultado for resultado in reconhecidos if resultado is not None]
                if len(validos) == len(candidatos):
                    revisor_automatico = RevisorAutomaticoLivro(
                        validos,
                        idioma=idioma,
                        caminho_pdf=entrada,
                        pasta_dados=pasta_dados_aplicativo(),
                    )
                    revisados = iter(revisor_automatico.revisar())
                    for resultado in reconhecidos:
                        itens.append(
                            ItemRevisao.de_reconhecimento(next(revisados))
                            if resultado is not None
                            else ItemRevisao(aviso="Não foi possível sugerir a posição.")
                        )
                else:
                    itens = [
                        ItemRevisao.de_reconhecimento(resultado)
                        if resultado is not None
                        else ItemRevisao(aviso="Não foi possível sugerir a posição.")
                        for resultado in reconhecidos
                    ]

            if self.cancelamento.is_set():
                raise ExtracaoCancelada("A extração foi cancelada.")
            self.eventos.put(
                (
                    "revisao_pronta",
                    (
                        total_paginas,
                        candidatos,
                        itens,
                        entrada,
                        saida,
                        idioma,
                        revisor_automatico,
                        livro_id,
                        Path(entrada).stem,
                        annotator,
                    ),
                )
            )
        except ExtracaoCancelada:
            self.eventos.put(("cancelado", None))
        except Exception as erro:
            self.logger.exception("Falha durante a preparação da revisão Forsyth.")
            self.eventos.put(("erro", erro))

    def _abrir_revisao(
        self,
        dados: tuple[
            int,
            list[Candidato],
            list[ItemRevisao],
            str,
            str,
            str,
            RevisorAutomaticoLivro | None,
        ],
    ) -> None:
        total_paginas, candidatos, itens, entrada, saida, idioma, revisor_automatico = dados[:7]
        self.estatistica_paginas.set(str(total_paginas))
        self.estatistica_diagramas.set(str(len(candidatos)))
        self.estatistica_atencao.set(
            str(sum(not validar_posicao(item.posicao, idioma)[0] or bool(item.aviso) for item in itens))
        )
        self.estatistica_excluidos.set(str(sum(item.nao_e_tabuleiro for item in itens)))
        self.estado_barra.set("Revisando diagramas")
        livro_id = dados[7] if len(dados) > 7 else None
        titulo_livro = dados[8] if len(dados) > 8 else Path(entrada).stem
        annotator_inicial = dados[9] if len(dados) > 9 else ""
        estado_annotator = {"valor": annotator_inicial}

        def salvar_annotator(valor: str) -> None:
            estado_annotator["valor"] = valor
            if livro_id is None:
                return
            livro = self.biblioteca.carregar(livro_id)
            if livro is None:
                return
            try:
                self.biblioteca.salvar(
                    livro.pdf_interno,
                    livro.titulo,
                    livro.diagramas,
                    idioma=livro.idioma,
                    annotator=valor,
                    paginas_originais=livro.paginas_originais,
                    livro_id=livro.id,
                )
                self._atualizar_biblioteca()
            except OSError:
                self.logger.warning("Nao foi possivel salvar o Annotator.", exc_info=True)
        self.processando = False
        self.revisando = True
        self.botao_cancelar.grid_remove()
        self.botao_processar.configure(text="Visualizando...")
        self._mostrar_progresso(
            100,
            f"{len(candidatos)} diagrama(s) pronto(s) para visualização.",
            "info",
            estimar=False,
        )

        def finalizar(anotacoes: list[AnotacaoSaida]) -> None:
            self.janela_revisao = None
            self.revisando = False
            self.processando = True
            self.inicio_progresso = time.monotonic()
            self.cancelamento.clear()
            self.botao_cancelar.configure(state="normal")
            self.botao_cancelar.grid()
            self._mostrar_progresso(0, "Gerando o PDF revisado...", "info", estimar=False)
            threading.Thread(
                target=self._gerar_pdf_revisado,
                args=(
                    total_paginas,
                    candidatos,
                    anotacoes,
                    entrada,
                    saida,
                    idioma,
                    titulo_livro,
                    estado_annotator["valor"],
                    livro_id,
                ),
                daemon=True,
            ).start()

        def cancelar() -> None:
            self.janela_revisao = None
            self.revisando = False
            self._mostrar_progresso(0, "Visualização pausada.", "warning", estimar=False)
            self.ultimo_resultado = ResultadoExtracao(
                total_paginas,
                len(candidatos),
                Path(saida),
            )
            self._alternar_controles(True)
            self._mostrar_acoes_resultado()
            self._definir_status(
                "Visualização pausada. O PDF de extrações está salvo e o rascunho foi mantido.",
                "warning",
            )

        try:
            self.janela_revisao = JanelaRevisaoForsyth(
                self.raiz,
                candidatos,
                itens,
                entrada,
                pasta_dados_aplicativo(),
                idioma,
                revisor_automatico,
                finalizar,
                cancelar,
                self.logger,
                annotator=annotator_inicial,
                titulo_livro=titulo_livro,
                ao_salvar_annotator=salvar_annotator,
            )
        except Exception as erro:
            self.revisando = False
            self._mostrar_erro(erro)

    def _gerar_pdf_revisado(
        self,
        total_paginas: int,
        candidatos: list[Candidato],
        anotacoes: list[AnotacaoSaida],
        entrada: str,
        saida: str,
        idioma: str,
        titulo_livro: str,
        annotator: str,
        livro_id: str | None,
    ) -> None:
        try:
            rascunho_anterior = caminho_rascunho(entrada, pasta_dados_aplicativo())
            arquivo_saida = criar_pdf_a4(
                candidatos,
                saida,
                anotacoes=anotacoes,
                cancelado=self.cancelamento.is_set,
            )
            mantidas = [anotacao for anotacao in anotacoes if not anotacao.excluir]
            confirmadas = sum(anotacao.posicao is not None for anotacao in mantidas)
            self.biblioteca.salvar(
                arquivo_saida,
                titulo_livro,
                diagramas_de_anotacoes(candidatos, anotacoes),
                idioma=idioma,
                annotator=annotator,
                paginas_originais=total_paginas,
                livro_id=livro_id,
            )
            rascunho_anterior.unlink(missing_ok=True)
            self.eventos.put(
                (
                    "concluido",
                    ResultadoExtracao(
                        total_paginas,
                        len(mantidas),
                        arquivo_saida,
                        confirmadas,
                        len(mantidas) - confirmadas,
                    ),
                )
            )
        except ExtracaoCancelada:
            self.eventos.put(("cancelado", None))
        except Exception as erro:
            self.logger.exception("Falha ao gerar o PDF revisado.")
            self.eventos.put(("erro", erro))

    def _verificar_eventos(self) -> None:
        try:
            while True:
                tipo, dados = self.eventos.get_nowait()
                if tipo == "progresso":
                    atual, total, encontrados = dados  # type: ignore[misc]
                    percentual = atual / max(1, total) * 100
                    self._mostrar_progresso(
                        percentual,
                        f"Processando página {atual} de {total} — {encontrados} diagrama(s) encontrado(s).",
                        "info",
                    )
                elif tipo == "progresso_deteccao_forsyth":
                    atual, total, encontrados = dados  # type: ignore[misc]
                    percentual = atual / max(1, total) * 55
                    self._mostrar_progresso(
                        percentual,
                        f"Localizando diagramas: página {atual} de {total} — {encontrados} encontrado(s).",
                        "info",
                    )
                elif tipo == "progresso_reconhecimento":
                    atual, total = dados  # type: ignore[misc]
                    percentual = 60 + atual / max(1, total) * 40
                    self._mostrar_progresso(
                        percentual,
                        f"Sugerindo posições: diagrama {atual} de {total}.", "info"
                    )
                elif tipo == "pdf_extraido":
                    quantidade, _arquivo = dados  # type: ignore[misc]
                    self._mostrar_progresso(
                        60,
                        f"PDF com {quantidade} extração(ões) criado. Iniciando a notação...",
                        "info",
                    )
                elif tipo == "revisao_pronta":
                    if self.cancelamento.is_set():
                        self._concluir_cancelamento()
                    else:
                        self._abrir_revisao(dados)  # type: ignore[arg-type]
                elif tipo == "concluido":
                    if self.cancelamento.is_set():
                        self._concluir_cancelamento()
                    else:
                        self._concluir(dados)  # type: ignore[arg-type]
                elif tipo == "erro":
                    self._mostrar_erro(dados)  # type: ignore[arg-type]
                elif tipo == "cancelado":
                    self._concluir_cancelamento()
                elif tipo == "biblioteca_carregada":
                    livro, candidatos = dados  # type: ignore[misc]
                    self._mostrar_livro_biblioteca(livro, candidatos)
                elif tipo == "erro_biblioteca":
                    self._mostrar_erro_biblioteca(dados)
                elif tipo == "atualizacao_disponivel":
                    self._oferecer_atualizacao(dados)  # type: ignore[arg-type]
                elif tipo == "atualizacao_ausente":
                    self._atualizacao_ausente()
                elif tipo == "atualizacao_erro":
                    self._erro_atualizacao(dados)  # type: ignore[arg-type]
                elif tipo == "download_atualizacao":
                    recebido, total = dados  # type: ignore[misc]
                    self._mostrar_progresso(
                        recebido / max(1, total) * 100,
                        f"Baixando atualização — {recebido / 1024 / 1024:.1f} de {total / 1024 / 1024:.1f} MB.",
                        "info",
                        estimar=False,
                    )
                elif tipo == "atualizacao_baixada":
                    self._instalar_atualizacao(dados)  # type: ignore[arg-type]
        except queue.Empty:
            pass
        self.raiz.after(100, self._verificar_eventos)

    def _concluir(self, resultado: ResultadoExtracao) -> None:
        self.processando = False
        self.estado_barra.set("Operação concluída")
        self.estatistica_paginas.set(str(resultado.paginas_processadas))
        self.estatistica_diagramas.set(str(resultado.diagramas_encontrados))
        self.estatistica_atencao.set(str(resultado.anotacoes_pendentes))
        self.botao_cancelar.grid_remove()
        self.ultimo_resultado = resultado
        self._mostrar_progresso(100, "Processamento concluído.", "success", estimar=False)
        self._alternar_controles(True)
        self._atualizar_biblioteca()
        if resultado.diagramas_encontrados == 0:
            self._mostrar_progresso(0, "Nenhum diagrama foi encontrado.", "warning", estimar=False)
            self._definir_status("Nenhum diagrama foi encontrado no arquivo selecionado.", "warning")
            self.detalhes.set("Nenhum PDF de saída foi criado.")
            self._ocultar_acoes_resultado()
            return
        if resultado.anotacoes_confirmadas or resultado.anotacoes_pendentes:
            diagramas = (
                "1 diagrama"
                if resultado.diagramas_encontrados == 1
                else f"{resultado.diagramas_encontrados} diagramas"
            )
            posicoes = (
                "1 posição Forsyth salva"
                if resultado.anotacoes_confirmadas == 1
                else f"{resultado.anotacoes_confirmadas} posições Forsyth salvas"
            )
            mensagem = (
                f"{diagramas} e {posicoes}.\n"
                "PDF criado com sucesso."
            )
        else:
            diagramas = (
                "1 diagrama salvo"
                if resultado.diagramas_encontrados == 1
                else f"{resultado.diagramas_encontrados} diagramas salvos"
            )
            mensagem = f"{diagramas}.\nPDF criado com sucesso."
        self._definir_status(mensagem, "success")
        self.detalhes.set(f"Diagramas salvos em {resultado.arquivo_saida}")
        self._mostrar_acoes_resultado()
        if self.abrir_ao_concluir.get():
            self._abrir_pdf()

    def _mostrar_erro(self, erro: object) -> None:
        self.processando = False
        self.estado_barra.set("Erro")
        self.botao_cancelar.grid_remove()
        self._mostrar_progresso(0, "Não foi possível concluir a extração.", "danger", estimar=False)
        self._alternar_controles(True)
        mensagem = str(erro) if isinstance(erro, (ErroExtracao, Exception)) else "Erro desconhecido."
        self._definir_status("Não foi possível concluir a extração.", "danger")
        self.detalhes.set(mensagem)
        messagebox.showerror(
            "Erro na extração",
            "Não foi possível concluir a extração. Verifique o PDF e tente novamente.",
            parent=self.raiz,
        )

    def _cancelar_processamento(self) -> None:
        if not self.processando or self.cancelamento.is_set():
            return
        self.cancelamento.set()
        self.botao_cancelar.configure(state="disabled")
        self._definir_status("Cancelando a extração com segurança...", "warning")
        self.detalhes.set("A etapa atual será encerrada assim que possível.")

    def _concluir_cancelamento(self) -> None:
        self.processando = False
        self.estado_barra.set("Operação cancelada")
        self.cancelamento.clear()
        self.ultimo_resultado = None
        self.botao_cancelar.grid_remove()
        self._alternar_controles(True)
        self._mostrar_progresso(0, "Extração cancelada.", "warning", estimar=False)
        self._definir_status("A extração foi cancelada.", "warning")
        self.detalhes.set("Nenhum arquivo incompleto foi criado.")
        self._ocultar_acoes_resultado()

    def _alternar_controles(self, habilitar: bool) -> None:
        estado_botao = "normal" if habilitar else "disabled"
        estado_campo = "readonly" if habilitar else "disabled"
        self.campo_entrada.configure(state=estado_campo)
        self.campo_saida.configure(state=estado_campo)
        self.botao_entrada.configure(state=estado_botao)
        self.botao_saida.configure(state=estado_botao)
        self.checkbox_abrir.configure(state=estado_botao)
        self.checkbox_forsyth.configure(state=estado_botao)
        self.radio_portugues.configure(state=estado_botao)
        self.radio_ingles.configure(state=estado_botao)
        if habilitar:
            self.botao_cancelar.grid_remove()
            self.botao_processar.configure(text="▷  Extrair diagramas")
            self._atualizar_estado_principal()
            self._ao_selecionar_livro()
        else:
            self.botao_processar.configure(state="disabled")
            self.botao_visualizar_livro.configure(state="disabled")
            self.botao_renomear_livro.configure(state="disabled")
            self.botao_excluir_livro.configure(state="disabled")
            self.botao_cancelar.configure(state="normal")
            self.botao_cancelar.grid()

    def _abrir_pdf(self) -> None:
        if (
            self.ultimo_resultado
            and self.ultimo_resultado.arquivo_saida
            and self.ultimo_resultado.arquivo_saida.is_file()
        ):
            try:
                os.startfile(str(self.ultimo_resultado.arquivo_saida))
            except OSError as erro:
                self.logger.exception("Falha ao abrir o PDF de saída.")
                messagebox.showerror("Não foi possível abrir o PDF", str(erro), parent=self.raiz)
        else:
            self._definir_status("O PDF de saída não foi encontrado.", "warning")

    def _abrir_pasta(self) -> None:
        if (
            self.ultimo_resultado
            and self.ultimo_resultado.arquivo_saida
            and self.ultimo_resultado.arquivo_saida.parent.is_dir()
        ):
            try:
                os.startfile(str(self.ultimo_resultado.arquivo_saida.parent))
            except OSError as erro:
                self.logger.exception("Falha ao abrir a pasta de saída.")
                messagebox.showerror("Não foi possível abrir a pasta", str(erro), parent=self.raiz)
        else:
            self._definir_status("A pasta do resultado não foi encontrada.", "warning")

    def _verificar_atualizacoes(self, silencioso: bool = False) -> None:
        if self.atualizando:
            return
        if not GITHUB_REPOSITORY:
            if not silencioso:
                messagebox.showinfo(
                    "Atualizações",
                    "A verificação automática será ativada nos builds publicados pelo GitHub.",
                    parent=self.raiz,
                )
            return
        self.atualizando = True
        self.verificacao_silenciosa = silencioso
        self.botao_atualizar.configure(state="disabled")
        if not silencioso:
            self._definir_status("Verificando atualizações...", "info")
        threading.Thread(target=self._consultar_atualizacao, daemon=True).start()

    def _consultar_atualizacao(self) -> None:
        try:
            atualizacao = consultar_atualizacao(GITHUB_REPOSITORY, __version__)
            self.eventos.put(("atualizacao_disponivel" if atualizacao else "atualizacao_ausente", atualizacao))
        except Exception as erro:
            self.logger.warning("Falha ao consultar atualizações.", exc_info=True)
            self.eventos.put(("atualizacao_erro", erro))

    def _oferecer_atualizacao(self, atualizacao: Atualizacao) -> None:
        self.atualizando = False
        self.botao_atualizar.configure(state="normal")
        self.atualizacao_pendente = atualizacao
        self._definir_status(f"Nova versão disponível: v{atualizacao.versao}", "info")
        self.botao_instalar_atualizacao.grid()

    def _iniciar_atualizacao_pendente(self) -> None:
        atualizacao = self.atualizacao_pendente
        if atualizacao is None or self.atualizando:
            return
        if self.processando or self.revisando:
            self._definir_status("Conclua a extração antes de instalar a atualização.", "warning")
            return
        self.atualizando = True
        self.atualizacao_pendente = None
        self.botao_atualizar.configure(state="disabled")
        self.botao_instalar_atualizacao.grid_remove()
        self._alternar_controles(False)
        self._definir_status(f"Baixando a versão {atualizacao.versao}...", "info")
        threading.Thread(target=self._baixar_atualizacao, args=(atualizacao,), daemon=True).start()

    def _baixar_atualizacao(self, atualizacao: Atualizacao) -> None:
        try:
            caminho = baixar_atualizacao(
                atualizacao,
                progresso=lambda recebido, total: self.eventos.put(("download_atualizacao", (recebido, total))),
            )
            self.eventos.put(("atualizacao_baixada", caminho))
        except Exception as erro:
            self.logger.warning("Falha ao baixar a atualização.", exc_info=True)
            self.eventos.put(("atualizacao_erro", erro))

    def _atualizacao_ausente(self) -> None:
        self.atualizando = False
        self.botao_atualizar.configure(state="normal")
        self._atualizar_estado_principal()
        if not self.verificacao_silenciosa:
            self._definir_status(f"Você já usa a versão mais recente (v{__version__}).", "success")

    def _erro_atualizacao(self, erro: object) -> None:
        self.atualizando = False
        self.botao_atualizar.configure(state="normal")
        self._alternar_controles(True)
        if not self.verificacao_silenciosa:
            self._definir_status("Não foi possível verificar atualizações.", "warning")
            messagebox.showerror(
                "Erro de atualização",
                "Não foi possível verificar atualizações. Confira sua conexão e tente novamente.",
                parent=self.raiz,
            )

    def _instalar_atualizacao(self, caminho: Path) -> None:
        try:
            iniciar_instalador(caminho)
        except Exception as erro:
            self.logger.exception("Falha ao iniciar o instalador da atualização.")
            self._erro_atualizacao(erro)
            return
        messagebox.showinfo(
            "Atualização iniciada",
            "O aplicativo será fechado e o instalador concluirá a atualização.",
            parent=self.raiz,
        )
        self.raiz.after(300, self.raiz.destroy)

    def _desinstalar(self) -> None:
        """Mantida para compatibilidade; a desinstalação fica no Windows."""
        desinstalador = localizar_desinstalador()
        if desinstalador is None:
            messagebox.showinfo(
                "Desinstalação",
                "Esta opção está disponível quando o aplicativo é instalado pelo Setup.exe.",
                parent=self.raiz,
            )
            return
        if not messagebox.askyesno(
            "Desinstalar Chess Book Diagram Extractor",
            "Deseja abrir o desinstalador do programa?",
            parent=self.raiz,
        ):
            return
        subprocess.Popen([str(desinstalador)], close_fds=True)
        self.raiz.after(300, self.raiz.destroy)

    def _ao_fechar(self) -> None:
        if self.processando or self.revisando:
            messagebox.showwarning(
                "Processamento em andamento",
                "Conclua ou feche a revisão antes de sair do aplicativo.",
                parent=self.raiz,
            )
            return
        if self.atualizando:
            messagebox.showwarning(
                "Atualização em andamento",
                "Aguarde a atualização terminar antes de fechar o aplicativo.",
                parent=self.raiz,
            )
            return
        self.raiz.destroy()


def main() -> None:
    raiz = ttk.Window(themename="litera")
    InterfaceExtrator(raiz)
    raiz.mainloop()


if __name__ == "__main__":
    main()
