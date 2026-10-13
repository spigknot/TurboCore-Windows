# TurboCore

App de bandeja (tray) para limitar os núcleos da CPU em tempo real via `powercfg`.

## Como funciona

- Detecta os núcleos físicos (`P`) e monta o menu: `1 Core, 2 Cores, 4 Cores, ... P`.
- Ao escolher N núcleos, calcula `X = teto(N / P * 100)` e executa, em ordem:
  `powercfg -setacvalueindex ... CPMINCORES 1-thread` (mínimo em 1 thread,
  senão o parking fica desabilitado e o máximo não pega),
  `powercfg -setacvalueindex ... CPMAXCORES X` e `powercfg -setactive`.
- Ex.: 10 de 18 núcleos → mínimo `teto(100/36) = 3`, máximo `teto(55,55)` = `56`.
- `Lembrar escolha` (JSON em `%APPDATA%\TurboCore\config.json`): reaplica no boot;
  desligado, o app **libera tudo explicitamente** (`CPMINCORES 100` + `CPMAXCORES 100`) ao iniciar.
- `Iniciar no boot` (Registro `HKCU\...\Run\TurboCore`): auto-executa no logon.

## Uso

Duplo clique em `dist\TurboCore\TurboCore.exe` → ícone do chip na bandeja → botão-direito.
De baixo para cima: `Sair`, `Iniciar no boot`, `Lembrar escolha`, núcleos.

O painel mostra a tabela de relógio ativo, com barras de clock, MHz e
multiplicador por núcleo físico, seguindo a janela de referência do HWiNFO.
O TurboCore lê os sensores diretamente pela biblioteca LibreHardwareMonitor
0.9.6 e pelo driver [PawnIO](https://pawnio.eu), sem usar o aplicativo HWiNFO.
Para essa leitura, o PawnIO deve estar instalado. O TurboCore pode ser aberto
normalmente: ao abrir o painel, inicia um leitor separado com a permissão de
administrador necessária ao driver, mantendo a interface e a bandeja sem
elevação. A confirmação depende da política de UAC do Windows. O boot silencioso
não solicita essa permissão; o leitor começa apenas ao abrir o painel.
Se a permissão for cancelada, reabra o painel para tentar novamente.
Sem acesso ao hardware, as células mostram `—` e o log
explica a falha; não há substituição por estimativas PDH.

Clique em qualquer ponto da tabela para alternar entre relógio ativo (barras
amarelas) e relógio efetivo (barras verdes). Outro clique volta ao modo anterior.
Os dois modos mantêm as colunas e a mesma escala de barras, sem título, contorno
ou botão de fechar internos.

O painel usa a mesma fonte Tahoma de 9 pixels da tabela, incluindo o log.
A janela tem 274 pixels de largura e ajusta a altura ao número de núcleos;
o log ocupa 98 pixels e permite rolar as mensagens. O slider verde mantém
as posições discretas, com o botão de raio ao lado e bordas suavizadas.

O relógio ativo vem da medição do clock base e dos multiplicadores de hardware.
No Xeon/Intel com suporte APERF/MPERF, o relógio efetivo usa a diferença dos
contadores de ciclos realmente executados durante o intervalo completo,
incluindo o tempo ocioso. A primeira amostra apenas estabelece o início do
intervalo; a leitura efetiva aparece na amostra seguinte. O modo ativo continua
funcionando se um modelo não oferecer os contadores efetivos suportados.
Leituras de programas distintos podem variar por calibração e instante de
amostragem. As barras usam uma escala comum que mantém o maior clock observado,
arredondado para cima em passos de 100 MHz. O fechamento usa o botão da janela
principal.

## Build

```
build_exe.bat
```

Requer Python 3.11+ (gera `dist\TurboCore\TurboCore.exe`, sem janela de console).
O build baixa as bibliotecas de hardware de uma versão fixa e verifica o SHA-256
do pacote antes de incluí-las. Não instala drivers automaticamente.

## Desinstalar o boot

Desmarque `Iniciar no boot` no menu, ou apague o valor `TurboCore` em
`HKCU\Software\Microsoft\Windows\CurrentVersion\Run`.

## Notas

- Gerencia só o perfil de **tomada (AC)**.
- Se o `powercfg` negar acesso, rode como administrador.
- Leitura do valor atual: `powercfg /QH SCHEME_CURRENT SUB_PROCESSOR CPMAXCORES`
  (vem em **hexadecimal**: `0x38` = 56, `0x64` = 100).
