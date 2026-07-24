"""Interface grafica simples para o extrator de diagramas."""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from autoupdate import Atualizacao, baixar_atualizacao, consultar_atualizacao, iniciar_instalador
from extrair_tabuleiros_pdf import ErroExtracao, ResultadoExtracao, processar_pdf
from version import GITHUB_REPOSITORY, PUBLISHER, __version__


COR_FUNDO = "#f4f6f8"
COR_PRIMARIA = "#2457a6"


def caminho_recurso(*partes: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base.joinpath(*partes)


def sugerir_saida(caminho_entrada: str) -> str:
    if not caminho_entrada:
        return ""
    return str(Path(caminho_entrada).parent / "Diagramas_Livro.pdf")


def localizar_desinstalador() -> Path | None:
    if not getattr(sys, "frozen", False):
        return None
    caminho = Path(sys.executable).resolve().parent / "unins000.exe"
    return caminho if caminho.is_file() else None


class InterfaceExtrator:
    def __init__(self, raiz: tk.Tk) -> None:
        self.raiz = raiz
        self.raiz.title(f"Chess Book Diagram Extractor — v{__version__}")
        self.raiz.geometry("780x550")
        self.raiz.minsize(700, 510)
        self.raiz.configure(bg=COR_FUNDO)
        caminho_icone = caminho_recurso("icon", "icon.png")
        if caminho_icone.is_file():
            self._icone_janela = tk.PhotoImage(file=caminho_icone)
            self.raiz.iconphoto(True, self._icone_janela)

        self.entrada = tk.StringVar()
        self.saida = tk.StringVar()
        self.status = tk.StringVar(value="Selecione um livro em PDF para começar.")
        self.detalhes = tk.StringVar(value="Nenhum processamento em andamento.")
        self.eventos: queue.Queue[tuple[str, object]] = queue.Queue()
        self.processando = False
        self.atualizando = False
        self.verificacao_silenciosa = False
        self.ultimo_resultado: ResultadoExtracao | None = None

        self._configurar_estilo()
        self._montar_tela()
        self.raiz.protocol("WM_DELETE_WINDOW", self._ao_fechar)
        self.raiz.after(100, self._verificar_eventos)
        if GITHUB_REPOSITORY:
            self.raiz.after(2500, lambda: self._verificar_atualizacoes(silencioso=True))

    def _configurar_estilo(self) -> None:
        estilo = ttk.Style(self.raiz)
        if "vista" in estilo.theme_names():
            estilo.theme_use("vista")
        estilo.configure("Fundo.TFrame", background=COR_FUNDO)
        estilo.configure("Titulo.TLabel", background=COR_FUNDO, foreground="#18202a", font=("Segoe UI", 18, "bold"))
        estilo.configure("Texto.TLabel", background=COR_FUNDO, foreground="#3b4654", font=("Segoe UI", 10))
        estilo.configure("Status.TLabel", background="#ffffff", foreground="#263442", font=("Segoe UI", 10))
        estilo.configure("Acao.TButton", font=("Segoe UI", 10, "bold"), padding=(14, 8))

    def _montar_tela(self) -> None:
        principal = ttk.Frame(self.raiz, style="Fundo.TFrame", padding=28)
        principal.pack(fill="both", expand=True)
        principal.columnconfigure(0, weight=1)

        ttk.Label(principal, text="Chess Book Diagram Extractor", style="Titulo.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(
            principal,
            text="Localize os tabuleiros 8×8 do livro e crie um PDF A4 com um diagrama por página.",
            style="Texto.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(4, 24))

        formulario = ttk.Frame(principal, style="Fundo.TFrame")
        formulario.grid(row=2, column=0, sticky="ew")
        formulario.columnconfigure(0, weight=1)

        ttk.Label(formulario, text="Livro em PDF", style="Texto.TLabel").grid(row=0, column=0, sticky="w")
        linha_entrada = ttk.Frame(formulario, style="Fundo.TFrame")
        linha_entrada.grid(row=1, column=0, sticky="ew", pady=(5, 16))
        linha_entrada.columnconfigure(0, weight=1)
        self.campo_entrada = ttk.Entry(linha_entrada, textvariable=self.entrada)
        self.campo_entrada.grid(row=0, column=0, sticky="ew", padx=(0, 10))
        self.botao_entrada = ttk.Button(linha_entrada, text="Selecionar...", command=self._selecionar_entrada)
        self.botao_entrada.grid(row=0, column=1)

        ttk.Label(formulario, text="PDF de saída", style="Texto.TLabel").grid(row=2, column=0, sticky="w")
        linha_saida = ttk.Frame(formulario, style="Fundo.TFrame")
        linha_saida.grid(row=3, column=0, sticky="ew", pady=(5, 22))
        linha_saida.columnconfigure(0, weight=1)
        self.campo_saida = ttk.Entry(linha_saida, textvariable=self.saida)
        self.campo_saida.grid(row=0, column=0, sticky="ew", padx=(0, 10))
        self.botao_saida = ttk.Button(linha_saida, text="Salvar como...", command=self._selecionar_saida)
        self.botao_saida.grid(row=0, column=1)

        self.progresso = ttk.Progressbar(principal, mode="determinate", maximum=100)
        self.progresso.grid(row=3, column=0, sticky="ew", pady=(0, 10))

        caixa_status = ttk.Frame(principal, padding=15)
        caixa_status.grid(row=4, column=0, sticky="ew", pady=(0, 22))
        caixa_status.columnconfigure(0, weight=1)
        ttk.Label(caixa_status, textvariable=self.status, style="Status.TLabel", wraplength=650).grid(row=0, column=0, sticky="w")
        ttk.Label(caixa_status, textvariable=self.detalhes, style="Status.TLabel").grid(row=1, column=0, sticky="w", pady=(6, 0))

        acoes = ttk.Frame(principal, style="Fundo.TFrame")
        acoes.grid(row=5, column=0, sticky="ew")
        acoes.columnconfigure(0, weight=1)
        self.botao_abrir = ttk.Button(acoes, text="Abrir pasta do resultado", command=self._abrir_pasta, state="disabled")
        self.botao_abrir.grid(row=0, column=0, sticky="w")
        self.botao_processar = ttk.Button(acoes, text="Extrair diagramas", style="Acao.TButton", command=self._iniciar)
        self.botao_processar.grid(row=0, column=1, sticky="e")

        utilitarios = ttk.Frame(principal, style="Fundo.TFrame")
        utilitarios.grid(row=6, column=0, sticky="ew", pady=(18, 0))
        utilitarios.columnconfigure(1, weight=1)
        self.botao_atualizar = ttk.Button(utilitarios, text="Verificar atualizações", command=self._verificar_atualizacoes)
        self.botao_atualizar.grid(row=0, column=0, sticky="w", padx=(0, 10))
        estado_desinstalar = "normal" if localizar_desinstalador() else "disabled"
        self.botao_desinstalar = ttk.Button(
            utilitarios,
            text="Desinstalar programa",
            command=self._desinstalar,
            state=estado_desinstalar,
        )
        self.botao_desinstalar.grid(row=0, column=1, sticky="w")
        ttk.Label(
            utilitarios,
            text=f"v{__version__} • Editor: {PUBLISHER}",
            style="Texto.TLabel",
        ).grid(row=0, column=2, sticky="e")

    def _selecionar_entrada(self) -> None:
        caminho = filedialog.askopenfilename(
            parent=self.raiz,
            title="Selecione o livro em PDF",
            filetypes=[("Arquivos PDF", "*.pdf"), ("Todos os arquivos", "*.*")],
        )
        if caminho:
            self.entrada.set(caminho)
            if not self.saida.get().strip():
                self.saida.set(sugerir_saida(caminho))

    def _selecionar_saida(self) -> None:
        entrada = self.entrada.get().strip()
        inicial = Path(entrada).parent if entrada else Path.cwd()
        caminho = filedialog.asksaveasfilename(
            parent=self.raiz,
            title="Salvar PDF com os diagramas",
            initialdir=inicial,
            initialfile="Diagramas_Livro.pdf",
            defaultextension=".pdf",
            filetypes=[("Arquivos PDF", "*.pdf")],
        )
        if caminho:
            self.saida.set(caminho)

    def _validar(self) -> tuple[str, str] | None:
        entrada, saida = self.entrada.get().strip(), self.saida.get().strip()
        if not entrada:
            messagebox.showwarning("Livro não selecionado", "Selecione o livro em PDF.", parent=self.raiz)
            return None
        if not Path(entrada).is_file():
            messagebox.showerror("Arquivo não encontrado", "O livro selecionado não existe.", parent=self.raiz)
            return None
        if not saida:
            messagebox.showwarning("Destino não selecionado", "Escolha onde salvar o PDF de saída.", parent=self.raiz)
            return None
        if Path(entrada).resolve() == Path(saida).resolve():
            messagebox.showerror("Destino inválido", "O PDF de saída não pode substituir o livro original.", parent=self.raiz)
            return None
        return entrada, saida

    def _iniciar(self) -> None:
        validado = self._validar()
        if validado is None:
            return
        entrada, saida = validado
        self.processando = True
        self.ultimo_resultado = None
        self.progresso["value"] = 0
        self.status.set("Preparando o livro...")
        self.detalhes.set("O tempo depende da quantidade de páginas.")
        self.botao_abrir.configure(state="disabled")
        self._alternar_controles(False)
        threading.Thread(target=self._processar, args=(entrada, saida), daemon=True).start()

    def _processar(self, entrada: str, saida: str) -> None:
        def informar(atual: int, total: int, encontrados: int) -> None:
            self.eventos.put(("progresso", (atual, total, encontrados)))

        try:
            resultado = processar_pdf(entrada, saida, progresso=informar)
            self.eventos.put(("concluido", resultado))
        except Exception as erro:
            self.eventos.put(("erro", erro))

    def _verificar_eventos(self) -> None:
        try:
            while True:
                tipo, dados = self.eventos.get_nowait()
                if tipo == "progresso":
                    atual, total, encontrados = dados  # type: ignore[misc]
                    self.progresso["value"] = atual / max(1, total) * 100
                    self.status.set(f"Processando página {atual} de {total}...")
                    self.detalhes.set(f"{encontrados} diagrama(s) encontrado(s) até agora.")
                elif tipo == "concluido":
                    self._concluir(dados)  # type: ignore[arg-type]
                elif tipo == "erro":
                    self._mostrar_erro(dados)  # type: ignore[arg-type]
                elif tipo == "atualizacao_disponivel":
                    self._oferecer_atualizacao(dados)  # type: ignore[arg-type]
                elif tipo == "atualizacao_ausente":
                    self._atualizacao_ausente()
                elif tipo == "atualizacao_erro":
                    self._erro_atualizacao(dados)  # type: ignore[arg-type]
                elif tipo == "download_atualizacao":
                    recebido, total = dados  # type: ignore[misc]
                    self.progresso["value"] = recebido / max(1, total) * 100
                    self.status.set("Baixando atualização...")
                    self.detalhes.set(f"{recebido / 1024 / 1024:.1f} de {total / 1024 / 1024:.1f} MB")
                elif tipo == "atualizacao_baixada":
                    self._instalar_atualizacao(dados)  # type: ignore[arg-type]
        except queue.Empty:
            pass
        self.raiz.after(100, self._verificar_eventos)

    def _concluir(self, resultado: ResultadoExtracao) -> None:
        self.processando = False
        self.ultimo_resultado = resultado
        self.progresso["value"] = 100
        self._alternar_controles(True)
        if resultado.diagramas_encontrados == 0:
            self.status.set("Processamento concluído, mas nenhum tabuleiro foi encontrado.")
            self.detalhes.set("Nenhum PDF de saída foi criado.")
            messagebox.showwarning("Nenhum diagrama", self.status.get(), parent=self.raiz)
            return
        self.status.set("Extração concluída com sucesso.")
        self.detalhes.set(f"{resultado.diagramas_encontrados} diagrama(s) salvos em {resultado.arquivo_saida}")
        self.botao_abrir.configure(state="normal")
        messagebox.showinfo(
            "Extração concluída",
            f"{resultado.diagramas_encontrados} diagrama(s) foram extraídos.",
            parent=self.raiz,
        )

    def _mostrar_erro(self, erro: object) -> None:
        self.processando = False
        self.progresso["value"] = 0
        self._alternar_controles(True)
        mensagem = str(erro) if isinstance(erro, (ErroExtracao, Exception)) else "Erro desconhecido."
        self.status.set("Não foi possível concluir a extração.")
        self.detalhes.set(mensagem)
        messagebox.showerror("Erro na extração", mensagem, parent=self.raiz)

    def _alternar_controles(self, habilitar: bool) -> None:
        estado = "normal" if habilitar else "disabled"
        for controle in (self.campo_entrada, self.campo_saida, self.botao_entrada, self.botao_saida, self.botao_processar):
            controle.configure(state=estado)

    def _abrir_pasta(self) -> None:
        if self.ultimo_resultado and self.ultimo_resultado.arquivo_saida:
            os.startfile(str(self.ultimo_resultado.arquivo_saida.parent))

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
            self.status.set("Verificando atualizações...")
            self.detalhes.set(f"Versão instalada: {__version__}")
        threading.Thread(target=self._consultar_atualizacao, daemon=True).start()

    def _consultar_atualizacao(self) -> None:
        try:
            atualizacao = consultar_atualizacao(GITHUB_REPOSITORY, __version__)
            self.eventos.put(("atualizacao_disponivel" if atualizacao else "atualizacao_ausente", atualizacao))
        except Exception as erro:
            self.eventos.put(("atualizacao_erro", erro))

    def _oferecer_atualizacao(self, atualizacao: Atualizacao) -> None:
        self.atualizando = False
        self.botao_atualizar.configure(state="normal")
        aceitar = messagebox.askyesno(
            "Nova versão disponível",
            f"A versão {atualizacao.versao} está disponível.\n\n"
            f"Versão instalada: {__version__}\n\n"
            "Deseja baixar e instalar agora?",
            parent=self.raiz,
        )
        if not aceitar:
            return
        self.atualizando = True
        self.botao_atualizar.configure(state="disabled")
        self._alternar_controles(False)
        threading.Thread(target=self._baixar_atualizacao, args=(atualizacao,), daemon=True).start()

    def _baixar_atualizacao(self, atualizacao: Atualizacao) -> None:
        try:
            caminho = baixar_atualizacao(
                atualizacao,
                progresso=lambda recebido, total: self.eventos.put(("download_atualizacao", (recebido, total))),
            )
            self.eventos.put(("atualizacao_baixada", caminho))
        except Exception as erro:
            self.eventos.put(("atualizacao_erro", erro))

    def _atualizacao_ausente(self) -> None:
        self.atualizando = False
        self.botao_atualizar.configure(state="normal")
        if not self.verificacao_silenciosa:
            messagebox.showinfo(
                "Aplicativo atualizado",
                f"Você já possui a versão mais recente ({__version__}).",
                parent=self.raiz,
            )

    def _erro_atualizacao(self, erro: object) -> None:
        self.atualizando = False
        self.botao_atualizar.configure(state="normal")
        self._alternar_controles(True)
        if not self.verificacao_silenciosa:
            messagebox.showerror("Erro de atualização", str(erro), parent=self.raiz)

    def _instalar_atualizacao(self, caminho: Path) -> None:
        try:
            iniciar_instalador(caminho)
        except Exception as erro:
            self._erro_atualizacao(erro)
            return
        messagebox.showinfo(
            "Atualização iniciada",
            "O aplicativo será fechado e o instalador concluirá a atualização.",
            parent=self.raiz,
        )
        self.raiz.after(300, self.raiz.destroy)

    def _desinstalar(self) -> None:
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
        if self.processando and not messagebox.askyesno(
            "Extração em andamento",
            "A extração ainda está em andamento. Deseja fechar mesmo assim?",
            parent=self.raiz,
        ):
            return
        self.raiz.destroy()


def main() -> None:
    raiz = tk.Tk()
    InterfaceExtrator(raiz)
    raiz.mainloop()


if __name__ == "__main__":
    main()
