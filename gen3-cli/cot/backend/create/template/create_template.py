import os
import re
import shutil
import enum
import uuid
import tempfile
from cot.backend.common.fsutils import Search
from cot.loggers import logging
from . import context_tree as ct
from .set_context import set_context
from .environment import Environment
from . import utils


logger = logging.getLogger('CREATE_TEMPLATE')


class PassResult(enum.Enum):
    DIFFERENCES_DETECTED = enum.auto()
    NO_CHANGE = enum.auto()
    IGNORED = enum.auto()
    ERROR = enum.auto()


# Defaults
CONFIGURATION_REFERENCE_DEFAULT = "unassigned"
REQUEST_REFERENCE_DEFAULT = "unassigned"
DEPLOYMENT_MODE_DEFAULT = "update"
GENERATION_PROVIDERS_DEFAULT = ("aws", )
GENERATION_FRAMEWORK_DEFAULT = "cf"
GENERATION_INPUT_SOURCE_DEFAULT = "composite"


def options(
    environment_obj,
    configuration_reference="",
    deployment_mode="",
    generation_framework="",
    resource_group="",
    generation_input_source="",
    level="",
    output_dir="",
    generation_providers=None,
    request_reference="",
    region="",
    deployment_unit="",
    deployment_unit_subset=""
):
    e = environment_obj
    # updating environment to use vars in other functions where direct env access required
    e.RESOURCE_GROUP = resource_group
    e.LEVEL = level
    e.OUTPUT_DIR = output_dir
    e.REGION = region
    e.DEPLOYMENT_UNIT = deployment_unit
    e.DEPLOYMENT_UNIT_SUBSET = deployment_unit_subset
    # Defaults
    e.CONFIGURATION_REFERENCE = configuration_reference or CONFIGURATION_REFERENCE_DEFAULT
    e.REQUEST_REFERENCE = request_reference or REQUEST_REFERENCE_DEFAULT
    e.DEPLOYMENT_MODE = deployment_mode or DEPLOYMENT_MODE_DEFAULT
    e.GENERATION_FRAMEWORK = generation_framework or GENERATION_FRAMEWORK_DEFAULT
    e.GENERATION_INPUT_SOURCE = generation_input_source or GENERATION_FRAMEWORK_DEFAULT
    e.GENERATION_PROVIDERS = generation_providers or GENERATION_PROVIDERS_DEFAULT

    if not ct.is_valid_unit(e.LEVEL, e.DEPLOYMENT_UNIT):
        logger.fatal('Deployment unit/level not valid')
        return False
    if not e.CONFIGURATION_REFERENCE or not e.REQUEST_REFERENCE:
        logger.fatal('request/configuration reference not provided')
        return False
    # Input control for composite/CMDB input
    if e.GENERATION_INPUT_SOURCE == 'composite':
        # Set up context
        set_context(os.getcwd(), e)
        # Ensure we are in the right place
        if e.LEVEL == 'account':
            if e.LEVEL in e.LOCATION:
                logger.fatal('Current directory doen\'t match request level "%s"', e.LEVEL)
                return False
        elif e.LEVEL in ('solution', 'segment', 'application', 'blueprint', 'unitlist'):
            if 'segment' in e.LOCATION:
                logger.fatal('Current directory doen\'t match request level "%s"', e.LEVEL)
                return False
        # Add default composite fragments including end fragment
        if (
            e.GENERATION_USE_CACHE != 'true'
            and e.GENERATION_USE_FRAGMENTS_CACHE != 'true'
            or os.path.isfile(os.path.join(e.CACHE_DIR, 'composite_account.ftl'))
        ):
            for composite in e.TEMPLATE_COMPOSITES:
                # only support provision of fragment files via cmdb
                # others can now be provided via the plugin mechanism
                composite_array_name = f'{composite}_array'
                composite_array = e.get(composite_array_name, [])
                e[composite_array_name] = composite_array
                if composite == 'fragment':
                    for blueprint_alternate_dir in e.blueprint_alternate_dirs:
                        if not blueprint_alternate_dir or not os.path.isdir(blueprint_alternate_dir):
                            continue
                        for fragment in Search.match_files(f'{composite}_*.ftl', root=blueprint_alternate_dir):
                            fragment_name = os.path.basename(fragment)
                            if fragment_name not in composite_array:
                                composite_array.append(fragment)
                    # Legacy fragments
                    pattern = os.path.join(e.GENERATION_DIR, 'templates', composite, f'{composite}_*.ftl')
                    for fragment in Search.match_files(pattern):
                        fragment_name = os.path.basename(fragment)
                        if fragment_name not in composite_array:
                            composite_array.append(fragment)
                    # Legacy end fragments
                    pattern = os.path.join(e.GENERATION_DIR, 'templates', composite, '*end.ftl')
                    for fragment in Search.match_files(pattern):
                        fragment_name = os.path.basename(fragment)
                        if fragment_name not in composite_array:
                            composite_array.append(fragment)
            # create the template composites
            for composite in e.TEMPLATE_COMPOSITES:
                with open(os.path.join(e.CACHE_DIR, f'composite_{composite}.ftl', 'at+')) as composite_file:
                    for filename in composite_array:
                        filename = os.path.join(filename)
                        if not os.path.isfile(filename):
                            continue
                        with open(filename, 'rt') as f:
                            composite_file.write(f.read())

            for composite in ('segment', 'solution', 'application', 'id', 'name', 'policy', 'resource'):
                filename = os.path.join(e.CACHE_DIR, f'{composite}.ftl')
                if os.path.isfile(filename):
                    os.remove(filename)
        # Assemble settings
        e.COMPOSITE_SETTINGS = os.path.join(e.CACHE_DIR, 'composite_settings.json')
        if (
            e.GENERATION_USE_CACHE != 'true'
            and e.GENERATION_USE_SETTINGS_CACHE != 'true'
            or not os.path.isfile(e.COMPOSITE_SETTINGS)
        ):
            logger.debug('Generating composite settings ...')
            ct.assemble_settings(e)
        # Create the composite definitions
        e.COMPOSITE_DEFINITIONS = os.path.join(e.CACHE_DIR, 'composite_definitions.json')
        if (
            e.GENERATION_USE_CACHE != 'true'
            and e.GENERATION_USE_DEFINITIONS_CACHE != 'true'
            or not os.path.isfile(e.COMPOSITE_DEFINITIONS)
        ):
            ct.assemble_composite_definitions(e)
        # Create the composite stack outputs
        e.COMPOSITE_STACK_OUTPUTS = os.path.join(e.CACHE_DIR, 'composite_stack_outputs.json')
        if (
            e.GENERATION_USE_CACHE != 'true'
            and e.GENERATION_USE_STACK_OUTPUTS_CACHE != 'true'
            or not os.path.isfile(e.COMPOSITE_STACK_OUTPUTS)
        ):
            ct.assemble_composite_stack_outputs(e)
    # Specific intput control for mock input
    if e.GENERATION_INPUT_SOURCE == 'mock':
        if not e.OUTPUT_DIR:
            logger.fatal('Generation input source mock requires output dir to be specified')
            return False


