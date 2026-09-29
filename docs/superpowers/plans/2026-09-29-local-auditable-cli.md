# TrilhaDocs — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Construir um CLI Python local que valide um inventário contábil sintético e produza pacotes ZIP auditáveis, seguros para retomar e sem efeitos destrutivos sobre as entradas.

**Architecture:** O CLI lê TOML e JSONL, valida escopo e referências sob uma raiz autorizada, executa preflight e coordena os ZIPs. Um verificador independente confere artefatos; o processo principal serializa journal e logs. Sem rede, banco ou serviço externo.

**Tech Stack:** Python 3.11+, Typer, Pydantic, pypdf, pytest, Ruff, GitHub Actions.

**Spec:** docs/superpowers/specs/2026-09-29-trilhadocs-design.md

## Global Constraints
- Não copiar dados, nomes, IDs, código, SQL, schemas, rotas, logs ou configuração do caso operacional.
- Usar somente dados sintéticos.
- Não apagar ou alterar entradas; não substituir saídas implicitamente.
- Resolver caminhos relativos ao TOML; não alterar o cwd.
- Validar IDs exatos e rejeitar duplicatas.
- Verificar tamanho e SHA-256 esperado; validar PDFs estruturalmente.
- Só declarar COMPLETE após verificação final de todos os ZIPs e manifests.
- Limitar caminhos de extração Windows a 185 caracteres e falhar antes de gravar se exceder.
- Truncar apenas o final do nome da conta; preservar prefixo identificável; resolver colisões deterministicamente.
- Processar em blocos; concorrência limitada na inspeção; um escritor para ZIP/journal/log.
- Logs sem conteúdo, nomes de clientes/contas, caminhos absolutos, SQL, IDs externos ou segredos.
- Sem SaaS, API, listener de rede, execução remota, conexão com banco de dados real ou upload externo.
- Sem licença aberta ou publicação remota até revisão de IP e autorização específica.

## Review Focus
- Caminhos com traversal, absolutos ou symlinks externos são rejeitados sem ler fora da raiz.
- ID duplicado, registro órfão, hash incorreto ou documento esperado ausente falha e preserva as entradas.
- Nome Windows inválido, colisão ou caminho acima de 185 falha antes da saída final.
- Retomada revalida cada checkpoint; interrupção não marca COMPLETE nem apaga entradas.
- Logs e manifests do demo não expõem dados reais nem apresentam hash como autenticação.

---

### Task 1: Package, config and domain models

**Files:** pyproject.toml; src/trilhadocs/__init__.py; config.py; models.py; tests/unit/test_config.py; tests/unit/test_models.py.

**Interfaces:** load_config(path: Path) -> ProjectConfig resolve caminhos relativos ao TOML sem mudar cwd. ProjectConfig contém inventário, raiz de origem, saída, limite de caminho, concorrência e opção de ZIP mestre. AccountRecord e AttachmentRecord usam discriminador record_type; campos extras e tipos desconhecidos são rejeitados.

- [x] Escrever testes primeiro: TOML válido, caminhos relativos, chave desconhecida, limite de caminho inválido, concorrência fora do intervalo, período/status inválidos e FileRef malformado.
- [x] Rodar os testes e observar falhas esperadas.
- [x] Criar metadados de pacote, dependências, estrutura src e modelos/config tipados.
- [x] Rodar testes direcionados e confirmar que cwd e entradas não mudaram.
- [x] Fazer commit local desta tarefa após validação.

### Task 2: Inventory, containment and content checks

**Files:** inventory.py; paths.py; hashing.py; pdf_validation.py; tests/unit/test_inventory.py; test_paths.py; test_pdf_validation.py.

**Interfaces:** load_inventory(path) -> Inventory preserva hash estável do inventário. validate_inventory(inventory) rejeita duplicatas, órfãos, status inválido e conta concluída sem capa. resolve_source(root, relative_path) -> Path rejeita caminho absoluto, traversal e alvo resolvido fora da raiz. inspect_file(path, size, sha256) faz streaming e devolve evidência. validate_pdf(path) usa pypdf estrito e exige ao menos uma página.

- [x] Escrever testes para IDs duplicados, tipo desconhecido, attachment órfão, capa ausente, tamanho/hash divergentes, traversal, caminho absoluto, symlink externo e PDF inválido.
- [x] Rodar os testes e confirmar falha pelo motivo esperado.
- [x] Implementar leitura JSONL, conjuntos exatos, contenção e hash em blocos.
- [x] Implementar validação estrutural de PDF e erros sem caminhos absolutos.
- [x] Confirmar com hashes antes/depois que falha alguma não altera entradas.
- [x] Fazer commit local.

### Task 3: Names, Windows paths and preflight

