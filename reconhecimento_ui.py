"""Reavalia um recorte sem bloquear a interface ou alterar a imagem original."""
from __future__ import annotations

import queue
import threading
from tkinter import messagebox

import ttkbootstrap as ttk

from notacao_forsyth import ReconhecedorForsyth


def reavaliar_imagem(pai, imagem, idioma, ao_concluir):
    captura = pai.grab_current()
    janela = ttk.Toplevel(master=pai)
    janela.title("Reavaliar imagem")
    janela.resizable(False, False)
    janela.transient(pai)
    quadro = ttk.Frame(janela, padding=24)
    quadro.pack()
    ttk.Label(quadro, text="Alinhando a grade e reconhecendo as 64 casas...").pack()
    progresso = ttk.Progressbar(quadro, mode="indeterminate", length=360)
    progresso.pack(pady=(14, 0))
    progresso.start()
    eventos = queue.Queue()
    ativo = True

    def fechar():
        nonlocal ativo
        ativo = False
        progresso.stop()
        janela.grab_release()
        janela.destroy()
        if captura is not None and captura.winfo_exists():
            captura.grab_set()

    def reconhecer():
        try:
            eventos.put((True, ReconhecedorForsyth(idioma=idioma).reconhecer(imagem)))
        except Exception as erro:
            eventos.put((False, erro))

    def consultar():
        if not ativo:
            return
        try:
            sucesso, resultado = eventos.get_nowait()
        except queue.Empty:
            janela.after(50, consultar)
            return
        fechar()
        if sucesso:
            ao_concluir(resultado)
        else:
            messagebox.showerror("Falha no reconhecimento", str(resultado), parent=pai)

    janela.protocol("WM_DELETE_WINDOW", fechar)
    janela.bind("<Escape>", lambda _evento: fechar())
    janela.grab_set()
    threading.Thread(target=reconhecer, daemon=True).start()
    janela.after(50, consultar)
