$p = Start-Process -FilePath 'D:\Projetos\TurboCore\updater\bin\TurboCoreUpdater.exe' -ArgumentList '--target','D:\Projetos\TurboCore\dist\TurboCore','--pid','0','--log','D:\Projetos\TurboCore\updater_probe.log','--relocated' -Wait -PassThru
Write-Output ("FROZEN_EXIT=" + $p.ExitCode)
