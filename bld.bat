SET PYTHONPATH=lib

python setup.py py2exe -O2 --compressed

rm -rf bin
mv dist bin

