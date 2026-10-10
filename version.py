"""Versao publica do aplicativo."""

try:
    from _build_config import BUILD_VERSION as __version__
    from _build_config import GITHUB_REPOSITORY, PUBLISHER
except ImportError:
    __version__ = "0.4.1"
    GITHUB_REPOSITORY = "e-Lopes/chess-book-diagram-extractor"
    PUBLISHER = "E-Lopes"
