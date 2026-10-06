# Runs in the interactive Windows user's desktop. No plaintext output/files.
$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Security
$root=Split-Path -Parent $PSScriptRoot
$keyPath=Join-Path $root 'config\jev-key.dpapi'
$form=New-Object System.Windows.Forms.Form
$form.Text='Jev API key - encrypted local storage'
$form.Size=New-Object System.Drawing.Size(550,220)
$form.StartPosition='CenterScreen'
$form.TopMost=$true
$form.FormBorderStyle='FixedDialog'
$form.MaximizeBox=$false
$form.MinimizeBox=$false
$label=New-Object System.Windows.Forms.Label
$label.Text="Paste the new Jev API key below, then click Save (or press Enter).`r`nThe key is hidden and encrypted for this Windows user."
$label.Location=New-Object System.Drawing.Point(20,20)
$label.Size=New-Object System.Drawing.Size(500,45)
$inputBox=New-Object System.Windows.Forms.TextBox
$inputBox.Location=New-Object System.Drawing.Point(20,75)
$inputBox.Size=New-Object System.Drawing.Size(495,28)
$inputBox.UseSystemPasswordChar=$true
$inputBox.MaxLength=4096
$save=New-Object System.Windows.Forms.Button
$save.Text='Save'
$save.Location=New-Object System.Drawing.Point(325,125)
$cancel=New-Object System.Windows.Forms.Button
$cancel.Text='Cancel'
$cancel.Location=New-Object System.Drawing.Point(420,125)
$cancel.DialogResult=[System.Windows.Forms.DialogResult]::Cancel
$form.AcceptButton=$save
$form.CancelButton=$cancel
$form.Controls.AddRange(@($label,$inputBox,$save,$cancel))
$save.Add_Click({
    $plain=$null
    try {
        if ([string]::IsNullOrWhiteSpace($inputBox.Text)) { return }
        $plain=[System.Text.Encoding]::UTF8.GetBytes($inputBox.Text.Trim())
        $encrypted=[System.Security.Cryptography.ProtectedData]::Protect($plain,$null,[System.Security.Cryptography.DataProtectionScope]::CurrentUser)
        New-Item -ItemType Directory -Force (Split-Path -Parent $keyPath) | Out-Null
        $temporary=$keyPath+'.pending'
        [System.IO.File]::WriteAllBytes($temporary,$encrypted)
        if (Test-Path $keyPath) {
            $backup=$keyPath+'.previous-'+(Get-Date -Format 'yyyyMMddHHmmss')
            [System.IO.File]::Replace($temporary,$keyPath,$backup)
        } else { [System.IO.File]::Move($temporary,$keyPath) }
        $inputBox.Clear()
        [System.Windows.Forms.MessageBox]::Show('Encrypted key saved. You can return to the game.','Jev key saved') | Out-Null
        $form.DialogResult=[System.Windows.Forms.DialogResult]::OK
        $form.Close()
    } catch {
        [System.Windows.Forms.MessageBox]::Show('Could not save the key. No key was printed.','Save failed') | Out-Null
    } finally {
        if ($null -ne $plain) { [Array]::Clear($plain,0,$plain.Length) }
    }
})
$form.Add_Shown({$inputBox.Focus()})
$null=$form.ShowDialog()
$inputBox.Clear()
$form.Dispose()
