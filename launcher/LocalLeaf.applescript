on run
    set launcherPath to "/Users/sz5380/Phd/Software/localleaf/launch.py"
    set logPath to "/private/tmp/localleaf-launch.log"
    try
        do shell script "/usr/bin/nohup /usr/bin/python3 " & quoted form of launcherPath & " > " & quoted form of logPath & " 2>&1 &"
    on error errorMessage
        display alert "LocalLeaf failed to start" message errorMessage as critical
    end try
end run
