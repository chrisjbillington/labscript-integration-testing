# Fit sigma^2 = sigma_0^2 + (kB T / m) t^2 to the cloud sizes of each MOT load time.
import lyse
import numpy as np

kB, m = 1.380649e-23, 1.443e-25
df = lyse.data()
for load_time, group in df.groupby(('mot_load_time', '')):
    t = group[('tof', '')].to_numpy() * 1e-3
    sigma = group[('fit_cloud', 'sigma_mm')].to_numpy() * 1e-3
    slope, _ = np.polyfit(t ** 2, sigma ** 2, 1)
    print(f'load time {load_time:g} s: T = {slope * m / kB * 1e6:.1f} uK')
