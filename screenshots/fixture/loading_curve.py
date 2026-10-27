import lyse

df = lyse.data()
for load_time, group in df.groupby(('mot_load_time', '')):
    print(f'load time {load_time:g} s: N = {group[("fit_cloud", "N")].mean():.3g}')
