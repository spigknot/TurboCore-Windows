# Relógio ativo — referência e validação

Referência fornecida: captura de 255 × 310 pixels da janela
`CPU #0 - Relógio ativo`. Observação local em 13/10/2026: HWiNFO64 8.26-5730,
Xeon E5-2696 v3, 18 núcleos e 36 processadores lógicos. A janela mostra uma linha
por núcleo físico, quatro colunas, fundo cinza e barras amarelas, com passo
vertical de 14 pixels. O quadro interno foi reproduzido em 250 × 304 pixels.

Na observação inicial, a janela mostrava 3746 MHz / x38.00, enquanto o resumo
mostrava 3745.6 MHz de clock ativo, BCLK de 98.6 MHz e clock efetivo médio de
70.6 MHz. Portanto, reduzir o clock pelo percentual de tempo ocioso não reproduz
o significado dessa tabela. O autor do HWiNFO explica a leitura tradicional como
BCLK × multiplicador, e diferencia essa leitura dos contadores efetivos:
https://www.hwinfo.com/forum/threads/effective-clock-vs-instant-discrete-clock.5958/

A implementação usa LibreHardwareMonitor 0.9.6 com PawnIO, independentemente do
HWiNFO instalado ou aberto. O código público da biblioteca amostra os MSRs de
clock da CPU Intel e mede a frequência do TSC para determinar BCLK:
https://github.com/LibreHardwareMonitor/LibreHardwareMonitor/blob/v0.9.6/LibreHardwareMonitorLib/Hardware/Cpu/IntelCpu.cs

O backend exige uma medição válida de BCLK e de todos os núcleos físicos.
Não aceita o fallback TSC da biblioteca como um clock de núcleo. A numeração
dos sensores físicos é preservada, sem agregar pares arbitrários de threads.
As barras usam o pico observado arredondado em 100 MHz; a escala interna exata
do HWiNFO não foi estabelecida pela observação. Sistemas com múltiplos sockets
geram uma mensagem explícita; suporte a outros modelos não foi validado nesta
máquina.

Validação real elevada: três amostras nos 18 núcleos, aproximadamente 3791 MHz
e multiplicador x38.00; leitura de 214–335 ms em segundo plano. A calibração
de BCLK dessa biblioteca difere da calibração inicial mostrada pelo HWiNFO.
Não se afirma igualdade numérica entre amostragens de programas diferentes.
O painel foi renderizado com os sensores reais; imagem e relatório de execução
ficam em `build/hardware-panel-live.png` e `build/hardware-clock-report.json`.

Limite da análise do executável: a inspeção REA de recursos PE falhou com
`Resource range is not entirely file-backed in one section`. Nenhuma conclusão
sobre código interno ou algoritmo de calibração proprietário foi derivada
desse resultado. O layout e o comportamento visível vieram da captura fornecida
e da observação da janela real, corroborados pela documentação do autor.

Ajuste posterior solicitado pelo usuário: removidos o título, o botão de fechar
interno e a moldura da tabela. A faixa superior foi eliminada, reduzindo a altura
do componente de 304 para 272 pixels para 18 núcleos.

## Abertura normal e privilégio do leitor

Auditoria local de 13/10/2026: `GetTokenInformation(TokenElevation)` retornou
verdadeiro para o HWiNFO64 aberto (PID 11444), cujo processo pai era Explorer
(PID 8356). O manifesto embutido contém `level="requireAdministrator"`.
A política `ConsentPromptBehaviorAdmin` era 0, com `EnableLUA` igual a 1:
nesta configuração a elevação é concedida sem exibir a confirmação de UAC.
Essas configurações foram apenas lidas, sem alterações.

O TurboCore agora mantém interface e bandeja sem elevação. Na primeira leitura
do painel, inicia uma instância separada de seu próprio leitor com `runas`.
O Windows decide se a confirmação é necessária conforme sua política.
O boot silencioso não inicia esse leitor nem solicita elevação. A permissão
cancelada fica registrada até o usuário reabrir o painel, evitando repetição
automática de prompts durante os refreshes.

O leitor elevado aceita apenas READ/CLOSE por conexão privada em 127.0.0.1,
autenticada com segredo aleatório de 256 bits. As mensagens são JSON limitado
a 64 KiB, com validação da quantidade de núcleos e de valores finitos.
Não há operações de arquivo, processos, configuração de energia ou leitura
arbitrária de registradores nessa interface. O leitor encerra ao perder a
conexão ou quando o processo proprietário termina; enquanto o painel está
fechado, aguarda pedidos sem continuar amostrando a CPU.

Validação por processo sem elevação: `build/broker-clock-report.json`, com
`interface_elevated: false` e leituras válidas nos 18 núcleos.

## Alternância entre relógio ativo e efetivo

Nova captura fornecida: tabela verde `CPU #0 - Relógio efetivo`. O usuário
descreveu que um clique na tabela alterna os modos e outro restaura o anterior.
O TurboCore implementa esse clique no próprio Canvas, preservando as remoções
anteriores de título, contorno e botão interno. A troca usa as duas séries da
mesma coleta e não inicia outro leitor nem bloqueia a interface.

A biblioteca 0.9.6 não oferece sensores efetivos para este Xeon. A extensão
usa a API pública IntelMsr com o módulo PawnIO já distribuído para ler os
registradores APERF (0xE8) e MPERF (0xE7), sem escritas ou resets. O bit
CPUID.06H:ECX[0] é verificado antes da leitura. As afinidades vêm da propriedade
pública CpuId, na mesma ordem física dos sensores ativos.

MHz efetivos = diferença dos ciclos APERF / intervalo completo em segundos /
1.000.000. MPERF também é verificado para detectar resets e épocas inválidas.
Cada thread tem seu próprio instante de amostragem; a linha física mostra o
maior valor entre os irmãos SMT, para representar carga em qualquer um deles.
Essa agregação física é uma escolha explícita da implementação; o algoritmo
privado de agregação do HWiNFO não foi estabelecido pela captura. O multiplicador
efetivo é MHz efetivos / BCLK medido. A escala das barras é a mesma dos clocks
ativos. A amostra inicial, resets, pausas maiores que cinco segundos e intervalos
curtos reancoram os contadores, sem inventar números.

O autor do HWiNFO descreve o modo efetivo como uma média dos estados de clock,
incluindo os estados suspensos. A definição dos contadores C0 é documentada
no manual Intel, volume 3B, seção de coordenação de P-states:
https://cdrdv2-public.intel.com/868137/325462-089-sdm-vol-1-2abcd-3abcd-4.pdf

Validação local por interface sem elevação: clique ativo → efetivo → ativo
confirmado em `build/effective-panel-report.json`. A carga controlada de três
segundos no processador lógico 35 elevou a linha física 17 de aproximadamente
7,5 MHz para 3445 MHz efetivos, em `build/effective-load-report.json`. As demais
linhas ociosas permaneceram próximas de 1–3 MHz. Nenhuma configuração de energia
foi alterada pela validação. O gradiente verde foi comparado aos pixels da
captura; ele se estende do verde escuro ao claro na parte preenchida da barra.
