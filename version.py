"""Versao publica do aplicativo."""

try:
    from _build_config import BUILD_VERSION as __version__
    from _build_config import GITHUB_REPOSITORY, PUBLISHER
except ImportError:
    __version__ = "0.2.0"
    GITHUB_REPOSITORY = ""
    PUBLISHER = "E-Lopes"