def process_template_pass(
    environment_obj,
    providers='',
    deployment_framework='',
    output_type='',
    output_format='',
    output_suffix='',
    pass_='',
    pass_alternative='',
    level='',
    deployment_unit='',
    resource_group='',
    deployment_unit_subset='',
    account='',
    account_region='',
    region='',
    request_reference='',
    configuration_reference='',
    deployment_mode='',
    cf_dir='',
    run_id=''
):
    e = environment_obj
    # Filename parts
    level_prefix = f'{level}-'
    deployment_unit_prefix = f'{deployment_unit}-' if deployment_unit else ''
    account_prefix = f'{account}-' if account else ''
    region_prefix = f'{region}-' if region else ''

    # Set up the level specific template information
    template_dir = os.path.join(e.GENERATION_DIR, 'templates')
    template = f'create{level.capitalize()}Template.ftl'
    if not os.path.isfile(os.path.join(template_dir, template)):
        template = f'create{level.capitalize()}.ftl'
    template_composites = []

    # Define possible passes
    pass_list = (
        "generationcontract",
        "testcase",
        "pregeneration",
        "prologue",
        "template",
        "epilogue",
        "cli",
        "parameters",
        "config"
    )

    # Initialise the components of the pass filenames
    pass_level_prefix = dict()
    pass_deployment_unit_prefix = dict()
    pass_deployment_unit_subset = dict()
    pass_deployment_unit_subset_prefix = dict()
    pass_account_prefix = dict()
    pass_region_prefix = dict()
    pass_description = dict()
    pass_suffix = dict()
    # Defaults
    for p in pass_list:
        pass_level_prefix[p] = level_prefix
        pass_deployment_unit_prefix[p] = deployment_unit_prefix
        pass_deployment_unit_subset[p] = p
        pass_deployment_unit_subset_prefix[p] = ""
        pass_account_prefix[p] = account_prefix
        pass_region_prefix[p] = region_prefix
        pass_description[p] = p
        pass_suffix[p] = ''
    # Template pass specifics
    pass_deployment_unit_subset['template'] = deployment_unit_subset
    pass_deployment_unit_subset_prefix['template'] = f'{deployment_unit_subset}-' if deployment_unit_subset else ''
    pass_description['template'] = 'cloud formation'

    if level == 'unitlist':
        # Blueprint applies across accounts and regions
        for p in pass_list:
            pass_account_prefix[p] = ''
            pass_region_prefix = ''
        pass_level_prefix['config'] = 'unitlist'
        pass_description['config'] = 'unitlist'
        pass_suffix['config'] = '.json'
    elif level == 'blueprint':
        template_composites.append('FRAGMENT')

        # Blueprint applies across accounts and regions
        for p in pass_list:
            pass_account_prefix[p] = ''
            pass_region_prefix[p] = ''
        pass_level_prefix['config'] = 'blueprint'
        pass_description['config'] = 'blueprint'
        if pass_ == 'config':
            output_suffix == '.json'
    elif level == 'buildblueprint':
        template_composites.append('FRAGMENT')
        # Blueprint applies across accounts and regions
        for p in pass_list:
            pass_account_prefix[p] = ''
            pass_region_prefix[p] = ''
        pass_level_prefix['config'] = 'blueprint_blueprint-'
        pass_description['config'] = 'buildblueprint'
    elif level == 'account':
        template_composites.append('ACCOUNT')
        for p in pass_list:
            pass_region_prefix[p] = f'{account_region}-'
        # LEGACY: Support stacks created before deployment units added to account level
        if (
            re.match('s3', e.DEPLOYMENT_UNIT)
            and os.path.isfile(os.path.join(cf_dir, f'{level_prefix}{region_prefix}template.json'))
        ):
            for p in pass_list:
                pass_deployment_unit_prefix[p] = ''
    elif level == 'solution':
        template_composites.append('FRAGMENT')
        if os.path.isfile(os.path.join(cf_dir, f'solution-{region}-template.json')):
            for p in pass_list:
                pass_deployment_unit_prefix[p] = ''
        else:
            for p in pass_list:
                pass_level_prefix[p] = 'soln-'
    elif level == 'segment':
        template_composites.append('FRAGMENT')
        for p in pass_list:
            pass_level_prefix[p] = 'seg-'
        # LEGACY: Support old formats for existing stacks so they can be updated
        if re.match(r'cmk|cert|dns'):
            if os.path.isfile(os.path.join(cf_dir, f'cont-{deployment_unit_prefix}{region_prefix}template.json')):
                for p in pass_list:
                    pass_level_prefix[p] = 'cont-'
            if os.path.isfile(os.path.join(cf_dir, f'container-{region}-template.json')):
                for p in pass_list:
                    pass_level_prefix[p] = 'container-'
                    pass_deployment_unit_prefix[p] = ''
            if os.path.isfile(os.path.join(cf_dir, f'{e.SEGMENT}-container-template.json')):
                for p in pass_list:
                    pass_level_prefix[p] = f'{e.SEGMENT}-container-'
                    pass_deployment_unit_prefix[p] = ''
                    pass_region_prefix[p] = ''
        # "cmk" now used instead of "key"
        if (
            e.DEPLOYMENT_UNIT == 'cmk'
            and os.path.isfile(os.path.join(cf_dir, f'{level_prefix}key-{region_prefix}template.json'))
        ):
            for p in pass_list:
                pass_deployment_unit_prefix[p] = 'key-'
    elif level == 'application':
        template_composites.append('FRAGMENT')
        for p in pass_list:
            pass_level_prefix[p] = 'app-'
    else:
        return PassResult.ERROR, ()

    # Args common across all passes
    args = []
    if providers:
        args += ['-v', f'providers={" ".join(providers)}']
    if deployment_framework:
        args += ['-v', f'deploymentFramework={deployment_framework}']
    if e.GENERATION_MODEL:
        args += ['-v', f'deploymentFrameworkModel={e.GENERATION_MODEL}']
    if output_type:
        args += ['-v', f'outputType={output_type}']
    if output_format:
        args += ['-v', f'outputFormat={output_format}']
    if deployment_unit:
        args += ['-v', f'deploymentUnit={deployment_unit}']
    if resource_group:
        args += ['-v', f'resourceGroup={resource_group}']
    if e.GENERATION_LOG_LEVEL:
        args += ['-v', f'logLevel={e.GENERATION_LOG_LEVEL}']
    if e.GENERATION_INPUT_SOURCE:
        args += ['-v', f'inputSource={e.GENERATION_INPUT_SOURCE}']

    # Include the template composites
    # Removal of drive letter (/?/) is specifically for MINGW
    # It shouldn't affect other platforms as it won't be matched
    for composite in template_composites:
        composite_var = f'COMPOSITE_{composite.upper()}'
        args += ('-r', f'{composite.lower()}List={re.sub(r"^/./", "", e[composite_var])}')
    args += ['-g', e.GENERATION_DATA_DIR]
    args += ['-v', f'region={region}']
    args += ['-v', f'accountRegion={account_region}']
    args += ['-v', f'blueprint={e.COMPOSITE_BLUEPRINT}']
    args += ['-v', f'settings={e.COMPOSITE_SETTINGS}']
    args += ['-v', f'definitions={e.COMPOSITE_DEFINITIONS}']
    args += ['-v', f'stackOutputs={e.COMPOSITE_STACK_OUTPUTS}']
    args += ['-v', f'requestReference={request_reference}']
    args += ['-v', f'configurationReference={configuration_reference}']
    args += ['-v', f'deploymentMode={e.DEPLOYMENT_MODE}']
    args += ['-v', f'runId={run_id}']

    # Directory for temporary files
    temp_dir = tempfile.mkdtemp()

    # Directory where we gather the result
    # As any file could change, we need to gather them all
    # and copy as a set at the end of processing if a change is detected
    results_dir = os.path.join(temp_dir, 'results')
    # No differences seen so far
    differences_detected = False

    # Determine output file
    output_prefix = '{}{}{}{}'.format(
        pass_level_prefix[pass_],
        pass_deployment_unit_prefix[pass_],
        pass_deployment_unit_subset_prefix[pass_],
        pass_region_prefix[pass_]
    )
    output_prefix_with_account = '{}{}{}{}{}'.format(
        pass_level_prefix[pass_],
        pass_deployment_unit_prefix[pass_],
        pass_deployment_unit_subset_prefix[pass_],
        pass_account_prefix[pass_],
        pass_region_prefix[pass_]
    )
    if pass_deployment_unit_subset[pass_]:
        args += ['-v', f'deploymentUnitSubset={deployment_unit_subset[pass_]}']
    file_description = pass_description[pass_]
    if pass_alternative == 'primary':
        pass_alternative = ''
    pass_alternative_prefix = ''
    if pass_alternative:
        args += ['-v', f'alternative={pass_alternative}']
        pass_alternative_prefix = pass_alternative

    output_filename = f'{output_prefix}{pass_alternative_prefix}{output_suffix}'
    if not os.path.isfile(os.path.join(cf_dir, output_filename)):
        # Include account prefix
        output_filename = f'{output_prefix_with_account}{pass_alternative_prefix}{output_suffix}'
        output_prefix = output_prefix_with_account
    args += ['-v', f'outputPrefix={output_prefix}']

    template_result_file = os.path.join(temp_dir, output_filename)
    output_file = os.path.join(cf_dir, output_filename)
    result_file = os.path.join(results_dir, output_filename)

    logger.info('Generating %s file...', file_description)
    results_list = ()
    return PassResult.DIFFERENCES_DETECTED, results_list


