# TurboCore — Pipeline de atualização e instalação (design)

Inspirado no SIG Windows (`D:/Projetos/SIG Windows`, `UPDATE.md` + `updater_v2/` +
`scripts/sync_r2.py` + `installer/`), reduzido ao tamanho do TurboCore
(~15 arquivos-fonte, sem ffmpeg/vad_deps).

## 1. Decisões (propostas — confirmar as marcadas com ❓)

| # | Decisão | Proposta |
|---|---------|----------|
| 1 | Versão | `YYYYMMDD_NNN` em `src/turbocore/__init__.py` (`__version__`), `build-info.json`, manifesto e tag GitHub (mesma regra do SIG; substitui `0.1.0` na 1ª release) |
| 2 | Instalação ✅ | `%ProgramFiles%\TurboCore` com admin, igual ao SIG (decisão do usuário). Transações em `%LOCALAPPDATA%\TurboCore\updater\transactions`, lock dentro do target |
| 3 | R2 | Bucket `turbocore-windows`; chaves = paths relativos (`TurboCore.exe`, `_internal/...`, `assets/...`, `build-info.json`, `TurboCoreUpdater.exe`) + `sync_manifest.json` na raiz. Apagar o placeholder `_internal/` (0 bytes) na 1ª sync |
| 4 | URL pública R2 ✅ | `https://pub-9c30acc6bc8a445f8ffee08d60df4dac.r2.dev` (informada pelo usuário) |
| 5 | Manifesto | Schema 2 IDÊNTICO ao SIG (`files[{path,sha256,size,drive_id:"",github_url}]`, assinatura RSA-SHA256 PKCS1v15, canônico `sort_keys`), mas com **par de chaves NOVO** do TurboCore (privada em `release/`, pública N/E embutida no updater) |
| 6 | Updater | `TurboCoreUpdater.exe` (onefile windowed): worker CLI `--target --pid --log` + UI standalone (diff R2 → full GitHub → reparar); self-update por relocação p/ `%TEMP%`; UA `TurboCoreUpdater/1.0 (+github)` |
| 7 | Tray | Item "Verificar atualização": compara `build-info.json` local vs manifesto; se houver nova, dispara o updater instalado com `--target <dir> --pid <pid>` e encerra |
| 8 | Instalador online | Tkinter+PyInstaller (como o do SIG): tenta R2 (manifesto, todos os `files`), fallback full.zip do GitHub; instala + atalhos per-user |
| 9 | Instalador offline ✅ | `.iss` do Inno no repo; Inno Setup 6 via `winget` (autorizado) |
| 10 | Releases GitHub ✅ | `full.zip` + 2 instaladores por versão; **MANTER histórico** (decisão do usuário — diferente do SIG) |
| 11 | Nomes | `turbocore_<v>_full.zip`, `setup_turbocore_<v>.exe`, `online_setup_turbocore<v>.exe` |

## 2. Layouts

```
R2 turbocore-windows/
  sync_manifest.json
  build-info.json            {"version": "YYYYMMDD_NNN", ...}
  TurboCore.exe
  TurboCoreUpdater.exe
  _internal/...              (stdlib + deps + assets/chip.ico|png do PyInstaller 6)

%LOCALAPPDATA%\TurboCore\    (instalação = espelho do package)
  updater/transactions/      (transações; nunca no pai do target)
  .turbocore.sig-update.lock (lock dentro do target)
%APPDATA%\TurboCore\config.json  (fora do install dir: update nunca apaga)
```

## 3. Fases

- **Fase 1 — updater no app**: `src/turbocore/updater_client.py` (fetch manifesto,
  verify RSA puro-python, `installed_version()`, spawn do updater) + item de menu +
  `TurboCoreUpdater` (worker transacional + UI mínima + self-update) + testes
  (verify/classify/zip-topology/version, tudo mockado) + `build-info.json` no package.
- **Fase 2 — release tooling**: `scripts/tc_release.py` (bump, build onedir c/
  Python311+PyInstaller 6.21.0, full.zip, instaladores), `scripts/tc_sync_r2.py`
  (snapshot sha256, diff por ETag/MD5, manifesto assinado), keypair RSA,
  `.iss` offline, installer online. Gate: updater recompilado bate com
  `updater/artifact.json` (size+sha256), como no SIG.
- **Fase 3 — 1ª publicação**: sync R2 → commit+push (`origin=github.com/spigknot/TurboCore-Windows`)
  → `gh release create` (metadados) + uploads separados → teste real de update.

## 4. Segurança / pitfalls herdados do SIG (não repetir)

- Transações e journals SÓ em `%LOCALAPPDATA%` (nunca no pai do target — trava).
- Lock dentro do target; fechar app/updater antes de build/release.
- `--package` = `.../package`, nunca a raiz (corrompe o manifesto).
- Validar ZIP: topology, symlinks, `MAX_*`, versão `YYYYMMDD_NNN`, startup do novo exe + rollback.
- `gh` com `cd` + paths relativos; uploads grandes em background; conferir assets depois.
- Credenciais (`release/r2_config.json`, `*.pem`) e logs NUNCA no git (já no `.gitignore`).
- Sem chaves reais embutidas no binário (só a chave PÚBLICA do manifesto).
- Builds do updater determinísticos p/ o gate de hash.

## 5. ❓ Perguntas abertas (bloqueiam a Fase 3)

1. **URL pública do R2**: qual o `pub-*.r2.dev` do bucket `turbocore-windows`
   (ou prefere domínio próprio)? Posso tentar descobrir via API token — ou você habilita?
2. **Local de instalação**: confirma `%LOCALAPPDATA%\TurboCore` sem admin?
3. **Inno Setup 6**: instalo via `winget` agora, ou o offline fica p/ depois?
4. **Releases**: deletar a anterior a cada versão (só a atual, como no SIG)?
