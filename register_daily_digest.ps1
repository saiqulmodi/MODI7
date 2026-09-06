# Registers MODI7_DailyDigest: runs run_daily_alerts_digest.bat once a day
# at 4:00 PM IST, Monday-Friday -- after market close (3:30 PM NSE close /
# 3:45 PM MODI2's own is_market_open cutoff) so the day's final alerts have
# already fired before the digest reads the log.
#
# Reuses an existing MODI7 task's Principal (same run-as user/logon type)
# so it behaves the same way unattended -- doesn't change or touch that
# task itself, only copies its run-as settings for this new one.
#
# Run this in an elevated PowerShell (Run as Administrator) from the
# MODI7 folder.

$existing = Get-ScheduledTask -TaskName "MODI7_TrendScan"

$trigger = New-ScheduledTaskTrigger -Weekly `
    -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 4:00PM

$action = New-ScheduledTaskAction -Execute "wscript.exe" `
    -Argument '"C:\Users\saiqu\Projects\MODI7\run_hidden_MODI7_DailyDigest.vbs"'

Register-ScheduledTask -TaskName "MODI7_DailyDigest" `
    -Action $action -Trigger $trigger -Principal $existing.Principal `
    -Description "MODI7: sends one consolidated Telegram digest of every alert every MODI project sent that day, 4:00 PM IST Mon-Fri."

Write-Host "Registered. Verifying:"
Get-ScheduledTask -TaskName "MODI7_DailyDigest" | Format-List TaskName, State
(Get-ScheduledTask -TaskName "MODI7_DailyDigest").Triggers
