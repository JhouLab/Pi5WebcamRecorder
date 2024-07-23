import os
import platform
import pygame
import tkinter as tk
from tkinter import *
import time

root = tk.Tk()
embed = tk.Frame(root, width=500, height=500) #creates embed frame for pygame window
embed.grid(columnspan=600, rowspan=500) # Adds grid
embed.pack(side=LEFT) #packs window to the left
buttonwin = tk.Frame(root, width=75, height=500)
buttonwin.pack(side=LEFT)

os.environ['SDL_WINDOWID'] = str(embed.winfo_id())
if platform.system() == 'Windows':
    os.environ['SDL_VIDEODRIVER'] = 'windib'
else:
    os.environ['SDL_VIDEODRIVER'] = 'wayland'
    

# pygame.init()
pygame.display.init()
screen = pygame.display.set_mode((500, 500))
screen.fill((255, 155, 55))   # pygame.Color(255, 155, 55))
pygame.display.update()


def draw2():
    pygame.draw.circle(screen, (50, 50, 100), (250, 250), 125)
    pygame.display.update()


button1 = Button(buttonwin, text='Draw',  command=draw2)
button1.pack(side=LEFT)
root.update()

while True:
    pygame.display.update()
    root.update()
    time.sleep(0.001)

