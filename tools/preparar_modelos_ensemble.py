"""Baixa pesos fixos e converte os dois CNNs TensorFlow para ONNX.

Ferramenta de desenvolvimento: TensorFlow e ONNX não são necessários no app.
Não executa código dos repositórios de origem. Valida os downloads por SHA-256
e compara a saída ONNX com a implementação TensorFlow original.
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import urllib.request
import zipfile
import sys

import numpy as np

RAIZ = Path(__file__).resolve().parents[1]
FONTES = {
    "linrock-nn-v0.5.zip": (
        "https://github.com/linrock/chessboard-recognizer/releases/download/v0.5/nn.zip",
        "26dead535194b61e97c7d9dc9bb2bd643cbf75dcc8e48e2c9057e026b1c1ff96",
    ),
    "legacy-frozen.pb": (
        "https://raw.githubusercontent.com/Elucidation/tensorflow_chessbot/34fe562eaaf9889a155133b2ceed6c007c6c9256/saved_models/frozen_graph.pb",
        "4dd6247d76600d3a686ce67ebea0aef382a8feed94a7f5c968feb5eac4add7cf",
    ),
    "linrock-LICENSE.txt": (
        "https://raw.githubusercontent.com/linrock/chessboard-recognizer/2d3fc85c4beb71e821925fdd24cc4860335fd7fd/LICENSE",
        "7a6372b1ee4c41aa4e29e12915c1fc04b08d28499332d1b735bfcdaef5e0e7fa",
    ),
    "legacy-LICENSE.txt": (
        "https://raw.githubusercontent.com/Elucidation/tensorflow_chessbot/34fe562eaaf9889a155133b2ceed6c007c6c9256/LICENSE",
        "1e129b8773b7f1687304ed6382c1aa3b55d26da77a6b26de77eae7907f24485d",
    ),
}


def baixar_fontes(pasta: Path) -> None:
    pasta.mkdir(parents=True, exist_ok=True)
    for nome, (url, digest) in FONTES.items():
        destino = pasta / nome
        if not destino.is_file():
            requisicao = urllib.request.Request(url, headers={"User-Agent": "ChessBookDiagramExtractor"})
            with urllib.request.urlopen(requisicao, timeout=60) as resposta:
                conteudo = resposta.read(64 * 1024 * 1024)
        else:
            conteudo = destino.read_bytes()
        if hashlib.sha256(conteudo).hexdigest() != digest:
            raise RuntimeError(f"SHA-256 incorreto: {nome}")
        destino.write_bytes(conteudo)
    with zipfile.ZipFile(pasta / "linrock-nn-v0.5.zip") as arquivo:
        raiz = (pasta / "linrock").resolve()
        for item in arquivo.infolist():
            if not (raiz / item.filename).resolve().is_relative_to(raiz):
                raise RuntimeError("Caminho inválido no ZIP do modelo.")
        arquivo.extractall(raiz)


def exportar(nome: str, pesos: list[np.ndarray], padding: int, classes: str) -> Path:
    import onnx
    from onnx import helper, numpy_helper, TensorProto
    nos, tensores = [], []

    def constante(chave: str, valor: np.ndarray) -> str:
        tensores.append(numpy_helper.from_array(np.asarray(valor), chave))
        return chave

    nos.append(helper.make_node("Reshape", ["tiles", constante("shape", np.array([-1, 1, 32, 32], np.int64))], ["image"]))
    entrada = "image"
    convolucoes = 3 if nome == "linrock" else 2
    for i in range(convolucoes):
        kernel, bias = pesos[i * 2:i * 2 + 2]
        saida = f"conv{i}"
        nos.append(helper.make_node("Conv", [entrada, constante(f"w{i}", kernel.transpose(3, 2, 0, 1).copy()),
                                             constante(f"b{i}", bias)], [saida], pads=[padding] * 4))
        nos.append(helper.make_node("Relu", [saida], [saida + "relu"]))
        entrada = saida + "relu"
        if i < 2:
            nos.append(helper.make_node("MaxPool", [entrada], [saida + "pool"], kernel_shape=[2, 2], strides=[2, 2]))
            entrada = saida + "pool"
    # Dense original usa a ordem NHWC, diferente da ordem NCHW do Conv ONNX.
    nos.append(helper.make_node("Transpose", [entrada], ["nhwc"], perm=[0, 2, 3, 1]))
    nos.append(helper.make_node("Flatten", ["nhwc"], ["flat"], axis=1))
    entrada = "flat"
    for i in range(2):
        kernel, bias = pesos[convolucoes * 2 + i * 2:convolucoes * 2 + i * 2 + 2]
        nos.append(helper.make_node("Gemm", [entrada, constante(f"densew{i}", kernel), constante(f"denseb{i}", bias)], [f"dense{i}"]))
        entrada = f"dense{i}"
        if i == 0:
            nos.append(helper.make_node("Relu", [entrada], ["hidden"]))
            entrada = "hidden"
    nos.append(helper.make_node("Softmax", [entrada], ["native_probs"], axis=1))
    ordem = np.array([classes.index(c) for c in "1KQRBNPkqrbnp"], np.int64)
    nos.append(helper.make_node("Gather", ["native_probs", constante("class_order", ordem)], ["probs"], axis=1))
    grafo = helper.make_graph(nos, nome, [helper.make_tensor_value_info("tiles", TensorProto.FLOAT, ["N", 1024])],
                             [helper.make_tensor_value_info("probs", TensorProto.FLOAT, ["N", 13])], tensores)
    modelo = helper.make_model(grafo, opset_imports=[helper.make_opsetid("", 13)], producer_name="ChessBookDiagramExtractor")
    modelo.ir_version = 8
    onnx.checker.check_model(modelo)
    pasta_saida = RAIZ / "build/model_sources/conversions"
    pasta_saida.mkdir(parents=True, exist_ok=True)
    destino = pasta_saida / f"{nome}-tiles.onnx"
    onnx.save(modelo, destino)
    return destino


def converter(pasta: Path) -> None:
    import tensorflow as tf
    import onnxruntime as ort
    checkpoint = tf.train.load_checkpoint(str(pasta / "linrock/nn/model.tf/variables/variables"))
    pesos = [checkpoint.get_tensor(f"layer_with_weights-{i}/{tipo}/.ATTRIBUTES/VARIABLE_VALUE")
             for i in range(5) for tipo in ("kernel", "bias")]
    entrada = tf.keras.Input(shape=(32, 32, 1))
    x = entrada
    for i in range(3):
        x = tf.keras.layers.Conv2D(pesos[i * 2].shape[-1], 3, activation="relu")(x)
        if i < 2:
            x = tf.keras.layers.MaxPooling2D(2)(x)
    x = tf.keras.layers.Flatten()(x)
    x = tf.keras.layers.Dense(64, activation="relu")(x)
    x = tf.keras.layers.Dense(13, activation="softmax")(x)
    referencia = tf.keras.Model(entrada, x)
    referencia.set_weights(pesos)
    dados = np.random.default_rng(42).random((64, 1024), dtype=np.float32)
    ordem = ["1RNBQKPrnbqkp".index(c) for c in "1KQRBNPkqrbnp"]
    destino = exportar("linrock", pesos, 0, "1RNBQKPrnbqkp")
    esperado = referencia(dados.reshape(64, 32, 32, 1), training=False).numpy()[:, ordem]
    validar_equivalencia(destino, esperado, dados, ort)

    grafo = tf.compat.v1.GraphDef()
    grafo.ParseFromString((pasta / "legacy-frozen.pb").read_bytes())
    constantes = {n.name: tf.make_ndarray(n.attr["value"].tensor) for n in grafo.node if n.op == "Const"}
    pesos = [constantes["Variable" if i == 0 else f"Variable_{i}"] for i in range(8)]
    destino = exportar("chessbot", pesos, 2, "1KQRBNPkqrbnp")
    with tf.Graph().as_default() as original:
        tf.import_graph_def(grafo, name="")
    with tf.compat.v1.Session(graph=original) as sessao:
        esperado = sessao.run(original.get_tensor_by_name("probabilities:0"),
                             {original.get_tensor_by_name("Input:0"): dados,
                              original.get_tensor_by_name("KeepProb:0"): 1.0})
    validar_equivalencia(destino, esperado, dados, ort)
    for nome in ("linrock", "legacy"):
        (RAIZ / "licenses" / f"{nome}-LICENSE.txt").write_bytes((pasta / f"{nome}-LICENSE.txt").read_bytes())


def validar_equivalencia(destino: Path, esperado: np.ndarray, dados: np.ndarray, ort: object) -> None:
    sessao = ort.InferenceSession(str(destino), providers=["CPUExecutionProvider"])
    obtido = sessao.run(["probs"], {"tiles": dados})[0]
    np.testing.assert_allclose(obtido, esperado, atol=2e-5, rtol=2e-4)
    np.testing.assert_array_equal(obtido.argmax(axis=1), esperado.argmax(axis=1))
    destino = destino.replace(RAIZ / "models" / destino.name)
    print(f"{destino.name}: equivalente; SHA-256 {hashlib.sha256(destino.read_bytes()).hexdigest()}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true", help="Usar downloads já validados na pasta de build.")
    args = parser.parse_args()
    # Dependências opcionais podem ser instaladas nesta pasta isolada.
    sys.path.insert(0, str(RAIZ / "build/model_tools"))
    fontes = RAIZ / "build/model_sources"
    if not args.offline:
        baixar_fontes(fontes)
    else:
        for nome, (_url, digest) in FONTES.items():
            if hashlib.sha256((fontes / nome).read_bytes()).hexdigest() != digest:
                raise RuntimeError(f"SHA-256 incorreto: {nome}")
    converter(fontes)
