param([string]$Dest)
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
Add-Type @'
using System;
using System.Runtime.InteropServices;
public class W {
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT rect);
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L; public int T; public int R; public int B; }
}
'@
$proc = Get-Process chrome -EA SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 -and $_.MainWindowTitle -match 'frontend|localhost|liquiddemocracy' } | Select-Object -First 1
if (-not $proc) { $proc = Get-Process chrome -EA SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1 }
if (-not $proc) { Write-Output "no chrome window"; exit 1 }
[W]::SetForegroundWindow($proc.MainWindowHandle) | Out-Null
Start-Sleep -Milliseconds 800
$r = New-Object W+RECT
[W]::GetWindowRect($proc.MainWindowHandle, [ref]$r) | Out-Null
$w = $r.R - $r.L; $h = $r.B - $r.T
$bmp = New-Object System.Drawing.Bitmap $w, $h
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($r.L, $r.T, 0, 0, [System.Drawing.Size]::new($w, $h))
$bmp.Save($Dest, [System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose(); $bmp.Dispose()
"saved $Dest $((Get-Item $Dest).Length) bytes ${w}x${h} title='$($proc.MainWindowTitle)'"
