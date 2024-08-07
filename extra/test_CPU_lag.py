import time

t_start = time.time()
next_report = t_start + 1
t_end = t_start + 20

while True:
    t1 = time.time()
    if t1 > t_end:
        break
    time.sleep(0.001)
    lag = time.time() - t1
    if lag > 0.002:
        print(f'{t1 - t_start:.6f}, lag {lag:.6f}s')

    if t1 > next_report:
        print(f'{t1 - t_start:.6f}')
        next_report = next_report + 1



