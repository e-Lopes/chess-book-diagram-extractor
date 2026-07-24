"""Versao publica do aplicativo."""

try:
    from _build_config import BUILD_VERSION as __version__
    from _build_config import GITHUB_REPOSITORY, PUBLISHER
except ImportError:
    __version__ = "0.1.3"
    GITHUB_REPOSITORY = ""
    PUBLISHER = "E-Lopes"
