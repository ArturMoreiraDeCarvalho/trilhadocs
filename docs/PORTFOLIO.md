# Narrativa de portfólio

Este texto descreve uma demonstração técnica de portfólio. Ajuste a narrativa para refletir com precisão sua contribuição individual; não apresente o projeto como produto usado por clientes ou como prova de conformidade legal.

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

**Título do projeto:** TrilhaDocs — pipeline local verificável para documentos contábeis

**Descrição sugerida:**

> Desenvolvi o TrilhaDocs como projeto de portfólio para demonstrar um fluxo local de organização de documentos relacionados a cargas contábeis. A CLI valida inventários e arquivos, planeja caminhos compatíveis com extração no Windows, gera pacotes ZIP com manifests e confere a cobertura e a integridade dos artefatos. A demonstração usa exclusivamente dados sintéticos e documenta limites de privacidade e segurança: controles técnicos podem apoiar práticas alinhadas à LGPD, mas não substituem avaliação jurídica, autorização, gestão de acesso ou políticas de retenção.

## Texto para a seção “About” do GitHub

**Descrição sugerida:** `CLI Python local para validar inventários contábeis, organizar documentos em ZIPs verificáveis e conferir integridade. Demo sintética, sem conexão com sistemas reais.`

**Tópicos sugeridos:** `python`, `cli`, `accounting`, `data-integrity`, `auditability`, `privacy-by-design`, `lgpd`, `synthetic-data`

Licença escolhida para o projeto: MIT. O tópico `lgpd` indica o tema demonstrado; não significa certificação ou garantia de conformidade. Consulte [Segurança](../SECURITY.md) sobre o canal privado de vulnerabilidades.

## Limites que acompanham a demonstração

O projeto não implementa criptografia, gestão de identidade, descarte automático ou conformidade LGPD automática. SHA-256 demonstra igualdade dos bytes comparados, não autoria ou anonimização. O operador continua responsável por autorização, controle de acesso, retenção, backups e descarte. A demo não é evidência de homologação ou aptidão para dados reais.

### Apresentação curta

> TrilhaDocs é uma CLI local para validar um inventário de documentos, empacotar fontes em ZIPs verificáveis e confirmar a cobertura produzida. O fluxo mantém checkpoints para retomar com segurança e reduz dados no journal a hashes e contagens. O projeto demonstra controles de integridade e limites de privacidade de forma explícita, usando apenas dados sintéticos.
