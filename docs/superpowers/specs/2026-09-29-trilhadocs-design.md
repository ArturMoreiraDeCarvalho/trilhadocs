# TrilhaDocs — especificação de design

**Data:** 2026-09-29  
**Estado:** aprovada para implementação local; publicação pública pendente de revisão de licença, titularidade e visibilidade
**Objetivo:** transformar o aprendizado da prova de conceito em um projeto Python de portfólio limpo, executável localmente e publicável depois de revisão.

## 1. Objetivo e limites

TrilhaDocs será uma ferramenta CLI local para conferir um inventário de documentos de um workflow contábil, validar os arquivos referenciados e gerar pacotes ZIP reproduzíveis com manifestos de auditoria.

O repositório demonstrará engenharia de cargas contábeis, validação de integridade, segurança por padrão, minimização de dados e privacidade desde o desenho. A demonstração usará exclusivamente dados sintéticos.

Esta fase não terá SaaS, API, painel web, banco gerenciado, acesso à produção, integração com um cliente real ou publicação automática. O primeiro conector será um inventário JSONL local e uma raiz local de arquivos. Uma interface de protocolo permitirá adicionar conectores depois sem incluir credenciais, SQL ou schema de clientes no repositório.

## 2. Usuário e fluxo demonstrável

O usuário é um analista contábil ou de dados que recebe um inventário autorizado e precisa entregar evidências documentais organizadas por empresa, divisão, período e conta.

Fluxo:

1. **validate** lê configuração e inventário sem escrever arquivos de saída.
2. **preview** informa escopo, totais, status, bytes estimados e maiores caminhos projetados.
3. **build** valida conteúdo e produz um ZIP por par empresa/divisão; pode produzir um ZIP mestre opcional.
4. **verify** reabre os artefatos e confere cobertura, nomes de membros, tamanho, CRC e SHA-256 contra os manifests.

Arquivos de origem nunca são removidos nem alterados. Uma execução inválida ou parcial retorna código diferente de zero. Arquivo de saída já existente não é substituído implicitamente.

## 3. Dados e regras do domínio

O modelo mínimo contém job, período, empresa, divisão, conta, documento, tipo de documento, situação e referência de origem. Identificadores de conta e documento são únicos no escopo. Duplicatas, contas sem mapeamento, arquivos ausentes e status desconhecidos interrompem o build com erro claro.

Os registros do inventário de exemplo definem quais contas estão concluídas e quais capas estão presentes. As invariantes são fixas e determinísticas: conta concluída exige capa; conta pendente não declara capa. O inventário inclui bytes esperados e SHA-256 de cada documento. O build compara ambos ao conteúdo lido.

O JSONL é tratado como snapshot imutável da entrada. O manifest do pacote registra a versão do esquema e o hash do inventário, vinculando o resultado ao escopo recebido. SHA-256 demonstra integridade do conteúdo; não será descrito como assinatura ou autenticação da origem.

## 4. Arquitetura proposta

- **CLI:** Typer, com comandos validate, preview, build e verify.
- **Configuração:** TOML versionado e validado por modelo tipado.
- **Domínio:** entidades e regras puras para job, conta, documento e status.
- **Entrada:** protocolo InventorySource e implementação local JSONL.
- **Arquivos:** protocolo DocumentStore e implementação local restrita a uma raiz autorizada.
- **Pipeline:** validação de escopo, preflight, cópia em blocos, geração dos ZIPs e manifests.
- **Auditoria:** eventos estruturados coordenados pelo processo principal; sem escrita concorrente no mesmo log.
- **Verificador:** processo independente do empacotador para reabrir cada arquivo produzido.
- **PDF:** leitura estrutural com pypdf; uma assinatura %PDF isolada não basta.
- **Testes:** unitários, integração com fixtures pequenas e testes de contrato do manifest.
- **CI:** GitHub Actions executa lint, formatação e testes sem segredos ou acesso externo.

O processamento pode usar concorrência limitada para conferir arquivos independentes. A escrita de cada ZIP e do journal permanece coordenada por um único escritor, evitando corrupção e interleaving dos logs.

## 5. Segurança, LGPD e uso de dados

### Minimização e rastreabilidade

Logs contêm job_id aleatório, contagens, duração, etapa e resultado. Não incluem conteúdo documental, credenciais, SQL, caminhos absolutos nem nomes de clientes. Os manifests de entrega podem conter identificadores e nomes de contas; a documentação os trata como dados potencialmente pessoais ou confidenciais, sujeitos a controle de acesso e retenção.

