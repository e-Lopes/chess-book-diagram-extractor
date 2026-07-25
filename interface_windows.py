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
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox

import ttkbootstrap as ttk
from ttkbootstrap.style import ThemeDefinition
from ttkbootstrap.widgets import ToolTip

from autoupdate import Atualizacao, baixar_atualizacao, consultar_atualizacao, iniciar_instalador
from extrair_tabuleiros_pdf import (
    AnotacaoSaida,
    Candidato,
    ErroExtracao,
    ExtracaoCancelada,
    ResultadoExtracao,
    carregar_diagramas_do_pdf_extraido,
    criar_pdf_a4,
    detectar_no_pdf,
    processar_pdf,
)
from notacao_forsyth import (
    ItemRevisao,
    ReconhecedorForsyth,
    RevisorAutomaticoLivro,
    ResultadoReconhecimento,
    remover_rascunho,
)
from revisor_forsyth import JanelaRevisaoForsyth
from version import GITHUB_REPOSITORY, __version__


TEMA = "chesslight"
LARGURA_JANELA = 760
ALTURA_JANELA = 460
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
        self.raiz.minsize(720, 440)
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
        self.abrir_ao_concluir = tk.BooleanVar(value=carregar_preferencia_abrir_pdf())
        self.incluir_forsyth = tk.BooleanVar(value=carregar_preferencia_incluir_forsyth())
        self.idioma_notacao = tk.StringVar(value=carregar_preferencia_idioma_notacao())
        self.status = tk.StringVar(value="Selecione um arquivo PDF para começar.")
        self.texto_percentual = tk.StringVar(value="0%")
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
        self.janela_revisao: JanelaRevisaoForsyth | None = None
        self.ultimo_diretorio = Path.cwd()
        self.logger = configurar_logger()

        self._configurar_estilo()
        self._montar_tela()
        self.entrada.trace_add("write", self._ao_alterar_entrada)
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
                        "primary": "#176B5B",
                        "secondary": "#667085",
                        "success": "#16803A",
                        "info": "#176B5B",
                        "warning": "#B26A00",
                        "danger": "#C62828",
                        "light": "#F5F7FA",
                        "dark": "#18212F",
                        "bg": "#F5F7FA",
                        "fg": "#18212F",
                        "selectbg": "#176B5B",
                        "selectfg": "#FFFFFF",
                        "border": "#D0D5DD",
                        "inputfg": "#18212F",
                        "inputbg": "#FFFFFF",
                        "active": "#E7ECEA",
                    },
                )
            )
        estilo.theme_use(TEMA)
        estilo.configure("TLabel", font=("Segoe UI", 10))
        estilo.configure("TButton", font=("Segoe UI", 10))
        estilo.configure("TCheckbutton", font=("Segoe UI", 9))
        estilo.configure("HeaderTitle.TLabel", font=("Segoe UI", 20, "bold"))
        estilo.configure("HeaderSubtitle.TLabel", font=("Segoe UI", 10))
        estilo.configure("FieldLabel.TLabel", font=("Segoe UI", 10, "bold"))
        estilo.configure("Status.TLabel", font=("Segoe UI", 9))
        estilo.configure("Footer.TLabel", font=("Segoe UI", 9))
        estilo.configure("primary.TButton", font=("Segoe UI", 10, "bold"), padding=(18, 11))
        estilo.configure("primary.Outline.TButton", font=("Segoe UI", 10), padding=(12, 8))
        estilo.configure("secondary.Outline.TButton", font=("Segoe UI", 10), padding=(12, 8))
        estilo.configure("success.Outline.TButton", font=("Segoe UI", 10), padding=(12, 8))
        estilo.configure("info.Outline.TButton", font=("Segoe UI", 9, "bold"), padding=(10, 6))
        estilo.configure("TEntry", padding=(9, 7), font=("Segoe UI", 9))

    def _centralizar_janela(self) -> None:
        self.raiz.update_idletasks()
        largura = max(self.raiz.winfo_width(), LARGURA_JANELA)
        altura = max(self.raiz.winfo_height(), ALTURA_JANELA)
        x = max(0, (self.raiz.winfo_screenwidth() - largura) // 2)
        y = max(0, (self.raiz.winfo_screenheight() - altura) // 2)
        self.raiz.geometry(f"{largura}x{altura}+{x}+{y}")

    def _montar_tela(self) -> None:
        principal = ttk.Frame(self.raiz, padding=(24, 20, 24, 12))
        principal.pack(fill="both", expand=True)
        principal.columnconfigure(0, weight=1)
        principal.rowconfigure(1, weight=1)

        self._criar_cabecalho(principal)
        self._criar_formulario(principal)
        self._criar_opcoes(principal)
        self._criar_progresso_e_acoes(principal)
        self._criar_rodape(principal)

    def _criar_cabecalho(self, principal: ttk.Frame) -> None:
        cabecalho = ttk.Frame(principal)
        cabecalho.grid(row=0, column=0, sticky="ew", pady=(0, 16))
        cabecalho.columnconfigure(0, weight=1)

        ttk.Label(
            cabecalho,
            text="Extraia diagramas de livros em PDF",
            style="HeaderTitle.TLabel",
        ).grid(row=0, column=0, sticky="sw")
        ttk.Label(
            cabecalho,
            text="Localize tabuleiros 8×8 e revise a notação das peças",
            style="HeaderSubtitle.TLabel",
            bootstyle="secondary",
        ).grid(row=1, column=0, sticky="nw", pady=(2, 0))

        self.botao_atualizar = ttk.Menubutton(
            cabecalho,
            text="Opções",
            bootstyle="secondary outline",
            direction="below",
        )
        self.botao_atualizar.grid(row=0, column=1, rowspan=2, sticky="ne")
        menu_acoes = tk.Menu(self.botao_atualizar, tearoff=False)
        menu_acoes.add_command(label="Verificar atualizações", command=self._verificar_atualizacoes)
        menu_acoes.add_command(label="Abrir página do GitHub", command=self._abrir_github)
        menu_acoes.add_separator()
        menu_acoes.add_command(label="Sobre", command=self._mostrar_sobre)
        menu_acoes.add_command(label="Sair", command=self._ao_fechar)
        self.botao_atualizar["menu"] = menu_acoes
        ToolTip(self.botao_atualizar, text="Mais opções", delay=400)

    def _criar_formulario(self, principal: ttk.Frame) -> None:
        formulario = ttk.Frame(principal, padding=16, bootstyle="@card")
        formulario.grid(row=1, column=0, sticky="nsew")
        formulario.columnconfigure(0, weight=1)

        ttk.Label(formulario, text="Arquivo de entrada", style="FieldLabel.TLabel").grid(
            row=0, column=0, columnspan=2, sticky="w"
        )
        self.campo_entrada = ttk.Entry(formulario, textvariable=self.entrada_exibida, state="readonly")
        self.campo_entrada.grid(row=1, column=0, sticky="ew", padx=(0, 10), pady=(5, 12))
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
        self.botao_entrada.grid(row=1, column=1, sticky="e", pady=(5, 12))

        ttk.Label(formulario, text="Arquivo de saída", style="FieldLabel.TLabel").grid(
            row=2, column=0, columnspan=2, sticky="w"
        )
        self.campo_saida = ttk.Entry(formulario, textvariable=self.saida_exibida, state="readonly")
        self.campo_saida.grid(row=3, column=0, sticky="ew", padx=(0, 10), pady=(5, 0))
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
        self.botao_saida.grid(row=3, column=1, sticky="e", pady=(5, 0))

    def _criar_opcoes(self, principal: ttk.Frame) -> None:
        opcoes = ttk.Frame(principal)
        opcoes.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        self.checkbox_abrir = ttk.Checkbutton(
            opcoes,
            text="Abrir o PDF ao concluir",
            variable=self.abrir_ao_concluir,
            bootstyle="primary",
            command=self._salvar_preferencia,
        )
        self.checkbox_abrir.pack(side="left")
        self.checkbox_forsyth = ttk.Checkbutton(
            opcoes,
            text="Incluir notação Forsyth",
            variable=self.incluir_forsyth,
            bootstyle="primary",
            command=self._salvar_preferencia,
        )
        self.checkbox_forsyth.pack(side="left", padx=(22, 0))
        ttk.Label(opcoes, text="Idioma:", bootstyle="secondary").pack(side="left", padx=(22, 5))
        self.radio_portugues = ttk.Radiobutton(
            opcoes,
            text="Português",
            variable=self.idioma_notacao,
            value="pt",
            bootstyle="primary",
            command=self._salvar_preferencia,
        )
        self.radio_portugues.pack(side="left")
        self.radio_ingles = ttk.Radiobutton(
            opcoes,
            text="Inglês",
            variable=self.idioma_notacao,
            value="en",
            bootstyle="primary",
            command=self._salvar_preferencia,
        )
        self.radio_ingles.pack(side="left", padx=(8, 0))

    def _criar_progresso_e_acoes(self, principal: ttk.Frame) -> None:
        linha_progresso = ttk.Frame(principal)
        linha_progresso.grid(row=3, column=0, sticky="ew", pady=(12, 7))
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
            font=("Segoe UI", 9, "bold"),
            bootstyle="secondary",
        ).grid(row=0, column=1, padx=(10, 0))

        linha_status = ttk.Frame(principal)
        linha_status.grid(row=4, column=0, sticky="ew")
        linha_status.columnconfigure(0, weight=1)
        self.rotulo_status = ttk.Label(
            linha_status,
            textvariable=self.status,
            style="Status.TLabel",
            bootstyle="secondary",
            anchor="w",
        )
        self.rotulo_status.grid(row=0, column=0, sticky="ew")
        self.botao_instalar_atualizacao = ttk.Button(
            linha_status,
            text="Atualizar",
            command=self._iniciar_atualizacao_pendente,
            bootstyle="info outline",
        )
        self.botao_instalar_atualizacao.grid(row=0, column=1, sticky="e", padx=(10, 0))
        self.botao_instalar_atualizacao.grid_remove()
        ToolTip(
            self.botao_instalar_atualizacao,
            text="Baixar e instalar a nova versão disponível.",
            delay=400,
        )

        acoes = ttk.Frame(principal)
        acoes.grid(row=5, column=0, sticky="ew", pady=(14, 0))
        acoes.columnconfigure(1, weight=1)

        self.botao_abrir_pdf = ttk.Button(
            acoes,
            text="Abrir PDF",
            command=self._abrir_pdf,
            bootstyle="success outline",
        )
        self.botao_abrir_pdf.grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.botao_abrir = ttk.Button(
            acoes,
            text="Abrir pasta",
            command=self._abrir_pasta,
            bootstyle="secondary outline",
        )
        self.botao_abrir.grid(row=0, column=1, sticky="w")
        ToolTip(self.botao_abrir, text="Abrir a pasta onde o PDF foi salvo.", delay=400)
        self.botao_processar = ttk.Button(
            acoes,
            text="Extrair diagramas",
            command=self._iniciar,
            state="disabled",
            bootstyle="primary",
        )
        self.botao_processar.grid(row=0, column=3, sticky="e")
        self.botao_cancelar = ttk.Button(
            acoes,
            text="Cancelar",
            command=self._cancelar_processamento,
            bootstyle="danger outline",
        )
        self.botao_cancelar.grid(row=0, column=2, sticky="e", padx=(0, 10))
        self.botao_cancelar.grid_remove()
        self._ocultar_acoes_resultado()

    def _criar_rodape(self, principal: ttk.Frame) -> None:
        rodape = ttk.Frame(principal)
        rodape.grid(row=6, column=0, sticky="ew", pady=(12, 0))
        ttk.Separator(rodape).pack(fill="x", pady=(0, 7))
        ttk.Label(
            rodape,
            text=f"v{__version__} · E-Lopes",
            style="Footer.TLabel",
            bootstyle="secondary",
        ).pack(side="right")

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
            self.tooltip_entrada.text = str(caminho_pdf)
            self.tooltip_saida.text = self.saida.get()
            self.ultimo_diretorio = caminho_pdf.parent
            self.ultimo_resultado = None
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
        self.cancelamento.clear()
        self.processando = True
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
                args=(entrada, saida, self.idioma_notacao.get()),
                daemon=True,
            ).start()
        else:
            threading.Thread(target=self._processar, args=(entrada, saida), daemon=True).start()

    def _processar(self, entrada: str, saida: str) -> None:
        def informar(atual: int, total: int, encontrados: int) -> None:
            self.eventos.put(("progresso", (atual, total, encontrados)))

        try:
            resultado = processar_pdf(
                entrada,
                saida,
                progresso=informar,
                cancelado=self.cancelamento.is_set,
            )
            self.eventos.put(("concluido", resultado))
        except ExtracaoCancelada:
            self.eventos.put(("cancelado", None))
        except Exception as erro:
            self.logger.exception("Falha durante a extração do PDF.")
            self.eventos.put(("erro", erro))

    def _preparar_revisao(self, entrada: str, saida: str, idioma: str) -> None:
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
        total_paginas, candidatos, itens, entrada, saida, idioma, revisor_automatico = dados
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
                args=(total_paginas, candidatos, anotacoes, entrada, saida),
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
    ) -> None:
        try:
            arquivo_saida = criar_pdf_a4(
                candidatos,
                saida,
                anotacoes=anotacoes,
                cancelado=self.cancelamento.is_set,
            )
            mantidas = [anotacao for anotacao in anotacoes if not anotacao.excluir]
            confirmadas = sum(anotacao.posicao is not None for anotacao in mantidas)
            remover_rascunho(entrada, pasta_dados_aplicativo())
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
        self.botao_cancelar.grid_remove()
        self.ultimo_resultado = resultado
        self._mostrar_progresso(100, "Processamento concluído.", "success", estimar=False)
        self._alternar_controles(True)
        if resultado.diagramas_encontrados == 0:
            self._mostrar_progresso(0, "Nenhum diagrama foi encontrado.", "warning", estimar=False)
            self._definir_status("Nenhum diagrama foi encontrado no arquivo selecionado.", "warning")
            self.detalhes.set("Nenhum PDF de saída foi criado.")
            self._ocultar_acoes_resultado()
            return
        if resultado.anotacoes_confirmadas or resultado.anotacoes_pendentes:
            mensagem = (
                f"{resultado.diagramas_encontrados} diagrama(s); "
                f"{resultado.anotacoes_confirmadas} posição(ões) confirmada(s). PDF criado com sucesso."
            )
        else:
            mensagem = (
                f"{resultado.diagramas_encontrados} diagrama(s) encontrado(s). PDF criado com sucesso."
            )
        self._definir_status(mensagem, "success")
        self.detalhes.set(f"Diagramas salvos em {resultado.arquivo_saida}")
        self._mostrar_acoes_resultado()
        if self.abrir_ao_concluir.get():
            self._abrir_pdf()

    def _mostrar_erro(self, erro: object) -> None:
        self.processando = False
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
            self.botao_processar.configure(text="Extrair diagramas")
            self._atualizar_estado_principal()
        else:
            self.botao_processar.configure(state="disabled")
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
