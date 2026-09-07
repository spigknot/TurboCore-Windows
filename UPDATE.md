# UPDATE.md — Procedimento de geração de nova versão (TurboCore Windows)

> Este documento é a FONTE DA VERDADE para gerar e publicar uma nova versão.
> Siga EXATAMENTE esta ordem. O design (decisões) está em
> `docs/update-pipeline.md`; aqui só há comandos literais e verificações.

---

## 0. Visão geral do fluxo

```
bump da versão → preflight → build (package + full.zip + instaladores)
  → sync no R2 (diff) → commit + push → GitHub (full + instaladores) → E2E
```

- **Sync por arquivo (atualização automática)**: Cloudflare R2, bucket
  `turbocore-windows` (`https://pub-9c30acc6bc8a445f8ffee08d60df4dac.r2.dev`).
- **Download manual / reparo**: GitHub Releases (full.zip + 2 instaladores).
- **O updater/app buscam o manifesto em**
  `https://pub-9c30acc6bc8a445f8ffee08d60df4dac.r2.dev/sync_manifest.json`
  (schema 2, assinado com RSA-2048; chave privada só em `release/`).

## 0.1 Contexto essencial

- **Repositório**: `D:\Projetos\TurboCore` (Windows; terminal bash/MSYS —
  caminhos `C:/...` viram glob no `gh`: entre no diretório e use relativos).
- **Python do build**: `C:\Users\Gustavo\AppData\Local\Programs\Python\Python311\python.exe`
  (3.11.0 + PyInstaller 6.21.0 + pywin32; `tc_release.py` valida o 3.11).
- **Python do dia a dia**: o venv do Hermes serve para dev/testes, NUNCA para release.
- **Versão nova**: `APP_VERSION` = `__version__` em `src\turbocore\__init__.py`.
  Formato obrigatório `YYYYMMDD_NNN` (valida o updater). Mesmo dia: incrementa
  `NNN`; dia novo: reinicia em `001`. Mesma versão em: `__version__`,
  `build-info.json`, manifesto sync e tag GitHub.
- **Credenciais R2** em `release\r2_config.json` e **chave privada** em
  `release\update_private_key.pem` (ambos NUNCA commitar — já no `.gitignore`).
- **Instalação alvo**: `C:\Program Files\TurboCore` (admin; o `.iss` dá
  `users-modify` para o updater trabalhar sem elevação).

## 0.2 Regras obrigatórias (não negociáveis)

1. Nenhum `TurboCore.exe` / `TurboCoreUpdater.exe` rodando durante o build.
2. O `--package` do `tc_sync_r2.py` DEVE apontar para `.../package` — nunca a raiz.
3. No GitHub: SOMENTE `turbocore_<v>_full.zip` + `setup_turbocore_<v>.exe` +
   `online_setup_turbocore<v>.exe`. NUNCA exes avulsos (servidos pelo R2).
4. **MANTER o histórico de releases** (diferente do SIG — decisão do usuário).
5. NUNCA commitar: `release_*.log`, `sync_*.log`, `r2_config.json`, `*.pem`,
   `settings.json`, `release/generated/`. Remover logs antes do `git add`.
6. Preflight e gates com código zero — QUALQUER `FAIL` impede a publicação.
7. Não inventar resultados: tudo reportado vem da saída real dos comandos.
8. Se QUALQUER etapa falhar: PARE e reporte erro exato + comando que falhou.
9. Ao terminar, atualize este documento se algo divergiu (§9).

## 1. Pré-requisitos

```bash
cd "D:/Projetos/TurboCore"
C:/Users/Gustavo/AppData/Local/Programs/Python/Python311/python.exe -c "import sys, PyInstaller; print(sys.version_info[:3], PyInstaller.__version__)"
# esperado: (3, 11, 0) 6.21.0
powershell.exe -NoProfile -Command "Get-Process TurboCore,TurboCoreUpdater -ErrorAction SilentlyContinue"
# esperado: vazio (se houver, fechar antes)
```

## 2. Bump da versão

```bash
C:/Users/Gustavo/AppData/Local/Programs/Python/Python311/python.exe scripts/tc_release.py bump --version YYYYMMDD_NNN
C:/Users/Gustavo/AppData/Local/Programs/Python/Python311/python.exe scripts/tc_release.py preflight
# esperado: "82 passed" (o número cresce) + "PASS: preflight (pytest)"
```

## 3. Build (package + full.zip + instaladores)

```bash
C:/Users/Gustavo/AppData/Local/Programs/Python/Python311/python.exe scripts/tc_release.py build --version YYYYMMDD_NNN
# esperado: "package: .../package" + "full: .../turbocore_<v>_full.zip (N bytes)"
C:/Users/Gustavo/AppData/Local/Programs/Python/Python311/python.exe scripts/tc_release.py installer-offline --version YYYYMMDD_NNN
# esperado: "offline: .../setup_turbocore_<v>.exe (N bytes)"
C:/Users/Gustavo/AppData/Local/Programs/Python/Python311/python.exe scripts/tc_release.py installer-online --version YYYYMMDD_NNN
# esperado: "online: .../online_setup_turbocore<v>.exe (N bytes)"
```

- O `build` falha se `release/generated/<v>/` já existir (não rode 2x a mesma versão).
- O `build` confere os obrigatórios (`TurboCore.exe`, `TurboCoreUpdater.exe`,
  `build-info.json`, `_internal/assets/*`, `_internal/base_library.zip`,
  `_internal/python311.dll`).
- Teste silencioso do offline (checklist): `setup_turbocore_<v>.exe /VERYSILENT /SUPPRESSMSGBOXES /DIR=<temp>` + conferir árvore.

