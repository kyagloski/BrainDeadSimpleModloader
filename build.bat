@echo off
echo on

copy bdsm.py utils
cd utils
rmdir /s /q build
rmdir /s /q dist
del /f /q bdsm.spec

powershell -Command "(Get-Content bdsm.py) -replace 'RUN_AS_EXE = False', 'RUN_AS_EXE = True' | Set-Content bdsm.py"

pyinstaller --hidden-import=yaml ^
            --hidden-import=patool ^
            --hidden-import=patoolib ^
            --hidden-import=patoolib.programs ^
            --hidden-import=patoolib.programs.p7zip ^
            --hidden-import=patoolib.programs.unzip ^
            --hidden-import=patoolib.programs.tar ^
            --hidden-import=patoolib.programs.gzip ^
            --hidden-import=patoolib.programs.bzip2 ^
            --hidden-import=patoolib.programs.zip ^
            --hidden-import=patoolib.programs.unar ^
            --onefile --windowed --name bdsm gui.py

mkdir dist\utils
xcopy /e /i resources dist\utils\resources
del /f /q bdsm.py

@echo off
echo done!
echo your binary lies in utils\dist\bdsm.exe, happy modding!
