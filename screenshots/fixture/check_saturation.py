import lyse

run = lyse.Run(lyse.path)
od = run.get_result('fit_cloud', 'peak_OD')
run.save_result('saturated', bool(od > 3))
