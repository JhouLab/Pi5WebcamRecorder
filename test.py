import tkinter as tk

root = tk.Tk()

root.columnconfigure(0, weight=1, uniform=1)
root.columnconfigure(1, weight=1, uniform=1)

for row, text in enumerate((
        "Hello", "short", "All the buttons are not the same size",
        "Options", "Test2", "ABC", "This button is so much larger")):
    button = tk.Button(root, text=text)
    button.grid(row=row, column=0, sticky="ew")
    button = tk.Button(root, text=text + " hi there")
    button.grid(row=row, column=1, sticky="ew")

root.mainloop()