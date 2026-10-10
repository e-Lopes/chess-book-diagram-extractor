"""Exportação assíncrona compartilhada pela revisão e pela biblioteca."""
from __future__ import annotations

import queue
import threading
from pathlib import Path
from tkinter import filedialog, messagebox

import ttkbootstrap as ttk

from extrair_tabuleiros_pdf import ExtracaoCancelada
from notacao_forsyth import validar_posicao
from tabuleiros_padronizados import (
    DiagramaPadronizado, exportar_pdf_padronizado, localizar_diagramas_antigos,
)


def exportar_livro_padronizado(parent, origem, candidatos, itens, idioma, titulo):
    # A edição pode continuar após a exportação: o trabalho usa esta fotografia.
    escolhidos = [(c, item.posicao) for c, item in zip(candidatos, itens)
                  if not item.nao_e_tabuleiro and validar_posicao(item.posicao, idioma)[0]]
    if not escolhidos:
        messagebox.showwarning("Nenhuma posição válida", "Informe ao menos uma posição Forsyth válida.", parent=parent)
        return
    relocalizar = origem is None or not Path(origem).is_file()
    if relocalizar:
        origem = filedialog.askopenfilename(parent=parent, title="Selecione o PDF original deste livro",
                                            filetypes=[("PDF original", "*.pdf")])
        if not origem:
            return
    nome = "".join("_" if c in '<>:"/\\|?*' else c for c in titulo).strip(" .") or "livro"
    destino = filedialog.asksaveasfilename(parent=parent, title="Salvar cópia com diagramas padronizados",
        initialfile=f"{nome}_padronizado.pdf", defaultextension=".pdf", filetypes=[("PDF", "*.pdf")])
    if not destino:
        return
    janela = ttk.Toplevel(master=parent)
    janela.title("Padronizar diagramas")
    janela.transient(parent)
    janela.resizable(False, False)
    quadro = ttk.Frame(janela, padding=24)
    quadro.pack(fill="both", expand=True)
    rotulo = ttk.Label(quadro, text="Preparando o livro…", width=56, wraplength=400)
    rotulo.pack(fill="x")
    barra = ttk.Progressbar(quadro, maximum=100, length=400)
    barra.pack(fill="x", pady=16)
    eventos = queue.Queue()
    cancelamento = threading.Event()
    janela.bind("<Destroy>", lambda evento: cancelamento.set() if evento.widget == janela else None)
    def cancelar():
        cancelamento.set()
        botao.configure(state="disabled")
        rotulo.configure(text="Cancelando…")
    botao = ttk.Button(quadro, text="Cancelar", command=cancelar, bootstyle="secondary outline")
    botao.pack(anchor="e")
    janela.protocol("WM_DELETE_WINDOW", cancelar)
    janela.grab_set()
    def informar(fase, atual, total):
        eventos.put(("progresso", (fase, atual, total)))
    def executar():
        try:
            faltantes = [i for i, (c, _) in enumerate(escolhidos) if relocalizar or not c.quadro_pdf]
            localizados = localizar_diagramas_antigos(origem, [escolhidos[i][0] for i in faltantes],
                progresso=lambda a, t: informar("Localizando diagramas", a, t),
                cancelado=cancelamento.is_set) if faltantes else {}
            recuperados = {i: localizados[j] for j, i in enumerate(faltantes) if j in localizados}
            diagramas = []
            for i, (c, posicao) in enumerate(escolhidos):
                quadro_pdf = recuperados.get(i, () if relocalizar else c.quadro_pdf)
                if quadro_pdf:
                    diagramas.append(DiagramaPadronizado(c.pagina, quadro_pdf, posicao))
            caminho = exportar_pdf_padronizado(origem, destino, diagramas, idioma=idioma,
                progresso=lambda a, t: informar("Substituindo diagramas", a, t), cancelado=cancelamento.is_set)
            omitidos = len(itens) - len(diagramas)
            eventos.put(("concluido", (caminho, len(diagramas), omitidos)))
        except ExtracaoCancelada:
            eventos.put(("cancelado", None))
        except Exception as erro:
            eventos.put(("erro", erro))
    def acompanhar():
        try:
            while True:
                tipo, dados = eventos.get_nowait()
                if tipo == "progresso":
                    fase, atual, total = dados
                    if not cancelamento.is_set():
                        rotulo.configure(text=f"{fase}: {atual} de {total}")
                        barra.configure(value=atual / max(total, 1) * 100)
                else:
                    janela.grab_release()
                    janela.destroy()
                    if tipo == "concluido":
                        caminho, total, omitidos = dados
                        texto = f"{total} diagrama(s) padronizado(s).\n\n{caminho}"
                        if omitidos:
                            texto += (f"\n\n{omitidos} recorte(s) mantido(s) como no original: "
                                      "excluídos, posições inválidas ou localização não confirmada.")
                        messagebox.showinfo("PDF padronizado", texto, parent=parent)
                    elif tipo == "erro":
                        messagebox.showerror("Não foi possível padronizar", str(dados), parent=parent)
                    return
        except queue.Empty:
            pass
        janela.after(100, acompanhar)
    janela.after(100, acompanhar)
    threading.Thread(target=executar, daemon=True).start()
