import collections
from unittest import mock
from click.testing import CliRunner
from cot.command.create.build_blueprint import build_blueprint as create_build_blueprint
from tests.unit.command.test_option_generation import run_options_test


ALL_VALID_OPTIONS = collections.OrderedDict()

ALL_VALID_OPTIONS['!-u,--deployment-unit'] = 'deployment_unit'
ALL_VALID_OPTIONS['-p,--generation-provider'] = 'generation_provider'
ALL_VALID_OPTIONS['-f,--generation-framework'] = 'generation_framework'
ALL_VALID_OPTIONS['-t,--generation-testcase'] = 'generation_testcase'
ALL_VALID_OPTIONS['-i,--generation-input-source'] = 'input-source'


@mock.patch('cot.command.create.template.create_template_backend')
def test_input_valid(create_template_backend):
    run_options_test(CliRunner(), create_build_blueprint, ALL_VALID_OPTIONS, create_template_backend.run)
