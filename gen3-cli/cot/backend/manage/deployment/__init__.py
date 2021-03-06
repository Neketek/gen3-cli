from cot.backend.common import runner


def run(
    delete=None,
    deployment_initiate=None,
    level=None,
    deployment_monitor=None,
    deployment_name=None,
    region=None,
    deployment_scope=None,
    deployment_unit=None,
    deployment_wait=None,
    deployment_unit_subset=None,
    _is_cli=False
):
    options = {
        '-d': delete,
        '-i': deployment_initiate,
        '-m': deployment_monitor,
        '-l': level,
        '-n': deployment_name,
        '-r': region,
        '-s': deployment_scope,
        '-u': deployment_unit,
        '-w': deployment_wait,
        '-z': deployment_unit_subset
    }
    runner.run('manageDeployment.sh', [], options, _is_cli)
