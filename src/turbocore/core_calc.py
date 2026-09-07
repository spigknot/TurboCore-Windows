"""Regras puras: lista de opcoes e % CPMAXCORES."""
from __future__ import annotations

import math
import re


def build_core_options(physical_cores: int) -> list[int]:
    """1 + pares ate P, incluindo P se ainda nao estiver.

    P=18 -> [1,2,4,6,8,10,12,14,16,18]; P=6 -> [1,2,4,6]; P=5 -> [1,2,4,5].
    """
    if not isinstance(physical_cores, int) or physical_cores < 1:
        raise ValueError("physical_cores deve ser int >= 1")
    if physical_cores == 1:
        return [1]
    opts = [1]
    n = 2
    while n < physical_cores:
        opts.append(n)
        n += 2
    if opts[-1] != physical_cores:
        opts.append(physical_cores)
    return opts


def percent_for_cores(chosen_cores: int, physical_cores: int) -> int:
    """X do CPMAXCORES: ceil(chosen/physical*100), clamp 1..100.

    Equivale a ceil(threads_usadas/threads_totais*100) qualquer que seja o HT.
    Ex.: 10/18 -> ceil(55.55) = 56.
    """
    if physical_cores < 1:
        raise ValueError("physical_cores deve ser >= 1")
    if not (1 <= chosen_cores <= physical_cores):
        raise ValueError("chosen_cores fora do intervalo 1..physical_cores")
    return max(1, min(100, math.ceil(chosen_cores / physical_cores * 100)))


def parse_powercfg_hex(output: str) -> int:
    """Extrai o ULTIMO 0xNN da saida e converte p/ decimal (generico).

    O Windows retorna hexadecimal (ex. 0x00000038 = 56). Saida pode ser PT-BR.
    Levanta ValueError se nao achar hex.
    """
    matches = re.findall(r"0x[0-9a-fA-F]+", output)
    if not matches:
        raise ValueError("nenhum valor hexadecimal encontrado na saida do powercfg")
    return int(matches[-1], 16)


def parse_powercfg_ac_hex(output: str) -> int:
    """Extrai o hex da linha AC (Correntes Alternadas / Current AC) do `/qh`.

    O `/qh` lista AC e DC; o ultimo hex da saida e o DC. Como o app so
    gerencia AC, a leitura deve mirar a linha AC. Levanta ValueError sem ela.
    """
    for line in output.splitlines():
        if "0x" not in line:
            continue
        low = line.lower()
        if " ac " in f" {low} " or " ac power" in low or "alternadas" in low:
            matches = re.findall(r"0x[0-9a-fA-F]+", line)
            if matches:
                return int(matches[0], 16)
    raise ValueError("nenhuma linha AC encontrada na saida do powercfg")
