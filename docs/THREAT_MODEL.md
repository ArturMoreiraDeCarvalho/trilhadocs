# Modelo de ameaças

Este modelo cobre a CLI local e os arquivos processados no computador do operador. Não é uma auditoria de segurança nem uma garantia de segurança ou conformidade.

## Ativos e limites de confiança

- Inventário JSONL, caminhos e metadados de documentos.
- Conteúdo dos arquivos de origem e dos ZIPs resultantes.
- Manifests, resumo final e journal de checkpoints.
- Permissões do diretório de entrada, saída, cópias temporárias e backups.

A CLI recebe configuração, inventário e arquivos locais como entradas não confiáveis. A raiz de origem e a pasta de saída são limites operacionais, mas o processo compartilha a identidade e permissões do usuário que o iniciou. O sistema operacional, a conta e o armazenamento local ficam fora do controle implementado pelo pacote.

## Ameaças e controles existentes

| Ameaça | Controles no código | Limite residual |
| --- | --- | --- |
| Inventário malformado, duplicado ou inconsistente | Esquemas estritos, chaves JSON duplicadas rejeitadas, relacionamentos e estados conferidos. | Um inventário válido ainda pode conter metadados excessivos ou não autorizados. |
| Traversal, link simbólico externo ou nome inválido | Resolução dentro da raiz, verificação de caminhos e nomes, preflight de comprimento. | Não é uma sandbox contra outros processos com a mesma conta ou permissões elevadas. |
| Fonte alterada, truncada ou PDF estruturalmente inválido | Comparação de tamanho e SHA-256; inspeção estrutural de PDF. | Hash não prova origem/autoria e não detecta conteúdo malicioso que passe nas regras estruturais. |
| Saída parcial, conflito ou retomada divergente | Temporários, publicação sem sobrescrita, checkpoints verificados e evento `COMPLETE` apenas após conferência final. | Um usuário/processo com acesso pode editar ou apagar artefatos locais; journal não tem assinatura nem cadeia criptográfica. |
| Caminho, credencial ou identificador sensível em evento futuro | Esquema enxuto e redação determinística na serialização do journal. | Padrões não detectam todo nome, segredo, identificador ou informação indireta; CLI e documentos de saída têm limites próprios. |
| Leitura indevida ou perda de arquivos no dispositivo | Nenhum controle criptográfico próprio. | Acesso, criptografia do volume, backups, sincronização, retenção e descarte dependem do operador e do ambiente. |

## Propriedades que não são oferecidas

- Criptografia em repouso ou em trânsito, gestão de chaves e autenticação de artefatos.
- Isolamento de processos, autorização multiusuário ou proteção contra malware e usuários com acesso ao mesmo dispositivo.
- Anonimização, classificação automática de documentos, detecção completa de segredos ou prevenção de cópia de conteúdo sensível em ZIPs/manifests.
- Remoção automática por prazo ou descarte seguro de backups.
- Conformidade automática com LGPD ou qualquer certificação.

O SHA-256 serve para comparar os bytes observados com o inventário; não é criptografia nem assinatura. Os hashes e contagens do journal podem revelar igualdade entre arquivos ou contexto de processamento. Os artefatos de saída podem expor rótulos comerciais e conteúdo recebido.

## Uso demonstrável

O demo usa nomes, IDs, hashes e PDFs inventados e é gerado fora do repositório. Não use dados de clientes para reproduzir exemplos ou testes. Antes de processar dados reais, revise acesso ao dispositivo, autorização, retenção, backups e descarte conforme a política aplicável.
