# Privacidade e LGPD

Este documento descreve limites técnicos do TrilhaDocs; não é parecer jurídico nem declaração de conformidade. A aplicação não determina finalidade, base legal, papéis de controlador/operador, transparência, atendimento a titulares ou prazos legais. Essas decisões dependem do tratamento concreto, dos contratos e das políticas da organização.

## Dados tratados

O inventário pode conter identificadores de conta e documento, códigos, nomes de empresa/divisão/conta, período, estado e metadados de arquivos. Nomes e metadados podem identificar uma pessoa ou revelar informação comercial. Os arquivos referenciados podem conter qualquer conteúdo fornecido pelo operador. ZIPs e manifests preservam o conteúdo e metadados necessários ao empacotamento e à conferência; seus nomes podem incluir rótulos do inventário.

`validate` lê fontes para conferir tamanho, hash e estrutura de PDFs. `preview` usa o inventário para calcular o plano e o preflight, sem abrir documentos. `build` cria cópias empacotadas na saída e não apaga inventário ou originais. A ferramenta opera localmente e não envia dados a um serviço remoto.

## Minimização em respostas e journal

A CLI apresenta contagens, tamanhos, estados e mensagens estáticas, sem incluir nomes de conta ou caminhos nas respostas normais. O journal contém somente UUID de job, hashes, índices, tamanhos e contagens definidos por eventos estruturados; não registra corpo de documentos, nomes nem caminhos.

Na fronteira de escrita do journal, `privacy.redact_sensitive_data` aplica substituição determinística a campos sensíveis conhecidos e padrões reconhecíveis, incluindo e-mail, CPF/CNPJ, telefone brasileiro, credenciais em formatos comuns, URL e caminhos absolutos. Eventos regulares e seus hashes continuam válidos para leitura e retomada. A redação é defesa em profundidade: nomes arbitrários, identificadores em formato inesperado, metadados embutidos e valores indiretos podem não ser reconhecidos. Ela não é executada sobre todo arquivo de entrada ou documento e não deve ser tratada como filtro universal.

SHA-256 é usado para comparar conteúdo e detectar divergência em relação ao inventário. Hashes não criptografam nem anonimizam dados; podem continuar vinculáveis ao conteúdo ou ao contexto, e não autenticam quem produziu o arquivo.

## Retenção e descarte

TrilhaDocs não define prazo de retenção nem apaga automaticamente fontes, pacotes, manifests, resumo ou journal. O operador deve determinar e documentar o prazo mínimo necessário para cada finalidade, considerando obrigações legais e contratuais. Ao fim do prazo, deve aplicar o processo aprovado de descarte, incluindo cópias temporárias, backups e mídias controladas pela organização. A exclusão feita pela aplicação não garante remoção segura de snapshots, sincronizações ou cópias de segurança.

A saída fica no sistema de arquivos local. O software não implementa criptografia em repouso, gestão de chaves, controle de acesso multiusuário, anonimização ou descarte seguro. Para qualquer dado real, o operador é responsável por restringir permissões, escolher armazenamento protegido segundo a política da organização, gerir cópias e backups e avaliar se o uso é autorizado. O exemplo distribuído contém somente conteúdo inventado.

## Responsabilidades antes de uso com dados reais

- Confirmar finalidade, necessidade, autorização e responsabilidades contratuais do tratamento.
- Minimizar o inventário e limitar o acesso a fontes, saída, manifests e backups.
- Definir retenção e descarte para fontes e artefatos produzidos.
- Avaliar os riscos do conteúdo documental e dos metadados que os arquivos carregam.
- Não inserir segredos em argumentos, configuração, inventário ou nomes de arquivos.
- Fazer uma avaliação jurídica e de segurança adequada ao ambiente; a execução local, a redação e o uso de hashes não dispensam essa avaliação.