Todos os fixtures serão inventados, sem derivação de nomes, números, documentos ou metadados do caso operacional. Não serão copiados para o novo repositório scripts PHP, endereços, configurações internas de integração, nomes de tabelas/colunas, IDs reais, logs, inventários, snapshots, PDFs, anexos ou ZIPs da operação.

### Controles obrigatórios

- Resolver cada caminho sob a raiz de entrada; rejeitar traversal, links simbólicos externos, colisões e nomes inválidos para Windows.
- Truncar somente o fim do nome da conta, preservando o prefixo identificável; não usar identificador técnico como nome visível. Desambiguar colisões de forma determinística.
- Limitar a 185 caracteres o caminho absoluto de extração Windows no preflight; falhar antes de criar a saída se exceder.
- Usar escrita temporária e renomeação atômica; preservar entradas em falha, cancelamento ou retomada.
- Validar conjuntos exatos de IDs esperados e recebidos; duplicatas não podem ser silenciosamente sobrescritas.
- Só declarar COMPLETE após conferências finais; falhas ou pendências geram estado e código de saída não zero.
- Não executar código recebido, abrir listener de rede ou aceitar SQL de usuário.
- Não gravar segredos em configuração, argumentos, manifests ou logs. O demo não exige segredo.
- Não alegar criptografia em repouso: para dados reais, exigir volume/dispositivo cifrado e controles do ambiente do cliente.
- Documentar retenção, descarte seguro, resposta a incidentes e limites do projeto. Não declarar “conformidade LGPD automática”; o papel de controlador/operador depende do tratamento real e do contrato.

## 6. Estrutura prevista

trilhadocs/
├── pyproject.toml
├── README.md
├── SECURITY.md
├── .gitignore
├── .github/workflows/ci.yml
├── docs/
│   ├── ARCHITECTURE.md
│   ├── PRIVACY_LGPD.md
│   ├── THREAT_MODEL.md
│   └── superpowers/
│       ├── specs/
│       └── plans/
├── examples/demo/
│   ├── config.toml
│   ├── inventory.jsonl
│   └── sources/
├── src/trilhadocs/
│   ├── cli.py
│   ├── config.py
│   ├── domain.py
│   ├── inventory.py
│   ├── paths.py
│   ├── privacy.py
│   ├── pdf_validation.py
│   ├── packaging.py
│   └── verification.py
└── tests/
    ├── unit/
    ├── integration/
    └── contract/

A licença MIT foi selecionada pelo mantenedor para a publicação pública deste projeto demonstrativo. O repositório não inclui dados de produção nem arquivos derivados de pacotes operacionais.

## 7. Requisitos de aceite

1. Clone limpo instala e executa o demo sem credenciais, banco ou serviços externos.
2. validate e preview não criam nem apagam documentos.
3. build preserva toda entrada e cria saídas atômicas e determinísticas.
4. IDs duplicados, escopo divergente, hash/tamanho incorretos, PDF inválido, path traversal, colisões e caminhos acima de 185 caracteres falham antes de marcar sucesso.
5. verify encontra adulteração e diferença de cobertura nos arquivos já produzidos.
6. Um job incompleto nunca retorna sucesso nem apaga inventário.
7. Logs não contêm conteúdo de documentos, segredos, caminhos absolutos ou nomes reais de clientes.
8. A amostra mostra contas concluídas e pendentes, anexos e capas; os nomes são claramente sintéticos.
9. CI roda testes, Ruff e verificação de formatação.
10. README, modelo de ameaças e guia LGPD descrevem o que o software faz, o que não faz e os controles que continuam sob responsabilidade do operador.
11. Busca de sanitização confirma ausência de nomes, identificadores e referências internas do ambiente de origem.
12. A publicação no GitHub só ocorre após revisão do diff final, licença/IP e visibilidade do repositório.

## 8. Fora do escopo desta fase

SaaS, cobrança, autenticação multi-tenant, dashboard, LLM/RAG, OCR, conexão com banco de dados real, consultas de cliente, execução remota, upload automático a serviços externos e promessa de certificação LGPD.

## 9. Decisões pendentes para a revisão

- Nome de trabalho TrilhaDocs é provisório; disponibilidade de marca e domínio não foi pesquisada.
- A primeira versão usa JSONL e arquivos locais como fonte pública demonstrável. Conectores reais só serão considerados em uma etapa separada, com autorização, contrato de interface e testes de contrato.
- A licença e a publicação pública aguardam revisão de titularidade intelectual e escolha expressa de licença/visibilidade.



