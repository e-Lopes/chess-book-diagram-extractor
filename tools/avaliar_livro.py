"""Testa um PDF completo e cria uma revisão local, sem presumir acurácia.

python tools/avaliar_livro.py --pdf books/TERCEIRA_VERSAO_unida.pdf
Use --reusar-recortes para repetir o reconhecimento sem renderizar novamente.
O HTML permite anotar posições de referência e exportar anotacoes.json.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
from pathlib import Path
import sys
import time

import cv2
import fitz
import numpy as np

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from extrair_tabuleiros_pdf import (
    detectar_tabuleiros, renderizar_pagina, _quadros_de_imagens_pdf, LIMIAR_PADRAO,
)
from notacao_forsyth import (
    ReconhecedorForsyth, _classes_modelo_da_posicao, compactar_tabuleiro,
    LIMIAR_CONFIANCA, MARGEM_AMBIGUIDADE,
)
from reconhecimento_ensemble import CLASSES, carregar_catalogo


def salvar_json(caminho: Path, dados) -> None:
    caminho.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")


def identidade_recortes(relatorio: dict) -> str:
    conteudo = {"pdf": relatorio["sha256_pdf"], "dpi": relatorio["dpi"], "quadros": [
        (c["id"], c["quadro_pixels"]) for c in relatorio["candidatos"]]}
    return hashlib.sha256(json.dumps(conteudo, sort_keys=True).encode()).hexdigest()


def identidade_reconhecedor() -> str:
    return hashlib.sha256(b"\n".join((RAIZ / nome).read_bytes() for nome in
        ("notacao_forsyth.py", "reconhecimento_ensemble.py", "alinhamento_tabuleiro.py",
         "restricoes_reconhecimento.py"))).hexdigest()


def posicao_classes(classes: list[str]) -> str:
    return compactar_tabuleiro([
        ["" if c == "1" else c for c in classes[i:i + 8]]
        for i in range(56, -1, -8)
    ])


def extrair(pdf: Path, saida: Path, dpi: int, limite: int | None) -> dict:
    relatorio = {"pdf": str(pdf.resolve()), "sha256_pdf": hashlib.sha256(pdf.read_bytes()).hexdigest(),
                 "dpi": dpi, "paginas": [], "candidatos": [], "referencia_anotada": False}
    for pasta in ("paginas", "recortes", "votos"):
        (saida / pasta).mkdir(parents=True, exist_ok=True)
    inicio = time.perf_counter()
    with fitz.open(pdf) as documento:
        relatorio["total_paginas_pdf"] = len(documento)
        total = min(limite or len(documento), len(documento))
        for numero in range(1, total + 1):
            pagina = documento[numero - 1]
            imagem = renderizar_pagina(pagina, dpi)
            candidatos = detectar_tabuleiros(imagem, pagina=numero,
                quadros_adicionais=_quadros_de_imagens_pdf(pagina, dpi))
            escala = 600 / imagem.shape[1]
            miniatura = cv2.resize(imagem, (600, round(imagem.shape[0] * escala)), interpolation=cv2.INTER_AREA)
            ids = []
            for indice, candidato in enumerate(candidatos, 1):
                identificador = f"p{numero:04d}-d{indice:02d}"
                ids.append(identificador)
                recorte = f"recortes/{identificador}.png"
                if not cv2.imwrite(str(saida / recorte), candidato.imagem):
                    raise OSError(f"Não foi possível salvar {recorte}")
                quadro = np.round(candidato.quadro * escala).astype(np.int32)
                cv2.polylines(miniatura, [quadro], True, (0, 70, 220), 2)
                cv2.putText(miniatura, str(indice), tuple(quadro[0]), cv2.FONT_HERSHEY_SIMPLEX,
                            .6, (0, 0, 220), 2)
                relatorio["candidatos"].append({"id": identificador, "pagina": numero,
                    "arquivo": recorte, "quadro_pixels": candidato.quadro.tolist(),
                    "quadro_pontos_pdf": (candidato.quadro * 72 / dpi).tolist(),
                    "escore_detector": candidato.confianca})
            caminho_miniatura = f"paginas/p{numero:04d}.webp"
            if not cv2.imwrite(str(saida / caminho_miniatura), miniatura):
                raise OSError(f"Não foi possível salvar {caminho_miniatura}")
            relatorio["paginas"].append({"pagina": numero, "arquivo": caminho_miniatura, "candidatos": ids})
            if numero % 20 == 0 or numero == total:
                print(f"Extração {numero}/{total}: {len(relatorio['candidatos'])} candidatos; "
                      f"{time.perf_counter() - inicio:.1f}s", flush=True)
    relatorio["segundos_extracao"] = time.perf_counter() - inicio
    relatorio["sha256_recortes"] = identidade_recortes(relatorio)
    salvar_json(saida / "extracao.json", relatorio)
    return relatorio


def reconhecer(relatorio: dict, saida: Path, cache: Path | None = None) -> None:
    reconhecedor = ReconhecedorForsyth(idioma="en")
    configuracoes = carregar_catalogo(RAIZ / "models/ensemble.json")
    relatorio["modelos"] = [vars(c) for c in configuracoes]
    relatorio["sha256_reconhecedor"] = identidade_reconhecedor()
    cache_por_imagem = {}
    if cache is not None:
        anterior = json.loads((cache / "relatorio.json").read_text(encoding="utf-8"))
        if (anterior.get("sha256_reconhecedor") != relatorio["sha256_reconhecedor"]
                or anterior.get("modelos") != relatorio["modelos"]):
            raise ValueError("O cache usa outro reconhecedor ou configuração de modelos.")
        for item in anterior["candidatos"]:
            arquivo = cache / item["arquivo"]
            votos = cache / "votos" / f"{item['id']}.json"
            if arquivo.is_file() and votos.is_file():
                digest = hashlib.sha256(arquivo.read_bytes()).hexdigest()
                if item.get("sha256_imagem") == digest:
                    cache_por_imagem[digest] = item, votos
    inicio = time.perf_counter()
    total = len(relatorio["candidatos"])
    reaproveitados = 0
    for numero, item in enumerate(relatorio["candidatos"], 1):
        digest = hashlib.sha256((saida / item["arquivo"]).read_bytes()).hexdigest()
        item["sha256_imagem"] = digest
        if digest in cache_por_imagem:
            anterior, votos = cache_por_imagem[digest]
            for campo in ("posicao", "confiavel", "confianca_minima", "confianca_media", "aviso",
                          "possivel_falso_positivo", "casas_divergentes", "casas_baixa_confianca", "posicoes_modelos"):
                item[campo] = anterior[campo]
            (saida / "votos" / f"{item['id']}.json").write_bytes(votos.read_bytes())
            reaproveitados += 1
            if numero % 50 == 0 or numero == total:
                print(f"Reconhecimento {numero}/{total}; {reaproveitados} idênticos reaproveitados; "
                      f"{time.perf_counter() - inicio:.1f}s", flush=True)
            continue
        imagem = cv2.imread(str(saida / item["arquivo"]))
        if imagem is None:
            raise ValueError(f"Recorte inválido: {item['arquivo']}")
        resultado = reconhecedor.reconhecer(imagem)
        item.update(posicao=resultado.posicao, confiavel=resultado.confiavel,
                    confianca_minima=resultado.confianca_minima, confianca_media=resultado.confianca_media,
                    aviso=resultado.aviso, possivel_falso_positivo=resultado.possivel_falso_positivo,
                    casas_divergentes=[c.coordenada for c in resultado.casas if c.divergencia_modelos],
                    casas_baixa_confianca=[c.coordenada for c in resultado.casas
                                          if c.confianca < LIMIAR_CONFIANCA or c.margem < MARGEM_AMBIGUIDADE])
        item["posicoes_modelos"] = {cfg.nome: posicao_classes([
            next(v.classe for v in casa.previsoes_modelos if v.nome == cfg.nome)
            for casa in resultado.casas]) for cfg in configuracoes}
        # As probabilidades completas ficam em arquivos separados para a revisão abrir rapidamente.
        salvar_json(saida / "votos" / f"{item['id']}.json", {
            "classes": CLASSES, "casas": [{"casa": c.coordenada, "eleita": c.classe_original,
                "confianca": c.confianca, "concordancia": c.concordancia,
                "divergencia": c.divergencia_modelos, "probabilidades": c.probabilidades.tolist(),
                "modelos": [{"nome": v.nome, "classe": v.classe, "confianca": v.confianca,
                             "probabilidades": v.probabilidades} for v in c.previsoes_modelos]}
                for c in resultado.casas]})
        if numero % 50 == 0 or numero == total:
            print(f"Reconhecimento {numero}/{total}; {time.perf_counter() - inicio:.1f}s", flush=True)
    relatorio["segundos_reconhecimento"] = time.perf_counter() - inicio
    relatorio["recortes_reaproveitados"] = reaproveitados
    relatorio["resumo"] = {"paginas_processadas": len(relatorio["paginas"]), "candidatos": total,
        "candidatos_com_grade": sum(c["escore_detector"] >= LIMIAR_PADRAO for c in relatorio["candidatos"]),
        "posicoes_sem_alertas": sum(c["confiavel"] for c in relatorio["candidatos"]),
        "posicoes_com_grade_sem_alertas": sum(c["confiavel"] and c["escore_detector"] >= LIMIAR_PADRAO
                                               for c in relatorio["candidatos"]),
        "posicoes_com_divergencias": sum(bool(c["casas_divergentes"]) for c in relatorio["candidatos"]),
        "casas_divergentes": sum(len(c["casas_divergentes"]) for c in relatorio["candidatos"])}
    salvar_json(saida / "relatorio.json", relatorio)


def avaliar_anotacoes(relatorio: dict, anotacoes: dict) -> dict:
    if anotacoes.get("sha256_pdf") != relatorio["sha256_pdf"]:
        raise ValueError("As anotações pertencem a outro PDF.")
    if relatorio.get("sha256_recortes") and anotacoes.get("sha256_recortes") != relatorio["sha256_recortes"]:
        raise ValueError("As anotações pertencem a outra extração deste PDF.")
    candidatos = {c["id"]: c for c in relatorio["candidatos"]}
    resultado = {"posicoes_anotadas": 0, "falsos_positivos_confirmados": 0, "modelos": {}, "paginas_anotadas": []}
    for identificador, referencia in anotacoes.get("diagramas", {}).items():
        if identificador not in candidatos:
            raise ValueError(f"Diagrama desconhecido: {identificador}")
        item = candidatos[identificador]
        if referencia.get("falso_positivo"):
            resultado["falsos_positivos_confirmados"] += 1
            continue
        posicao = referencia.get("posicao", "").strip()
        if not posicao:
            continue
        esperadas = _classes_modelo_da_posicao(posicao)
        resultado["posicoes_anotadas"] += 1
        for nome, prevista in {"ensemble": item["posicao"], **item["posicoes_modelos"]}.items():
            dados = resultado["modelos"].setdefault(nome, {"posicoes_exatas": 0, "casas_corretas": 0,
                "casas": 0, "casas_ocupadas": 0, "casas_ocupadas_corretas": 0, "erros": []})
            classes = _classes_modelo_da_posicao(prevista)
            erros = [{"casa": f"{chr(97 + i % 8)}{i // 8 + 1}", "esperada": e, "prevista": p}
                     for i, (e, p) in enumerate(zip(esperadas, classes)) if e != p]
            dados["posicoes_exatas"] += int(not erros)
            dados["casas"] += 64
            dados["casas_corretas"] += 64 - len(erros)
            dados["casas_ocupadas"] += sum(e != "1" for e in esperadas)
            dados["casas_ocupadas_corretas"] += sum(e != "1" and e == p for e, p in zip(esperadas, classes))
            if erros:
                dados["erros"].append({"id": identificador, "casas": erros})
            if nome == "ensemble":
                dados["posicoes_sem_alertas"] = dados.get("posicoes_sem_alertas", 0) + int(item.get("confiavel", False))
                dados["posicoes_erradas_sem_alertas"] = dados.get("posicoes_erradas_sem_alertas", 0) + int(
                    bool(erros) and item.get("confiavel", False))
    for numero, quantidade in anotacoes.get("paginas", {}).items():
        pagina = next((p for p in relatorio["paginas"] if p["pagina"] == int(numero)), None)
        if pagina is None or not isinstance(quantidade, int) or quantidade < 0:
            raise ValueError(f"Anotação de página inválida: {numero}")
        validos = len(pagina["candidatos"]) - sum(
            bool(anotacoes.get("diagramas", {}).get(i, {}).get("falso_positivo")) for i in pagina["candidatos"])
        resultado["paginas_anotadas"].append({"pagina": int(numero), "quantidade_real": quantidade,
            "candidatos_nao_excluidos": validos, "diferenca_contagem": validos - quantidade})
    return resultado


def criar_revisao(relatorio: dict, saida: Path) -> None:
    itens = {c["id"]: c for c in relatorio["candidatos"]}
    trechos = []
    for pagina in relatorio["paginas"]:
        numero = pagina["pagina"]
        trechos.append(f'<section><h2>Página {numero} — {len(pagina["candidatos"])} candidatos</h2>'
            f'<label>Quantidade real após conferir a página: <input type="number" min="0" '
            f'data-pagina="{numero}" aria-label="Quantidade de diagramas da página {numero}"></label>'
            f'<div class="pagina"><img loading="lazy" src="{pagina["arquivo"]}" alt="Página {numero}"><div>')
        for identificador in pagina["candidatos"]:
            c = itens[identificador]
            trechos.append(f'<article><h3>{identificador}</h3><div class="comparacao">'
                f'<img loading="lazy" src="{c["arquivo"]}" alt="Diagrama original"><div class="tabuleiro" '
                f'data-id="{identificador}"></div></div><code>{html.escape(c["posicao"])}</code>'
                f'<p>{html.escape(c["aviso"] or "Sem alertas automáticos. Conferência visual necessária.")}</p>'
                + ('<p>Grade não confirmada pelo detector; confira se o recorte é um diagrama.</p>'
                   if c["escore_detector"] < LIMIAR_PADRAO else '') +
                f'<details><summary>Previsões individuais e votos</summary><pre>'
                f'{html.escape(json.dumps(c["posicoes_modelos"], indent=2))}</pre>'
                f'<a href="votos/{identificador}.json">Probabilidades das 64 casas</a></details>'
                f'<label><input type="checkbox" data-falso="{identificador}"> Não é um diagrama</label><br>'
                f'<label>Posição correta, conferida na imagem (FEN inglês):<br><input class="fen" '
                f'data-posicao="{identificador}" placeholder="Preencha após conferir cada peça"></label></article>')
        trechos.append('</div></div></section>')
    # Dados embutidos permitem abrir o HTML diretamente, sem servidor nem chamadas externas.
    dados_js = json.dumps({c["id"]: {"posicao": c["posicao"], "divergencias": c["casas_divergentes"]}
                         for c in itens.values()}, ensure_ascii=True).replace("<", "\\u003c")
    documento = '''<!doctype html><html lang="pt-BR"><meta charset="utf-8"><title>Teste do livro</title>
<style>body{font:16px system-ui;margin:24px;background:#f5f4ef;color:#222}section,article{background:white;padding:16px;margin:16px 0;border:1px solid #ccc;border-radius:8px}.pagina{display:grid;grid-template-columns:minmax(300px,600px) 1fr;gap:24px}.pagina>img{width:100%}.comparacao{display:flex;gap:16px;flex-wrap:wrap}.comparacao img{width:256px;height:256px;object-fit:contain}.tabuleiro{display:grid;grid-template-columns:repeat(8,32px);width:256px;height:256px}.casa{font:28px serif;display:grid;place-items:center}.duvida{box-shadow:inset 0 0 0 3px #d22}code{overflow-wrap:anywhere}.fen{width:95%;padding:6px}button{padding:12px;cursor:pointer}header{position:sticky;top:0;background:#f5f4ef;padding:12px;z-index:2}input[type=number]{width:70px}@media(max-width:950px){.pagina{display:block}}</style>
<header><h1>Teste do livro</h1><button id="exportar">Exportar anotações</button> <span id="status"></span></header>
<p>Os retângulos vermelhos marcam candidatos. Confira também páginas sem recortes para encontrar diagramas ausentes.
Ao lado de cada recorte está a posição eleita; casas vermelhas indicam divergência. Confiança e concordância não medem acurácia.
Anote a posição na orientação da imagem. As anotações ficam neste navegador e podem ser exportadas.</p>
<p>Modelos individuais usam o alinhamento escolhido pelo ensemble. Não houve adaptação automática pelo livro.</p>
''' + f'<p>{html.escape(json.dumps(relatorio["resumo"], ensure_ascii=False))}</p>' + ''.join(trechos) + '''
<script>
const dados=DADOS, hash=HASH, recortes=RECORTES, chave='teste-livro-'+hash+'-'+recortes;
let notas;try{notas=JSON.parse(localStorage.getItem(chave))}catch(e){};
notas=notas||{sha256_pdf:hash,sha256_recortes:recortes,diagramas:{},paginas:{}};
const pecas={K:'♔',Q:'♕',R:'♖',B:'♗',N:'♘',P:'♙',k:'♚',q:'♛',r:'♜',b:'♝',n:'♞',p:'♟'};
document.querySelectorAll('.tabuleiro').forEach(el=>{const item=dados[el.dataset.id];item.posicao.split('/').forEach((linha,l)=>{let col=0;for(const c of linha){const n=/[1-8]/.test(c)?Number(c):1;for(let j=0;j<n;j++){const casa=document.createElement('span'),coord=String.fromCharCode(97+col)+(8-l);casa.className='casa'+(item.divergencias.includes(coord)?' duvida':'');casa.style.background=(l+col)%2?'#ac9777':'#eee6d5';casa.textContent=pecas[c]||'';casa.title=coord;el.appendChild(casa);col++}}})});
function salvar(){localStorage.setItem(chave,JSON.stringify(notas));document.querySelector('#status').textContent='Anotações salvas neste navegador'}
document.querySelectorAll('[data-posicao]').forEach(el=>{const id=el.dataset.posicao;el.value=notas.diagramas[id]?.posicao||'';el.addEventListener('change',()=>{notas.diagramas[id]={...notas.diagramas[id],posicao:el.value.trim()};salvar()})});
document.querySelectorAll('[data-falso]').forEach(el=>{const id=el.dataset.falso;el.checked=notas.diagramas[id]?.falso_positivo||false;el.addEventListener('change',()=>{notas.diagramas[id]={...notas.diagramas[id],falso_positivo:el.checked};salvar()})});
document.querySelectorAll('[data-pagina]').forEach(el=>{const id=el.dataset.pagina;el.value=notas.paginas[id]??'';el.addEventListener('change',()=>{if(el.value==='')delete notas.paginas[id];else notas.paginas[id]=Number(el.value);salvar()})});
document.querySelector('#exportar').onclick=()=>{const url=URL.createObjectURL(new Blob([JSON.stringify(notas,null,2)],{type:'application/json'})),a=document.createElement('a');a.href=url;a.download='anotacoes.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)};
</script></html>'''
    documento = documento.replace("DADOS", dados_js).replace("HASH", json.dumps(relatorio["sha256_pdf"]))
    documento = documento.replace("RECORTES", json.dumps(relatorio.get("sha256_recortes")))
    (saida / "revisao.html").write_text(documento, encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", type=Path, default=RAIZ / "books/TERCEIRA_VERSAO_unida.pdf")
    parser.add_argument("--saida", type=Path, default=RAIZ / "build/teste-livro")
    parser.add_argument("--dpi", type=int, default=240)
    parser.add_argument("--paginas", type=int, help="Limita a execução a uma amostra inicial")
    parser.add_argument("--reusar-recortes", action="store_true")
    parser.add_argument("--cache-reconhecimento", type=Path,
                        help="Reutiliza previsões de uma avaliação com recortes idênticos e modelos iguais")
    parser.add_argument("--anotacoes", type=Path, help="Avalia anotações exportadas pelo HTML")
    parser.add_argument("--referencia-fontes", action="store_true",
                        help="Compara com grades completas ChessMerida e DiagramTTFritz do texto PDF")
    args = parser.parse_args()
    if args.dpi <= 0 or (args.paginas is not None and args.paginas <= 0):
        parser.error("DPI e quantidade de páginas devem ser positivos")
    if args.cache_reconhecimento is not None and args.cache_reconhecimento.resolve() == args.saida.resolve():
        parser.error("Use pastas distintas para a avaliação e seu cache")
    args.saida.mkdir(parents=True, exist_ok=True)
    if args.anotacoes:
        relatorio = json.loads((args.saida / "relatorio.json").read_text(encoding="utf-8"))
        metricas = avaliar_anotacoes(relatorio, json.loads(args.anotacoes.read_text(encoding="utf-8")))
        salvar_json(args.saida / "metricas-anotadas.json", metricas)
        print(json.dumps(metricas, ensure_ascii=False, indent=2))
    else:
        if args.reusar_recortes:
            relatorio = json.loads((args.saida / "extracao.json").read_text(encoding="utf-8"))
            if hashlib.sha256(args.pdf.read_bytes()).hexdigest() != relatorio["sha256_pdf"] or args.dpi != relatorio["dpi"]:
                raise ValueError("Os recortes são de outro PDF ou DPI.")
        else:
            relatorio = extrair(args.pdf, args.saida, args.dpi, args.paginas)
        relatorio["sha256_recortes"] = identidade_recortes(relatorio)
        reconhecer(relatorio, args.saida, args.cache_reconhecimento)
        if args.referencia_fontes:
            from tools.referencia_fontes_pdf import gerar_referencias
            anotacoes, correspondencia = gerar_referencias(args.pdf, relatorio)
            salvar_json(args.saida / "referencias-fontes.json", anotacoes)
            salvar_json(args.saida / "correspondencia-fontes.json", correspondencia)
            metricas = avaliar_anotacoes(relatorio, anotacoes)
            metricas["origem_referencia"] = anotacoes["origem"]
            metricas["diagramas_referencia"] = len(correspondencia["referencias"])
            metricas["diagramas_referencia_detectados"] = correspondencia["detectadas"]
            metricas["por_fonte"] = {}
            for fonte in sorted({r["fonte"] for r in anotacoes["diagramas"].values()}):
                subset = {**anotacoes, "diagramas": {i: r for i, r in anotacoes["diagramas"].items()
                                                     if r["fonte"] == fonte}}
                metricas["por_fonte"][fonte] = avaliar_anotacoes(relatorio, subset)
            salvar_json(args.saida / "metricas-fontes.json", metricas)
            print(f"Referência textual: {correspondencia['detectadas']}/{len(correspondencia['referencias'])} localizados", flush=True)
            for nome, m in metricas["modelos"].items():
                print(f"{nome}: {m['posicoes_exatas']}/{metricas['posicoes_anotadas']} posições; "
                      f"{m['casas_corretas']}/{m['casas']} casas", flush=True)
        criar_revisao(relatorio, args.saida)
        print(json.dumps(relatorio["resumo"], ensure_ascii=False, indent=2))
        print(f"Revisão: {args.saida / 'revisao.html'}")
