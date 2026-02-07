@echo off
REM Launch Bank Beacon Reconciliation GUI for this data folder
set "DATA_DIR=%~dp0"
set "DATA_DIR=%DATA_DIR:~0,-1%"
python "%DATA_DIR%\..\..\reconciliation_gui.py" "%DATA_DIR%"
pause
