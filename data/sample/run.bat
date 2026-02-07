@echo off
REM Launch Bank Beacon Reconciliation GUI for this data folder
python "%~dp0..\..\reconciliation_gui.py" "%~dp0"
pause
