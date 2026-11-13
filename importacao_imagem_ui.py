"""Janela para colar ou abrir a imagem de um único diagrama e obter sua FEN."""
from __future__ import annotations

import queue
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog

import numpy as np
import ttkbootstrap as ttk
from ttkbootstrap.widgets import ToolTip

from importacao_imagem import (
    EXTENSOES_IMAGEM,
    ErroImportacaoImagem,
    carregar_imagem,
    fen_completa,
    imagem_da_area_transferencia,
    interpretar_posicao,
    localizar_tabuleiro,
    parece_invertido,
)
from notacao_forsyth import (
    ReconhecedorForsyth,
    converter_idioma_para_padrao,
    converter_padrao_para_idioma,
    girar_posicao,
    separar_posicao_lado,
)
from visualizacao_diagramas import ComparadorDiagramas

TEXTO_INICIAL = (
    "Copie a imagem de um diagrama (site, PDF, captura de tela)\n"
    "e pressione Ctrl+V nesta janela, ou abra um arquivo de imagem."
)


def foco_em_campo_de_texto(janela: tk.Misc) -> bool:
    try:
        widget = janela.focus_get()
    except (KeyError, tk.TclError):
        # focus_get falha quando o foco está em um popup interno do Tk, como a
        # lista de um Combobox. Nesse caso não há campo de texto envolvido.
        return False
    return isinstance(widget, (tk.Entry, tk.Text, ttk.Entry))


