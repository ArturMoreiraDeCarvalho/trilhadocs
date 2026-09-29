# Segurança

Este documento descreve o escopo e os limites de segurança do TrilhaDocs. Não é uma auditoria nem uma garantia de que todos os defeitos serão encontrados ou corrigidos.

## Superfície de ataque

A ferramenta processa configuração TOML, inventário JSONL e arquivos locais fornecidos pelo operador. `validate` lê fontes e PDFs; `build` lê as fontes e grava cópias em ZIPs, manifests, resumo e journal; `verify` reabre ZIPs já produzidos. Os caminhos, nomes, tamanhos e conteúdos recebidos devem ser tratados como entrada não confiável. A biblioteca `pypdf` e as demais dependências fazem parte da superfície de ataque.

O código verifica caminhos dentro da raiz de origem, integridade por tamanho e SHA-256 e estrutura básica de PDFs, e rejeita vários conflitos e entradas ZIP inválidas. Essas verificações não formam uma sandbox contra arquivos maliciosos, esgotamento de recursos, vulnerabilidades nas dependências, processos concorrentes com acesso ao mesmo usuário ou malware no dispositivo. O programa roda com as permissões da conta que o iniciou; o sistema de arquivos e o sistema operacional são parte do limite de confiança.

O projeto não abre listener, API ou serviço de rede e não conecta a banco de dados nem envia arquivos a serviços remotos. O build preserva o conteúdo recebido; ele não faz classificação de malware nem sanitização geral dos documentos.

## Dados, retenção e proteção

A saída pode conter cópias integrais dos documentos e manifests com dados derivados do inventário, incluindo identificadores e nomes. O journal e as respostas normais da CLI têm esquema reduzido e redação determinística de alguns padrões reconhecíveis, mas isso não detecta todo nome, identificador, segredo ou contexto indireto e não se aplica universalmente aos documentos e artefatos de saída.

O TrilhaDocs não criptografa arquivos, não gerencia chaves, não impõe permissões de acesso, não define prazo de retenção e não apaga dados automaticamente. Arquivos permanecem no armazenamento local até que o operador os remova. Cópias, backups, sincronização e descarte dependem do ambiente e das políticas do operador; excluir um arquivo não garante remoção segura de outras cópias. SHA-256 detecta divergência de bytes em relação ao inventário, mas não é criptografia, anonimização ou assinatura digital.

Antes de processar dados reais, confirme a autorização e aplique controles adequados no dispositivo e nos diretórios de origem, saída e backup. Defina retenção e descarte para os documentos, ZIPs e manifests. O uso local ou a redação do journal não constitui conformidade automática com a LGPD.

## Relato de vulnerabilidades

Este repositório tem o recurso **Private vulnerability reporting** habilitado. Para relatar uma vulnerabilidade em privado, use **Report a vulnerability** na página de segurança do projeto, conforme a [documentação oficial](https://docs.github.com/en/code-security/how-tos/report-and-fix-vulnerabilities/configure-vulnerability-reporting). Se o recurso estiver indisponível, peça um contato privado ao mantenedor sem incluir detalhes exploráveis.

Se o recurso ainda não estiver habilitado, peça um contato privado ao mantenedor sem incluir detalhes exploráveis. Não publique detalhes técnicos sensíveis nem anexe inventários, PDFs, ZIPs, credenciais ou dados reais em uma issue pública. Não há prazo de resposta prometido neste documento.

Inclua a versão ou commit, sistema operacional, versão do Python, impacto observado e passos mínimos para reproduzir usando somente dados sintéticos. Remova caminhos locais, nomes, identificadores e outros dados sensíveis da reprodução.
