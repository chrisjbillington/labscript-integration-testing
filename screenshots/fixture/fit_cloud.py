# Synthetic results for the screenshots: the atom number and the cloud size of a
# ballistically expanding cloud of rubidium-87 at 25 uK, with 3 % noise.
import zlib

import lyse
import numpy as np

run = lyse.Run(lyse.path)
g = run.get_globals()
rng = np.random.default_rng(zlib.crc32(lyse.path.encode()))
kB, m = 1.380649e-23, 1.443e-25
N = 2.4e7 * (1 - np.exp(-g['mot_load_time'] / 1.2)) * (1 + 0.03 * rng.normal())
sigma = np.sqrt((0.35e-3) ** 2 + kB * 25e-6 / m * (g['tof'] * 1e-3) ** 2)
sigma *= 1 + 0.03 * rng.normal()
od = 3 * 780e-9 ** 2 / (2 * np.pi) * N / (2 * np.pi * sigma ** 2)
run.save_result('N', N)
run.save_result('sigma_mm', sigma * 1e3)
run.save_result('peak_OD', od)
print(f'N = {N:.3g}, sigma = {sigma * 1e3:.3f} mm, peak OD = {od:.2f}')
