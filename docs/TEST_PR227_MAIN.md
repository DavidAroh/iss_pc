# Teste local: main + PR #227

- Base main: `48022f0` (inclui RX580 #232/#278 e apoio #284).
- PR #227: `cba0486c40f3d24040b44af33e60baecbbe9c3a4`.
- Branch: `feat/test-pr227-main`, worktree `~/decomp/infamous_pc-pr227`.
- Integração local para teste; não altera a main nem publica release.

Conflitos resolvidos preservando os diagnósticos de performance da main e as mudanças do PR. No GC em lote, cada imagem é liberada uma única vez e mantém o motivo de descarte nos eventos de diagnóstico. Cache SPIR-V é carregado em todos os caminhos conforme o PR, preservando eventos de tradução/leitura. Readback local permanece opt-in. Os gatilhos e condições de release manual da main foram conferidos.

## Roteiro

1. Abrir o launcher desta branch e iniciar manualmente com as opções atuais do jogador; as opções experimentais novas continuam nos padrões do PR.
2. Comparar o mesmo save/cena com a main: FPS, engasgos, fumaça, partículas, luzes, água e fogo. A alteração do tradutor renova a chave de cache; aguardar a compilação inicial antes de comparar desempenho.
3. Conferir idioma automático e opções detectadas no dump, saves, mods e fechamento normal.
4. Testar VSync e redimensionamento; não instalar atualização pelo launcher durante este teste da branch.

Compilação, testes locais e resultados de gameplay são registrados em `~/decomp/iss_pr227_review/` e nas docs de estado do workspace. O usuário faz a validação visual; nenhum resultado de gameplay é presumido.
