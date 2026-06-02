$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$BotPath = Join-Path $ProjectDir "bot.py"
$StdoutLog = Join-Path $ProjectDir "bot.stdout.log"
$StderrLog = Join-Path $ProjectDir "bot.stderr.log"

$runningBot = Get-CimInstance Win32_Process |
    Where-Object {
        $_.Name -like "python*" -and
        (
            $_.CommandLine -like "*$BotPath*" -or
            ($_.CommandLine -like "*restaurant_ai_bot_pro*" -and $_.CommandLine -like "*bot.py*")
        )
    }

if ($runningBot) {
    exit 0
}

$python = (Get-Command python -ErrorAction Stop).Source

Start-Process `
    -FilePath $python `
    -ArgumentList "`"$BotPath`"" `
    -WorkingDirectory $ProjectDir `
    -WindowStyle Hidden `
    -RedirectStandardOutput $StdoutLog `
    -RedirectStandardError $StderrLog
