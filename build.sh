#!/bin/bash
set -x
cp bdsm.py utils
cd utils
rm -rf build dist bdsm.spec
# set build flag
sed -i '0,/RUN_AS_EXE = False/s/RUN_AS_EXE = False/RUN_AS_EXE = True/' bdsm.py
pyinstaller --hidden-import=yaml \
            --hidden-import=patool \
            --hidden-import=patoolib \
            --hidden-import=patoolib.programs \
            --hidden-import=patoolib.programs.p7zip \
            --hidden-import=patoolib.programs.unzip \
            --hidden-import=patoolib.programs.tar \
            --hidden-import=patoolib.programs.gzip \
            --hidden-import=patoolib.programs.bzip2 \
            --hidden-import=patoolib.programs.zip \
--onefile --windowed --name bdsm gui.py
mkdir dist/utils
cp -r resources dist/utils
rm bdsm.py
set +x

echo done!
echo your binary lies in utils/dist/bdsm, happy modding!
