# Contribuindo

1. Crie um ambiente virtual com Python 3.12.
2. Instale `requirements-build.txt`.
3. Execute `python -m unittest discover -s tests -v`.
4. Faça alterações pequenas e descreva como foram testadas.

Para gerar somente o aplicativo Windows durante o desenvolvimento:

```powershell
.\Build_Windows.bat -SkipInstaller
```

Antes de publicar uma versão estável, atualize a versão padrão em `version.py`,
execute todos os testes e crie uma tag como `v0.1.0`. Os metadados do binário
são gerados automaticamente a partir do parâmetro ou da tag.

Todos os responsáveis pelo repositório e pela assinatura devem usar
autenticação de dois fatores. Consulte a [Code signing policy](CODE_SIGNING_POLICY.md)
antes de alterar o processo de build ou publicação.
