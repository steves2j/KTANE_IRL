# KTANE_IRL
Keep Talking and Nobody Explosed in real Life

#Aid Memory
python3 -m pip install -r ../CanBusSysFirmware/micropython/tools/mpremote/requirements.txt

python3 ../CanBusSysFirmware/micropython/tools/mpremote/mpremote.py connect /dev/cu.usbmodem1411401 fs cp ktane_who_on_first.py :main.py

python3 ../CanBusSysFirmware/micropython/tools/mpremote/mpremote.py connect /dev/cu.usbmodem1411401
exec(open("main.py").read())