Set objShell = CreateObject("WScript.Shell")
objShell.CurrentDirectory = "C:\Users\saiqu\Projects\MODI7"
objShell.Run "C:\Users\saiqu\AppData\Local\Python\pythoncore-3.14-64\python.exe check_commodity_filter.py", 0, False