def process_template(
    environment_obj,
    level="",
    deployment_unit="",
    resource_group="",
    deployment_unit_subset="",
    account="",
    account_region="",
    region="",
    request_reference="",
    configuration_reference="",
    deployment_mode=""
):
    e = environment_obj
    # Defaults
    passes = ['template']
    template_alternatives = ['primary']
    if level in ('unitlist', 'blueprint', 'buildblueprint'):
        cf_dir_default = os.path.join(e.PRODUCT_STATE_DIR, 'cot', e.ENVIRONMENT, e.SEGMENT)
    elif level == 'account':
        cf_dir_default = os.path.join(e.ACCOUNT_STATE_DIR, 'cf', 'shared')
    elif level == 'product':
        cf_dir_default = os.path.join(e.PRODUCT_STATE_DIR, 'cf', 'shared')
    elif level in ('solution', 'segment', 'application'):
        cf_dir_default = os.path.join(e.PRODUCT_STATE_DIR, 'cf', e.ENVIRONMENT, e.SEGMENT)
    else:
        logger.fatal('"%s" is not one of the known stack levels', level)
        return False
    # Handle >=v2.0.1 cmdb where du/placement subdirectories were introduced for state
    #
    # Assumption is that if files whose names contain the du are not present in
    # the base cf_dir, then the du directory structure should be used
    #
    # This will start to cause the new structure to be created by default for new units,
    # and will accommodate the cmdb update when it is performed.
    if level in ('unitlist', 'blueprint', 'buildblueprint'):
        # No subdirectories for deployment units
        pass
    else:
        legacy_files = Search.match_files(f'*{deployment_unit}*', root=cf_dir_default)
        if os.path.isdir(os.path.join(cf_dir_default, deployment_unit)) or not legacy_files:
            cf_dir_default = ct.get_unit_cf_dir(
                base_dir=cf_dir_default,
                level=level,
                unit=deployment_unit,
                placement='',
                region=region
            )
    # Permit an override
    cf_dir = e.OUTPUT_DIR or cf_dir_default
    # Ensure the aws tree for the templates exists
    if not os.path.isdir(cf_dir):
        os.makedirs(cf_dir, exist_ok=True)

    run_id = str(uuid.uuid4().hex()[:10])
    temp_dir = tempfile.mkdtemp('', 'create_template_')

    differences_detected = False

    results_dir = os.path.join(temp_dir, 'results')
    os.makedirs(results_dir, exist_ok=True)
    result, results_list = process_template_pass(
        environment_obj,
        providers=e.GENERATION_PROVIDERS,
        deployment_framework=e.GENERATION_FRAMEWORK,
        output_type='contract',
        output_format='',
        output_suffix='generation-contract.json',
        pass_='generationcontract',
        pass_alternative='',
        level=level,
        deployment_unit=deployment_unit,
        resource_group=resource_group,
        deployment_unit_subset=deployment_unit_subset,
        account=account,
        account_region=account_region,
        region=region,
        request_reference=request_reference,
        configuration_reference=configuration_reference,
        deployment_mode=deployment_mode,
        cf_dir=cf_dir,
        run_id=run_id
    )

    if result == PassResult.DIFFERENCES_DETECTED or result == PassResult.NO_CHANGE:
        generation_contract = os.path.join(results_dir, results_list[0])
        logger.info('Generating documents from generation contract %s', generation_contract)
        process_template_tasks_list = utils.get_tasks_from_contract(generation_contract)
    else:
        logger.fatal('No execution plan')
        return False

    for task_type, task_parameters in process_template_tasks_list:

        (
            providers,
            deployment_framework,
            output_type,
            output_format,
            output_suffix,
            pass_,
            pass_alternative
        ) = task_parameters

        result, results_list = process_template_pass(
            environment_obj,
            providers=providers,
            deployment_framework=deployment_framework,
            output_type=output_type,
            output_format=output_format,
            output_suffix=output_suffix,
            pass_=pass_,
            pass_alternative=pass_alternative,
            level=level,
            deployment_unit=deployment_unit,
            resource_group=resource_group,
            deployment_unit_subset=deployment_unit_subset,
            account=account,
            account_region=account_region,
            region=region,
            request_reference=request_reference,
            configuration_reference=configuration_reference,
            deployement_mode=deployment_mode,
            cf_dir=cf_dir,
            run_id=run_id
        )

    if result == PassResult.DIFFERENCES_DETECTED:
        differences_detected = True
    elif result == PassResult.NO_CHANGE:
        differences_detected = False
    elif result.IGNORED:
        pass
    else:
        return False

    if differences_detected:
        logger.info('Differences detected')
        for result_file in results_list:
            logger.info('Updating %s ...', result_file)
            shutil.copy2(os.path.join(results_dir, result_file), os.path.join(cf_dir, result_file))
    else:
        logger.info('No differences detected')
    return True


