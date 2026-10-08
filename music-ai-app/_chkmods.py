import sys
mods = ['requests', 'urllib.request', 'json']
for m in mods:
    try:
        __import__(m.split('.')[0])
        print(f"OK  {m}")
    except Exception as e:
        print(f"FAIL {m}: {e}")
print("python", sys.version.split()[0])
