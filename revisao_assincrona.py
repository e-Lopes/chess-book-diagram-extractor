"""Revisão do livro sem bloquear Tk nem modificar itens a partir da worker."""
from __future__ import annotations

import copy
import queue
import threading


class RevisaoAssincrona:
    def __init__(self, janela, indicar, aplicar, erro):
        self.janela = janela
        self.indicar = indicar
        self.aplicar = aplicar
        self.erro = erro
        self._geracao = 0
        self._pendente = None
        self._executando = False
        self._fechada = False
        self._timer = None
        self._consulta = None
        self._fila = queue.Queue()
        self._continuacoes = []

    def agendar(self, revisor, itens):
        if self._fechada:
            return
        self._geracao += 1
        self._pendente = (revisor, itens)
        self.indicar("Atualizando reconhecimento…")
        if self._timer is not None:
            self.janela.after_cancel(self._timer)
        self._timer = self.janela.after(250, self._iniciar)

    def _iniciar(self):
        self._timer = None
        if self._fechada or self._executando or self._pendente is None:
            return
        revisor, itens = self._pendente
        self._pendente = None
        geracao = self._geracao
        # Arrays de imagens são somente lidos; listas e estados são isolados.
        copia = copy.copy(revisor)
        copia.resultados_originais = list(revisor.resultados_originais)
        copia.referencias_manuais = list(revisor.referencias_manuais)
        copia.excluidos = set(revisor.excluidos)
        copia.fundos = dict(revisor.fundos)
        copia.referencias_automaticas = list(revisor.referencias_automaticas)
        estados = [copy.copy(item) for item in itens]
        anteriores = [item.posicao for item in itens]
        self._executando = True

        def trabalhar():
            try:
                copia.revisar_itens(estados)
                self._fila.put((geracao, anteriores, estados, None))
            except Exception as erro:
                self._fila.put((geracao, anteriores, None, erro))

        threading.Thread(target=trabalhar, daemon=True, name="revisao-livro").start()
        self._consulta = self.janela.after(30, self._consultar)

    def _consultar(self):
        self._consulta = None
        if self._fechada:
            return
        try:
            geracao, anteriores, estados, erro = self._fila.get_nowait()
        except queue.Empty:
            self._consulta = self.janela.after(30, self._consultar)
            return
        self._executando = False
        if geracao == self._geracao:
            if erro is None:
                self.aplicar(anteriores, estados)
            else:
                self.erro(erro)
        if self._pendente is not None:
            if self._timer is not None:
                self.janela.after_cancel(self._timer)
                self._timer = None
            self._iniciar()
        else:
            self.indicar("")
            continuacoes, self._continuacoes = self._continuacoes, []
            for callback in continuacoes:
                if not self._fechada:
                    callback()

    def quando_pronto(self, callback):
        """Exportações aguardam os resultados sem bloquear o loop da interface."""
        if self._executando or self._pendente is not None:
            if callback not in self._continuacoes:
                self._continuacoes.append(callback)
            return False
        return True

    def fechar(self):
        self._fechada = True
        for timer in (self._timer, self._consulta):
            if timer is not None:
                self.janela.after_cancel(timer)
        self._timer = self._consulta = None
        self._pendente = None
        self._continuacoes.clear()
