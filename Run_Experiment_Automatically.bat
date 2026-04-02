@echo off
echo ==========================================================
echo    KBCS Automated Virtual Machine Runner
echo ==========================================================
echo.
echo This script will automatically:
echo 1. Zip your Windows code
echo 2. Send it securely to your running P4 Ubuntu VM
echo 3. Run the Mininet experiment inside the VM
echo 4. Extract the final graphs to your Windows folder
echo.

set VM_NAME="P4 Tutorials Development 2026-03-01 1"
set VBOX_PATH="C:\Program Files\Oracle\VirtualBox\VBoxManage.exe"
set SRC_DIR="C:\Users\ishan\OneDrive\Documents\RM3\Research_KBCS"

REM Step 1: Zip the kbcs directory
echo [1/4] Zipping code project...
cd /d %SRC_DIR%
IF EXIST kbcs.zip del kbcs.zip
powershell -Command "Compress-Archive -Path 'kbcs\*' -DestinationPath 'kbcs.zip' -Force"

REM Step 2: Push to VM
echo [2/4] Uploading to VM... (Make sure your Ubuntu VM is turned ON)
%VBOX_PATH% guestcontrol %VM_NAME% copyto "%SRC_DIR%\kbcs.zip" "/home/p4/kbcs.zip" --username "p4" --password "p4"
%VBOX_PATH% guestcontrol %VM_NAME% copyto "%SRC_DIR%\runner.sh" "/home/p4/runner.sh" --username "p4" --password "p4"

REM Step 3: Execute on VM
echo [3/4] Running experiment inside the Ubuntu VM... (This takes ~2 minutes, please wait)
%VBOX_PATH% guestcontrol %VM_NAME% run --exe "/bin/bash" --username "p4" --password "p4" --wait-stdout -- -c "chmod +x /home/p4/runner.sh && /home/p4/runner.sh"

REM Step 4: Download Results
echo [4/4] Downloading Results from VM...
IF EXIST final_results rmdir /S /Q final_results
%VBOX_PATH% guestcontrol %VM_NAME% copyfrom "/home/p4/results.zip" "%SRC_DIR%\results.zip" --username "p4" --password "p4"
powershell -Command "Expand-Archive -Path 'results.zip' -DestinationPath 'final_results' -Force"

echo.
echo ==========================================================
echo   DONE! Check the 'final_results' folder for your graphs!
echo ==========================================================
pause
