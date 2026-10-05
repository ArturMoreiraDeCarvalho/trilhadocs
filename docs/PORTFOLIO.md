# Narrativa de portfólio

Este texto descreve uma demonstração técnica de portfólio, feita como projeto pessoal com desenvolvimento assistido por agentes de IA (plano e especificação em [`docs/superpowers/`](superpowers/)). Não é um produto usado por clientes nem prova de conformidade legal.

## Resumo

TrilhaDocs demonstra um pipeline local para organizar documentos contábeis a partir de um inventário JSONL. A ferramenta valida o escopo, confere tamanho e SHA-256 de cada fonte, cria pacotes ZIP com manifests e oferece uma verificação independente da saída. O demo e seus PDFs são inteiramente sintéticos.

## O que mostrar

1. Gere os arquivos da demo fora do checkout com `python examples/demo/create_demo.py ../trilhadocs-demo`.
2. Execute `validate` para conferir fontes e `preview` para apresentar contagens e estimativa sem gravar pacotes.
3. Execute `build` para produzir os ZIPs, manifests, resumo e journal local.
4. Execute `verify` para reabrir os arquivos e comparar a cobertura e o conteúdo esperado.
5. Mostre no journal que os eventos registram hashes e contagens, enquanto o nome da conta e os caminhos de origem não entram nos checkpoints.

## Competências demonstradas

- Modelagem e validação estrita de inventário e configuração.
- Resolução de caminhos dentro de uma raiz autorizada e preflight de saída.
- Escrita de artefatos com verificação, publicação sem sobrescrita e retomada por checkpoints.
- Separação entre empacotamento e verificação independente.
- Minimização de dados no journal e documentação explícita de retenção e limites.

## Texto de apresentação para LinkedIn

**Título do projeto:** TrilhaDocs — pacotes verificáveis de documentos contábeis (Python)

**Descrição:**

> Projeto pessoal, com dados sintéticos e desenvolvimento assistido por agentes de IA: CLI Python local que valida o inventário de uma carga de documentos contábeis, organiza capas e anexos em ZIPs por empresa e divisão e confere a integridade do resultado.
>
> • Quatro comandos: validate (configuração TOML e inventário JSONL tipados, tamanho, SHA-256 e estrutura dos PDFs), preview, build (ZIPs atômicos e retomáveis, com manifests e journal) e verify (reabre os pacotes e compara com o inventário).
> • Journal com minimização de dados e limites de LGPD documentados.
> • pydantic, typer, pypdf, pytest e ruff; CI no GitHub Actions em Ubuntu e Windows, com Python 3.11 e 3.12.
>
> Organiza e verifica documentos; não extrai dados do conteúdo dos PDFs.

## Seção “About” do GitHub

**Descrição:** `CLI Python local que valida o inventário de documentos contábeis, empacota capas e anexos em ZIPs verificáveis e confere integridade (SHA-256). Dados sintéticos.`

**Tópicos:** `python`, `cli`, `accounting`, `data-integrity`, `auditability`, `privacy-by-design`, `lgpd`, `synthetic-data`, `pydantic`, `pytest`

Licença escolhida para o projeto: MIT. O tópico `lgpd` indica o tema demonstrado; não significa certificação ou garantia de conformidade. Consulte [Segurança](../SECURITY.md) sobre o canal privado de vulnerabilidades.

## Limites que acompanham a demonstração

O projeto não implementa criptografia, gestão de identidade, descarte automático ou conformidade LGPD automática. SHA-256 demonstra igualdade dos bytes comparados, não autoria ou anonimização. O operador continua responsável por autorização, controle de acesso, retenção, backups e descarte. A demo não é evidência de homologação ou aptidão para dados reais.

### Apresentação curta

> TrilhaDocs é uma CLI local para validar um inventário de documentos, empacotar fontes em ZIPs verificáveis e confirmar a cobertura produzida. O fluxo mantém checkpoints para retomar com segurança e reduz dados no journal a hashes e contagens. O projeto demonstra controles de integridade e limites de privacidade de forma explícita, usando apenas dados sintéticos.