## 4. Sync no Cloudflare R2 (o diff)

```bash
C:/Users/Gustavo/AppData/Local/Programs/Python/Python311/python.exe scripts/tc_sync_r2.py --package release/generated/YYYYMMDD_NNN/package --version YYYYMMDD_NNN
# esperado: "subir: N" (pequeno após a 1ª versão) + "sync_manifest.json publicado no R2"
```

Verificação pós-sync (obrigatória):

```bash
curl -s -A "TurboCoreUpdater/1.0" https://pub-9c30acc6bc8a445f8ffee08d60df4dac.r2.dev/sync_manifest.json | head -c 120
# esperado: HTTP 200 + {"schema":2,"version":"YYYYMMDD_NNN",...
PYTHONPATH=src python -c "from turbocore import updater_client; m = updater_client.fetch_sync_manifest(); print('manifesto R2:', m['version'], len(m['files']), 'arquivos')"
# esperado: a versão nova (valida a assinatura de ponta a ponta)
```

## 5. Commit e push

```bash
cd "D:/Projetos/TurboCore"
rm -f release_*.log sync_*.log
git add -A
git commit -m "Versao YYYYMMDD_NNN: <descrição curta>"
git push origin main
```

## 6. GitHub Releases (full + instaladores)

NUNCA passar os 3 assets juntos no `create` (upload interrompido deixa release
parcial). Metadados primeiro, depois um upload por comando:

```bash
cd "D:/Projetos/TurboCore/release/generated/YYYYMMDD_NNN"
gh release create YYYYMMDD_NNN --repo spigknot/TurboCore-Windows --title "TurboCore Windows YYYYMMDD_NNN" --notes "<descrição>"
gh release upload YYYYMMDD_NNN ./turbocore_YYYYMMDD_NNN_full.zip --repo spigknot/TurboCore-Windows
gh release upload YYYYMMDD_NNN ./setup_turbocore_YYYYMMDD_NNN.exe --repo spigknot/TurboCore-Windows
gh release upload YYYYMMDD_NNN ./online_setup_turbocoreYYYYMMDD_NNN.exe --repo spigknot/TurboCore-Windows
gh release view YYYYMMDD_NNN --repo spigknot/TurboCore-Windows --json tagName,url,assets
```

A view final deve listar exatamente os 3 assets. Se a release ficar em draft:
`gh release edit YYYYMMDD_NNN --draft=false`. Histórico é MANTIDO (não deletar
a anterior).

## 7. E2E (antes de declarar pronto)

```bash
C:/Users/Gustavo/AppData/Local/Programs/Python/Python311/python.exe scripts/e2e_update.py
# esperado: download do R2, "Atualização aplicada e validada", E2E_UPDATE_OK
```

O script instala a v1 corrompida num dir temp, atualiza pelo updater congelado
e limpa tudo (inclui matar o tray de verificação).

## 8. Entrega (relatório final obrigatório)

Reportar APENAS valores reais: 1. versão; 2. preflight (contagem real);
3. `subir: N` do sync; 4. link da release; 5. `git rev-parse HEAD`.

## 9. Manutenção do documento (obrigatório)

Se QUALQUER passo divergir, atualize este arquivo no mesmo commit da versão.

---

## Pitfalls e resolução (já vividos — não repetir)

| Sintoma | Causa | Resolução |
|---|---|---|
| `NameError: Path` no `tc_release.py` | `import pathlib` sem `from pathlib import Path` | importar os dois |
| `package incompleto: assets/...` | PyInstaller 6 põe datas em `_internal/assets/` | required mira `_internal/assets/*` |
| `Unable to find 'build/updater/assets/chip.png'` | `--add-data` relativo resolve contra `--specpath` | caminho absoluto (`$ROOT\...`) no build.ps1 |
| Gate do updater falha com `json.decode` | `Set-Content -Encoding utf8` grava BOM (PS 5.1) | ler com `utf-8-sig` |
| Gate `updater.exe não corresponde` | `turbocore_updater.py` mudou | rebuild via `updater/build.ps1`, revisar composição |
| `no matches found for C:/...` no `gh` | MSYS trata `C:/` como glob | `cd` + caminhos relativos `./arquivo` |
| `taskkill //F` não mata | MSYS mangla as flags | `Stop-Process` via powershell |
| `dist/TurboCore.exe: No such file` no build | onedir gera `dist/TurboCore/TurboCore.exe` | caminho com a subpasta |
| `build` recusa a versão | `release/generated/<v>/` já existe | nunca rodar 2x; apagar só se for refazer ANTES de publicar |
| Botão de update fantasma no painel | `dist/` dev sem `build-info.json` (instalado=None < remoto) | `write_dev_build_info.py` em todo build dev |
| `Permission denied` no lock (updater) | instalação sem `users-modify` (cópia manual) | reinstalar pelo setup; mensagem orienta (sem runas — igual ao SIG) |
| Console preta piscando (app) | `subprocess` sem `CREATE_NO_WINDOW` | flag em todo spawn (power.py, cpu_info.py, pdh.py) |
| Monitor zerado/viciado | `ProcessorFrequency` é o nominal fixo | ler `ActualFrequency` + `PercentIdleTime` (WMI) |
| Painel travando | leitura WMI (~1s) na thread da UI | thread leitora + fila, UI só drena |
| Release parcial/draft no GitHub | assets junto do `create` + timeout | metadados primeiro, uploads separados |
| `401/503` transitórios (R2/GitHub) | rede/API | repetir e conferir depois; nunca confiar em data, conferir SHA/nomes |