**Files:** planning.py; paths.py; tests/unit/test_planning.py; tests/unit/test_names.py.

**Interfaces:** safe_windows_component(value) remove caracteres inválidos e espaços/pontos finais. build_member_plan(config, inventory) calcula ZIPs, pastas e caminhos absolutos. preflight(plan, free_bytes) verifica colisões, path limit e espaço antes de criar saída. O nome visível vem da conta, não do ID técnico; só seu final é truncado e colisões recebem sufixo estável.

- [x] Testar nomes reservados do Windows, Unicode, caracteres inválidos, finais inválidos, colisões após sanitização, nomes longos de conta/anexo e limite total de 185.
- [x] Testar espaço suficiente/insuficiente e provar que preview/preflight não cria nem remove arquivos.
- [x] Implementar nomes determinísticos, orçamento do caminho e estimativa de saída.
- [x] Rodar testes direcionados e fazer commit local.

### Task 4: Atomic, auditable, resumable packaging

**Files:** journal.py; packaging.py; tests/unit/test_journal.py; tests/integration/test_build.py.

**Interface:** build_job(config, inventory, plan, resume) -> BuildResult. Cada ZIP de par é produzido em temporário, escrito em blocos, verificado, sincronizado e renomeado atomicamente. Um único coordenador grava journal após verificação. Resume reutiliza somente arquivos cujo digest do plano, membros, bytes, CRC e SHA-256 correspondem. ZIP mestre e resumo COMPLETE só surgem após todos os pares verificados.

- [x] Escrever testes para sucesso multi-par, preservação de entradas, conflito de saída, falha intermediária, retomada válida, checkpoint adulterado e ausência de COMPLETE prematuro.
- [x] Rodar testes e observar falha esperada.
- [x] Implementar escrita streaming, manifest por ZIP, journal append-only, temporários e finalização atômica.
- [x] Manter escrita/log serializados; usar concorrência limitada apenas em inspeções independentes.
- [x] Verificar lista exata de membros, ZipFile.testzip, tamanhos e hashes.
- [x] Rodar integração e fazer commit local.

### Task 5: Independent verifier and CLI exits

**Files:** verification.py; cli.py; __main__.py; tests/integration/test_verification.py; tests/integration/test_cli.py.

**Interfaces:** verify_job(output_dir, expected_inventory) -> VerificationResult compara conteúdo/manifests independentemente. Comandos validate, preview, build e verify retornam 0 só para sucesso completo, 2 para entrada/configuração inválida e 3 para falha parcial/integridade/conflito. Resumos JSON não incluem caminhos ou nomes de conta.

- [x] Testar comandos, formato JSON, códigos, falha parcial, IDs repetidos em logs e ZIP adulterado.
- [x] Rodar e observar as falhas esperadas.
- [x] Implementar verificador, CLI e imports sem efeito colateral.
- [x] Importar todos os módulos em teste e provar ausência de mutação/execução externa.
- [x] Rodar testes e fazer commit local.

### Task 6: Demo, LGPD/privacy docs and CI

**Files:** examples/demo/{config.toml,inventory.jsonl,create_demo.py}; src/trilhadocs/privacy.py; docs/{ARCHITECTURE.md,PRIVACY_LGPD.md,THREAT_MODEL.md,PORTFOLIO.md}; README.md; SECURITY.md; .gitignore; .github/workflows/ci.yml; tests/integration/test_demo.py; tests/unit/test_log_redaction.py.

- [x] Testar gerador sintético, status concluído/pendente, PDF válido, redação de logs e validate/preview sem escrita.
- [x] Gerar demo somente com contas, documentos e empresas inventados.
- [x] Documentar arquitetura, limites LGPD, retenção, threat model, instalação, comandos e narrativa de portfólio sem alegação de conformidade automática.
- [x] Adicionar CI com permissões de leitura, Ruff e pytest, sem segredos.
- [x] Rodar demo end-to-end, instalação limpa e sanitização de todos os arquivos rastreados.
- [x] Fazer commit local.

### Task 7: Full verification and portfolio review

**Files:** todo o repositório; alterar somente defeitos confirmados.

- [x] Rodar pytest completo, Ruff lint/format check e build do pacote em ambiente limpo.
- [x] Executar validate/preview/build/verify no demo e reconciliar IDs, pares, bytes e hashes.
- [x] Exercitar duplicatas, symlink externo, path longo, fonte alterada, PDF corrompido, interrupção, retomada e ZIP adulterado.
- [x] Confirmar que falhas nunca alteram fontes nem declaram COMPLETE.
- [x] Confirmar ausência de dados reais/segredos, repositório sem remote e material GitHub/LinkedIn verdadeiro.
- [x] Não publicar, criar remote ou escolher licença até revisão final explícita.
