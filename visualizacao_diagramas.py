"""Prévia comum aos dois revisores, com comparação sem alterar os recortes."""
from __future__ import annotations

import cv2
import numpy as np
import tkinter as tk
import ttkbootstrap as ttk
from PIL import Image, ImageTk
from ttkbootstrap.widgets import ToolTip

from tabuleiros_padronizados import renderizar_previa
from notacao_forsyth import substituir_casa


class ComparadorDiagramas(ttk.Frame):
    def __init__(self, master, ao_editar=None):
        super().__init__(master, width=200, height=200)
        self.columnconfigure(0, weight=1, uniform="diagramas")
        self.columnconfigure(1, weight=0)
        self.columnconfigure(2, weight=1, uniform="diagramas")
        self.rowconfigure(0, weight=1)
        self.paineis = {}
        self.rotulos = {}
        self._imagens_tk = {}
        self._chave_previa = None
        self._previsao = None
        self.ao_editar = ao_editar
        self._texto = ""
        self._idioma = "pt"
        self._tamanho_padronizado = None
        self._seletor = None
        self._icones = {}
        self._modo = None
        self._origem_cache = None
        self._chaves_imagens = {}
        self._selecionada = None
        self._arraste = None
        self._paleta = None
        self.trabalho = ttk.Frame(self)
        self.progresso = ttk.Progressbar(self.trabalho, mode="indeterminate", length=48)
        self.progresso.pack(side="left", padx=(0, 8))
        self.rotulo_trabalho = ttk.Label(self.trabalho, bootstyle="secondary", font=("Segoe UI", 9))
        self.rotulo_trabalho.pack(side="left")
        self.seta = ttk.Label(self, text="→", font=("Segoe UI", 22), bootstyle="secondary", anchor="center")
        for nome, titulo in (("original", "Original"), ("padronizado", "Reconstruído pela Forsyth")):
            painel = ttk.Frame(self, width=100, height=100)
            painel.grid_propagate(False)
            painel.columnconfigure(0, weight=1)
            painel.rowconfigure(1, weight=1)
            ttk.Label(painel, text=titulo, anchor="center", bootstyle="secondary").grid(
                row=0, column=0, sticky="ew", pady=(0, 8))
            rotulo = ttk.Label(painel, anchor="center", justify="center", wraplength=180)
            rotulo.grid(row=1, column=0, sticky="nsew")
            self.paineis[nome] = painel
            self.rotulos[nome] = rotulo
        self.rotulos["padronizado"].bind("<Button-1>", self._clicar_casa)
        self._bordas = [tk.Frame(self.rotulos["padronizado"], background="#1769C2") for _ in range(4)]

    def exibir(self, original: np.ndarray, posicao: str, idioma: str, modo: str = "comparar"):
        if self._origem_cache is not None and original is not self._origem_cache:
            self._marcar_casa(None)
        self._origem_cache = original  # Mantém a identidade também no modo reconstruído.
        self._texto, self._idioma = posicao, idioma
        self._tamanho_padronizado = None
        nomes = ("original", "padronizado") if modo == "comparar" else (modo,)
        if any(nome not in self.paineis for nome in nomes):
            raise ValueError("Modo de visualização inválido.")
        if modo != self._modo:
            for painel in self.paineis.values():
                painel.grid_remove()
            self.seta.grid_remove()
            if len(nomes) == 2:
                self.seta.grid(row=0, column=1, sticky="ns", padx=5)
            for coluna, nome in enumerate(nomes):
                self.paineis[nome].grid(row=0, column=coluna * 2, sticky="nsew", padx=0,
                    columnspan=1 if len(nomes) == 2 else 3)
            self._modo = modo
        largura = max(48, (self.winfo_width() - (40 if len(nomes) == 2 else 0)) // len(nomes))
        altura = max(48, self.winfo_height() - 32
                     - (65 if self.ao_editar and "padronizado" in nomes else 0)
                     - (24 if self.trabalho.winfo_manager() else 0))
        for nome in nomes:
            imagem = original
            if nome == "padronizado":
                chave = (posicao, idioma)
                if chave != self._chave_previa:
                    try:
                        self._previsao = renderizar_previa(posicao, idioma)
                    except ValueError:
                        self._previsao = None
                    self._chave_previa = chave
                imagem = self._previsao
            rotulo = self.rotulos[nome]
            if imagem is None:
                self._imagens_tk.pop(nome, None)
                self._chaves_imagens.pop(nome, None)
                rotulo.configure(image="", text="Forsyth inválida.\nCorrija a posição para montar o tabuleiro.", bootstyle="danger", cursor="")
                self._marcar_casa(None)
                continue
            chave_imagem = (id(original) if nome == "original" else self._chave_previa, largura, altura)
            if nome == "original":
                self._origem_cache = original  # Impede reutilização de id após trocar de diagrama.
            if chave_imagem == self._chaves_imagens.get(nome):
                if nome == "padronizado":
                    previa = self._imagens_tk[nome]
                    self._tamanho_padronizado = previa.width(), previa.height()
                continue
            rgb = cv2.cvtColor(imagem, cv2.COLOR_BGR2RGB) if imagem.ndim == 3 else imagem
            pil = Image.fromarray(rgb)
            escala = min(largura / pil.width, altura / pil.height)
            pil = pil.resize((max(1, round(pil.width * escala)), max(1, round(pil.height * escala))),
                             Image.Resampling.LANCZOS)
            self._imagens_tk[nome] = ImageTk.PhotoImage(pil)
            self._chaves_imagens[nome] = chave_imagem
            rotulo.configure(image=self._imagens_tk[nome], text="", bootstyle="default",
                             cursor="hand2" if nome == "padronizado" and self.ao_editar else "")
            if nome == "padronizado":
                self._tamanho_padronizado = pil.size
        if self.ao_editar and "padronizado" in nomes:
            self._mostrar_paleta()
            self._marcar_casa(self._selecionada)
        elif self._paleta is not None:
            self._paleta.grid_remove()
            self._marcar_casa(None)

    def _icone_peca(self, padrao):
        if padrao not in self._icones:
            imagem = renderizar_previa(f"{padrao}7/8/8/8/8/8/8/8", "en")[:100, :100]
            pil = Image.fromarray(cv2.cvtColor(imagem, cv2.COLOR_BGR2RGB)).resize((32, 32), Image.Resampling.LANCZOS)
            self._icones[padrao] = ImageTk.PhotoImage(pil)
        return self._icones[padrao]

    def _mostrar_paleta(self):
        if self._paleta is None:
            self._paleta = ttk.Frame(self)
            ttk.Label(self._paleta, text="Arraste para o tabuleiro ou clique em uma casa.",
                      bootstyle="secondary", font=("Segoe UI", 9)).grid(row=0, column=0, columnspan=13, sticky="w")
            nomes = ("Rei", "Dama", "Torre", "Bispo", "Cavalo", "Peão")
            for indice, peca in enumerate("KQRBNPkqrbnp" + " "):
                peca = peca.strip()
                botao = ttk.Button(self._paleta, bootstyle="secondary outline", padding=2,
                                  image=self._icone_peca(peca) if peca else "", text="×" if not peca else "",
                                  width=3 if not peca else None, cursor="hand2")
                botao.grid(row=1, column=indice, padx=1, pady=(3, 0))
                titulo = (f"{nomes[indice % 6]} {'branco' if indice < 6 else 'preto'}" if peca else "Casa vazia")
                ToolTip(botao, text=f"{titulo} — arraste para substituir", delay=400)
                botao.bind("<ButtonPress-1>", lambda evento, p=peca: self._iniciar_arraste(evento, p))
                botao.bind("<B1-Motion>", self._mover_arraste)
                botao.bind("<ButtonRelease-1>", self._terminar_arraste)
        self._paleta.grid(row=1, column=0, columnspan=3, sticky="w", pady=(5, 0))

    def _marcar_casa(self, casa):
        self._selecionada = casa
        if casa is None or self._tamanho_padronizado is None:
            for borda in self._bordas:
                borda.place_forget()
            return
        largura, altura = self._tamanho_padronizado
        rotulo = self.rotulos["padronizado"]
        linha, coluna = casa
        x = round((rotulo.winfo_width() - largura) / 2 + coluna * largura / 8)
        y = round((rotulo.winfo_height() - altura) / 2 + linha * altura / 8)
        w, h = round(largura / 8), round(altura / 8)
        for borda, geometria in zip(self._bordas, ((x, y, w, 2), (x, y + h - 2, w, 2),
                                                  (x, y, 2, h), (x + w - 2, y, 2, h))):
            px, py, pw, ph = geometria
            borda.place(x=px, y=py, width=pw, height=ph)
            borda.lift()

    def _iniciar_arraste(self, evento, peca):
        if self._tamanho_padronizado is None:
            return "break"
        self._arraste = (peca, evento.x_root, evento.y_root, self._selecionada)
        evento.widget.configure(cursor="fleur")
        return "break"

    def _mover_arraste(self, evento):
        if self._arraste is not None:
            rotulo = self.rotulos["padronizado"]
            self._marcar_casa(self.casa_no_ponto(evento.x_root - rotulo.winfo_rootx(),
                                               evento.y_root - rotulo.winfo_rooty()))
        return "break"

    def _terminar_arraste(self, evento):
        if self._arraste is None:
            return "break"
        peca, x, y, anterior = self._arraste
        self._arraste = None
        evento.widget.configure(cursor="hand2")
        rotulo = self.rotulos["padronizado"]
        casa = self.casa_no_ponto(evento.x_root - rotulo.winfo_rootx(), evento.y_root - rotulo.winfo_rooty())
        if casa is not None and abs(evento.x_root - x) + abs(evento.y_root - y) >= 6:
            self._marcar_casa(casa)
            letras = dict(zip("KQRBNPkqrbnp", "RDTBCPrdtbcp"))
            peca = letras.get(peca, peca) if self._idioma == "pt" else peca
            self.ao_editar(substituir_casa(self._texto, *casa, peca, self._idioma))
        else:
            self._marcar_casa(anterior)
        return "break"

    def casa_no_ponto(self, x: float, y: float):
        """Desconta a área vazia ao redor da imagem centralizada no Label."""
        if self._tamanho_padronizado is None:
            return None
        largura, altura = self._tamanho_padronizado
        rotulo = self.rotulos["padronizado"]
        x -= (rotulo.winfo_width() - largura) / 2
        y -= (rotulo.winfo_height() - altura) / 2
        if not (0 <= x < largura and 0 <= y < altura):
            return None
        return int(y * 8 / altura), int(x * 8 / largura)

    def _clicar_casa(self, evento):
        casa = self.casa_no_ponto(evento.x, evento.y)
        if casa is not None and self.ao_editar and self._seletor is None:
            self._marcar_casa(casa)
            self._abrir_seletor(*casa)

    def _abrir_seletor(self, linha: int, coluna: int):
        pai = self.winfo_toplevel()
        captura = pai.grab_current()
        janela = ttk.Toplevel(master=pai)
        self._seletor = janela
        janela.title(f"Editar {chr(97 + coluna)}{8 - linha}")
        janela.resizable(False, False)
        janela.transient(pai)
        quadro = ttk.Frame(janela, padding=16)
        quadro.pack(fill="both", expand=True)
        ttk.Label(quadro, text=f"Escolha a peça para {chr(97 + coluna)}{8 - linha}",
                  font=("Segoe UI", 12, "bold")).grid(row=0, column=0, columnspan=6, sticky="w", pady=(0, 12))

        def fechar():
            self._seletor = None
            janela.grab_release()
            janela.destroy()
            if captura is not None and captura.winfo_exists():
                captura.grab_set()

        def escolher(peca):
            texto = substituir_casa(self._texto, linha, coluna, peca, self._idioma)
            fechar()
            self.ao_editar(texto)

        letras = "RDTBCP" if self._idioma == "pt" else "KQRBNP"
        nomes = ("Rei", "Dama", "Torre", "Bispo", "Cavalo", "Peão")
        for grupo, cor in enumerate(("Brancas", "Pretas")):
            ttk.Label(quadro, text=cor, bootstyle="secondary").grid(row=1 + grupo * 2, column=0,
                columnspan=6, sticky="w", pady=(4, 5))
            for indice, (letra, nome, padrao) in enumerate(zip(letras, nomes, "KQRBNP")):
                peca = letra if grupo == 0 else letra.lower()
                padrao = padrao if grupo == 0 else padrao.lower()
                self._icone_peca(padrao)
                ttk.Button(quadro, text=nome, image=self._icones[padrao], compound="top",
                    command=lambda p=peca: escolher(p), bootstyle="secondary outline", width=7
                ).grid(row=2 + grupo * 2, column=indice, padx=3, pady=(0, 8))
        ttk.Button(quadro, text="Casa vazia", command=lambda: escolher(""), bootstyle="primary"
        ).grid(row=5, column=0, columnspan=4, sticky="ew", padx=3, pady=(8, 0))
        ttk.Button(quadro, text="Cancelar", command=fechar, bootstyle="secondary outline"
        ).grid(row=5, column=4, columnspan=2, sticky="ew", padx=3, pady=(8, 0))
        janela.protocol("WM_DELETE_WINDOW", fechar)
        janela.bind("<Escape>", lambda _evento: fechar())
        janela.update_idletasks()
        x = max(0, min(pai.winfo_rootx() + (pai.winfo_width() - janela.winfo_width()) // 2,
                       janela.winfo_screenwidth() - janela.winfo_width()))
        y = max(0, min(pai.winfo_rooty() + (pai.winfo_height() - janela.winfo_height()) // 2,
                       janela.winfo_screenheight() - janela.winfo_height()))
        janela.geometry(f"+{x}+{y}")
        janela.grab_set()
        janela.focus_set()

    def indicar_trabalho(self, texto: str = ""):
        if texto:
            self.rotulo_trabalho.configure(text=texto)
            self.trabalho.grid(row=2, column=0, columnspan=3, sticky="w", pady=(4, 0))
            self.progresso.start(60)
        else:
            self.progresso.stop()
            self.trabalho.grid_remove()

    def limpar(self, texto: str):
        self._marcar_casa(None)
        if self._paleta is not None:
            self._paleta.grid_remove()
        self._modo = None
        self._chaves_imagens.clear()
        self._origem_cache = None
        self._imagens_tk.clear()
        self._tamanho_padronizado = None
        self.seta.grid_remove()
        self.paineis["padronizado"].grid_remove()
        self.paineis["original"].grid(row=0, column=0, columnspan=3, sticky="nsew", padx=0)
        self.rotulos["original"].configure(image="", text=texto, bootstyle="secondary")
