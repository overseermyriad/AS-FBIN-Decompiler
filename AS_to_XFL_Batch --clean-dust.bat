@echo off
setlocal enabledelayedexpansion

echo ===================================================
echo     Batch Processing Flash Animation Assets
echo ===================================================

:: Ensure python is installed and in the system PATH
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo Error: Python is not installed or not added to your Environment PATH.
    echo Please install Python and try again.
    pause
    exit /b 1
)

set "PROCESSED_COUNT=0"

:: Loop through every .bin file in the current directory
for %%F in (*.bin) do (
    set "BIN_FILE=%%F"
    set "BASE_NAME=%%~nF"
    set "PVR_FILE=!BASE_NAME!.pvr"
    set "PNG_FILE=!BASE_NAME!.png"

    echo.
    echo ---------------------------------------------------
    echo Checking asset group: [!BASE_NAME!]
    
    :: Check if a matching .pvr file exists for this .bin file
    if exist "!PVR_FILE!" (
        echo Found matching pair: !BIN_FILE! ^<---^> !PVR_FILE!
        echo Executing pipeline python script...
        
        python AS_to_XFL.py "!BIN_FILE!" "!PVR_FILE!" --clean-dust
        
        if !errorlevel! equ 0 (
            set /a PROCESSED_COUNT+=1
        ) else (
            echo [ERROR] Pipeline failed or encountered an error processing !BASE_NAME!
            echo Halting batch process.
            pause
            exit /b 1
        )
    ) else if exist "!PNG_FILE!" (
        echo Found matching pair: !BIN_FILE! ^<---^> !PNG_FILE!
        echo Executing pipeline python script...
        
        python AS_to_XFL.py "!BIN_FILE!" "!PNG_FILE!" --clean-dust
        
        if !errorlevel! equ 0 (
            set /a PROCESSED_COUNT+=1
        ) else (
            echo [ERROR] Pipeline failed or encountered an error processing !BASE_NAME!
            echo Halting batch process.
            pause
            exit /b 1
        )
    ) else (
        echo [SKIP] Found !BIN_FILE! but no matching !PVR_FILE! or !PNG_FILE! was detected.
    )
)

echo.
echo ===================================================
echo Done! Successfully processed %PROCESSED_COUNT% animation asset(s).
echo ===================================================
pause