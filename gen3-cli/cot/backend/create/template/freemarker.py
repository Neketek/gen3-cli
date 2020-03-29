import os
import subprocess


# Wrapper of the script located in env.GENERATION_BASE_DIR/execution/
def run(environment_obj, *args):
    e = environment_obj
    script_filename = os.path.join(e.GENERATION_BASE_DIR, 'execution', 'freemaker.sh')
    script_call_line = ' '.join([script_filename, *args])
    try:
        process = subprocess.Popen(
            ['/bin/bash', '-c', script_call_line],
            stderr=subprocess.PIPE,
            encoding='utf-8'
        )
        process.wait()
        return process.returncode
    finally:
        try:
            process.kill()
        except ProcessLookupError:
            pass
