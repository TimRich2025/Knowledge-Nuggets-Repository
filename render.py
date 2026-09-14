import runpy, subprocess

_REAL_RUN = subprocess.run

def _patched_run(cmd, *args, **kwargs):
    if isinstance(cmd, (list, tuple)) and cmd and str(cmd[0]) == 'ffmpeg':
        cmd = list(cmd)
        if kwargs.get('timeout') == 900:
            kwargs['timeout'] = 1000
        for i, x in enumerate(cmd[:-1]):
            if x == '-preset' and cmd[i + 1] == 'slow':
                cmd[i + 1] = 'medium'
            if x == '-filter_complex':
                fc = cmd[i + 1]
                fc = fc.replace('scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,gblur=sigma=28,eq=brightness=-0.06:saturation=0.85', 'scale=270:480:force_original_aspect_ratio=increase,crop=270:480,gblur=sigma=8,scale=1080:1920:flags=bilinear,eq=brightness=-0.06:saturation=0.85')
                cmd[i + 1] = fc
        print('KN_RENDER_PATCH: optimized FIT_BLUR + preset=medium')
    return _REAL_RUN(cmd, *args, **kwargs)

subprocess.run = _patched_run
runpy.run_path('render_core.py', run_name='__main__')
