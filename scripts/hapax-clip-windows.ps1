param([ValidateSet('Client','Server','Build')][string]$Mode = 'Client')
$ErrorActionPreference = 'Stop'
try {
    $source = Join-Path $PSScriptRoot 'hapax-clip-windows.cs'
    if ($Mode -eq 'Build') {
        $output = Join-Path $PSScriptRoot 'hapax-clip-windows.exe'
        if (Test-Path $output) { throw 'Preserve existing build before replacement' }
        Add-Type -Path $source -ReferencedAssemblies 'System.Web.Extensions.dll' -OutputAssembly $output -OutputType ConsoleApplication
        return
    }
    Add-Type -Path $source -ReferencedAssemblies 'System.Web.Extensions.dll'
    if ($Mode -eq 'Client') {
        [HapaxClipboard]::Client()
    } else {
        if ([Threading.Thread]::CurrentThread.ApartmentState -ne 'STA') { throw 'STA required' }
        $config = [string](Get-Content -Raw (Join-Path $PSScriptRoot 'endpoint.json')) | ConvertFrom-Json
        $owner = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
        if ($config.v -ne 1 -or $config.principal -ne $owner) { throw 'Enrollment required' }
        [HapaxClipboard]::Server([string]$config.endpoint)
    }
} catch {
    [Console]::Error.WriteLine('Clipboard request refused. Next action: check enrollment and the active unlocked interactive desktop endpoint.')
    exit 1
}
