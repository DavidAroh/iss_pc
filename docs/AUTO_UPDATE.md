# Atualização do launcher / Launcher updates

## Português

O launcher Qt consulta a última release publicada do iss_pc. A opção de consultar
ao abrir é configurável e começa desligada; instalar exige confirmação do jogador.
Uma release nova só fica disponível quando o mantenedor a publica manualmente.

No Windows empacotado, o pacote verificado por SHA-256 substitui apenas arquivos
do manifesto `package-files.json`, na pasta atual. Saves, configurações, caches,
mods e arquivos do jogo são preservados. O auxiliar espera o launcher fechar;
o diário permite recuperar uma troca interrompida. O backup da versão anterior
permite restaurá-la até a confirmação da atualização seguinte.

Se a pasta temporária de uma atualização concluída for apagada, o launcher
confere os hashes registrados na instalação antes de descartar o estado antigo.
A restauração deixa de estar disponível. Se a atualização foi interrompida ou
os arquivos não conferem, o estado é preservado e a recuperação exige intervenção.
Registros antigos sem evidência de conclusão também exigem intervenção.
A limpeza automática só remove backups concluídos da mesma instalação.

Linux mantém a instalação em pasta vizinha. Checkouts Git não recebem instalação
no lugar pelo updater do Windows.

Validação em 19/10/2026: 42 testes de updater, disco/recuperação e Qt passaram.
Ainda falta validar a atualização completa com o auxiliar PyInstaller no Windows,
incluindo manifesto produzido pelo empacotamento e arquivos em uso. Não houve
teste de jogo nesta etapa.

## English

The Qt launcher checks the latest published iss_pc release. Checking on startup
is optional and disabled by default; installation requires player confirmation.
New releases become available when the maintainer publishes them manually.

Packaged Windows builds verify the download using SHA-256 and replace only files
owned by `package-files.json` in the current folder. Game files, saves, settings,
caches and mods are preserved. A helper waits for the launcher to exit, then
applies a recovery journal. The previous version remains restorable until the
next update is confirmed.

If a completed update's temporary folder is deleted, recorded installed hashes
must match before its stale recovery state is retired. Rollback is then
unavailable. Interrupted updates, mismatching files and legacy state without
completion evidence still require intervention. Automatic cleanup only removes
completed backups belonging to this installation.

Linux retains installation into a sibling folder. Windows in-place updates refuse
Git checkouts. On 2026-10-19, all 42 updater, disk recovery and Qt tests passed.
An end-to-end Windows PyInstaller update, packaging-generated manifest and locked
files still need validation. No game was launched during this work.