def run(
    configuration_reference="",
    deployment_mode="",
    generation_framework="",
    resource_group="",
    generation_input_source="",
    level="",
    output_dir="",
    generation_providers=None,
    request_reference="",
    region="",
    deployment_unit="",
    deployment_unit_subset=""
):
    environment_obj = Environment(os.environ)
    e = environment_obj
    options(
        e,
        configuration_reference=configuration_reference,
        deployment_mode=deployment_mode,
        generation_framework=generation_framework,
        resource_group=resource_group,
        generation_input_source=generation_input_source,
        level=level,
        output_dir=output_dir,
        generation_providers=generation_providers,
        request_reference=request_reference,
        region=region,
        deployment_unit=deployment_unit,
        deployment_unit_subset=deployment_unit_subset
    )
    if e.LEVEL == 'blueprint-disabled':
        return process_template(
            e,
            level=e.LEVEL,
            deployment_unit=e.DEPLOYMENT_UNIT,
            resource_group=e.RESOURCE_GROUP,
            deployment_unit_subset=e.DEPLOYMENT_UNIT_SUBSET,
            account="",
            account_region=e.ACCOUNT_REGION,
            region="",
            request_reference=e.REQUEST_REFERENCE,
            configuration_reference=e.CONFIGURATION_REFERENCE,
            deployment_mode=e.DEPLOYMENT_MODE
        )
    else:
        return process_template(
            e,
            level=e.LEVEL,
            deployment_unit=e.DEPLOYMENT_UNIT,
            resource_group=e.RESOURCE_GROUP,
            deployment_unit_subset=e.DEPLOYMENT_UNIT_SUBSET,
            account=e.ACCOUNT,
            account_region=e.ACCOUNT_REGION,
            region=e.REGION,
            request_reference=e.REQUEST_REFERENCE,
            configuration_reference=e.CONFIGURATION_REFERENCE,
            deployment_mode=e.DEPLOYMENT_MODE
        )
