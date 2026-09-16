If (-NOT (Test-Path 'HKLM:\SOFTWARE\Microsoft\Edge')) {
    New-Item -Path 'HKLM:\SOFTWARE\Microsoft\Edge' -Force | Out-Null }
  New-ItemProperty -Path 'HKLM:\SOFTWARE\Microsoft\Edge' -Name 'HideFirstRunExperience' -Value '1' -PropertyType DWORD -Force

  If (-NOT (Test-Path 'HKLM:\SOFTWARE\Policies\Microsoft\Edge')) {
    New-Item -Path 'HKLM:\SOFTWARE\Policies\Microsoft\Edge' -Force | Out-Null }
  New-ItemProperty -Path 'HKLM:\SOFTWARE\Policies\Microsoft\Edge' -Name 'HideFirstRunExperience' -Value '1' -PropertyType DWORD -Force

  If (-NOT (Test-Path 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\OOBE')) {
    New-Item -Path 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\OOBE' -Force | Out-Null }
  New-ItemProperty -Path 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\OOBE' -Name 'DisablePrivacyExperience' -Value '1' -PropertyType DWORD -Force