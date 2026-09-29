# Arquitetura

TrilhaDocs é uma CLI local, escrita para Python 3.11 ou posterior, que valida um inventário JSONL, empacota documentos referenciados em arquivos ZIP e confere a saída. A execução não requer banco de dados, credenciais, serviço remoto ou listener de rede.

## Fluxo

1. A configuração TOML é carregada com caminhos relativos resolvidos a partir do próprio arquivo. O modelo rejeita campos desconhecidos.
2. O inventário JSONL é lido e validado com modelos estritos. Referências, estados de conta e identificadores duplicados são conferidos antes do build.
3. O plano agrupa contas por empresa e divisão, define nomes de arquivos/membros e calcula espaço e limites de caminho.
4. `validate` percorre os documentos referenciados, compara tamanho e SHA-256 e valida estruturalmente PDFs. Não cria nem remove saídas.
5. `preview` mostra contagens e estimativas após o preflight. Não abre o conteúdo dos documentos nem escreve a saída.
6. `build` cria pacotes e manifests, verifica os artefatos, e só então grava o resumo `COMPLETE`. Se interrompido, pode conferir os checkpoints locais antes de retomar.
7. `verify` reabre os ZIPs e compara cobertura, manifests e conteúdo com o inventário esperado.

A raiz de origem limita a resolução de caminhos e impede traversal para fora do conjunto autorizado. Escritas usam arquivos temporários e publicação sem substituição para preservar entradas e saídas existentes em caso de conflito.

## Módulos principais

| Módulo | Responsabilidade |
| --- | --- |
| `config.py`, `models.py`, `inventory.py` | Configuração TOML e esquema tipado do inventário JSONL. |
| `paths.py`, `planning.py` | Resolução segura, nomes de saída, agrupamento e preflight. |
| `hashing.py`, `pdf_validation.py` | Conferência de tamanho/hash e validação estrutural de PDF. |
| `packaging.py` | Escrita dos pacotes, manifests, resumo e recuperação por checkpoints. |
| `journal.py`, `privacy.py` | Serialização local de eventos e redação determinística de valores sensíveis reconhecíveis. |
| `verification.py` | Leitura independente dos ZIPs já produzidos e conferência do resultado. |
| `cli.py` | Comandos locais e respostas JSON resumidas. |

O comando `validate` inspeciona documentos independentes com paralelismo limitado por `max_workers`. O build coordena a gravação de ZIPs e do journal em série, sem múltiplos escritores concorrentes no journal.

## Journal e saída da CLI

O journal é um arquivo JSONL append-only criado no diretório de saída. Seu esquema atual contém eventos `START`, `ARCHIVE_VERIFIED`, `MASTER_VERIFIED` e `COMPLETE`: UUID do job, hashes SHA-256, contagens, índice do ZIP, tamanhos e sinalização da criação do ZIP mestre. Ele não guarda nomes de conta, nomes de arquivo, caminhos de origem nem conteúdo documental. Erros da CLI são resumidos sem detalhes brutos de exceções ou caminhos.

A redação determinística é aplicada durante a codificação de cada evento no journal, tanto na criação quanto em cada append. Eventos válidos gerados pelo build preservam seus campos e hashes; hashes de 64 caracteres hexadecimais nos campos `sha256` são mantidos para permitir verificação e retomada. A rotina também cobre padrões comuns e campos sensíveis como defesa em profundidade para futuras mensagens estruturadas. Ela não substitui o esquema estrito nem constitui garantia de que todo dado identificável será detectado.

Os hashes vinculam os artefatos conferidos ao inventário recebido, mas não são assinatura digital, prova de autoria, anonimização ou criptografia. O journal é um arquivo local sujeito às permissões, backups e controles do sistema operacional.

## Instalação e uso local

A instalação de desenvolvimento e o exemplo usam somente dados sintéticos:

```sh
python -m pip install -e ".[dev]"
python examples/demo/create_demo.py ../trilhadocs-demo
python -m trilhadocs validate --config ../trilhadocs-demo/config.toml
python -m trilhadocs preview --config ../trilhadocs-demo/config.toml
python -m trilhadocs build --config ../trilhadocs-demo/config.toml
python -m trilhadocs verify --config ../trilhadocs-demo/config.toml
```

O gerador exige um destino fora do repositório. `validate` e `preview` não gravam a saída; `build` cria arquivos sob `out` dentro da pasta da demo. Para validar o código localmente, use `pytest`, `ruff check src tests` e `ruff format --check src tests`.