class JanelaImportarImagem:
    def __init__(self, pai: tk.Misc, idioma: str, ultimo_diretorio: Path | None = None) -> None:
        self.pai = pai
        self.idioma = idioma
        self.ultimo_diretorio = ultimo_diretorio or Path.home()
        self._reconhecedor: ReconhecedorForsyth | None = None
        self._eventos: queue.Queue = queue.Queue()
        self._trabalhando = False
        self._imagem: np.ndarray | None = None
        self._redimensionamento: str | None = None
        self._aviso_reconhecimento = ""
        self._invertido = False
        self.posicao = tk.StringVar()
        self.lado = tk.StringVar(value="w")
        self.status = tk.StringVar(value="")
        self.aviso = tk.StringVar(value="")

        self.janela = ttk.Toplevel(master=pai)
        self.janela.title("Importar diagrama de imagem")
        self.janela.geometry("980x760")
        self.janela.minsize(720, 600)
        self.janela.transient(pai)
        self._montar()
        for sequencia in ("<Control-v>", "<Control-V>"):
            self.janela.bind(sequencia, self._ao_colar)
        self.janela.bind("<Escape>", lambda _e: self.fechar())
        self.janela.protocol("WM_DELETE_WINDOW", self.fechar)
        self.comparador.bind("<Configure>", self._agendar_redimensionamento)
        self.comparador.limpar(TEXTO_INICIAL)
        self._atualizar_acoes()

    # ---------------------------------------------------------------- layout
    def _montar(self) -> None:
        quadro = ttk.Frame(self.janela, padding=18)
        quadro.pack(fill="both", expand=True)
        quadro.columnconfigure(0, weight=1)
        quadro.rowconfigure(1, weight=1)

        topo = ttk.Frame(quadro)
        topo.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        topo.columnconfigure(2, weight=1)
        ttk.Button(topo, text="Colar imagem  (Ctrl+V)", bootstyle="primary",
                   command=self.colar).grid(row=0, column=0, padx=(0, 8))
        ttk.Button(topo, text="Abrir arquivo…", bootstyle="secondary outline",
                   command=self.abrir_arquivo).grid(row=0, column=1, padx=(0, 12))
        ttk.Label(topo, textvariable=self.status, bootstyle="secondary", anchor="w").grid(
            row=0, column=2, sticky="ew")

        self.comparador = ComparadorDiagramas(quadro, ao_editar=self._editar_pelo_tabuleiro)
        self.comparador.grid(row=1, column=0, sticky="nsew")

        ttk.Label(quadro, textvariable=self.aviso, bootstyle="warning", wraplength=900,
                  justify="left", font=("Segoe UI", 9)).grid(row=2, column=0, sticky="ew", pady=(8, 0))

        linha_fen = ttk.Frame(quadro)
        linha_fen.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        linha_fen.columnconfigure(1, weight=1)
        ttk.Label(linha_fen, text="Posição:").grid(row=0, column=0, padx=(0, 8))
        self.campo_posicao = ttk.Entry(linha_fen, textvariable=self.posicao, font=("Consolas", 11))
        self.campo_posicao.grid(row=0, column=1, sticky="ew")
        self.campo_posicao.bind("<KeyRelease>", lambda _e: self._atualizar_previa())
        self.rotulo_validacao = ttk.Label(linha_fen, text="", width=3, anchor="center")
        self.rotulo_validacao.grid(row=0, column=2, padx=(6, 0))

        acoes = ttk.Frame(quadro)
        acoes.grid(row=4, column=0, sticky="ew", pady=(10, 0))
        ttk.Radiobutton(acoes, text="Brancas jogam", value="w", variable=self.lado,
                        bootstyle="primary").pack(side="left", padx=(0, 10))
        ttk.Radiobutton(acoes, text="Pretas jogam", value="b", variable=self.lado,
                        bootstyle="primary").pack(side="left", padx=(0, 18))
        self.botao_inverter = ttk.Button(acoes, text="⇅  Inverter tabuleiro", bootstyle="secondary outline",
                                         command=self._inverter)
        self.botao_inverter.pack(side="left")
        ToolTip(self.botao_inverter, delay=400, wraplength=320,
                text="Use quando o diagrama mostra as pretas embaixo.")
        self.botao_lichess = ttk.Button(acoes, text="Abrir no Lichess", bootstyle="secondary outline",
                                        command=self._abrir_lichess)
        self.botao_lichess.pack(side="right")
        self.botao_copiar = ttk.Button(acoes, text="Copiar FEN", bootstyle="success",
                                       command=self._copiar_fen)
        self.botao_copiar.pack(side="right", padx=(0, 8))
        ToolTip(self.botao_copiar, delay=400, wraplength=320,
                text="Copia a FEN completa em notação inglesa (KQRBNP), aceita por Lichess, ChessBase etc.")

    # --------------------------------------------------------------- entrada
    def _ao_colar(self, _evento: object = None) -> str | None:
        if foco_em_campo_de_texto(self.janela):
            # Permite colar uma posição digitada; só intercepta se houver imagem.
            imagem = self._imagem_colada(silencioso=True)
            if imagem is None:
                return None
            self.processar(imagem, "Imagem colada")
            return "break"
        self.colar()
        return "break"

    def _imagem_colada(self, silencioso: bool = False) -> np.ndarray | None:
        try:
            imagem = imagem_da_area_transferencia()
        except ErroImportacaoImagem as erro:
            if not silencioso:
                self._mostrar_erro(str(erro))
            return None
        if imagem is None and not silencioso:
            self._mostrar_erro("A área de transferência não contém uma imagem. "
                               "Copie o diagrama (botão direito → Copiar imagem, ou Win+Shift+S).")
        return imagem

    def colar(self) -> None:
        imagem = self._imagem_colada()
        if imagem is not None:
            self.processar(imagem, "Imagem colada")

    def abrir_arquivo(self) -> None:
        padrao = " ".join(f"*{e}" for e in EXTENSOES_IMAGEM)
        caminho = filedialog.askopenfilename(
            parent=self.janela, title="Abrir imagem do diagrama",
            initialdir=str(self.ultimo_diretorio),
            filetypes=[("Imagens", padrao), ("Todos os arquivos", "*.*")],
        )
        if not caminho:
            return
        self.ultimo_diretorio = Path(caminho).parent
        try:
            imagem = carregar_imagem(caminho)
        except ErroImportacaoImagem as erro:
            self._mostrar_erro(str(erro))
            return
        self.processar(imagem, Path(caminho).name)

    # --------------------------------------------------------- reconhecimento
    def processar(self, imagem: np.ndarray, origem: str) -> None:
        if self._trabalhando:
            self.status.set("Aguarde o reconhecimento atual terminar e cole novamente.")
            return
        self._trabalhando = True
        self.status.set(f"{origem}: localizando o tabuleiro e reconhecendo as peças…")
        self.aviso.set("")
        self.comparador.indicar_trabalho("Reconhecendo…")
        self._atualizar_acoes()
        threading.Thread(target=self._reconhecer, args=(imagem, origem, self.idioma), daemon=True).start()
        self.janela.after(50, self._consultar)

    def _reconhecer(self, imagem: np.ndarray, origem: str, idioma: str) -> None:
        try:
            # Só uma thread de reconhecimento roda por vez; o reconhecedor
            # carrega três modelos e é reaproveitado entre colagens.
            if self._reconhecedor is None:
                self._reconhecedor = ReconhecedorForsyth(idioma=idioma)
            self._reconhecedor.idioma = idioma
            tabuleiro = localizar_tabuleiro(imagem)
            resultado = self._reconhecedor.reconhecer(tabuleiro.imagem)
            self._eventos.put((True, (origem, tabuleiro, resultado, idioma)))
        except Exception as erro:  # noqa: BLE001 - exibido na janela
            self._eventos.put((False, erro))

    def _consultar(self) -> None:
        if not self.existe():
            return
        try:
            sucesso, dados = self._eventos.get_nowait()
        except queue.Empty:
            self.janela.after(50, self._consultar)
            return
        self._trabalhando = False
        self.comparador.indicar_trabalho("")
        if not sucesso:
            self._mostrar_erro(f"Falha no reconhecimento: {dados}")
            self._atualizar_acoes()
            return
        origem, tabuleiro, resultado, idioma = dados
        posicao = resultado.posicao
        if idioma != self.idioma:  # Notação trocada durante o reconhecimento.
            posicao = converter_padrao_para_idioma(converter_idioma_para_padrao(posicao, idioma), self.idioma)
        self._imagem = tabuleiro.imagem
        self.posicao.set(posicao)
        self.lado.set("w")
        self._invertido = False
        localizacao = ("tabuleiro localizado na imagem" if tabuleiro.detectado
                       else "nenhuma moldura encontrada; usada a imagem inteira")
        self.status.set(f"{origem}: {localizacao}.")
        avisos = [resultado.aviso] if resultado.aviso else []
        if not tabuleiro.detectado:
            avisos.append("Se a reconstrução estiver errada, recorte a imagem apenas no tabuleiro e cole novamente.")
        if parece_invertido(posicao, self.idioma):
            avisos.append("Pelos peões, as pretas parecem estar embaixo neste diagrama: "
                          "confira e use Inverter tabuleiro se for o caso.")
        self._aviso_reconhecimento = " ".join(avisos)
        self._mostrar_aviso()
        self._atualizar_previa()

    def _mostrar_aviso(self) -> None:
        texto = self._aviso_reconhecimento
        if texto and self._invertido:
            texto = ("Tabuleiro invertido; as casas citadas a seguir seguem a orientação da imagem. "
                     + texto)
        self.aviso.set(texto)

    # ----------------------------------------------------------------- edição
    def definir_idioma(self, idioma: str) -> None:
        """Acompanha a troca de Português/Inglês feita na janela principal."""
        if idioma == self.idioma:
            return
        anterior = self.idioma
        posicao = self._posicao_valida()
        self.idioma = idioma
        if posicao is not None:
            self.posicao.set(converter_padrao_para_idioma(converter_idioma_para_padrao(posicao, anterior), idioma))
        self._atualizar_previa()

    def _editar_pelo_tabuleiro(self, texto: str) -> None:
        posicao, _lado = separar_posicao_lado(texto, self.lado.get())
        self.posicao.set(posicao)
        self._atualizar_previa()

    def _inverter(self) -> None:
        posicao = self._posicao_valida()
        if posicao is not None:
            self.posicao.set(girar_posicao(posicao, self.idioma))
            self._invertido = not self._invertido
            self._mostrar_aviso()
            self._atualizar_previa()

    def _posicao_valida(self) -> str | None:
        return interpretar_posicao(self.posicao.get(), self.idioma)[0]

    def _texto_previa(self) -> str:
        # A prévia usa a posição já interpretada, para que uma FEN completa ou
        # no outro alfabeto seja desenhada exatamente como será copiada.
        return self._posicao_valida() or self.posicao.get().strip()

    def _atualizar_previa(self) -> None:
        posicao, lado = interpretar_posicao(self.posicao.get(), self.idioma)
        if lado is not None:
            self.lado.set(lado)
        if self._imagem is not None:
            self.comparador.exibir(self._imagem, self._texto_previa(), self.idioma)
        valida = posicao is not None
        self.rotulo_validacao.configure(text="✓" if valida else "✗",
                                        bootstyle="success" if valida else "danger")
        self._atualizar_acoes()

    def _agendar_redimensionamento(self, _evento: object = None) -> None:
        if self._redimensionamento is not None:
            self.janela.after_cancel(self._redimensionamento)
        self._redimensionamento = self.janela.after(120, self._redimensionar)

    def _redimensionar(self) -> None:
        self._redimensionamento = None
        if self.existe() and self._imagem is not None:
            self.comparador.exibir(self._imagem, self._texto_previa(), self.idioma)

    def _atualizar_acoes(self) -> None:
        estado = "normal" if self._posicao_valida() is not None and not self._trabalhando else "disabled"
        for botao in (self.botao_copiar, self.botao_lichess, self.botao_inverter):
            botao.configure(state=estado)

    # ---------------------------------------------------------------- saídas
    def fen_atual(self) -> str | None:
        posicao = self._posicao_valida()
        return None if posicao is None else fen_completa(posicao, self.lado.get(), self.idioma)

    def _copiar_fen(self) -> None:
        fen = self.fen_atual()
        if fen is None:
            return
        self.janela.clipboard_clear()
        self.janela.clipboard_append(fen)
        self.status.set(f"FEN copiada: {fen}")

    def _abrir_lichess(self) -> None:
        fen = self.fen_atual()
        if fen is not None:
            webbrowser.open("https://lichess.org/editor/" + fen.replace(" ", "_"))

    def _mostrar_erro(self, mensagem: str) -> None:
        self.status.set("")
        self.aviso.set(mensagem)

    # ---------------------------------------------------------------- janela
    def mostrar(self) -> None:
        self.janela.deiconify()
        self.janela.lift()
        self.janela.focus_force()

    def existe(self) -> bool:
        try:
            return bool(self.janela.winfo_exists())
        except tk.TclError:
            return False

    def fechar(self) -> None:
        if self._redimensionamento is not None:
            self.janela.after_cancel(self._redimensionamento)
            self._redimensionamento = None
        self.janela.destroy()
