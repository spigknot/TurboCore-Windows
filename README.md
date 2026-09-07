# TurboCore

App de bandeja (tray) para limitar os núcleos da CPU em tempo real via `powercfg`.

## Como funciona

- Detecta os núcleos físicos (`P`) e monta o menu: `1 Core, 2 Cores, 4 Cores, ... P`.
- Ao escolher N núcleos, calcula `X = teto(N / P * 100)` e executa, em ordem:
  `powercfg -setacvalueindex scheme_current sub_processor CPMAXCORES X` e
  `powercfg -setactive scheme_current`.
- Ex.: 10 de 18 núcleos → `teto(55,55)` = `56`.
- `Lembrar escolha` (JSON em `%APPDATA%\TurboCore\config.json`): reaplica no boot;
  desligado, o app **libera tudo explicitamente** (`CPMAXCORES 100`) ao iniciar.
- `Iniciar no boot` (Registro `HKCU\...\Run\TurboCore`): auto-executa no logon.

## Uso

Duplo clique em `dist\TurboCore.exe` → ícone do chip na bandeja → botão-direito.
De baixo para cima: `Iniciar no boot`, `Lembrar escolha`, núcleos.

## Build

```
build_exe.bat
```

Requer Python 3.11+ (gera `dist\TurboCore.exe`, sem janela de console).

## Desinstalar o boot

Desmarque `Iniciar no boot` no menu, ou apague o valor `TurboCore` em
`HKCU\Software\Microsoft\Windows\CurrentVersion\Run`.

## Notas

- Gerencia só o perfil de **tomada (AC)**.
- Se o `powercfg` negar acesso, rode como administrador.
- Leitura do valor atual: `powercfg /QH SCHEME_CURRENT SUB_PROCESSOR CPMAXCORES`
  (vem em **hexadecimal**: `0x38` = 56, `0x64` = 100).
